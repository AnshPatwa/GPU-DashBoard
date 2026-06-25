#!/usr/bin/env bash
#
# Cleanly remove the GPU agent + Cloudflare tunnel from this server.
#
# What it does:
#   1. Stops the gpu_fastapi uvicorn process (port 8900).
#   2. Stops any cloudflared tunnel pointing at port 8900.
#   3. Deletes every install folder:
#        ~/gpu-agent           ~/gpu-agent-YYYYMMDD-HHMMSS
#        ~/gpu-dashboard       ~/gpu-dashboard-YYYYMMDD-HHMMSS
#   4. Deletes the cloudflared binary (~/cloudflared).
#
# It does NOT touch:
#   - Anything outside the user's home directory.
#   - Any other Python venvs, repos, or processes on the box.
#   - The dashboard on Render (the L40S card there will simply go offline).
#
# Run:
#   curl -sSL https://raw.githubusercontent.com/AnshPatwa/GPU-DashBoard/main/uninstall-agent.sh | bash

set -euo pipefail

PORT=8900
CLOUDFLARED="$HOME/cloudflared"

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m   ✓ %s\033[0m\n' "$*"; }
warn(){ printf '\033[1;33m   ! %s\033[0m\n' "$*"; }

say "1/4  Stopping the GPU agent (uvicorn gpu_fastapi on port $PORT)"
if pgrep -f "uvicorn gpu_fastapi:app.*--port $PORT" >/dev/null; then
  pkill -f "uvicorn gpu_fastapi:app.*--port $PORT" || true
  sleep 2
  ok "agent stopped"
else
  ok "no agent was running"
fi

say "2/4  Stopping the Cloudflare tunnel"
if pgrep -f "cloudflared tunnel --url http://localhost:$PORT" >/dev/null; then
  pkill -f "cloudflared tunnel --url http://localhost:$PORT" || true
  sleep 2
  ok "tunnel stopped"
else
  ok "no tunnel was running"
fi

say "3/4  Removing install folders in \$HOME"
removed_any=0
shopt -s nullglob
for d in "$HOME"/gpu-agent "$HOME"/gpu-dashboard "$HOME"/gpu-agent-* "$HOME"/gpu-dashboard-*; do
  [ -e "$d" ] || continue
  rm -rf "$d"
  ok "removed $d"
  removed_any=1
done
shopt -u nullglob
[ "$removed_any" -eq 0 ] && ok "no install folders to remove"

say "4/4  Removing cloudflared binary"
if [ -e "$CLOUDFLARED" ]; then
  rm -f "$CLOUDFLARED"
  ok "removed $CLOUDFLARED"
else
  ok "cloudflared was not present"
fi

cat <<EOF

================================================================
  UNINSTALL COMPLETE
================================================================
  Verify nothing left behind:
    pgrep -af 'uvicorn gpu_fastapi'   # should print nothing
    pgrep -af cloudflared             # should print nothing
    ls ~ | grep -E 'gpu-(agent|dashboard)|cloudflared'   # empty

  To install fresh again:
    curl -sSL https://raw.githubusercontent.com/AnshPatwa/GPU-DashBoard/main/install-agent.sh | bash

  Heads-up: the dashboard's card for this server will now show
  'offline' until you reinstall and update GPU_REMOTES with the
  new URL.
================================================================
EOF
