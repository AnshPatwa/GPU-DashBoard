#!/usr/bin/env bash
#
# Rotate the Cloudflare tunnel and print a fresh public URL.
#
# Use this when the previous trycloudflare URL has died (server reboot,
# cloudflared crashed, or it just got disconnected) and you need a new one
# WITHOUT reinstalling Python / cloning the repo / setting up the agent.
#
# Assumes the agent and cloudflared were already installed earlier via
# install-agent.sh or setup.sh.
#
# Run:
#   curl -sSL https://raw.githubusercontent.com/AnshPatwa/GPU-DashBoard/main/new-url.sh | bash
#
# Or, if a local copy exists:
#   bash new-url.sh

set -euo pipefail

PORT=8900
CLOUDFLARED="$HOME/cloudflared"

# Find the most recent install folder. install-agent.sh creates
# ~/gpu-agent-YYYYMMDD-HHMMSS and setup.sh creates ~/gpu-dashboard-YYYYMMDD-HHMMSS.
# We pick whichever is newest (or fall back to a fresh ~/gpu-agent if none exist).
DIR="$(ls -1dt "$HOME"/gpu-agent-* "$HOME"/gpu-dashboard-* 2>/dev/null | head -1 || true)"
if [ -z "$DIR" ]; then
  DIR="$HOME/gpu-agent"
  mkdir -p "$DIR"
fi
TUNNEL_LOG="$DIR/tunnel.log"

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m   ✓ %s\033[0m\n' "$*"; }
warn(){ printf '\033[1;33m   ! %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m   ✗ %s\033[0m\n' "$*" >&2; exit 1; }

say "Sanity check"
[ -x "$CLOUDFLARED" ] || die "cloudflared not found at $CLOUDFLARED — re-run install-agent.sh first."
ok "cloudflared present: $($CLOUDFLARED --version 2>&1 | head -1)"

if curl -sf -m 5 "http://127.0.0.1:$PORT/api/gpus" >/dev/null; then
  ok "agent responding on 127.0.0.1:$PORT"
else
  warn "agent on 127.0.0.1:$PORT is NOT responding."
  warn "the tunnel will start, but the URL will return errors until the agent is running."
  warn "fix: re-run install-agent.sh to start the agent again."
fi

say "Killing any existing cloudflared processes"
if pgrep -f "cloudflared tunnel --url" >/dev/null; then
  pkill -f "cloudflared tunnel --url" || true
  sleep 2
  ok "old tunnel(s) stopped"
else
  ok "no existing tunnel to stop"
fi

say "Starting a fresh tunnel -> http://localhost:$PORT"
cd "$DIR"
: > "$TUNNEL_LOG"
nohup "$CLOUDFLARED" tunnel --url "http://localhost:$PORT" > "$TUNNEL_LOG" 2>&1 &
ok "new tunnel pid: $!  (log: $TUNNEL_LOG)"

say "Waiting for new public URL..."
URL=""
for _ in $(seq 1 15); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 2
done

if [ -z "$URL" ]; then
  warn "Could not detect tunnel URL yet. Last lines of $TUNNEL_LOG:"
  tail -15 "$TUNNEL_LOG"
  exit 1
fi

EXT_OK=no
if curl -sf -m 10 "$URL/api/gpus" >/dev/null; then EXT_OK=yes; fi

cat <<EOF

================================================================
  NEW PUBLIC URL
================================================================
  $URL

  External OK: $EXT_OK

  NEXT STEP — update the dashboard with this URL:
    Render → gpu-dashboard → Environment → GPU_REMOTES
    Replace the old URL for this server with:
        $URL
    Save Changes (Render redeploys in ~1 min).

  Or, the quick way — re-add via the dashboard UI:
    1. Open  https://gpu-dashboard-96zn.onrender.com
    2. Click '+ Add server'
    3. Server URL  : $URL
    4. Admin token : GGFC
================================================================
EOF
