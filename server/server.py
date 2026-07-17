"""
GPU Utilz — Main Server (WebSocket Hub)
========================================
Ye server sirf ek hub hai:
  - Agents  -> ws://<this-server>:8765/ws/agent      (GPU servers yahan push karte hain)
  - Browser -> ws://<this-server>:8765/ws/dashboard  (dashboard yahan se live data leta hai)
  - HTTP    -> http://<this-server>:8765/            (anime dashboard UI)

Koi GPU remote manually add nahi hota — jaise hi agent connect hota hai,
wo auto-register ho jata hai. Agent disconnect ho jaye to OFFLINE dikhta hai.

Run:
    python server.py                     # 0.0.0.0:8765 pe sunta hai
    GPU_MONITOR_PORT=9000 python server.py
    GPU_MONITOR_TOKEN=secret123 python server.py   # optional auth
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from aiohttp import web, WSMsgType

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("gpu-hub")

HOST = os.environ.get("GPU_MONITOR_HOST", "0.0.0.0")
PORT = int(os.environ.get("GPU_MONITOR_PORT", "8765"))
TOKEN = os.environ.get("GPU_MONITOR_TOKEN", "")          # empty = auth off
OFFLINE_AFTER = float(os.environ.get("GPU_MONITOR_OFFLINE_AFTER", "8"))  # seconds
FORGET_AFTER = float(os.environ.get("GPU_MONITOR_FORGET_AFTER", "600"))  # drop dead agents after 10 min
BROADCAST_INTERVAL = 1.0

STATIC_DIR = Path(__file__).parent / "static"

# host -> {"data": <last metrics payload>, "last_seen": ts, "connected_at": ts}
AGENTS: dict[str, dict] = {}
DASHBOARDS: set[web.WebSocketResponse] = set()


def check_token(request: web.Request) -> bool:
    if not TOKEN:
        return True
    supplied = request.query.get("token") or request.headers.get("X-Auth-Token", "")
    return supplied == TOKEN


def build_snapshot() -> dict:
    now = time.time()
    for host in [h for h, e in AGENTS.items() if now - e["last_seen"] > FORGET_AFTER]:
        del AGENTS[host]
        log.info("forgot stale agent: %s", host)
    servers = []
    for host, entry in AGENTS.items():
        online = (now - entry["last_seen"]) <= OFFLINE_AFTER
        servers.append({
            "host": host,
            "online": online,
            "last_seen": entry["last_seen"],
            "connected_at": entry["connected_at"],
            "metrics": entry["data"],
        })
    servers.sort(key=lambda s: s["host"])
    return {"type": "snapshot", "ts": now, "servers": servers}


async def ws_agent(request: web.Request) -> web.WebSocketResponse:
    if not check_token(request):
        raise web.HTTPUnauthorized(text="bad token")

    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)

    host = None
    peer = request.remote
    log.info("agent connected from %s", peer)

    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                payload = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            if payload.get("type") != "metrics":
                continue
            host = payload.get("host") or f"unknown@{peer}"
            entry = AGENTS.setdefault(host, {"connected_at": time.time(), "data": {}, "last_seen": 0})
            entry["data"] = payload
            entry["last_seen"] = time.time()
    finally:
        log.info("agent disconnected: %s (%s)", host or "?", peer)

    return ws


async def ws_dashboard(request: web.Request) -> web.WebSocketResponse:
    if not check_token(request):
        raise web.HTTPUnauthorized(text="bad token")

    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    DASHBOARDS.add(ws)
    log.info("dashboard connected (%d total)", len(DASHBOARDS))

    try:
        await ws.send_json(build_snapshot())  # instant first paint
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
    finally:
        DASHBOARDS.discard(ws)
        log.info("dashboard disconnected (%d left)", len(DASHBOARDS))

    return ws


async def broadcaster(app: web.Application):
    while True:
        await asyncio.sleep(BROADCAST_INTERVAL)
        if not DASHBOARDS:
            continue
        snapshot = build_snapshot()
        dead = []
        for ws in DASHBOARDS:
            try:
                await ws.send_json(snapshot)
            except (ConnectionResetError, RuntimeError):
                dead.append(ws)
        for ws in dead:
            DASHBOARDS.discard(ws)


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def on_startup(app: web.Application):
    app["broadcaster"] = asyncio.create_task(broadcaster(app))


async def on_cleanup(app: web.Application):
    app["broadcaster"].cancel()


def main():
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/ws/agent", ws_agent)
    app.router.add_get("/ws/dashboard", ws_dashboard)
    app.router.add_static("/static", STATIC_DIR)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    log.info("GPU Utilz hub listening on http://%s:%d  (auth: %s)",
             HOST, PORT, "ON" if TOKEN else "off")
    web.run_app(app, host=HOST, port=PORT, print=None)


if __name__ == "__main__":
    main()
