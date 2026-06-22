"""
Minimal GPU agent for the GPU Dashboard.

Runs on a GPU server and exposes ONLY the data the dashboard needs:
    GET /api/gpus  ->  {"ok": true, "servers": [{"name", "gpus": [...]}]}

Deliberately tiny: pure Python standard library (no FastAPI / uvicorn / pip) and
it reads the GPU with nvidia-smi, which is already on every NVIDIA box. The full
dashboard UI lives on the aggregator (Render); a server only needs to serve data.

Run:  python3 agent.py [port]      (default 8900)
"""
import json
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

_FIELDS = "index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"


def _num(token):
    token = token.strip()
    if not token or token.startswith("[") or token.lower() == "n/a":
        return None
    try:
        return float(token)
    except ValueError:
        return None


def read_gpus():
    out = subprocess.run(
        ["nvidia-smi", f"--query-gpu={_FIELDS}", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    gpus = []
    for line in out.splitlines():
        idx, name, util, used, total, temp, power = (c.strip() for c in line.split(","))
        used_n = _num(used) or 0.0
        total_n = _num(total) or 0.0
        temp_n = _num(temp)
        gpus.append({
            "index": int(idx),
            "name": name,
            "gpu_util": int(_num(util) or 0),
            "mem_used": round(used_n, 1),
            "mem_total": round(total_n, 1),
            "mem_util": round(used_n / total_n * 100, 1) if total_n else 0.0,
            "temperature": int(temp_n) if temp_n is not None else None,
            "power": _num(power),
        })
    return gpus


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not self.path.startswith("/api/gpus"):
            self.send_response(404)
            self.end_headers()
            return
        try:
            payload = {"ok": True, "servers": [
                {"name": socket.gethostname(), "gpus": read_gpus(), "online": True}]}
            code = 200
        except Exception as exc:
            payload = {"ok": False, "error": str(exc)}
            code = 500
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # stay quiet


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8900
    print(f"GPU agent serving on http://127.0.0.1:{port}/api/gpus")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
