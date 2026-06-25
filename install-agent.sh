#!/usr/bin/env bash
#
# Agent-only installer for a GPU server.
#
# Fetches ONLY the files needed to expose this machine's GPUs:
#   - gpu_fastapi.py    (the FastAPI service that reads NVML / nvidia-smi)
#   - requirements.txt  (fastapi, uvicorn, nvidia-ml-py)
#   - cloudflared       (the tunnel binary)
#
# Does NOT clone the dashboard/website code — only what's needed to report
# this server's GPU stats to the central dashboard.
#
# Run on a fresh GPU box:
#   curl -sSL https://raw.githubusercontent.com/AnshPatwa/GPU-DashBoard/main/install-agent.sh | bash
#
# Idempotent: safe to re-run. Won't double-start the agent or tunnel.

set -euo pipefail

RAW="https://raw.githubusercontent.com/AnshPatwa/GPU-DashBoard/main"
AGENT_DIR="$HOME/gpu-agent"
PORT=8900
APP_LOG="$AGENT_DIR/app.log"
TUNNEL_LOG="$AGENT_DIR/tunnel.log"
CLOUDFLARED="$HOME/cloudflared"

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m   ✓ %s\033[0m\n' "$*"; }
warn(){ printf '\033[1;33m   ! %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m   ✗ %s\033[0m\n' "$*" >&2; exit 1; }

say "1/5  Checking prerequisites"
command -v python3 >/dev/null || die "python3 not found — try: sudo apt install -y python3 python3-venv"
command -v curl    >/dev/null || die "curl not found — try: sudo apt install -y curl"
command -v wget    >/dev/null || die "wget not found — try: sudo apt install -y wget"
command -v nvidia-smi >/dev/null || warn "nvidia-smi not on PATH — the agent will return 'no GPU access' until NVIDIA drivers are installed"
ok "python3 / curl / wget present"

say "2/5  Fetching agent files into $AGENT_DIR"
mkdir -p "$AGENT_DIR"
cd "$AGENT_DIR"
curl -fsSL -o gpu_fastapi.py    "$RAW/gpu_fastapi.py"
curl -fsSL -o requirements.txt  "$RAW/requirements.txt"
ok "downloaded gpu_fastapi.py + requirements.txt"

say "3/5  Setting up Python venv + dependencies"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
ok "deps installed"

say "4/5  Downloading cloudflared (if missing)"
if [ ! -x "$CLOUDFLARED" ]; then
  wget -q -O "$CLOUDFLARED" https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
  chmod +x "$CLOUDFLARED"
  ok "downloaded $($CLOUDFLARED --version 2>&1 | head -1)"
else
  ok "already present: $($CLOUDFLARED --version 2>&1 | head -1)"
fi

say "5/5  Starting agent on 127.0.0.1:$PORT and the Cloudflare tunnel"

if pgrep -f "uvicorn gpu_fastapi:app.*--port $PORT" >/dev/null; then
  ok "agent already running (pid $(pgrep -f "uvicorn gpu_fastapi:app.*--port $PORT" | head -1))"
else
  nohup .venv/bin/python -m uvicorn gpu_fastapi:app --host 127.0.0.1 --port "$PORT" \
    > "$APP_LOG" 2>&1 &
  sleep 3
  ok "agent started (pid $!)"
fi

if ! curl -sf -m 5 "http://127.0.0.1:$PORT/api/gpus" >/dev/null; then
  warn "local /api/gpus did not respond — see $APP_LOG"
fi

if pgrep -f "cloudflared tunnel --url http://localhost:$PORT" >/dev/null; then
  ok "tunnel already running (pid $(pgrep -f "cloudflared tunnel --url http://localhost:$PORT" | head -1))"
else
  : > "$TUNNEL_LOG"
  nohup "$CLOUDFLARED" tunnel --url "http://localhost:$PORT" > "$TUNNEL_LOG" 2>&1 &
  ok "tunnel started (pid $!) — waiting for public URL..."
fi

URL=""
for _ in $(seq 1 15); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 2
done

echo
if [ -z "$URL" ]; then
  warn "Could not detect tunnel URL yet. Last lines of $TUNNEL_LOG:"
  tail -15 "$TUNNEL_LOG"
  exit 1
fi

EXT_OK=no
if curl -sf -m 10 "$URL/api/gpus" >/dev/null; then EXT_OK=yes; fi

cat <<EOF

================================================================
  GPU AGENT IS LIVE
================================================================
  Public URL : $URL
  Local API  : http://127.0.0.1:$PORT/api/gpus
  External OK: $EXT_OK

  NEXT STEP — send this URL to Ansh so it can be added to the
  dashboard's GPU_REMOTES list. He will paste:

      $URL

  into the GPU_REMOTES environment variable on Render
  (comma-separated with any existing URLs).

  Or, to add it yourself via the dashboard:
    1. Open  https://gpu-dashboard-96zn.onrender.com
    2. Click '+ Add server' (top-right)
    3. Server URL  : $URL
    4. Admin token : GGFC
    5. Click Add
================================================================

  Logs:
    agent  -> $APP_LOG
    tunnel -> $TUNNEL_LOG

  Note: this URL stays valid only while the cloudflared process
  is alive. After a reboot you'll get a new URL — re-run this
  one-liner to get a fresh one.
EOF
