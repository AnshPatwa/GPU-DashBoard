"""
GPU Utilz — Fetching Agent
===========================
Har GPU server pe ye agent chalta hai. Ye:
  1. `nvidia-smi` se GPU utilization / VRAM / temp / power fetch karta hai
  2. System RAM read karta hai (no extra dependency — pure stdlib)
  3. WebSocket se MAIN SERVER ko push karta hai (agent = client, server = hub)

Server ko kuch add nahi karna padta — agent start karo, dashboard pe
apne aap dikh jayega.

Server change karna ho (boss ka scenario):
  config.json me "server_urls" ek LIST hai — naya URL daal do ya replace
  kar do. Agent order me try karta hai aur fail hone pe agle pe chala
  jata hai (automatic failover + reconnect).

Run:
    python agent.py                 # config.json se server uthata hai
    python agent.py --demo          # fake GPUs (testing without nvidia-smi)
    GPU_AGENT_SERVER=ws://10.0.0.5:8765/ws/agent python agent.py
"""

import asyncio
import ctypes
import json
import math
import os
import platform
import random
import socket
import subprocess
import sys
import time
from pathlib import Path

import aiohttp

CONFIG_PATH = Path(__file__).parent / "config.json"

NVIDIA_SMI_QUERY = [
    "nvidia-smi",
    "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit,fan.speed,clocks.current.graphics",
    "--format=csv,noheader,nounits",
]


def load_config() -> dict:
    cfg = {"server_urls": [], "token": "", "interval": 2.0, "hostname": None}
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    if os.environ.get("GPU_AGENT_SERVER"):
        cfg["server_urls"] = [os.environ["GPU_AGENT_SERVER"]]
    if os.environ.get("GPU_AGENT_TOKEN"):
        cfg["token"] = os.environ["GPU_AGENT_TOKEN"]
    if os.environ.get("GPU_AGENT_INTERVAL"):
        cfg["interval"] = float(os.environ["GPU_AGENT_INTERVAL"])
    if os.environ.get("GPU_AGENT_HOSTNAME"):
        cfg["hostname"] = os.environ["GPU_AGENT_HOSTNAME"]
    if not cfg["server_urls"]:
        sys.exit("No server configured. Set server_urls in config.json or GPU_AGENT_SERVER env var.")
    return cfg


def _f(value: str) -> float:
    try:
        return float(value.strip())
    except ValueError:  # nvidia-smi prints "[N/A]" for unsupported fields
        return 0.0


def read_gpus() -> list[dict]:
    out = subprocess.run(NVIDIA_SMI_QUERY, capture_output=True, text=True, timeout=10)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "nvidia-smi failed")
    gpus = []
    for line in out.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 10:
            continue
        gpus.append({
            "index": int(_f(parts[0])),
            "name": parts[1],
            "util": _f(parts[2]),
            "mem_used": _f(parts[3]),
            "mem_total": _f(parts[4]),
            "temp": _f(parts[5]),
            "power": _f(parts[6]),
            "power_limit": _f(parts[7]),
            "fan": _f(parts[8]),
            "clock": _f(parts[9]),
        })
    return gpus


_demo_t0 = time.time()


def read_gpus_demo() -> list[dict]:
    t = time.time() - _demo_t0
    gpus = []
    for i, name in enumerate(["NVIDIA RTX 4090 (demo)", "NVIDIA A100 80GB (demo)"]):
        wave = 50 + 45 * math.sin(t / (7 + i * 3) + i * 2)
        util = max(0, min(100, wave + random.uniform(-6, 6)))
        total = 24576 if i == 0 else 81920
        gpus.append({
            "index": i,
            "name": name,
            "util": round(util, 1),
            "mem_used": round(total * (0.25 + util / 220), 0),
            "mem_total": total,
            "temp": round(38 + util * 0.42, 1),
            "power": round((120 if i == 0 else 90) + util * 3.1, 1),
            "power_limit": 450 if i == 0 else 400,
            "fan": round(min(100, 25 + util * 0.6), 0),
            "clock": round(1200 + util * 12, 0),
        })
    return gpus


def read_ram() -> dict:
    system = platform.system()
    if system == "Windows":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        total = stat.ullTotalPhys
        used = total - stat.ullAvailPhys
    else:  # Linux (GPU servers are usually Linux)
        meminfo = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                meminfo[key] = int(rest.strip().split()[0]) * 1024  # kB -> bytes
        total = meminfo.get("MemTotal", 0)
        used = total - meminfo.get("MemAvailable", 0)
    return {
        "total_gb": round(total / 1024**3, 2),
        "used_gb": round(used / 1024**3, 2),
        "percent": round(used / total * 100, 1) if total else 0.0,
    }


async def run(cfg: dict, demo: bool):
    hostname = cfg.get("hostname") or socket.gethostname()
    interval = float(cfg.get("interval", 2.0))
    urls = cfg["server_urls"]
    token = cfg.get("token", "")
    url_idx = 0
    backoff = 1.0

    async with aiohttp.ClientSession() as session:
        while True:
            url = urls[url_idx % len(urls)]
            full_url = url + (("&" if "?" in url else "?") + "token=" + token if token else "")
            try:
                async with session.ws_connect(full_url, heartbeat=20) as ws:
                    print(f"[agent] connected -> {url}  (host: {hostname})")
                    backoff = 1.0
                    while True:
                        try:
                            gpus = read_gpus_demo() if demo else read_gpus()
                            gpu_error = None
                        except (RuntimeError, FileNotFoundError, subprocess.TimeoutExpired) as e:
                            gpus, gpu_error = [], str(e)
                        payload = {
                            "type": "metrics",
                            "host": hostname,
                            "ts": time.time(),
                            "gpus": gpus,
                            "gpu_error": gpu_error,
                            "ram": read_ram(),
                        }
                        await ws.send_json(payload)
                        await asyncio.sleep(interval)
            except (aiohttp.ClientError, ConnectionError, OSError) as e:
                print(f"[agent] connection lost/failed ({url}): {e} — retry in {backoff:.0f}s")
                url_idx += 1  # failover: agla server URL try karo
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)


def main():
    demo = "--demo" in sys.argv
    cfg = load_config()
    try:
        asyncio.run(run(cfg, demo))
    except KeyboardInterrupt:
        print("\n[agent] stopped")


if __name__ == "__main__":
    main()
