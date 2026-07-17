# GPU//TACTICAL — WebSocket-only GPU Monitoring

Realtime GPU + RAM monitoring. **Pure WebSocket. No SSH, no polling, no localhost dependency, no manually adding GPU remotes.**

```
GPU Server 1 ──┐
GPU Server 2 ──┼── agent.py  ── ws://MAIN-SERVER:8765/ws/agent ──►  ┌────────────┐
GPU Server N ──┘   (pushes nvidia-smi + RAM every 2s)               │ MAIN SERVER │
                                                                    │  server.py  │
        Browser ◄── ws://MAIN-SERVER:8765/ws/dashboard ──────────── └────────────┘
        (anime dashboard, live broadcast every 1s)
```

**How it works:** every GPU server runs a tiny agent that reads `nvidia-smi`
(GPU util, VRAM, temp, power) + system RAM, and *pushes* it over an outbound
WebSocket to the main server (the hub). The hub broadcasts everything to any
open dashboard. Because agents connect **outward** to the hub, the hub never
needs a list of GPU machines — **start an agent anywhere and it auto-appears
on the dashboard**. Kill it and it shows OFFLINE.

---

## 1. Main server setup (hub)

```bash
pip install aiohttp
python server/server.py
```

- Listens on `0.0.0.0:8765` — dashboard at `http://<server-ip>:8765`
- **Current setup:** main server = ye laptop (`192.168.29.200`), agents isi pe point karte hain
- **Windows pe firewall kholna padega** taaki doosre machines connect kar sakein
  (admin PowerShell me ek baar):
  ```powershell
  New-NetFirewallRule -DisplayName "GPU Utilz Hub" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow
  ```
- Env options:
  - `GPU_MONITOR_PORT=9000` — change port
  - `GPU_MONITOR_TOKEN=secret123` — require a token from agents & dashboards
    (dashboard URL then becomes `http://<ip>:8765/?token=secret123`)

## 2. Agent setup (every GPU server)

```bash
pip install aiohttp
# edit agent/config.json -> put your MAIN SERVER address:
{
  "server_urls": ["ws://10.0.0.5:8765/ws/agent"],
  "token": "",
  "interval": 2.0,
  "hostname": null
}
python agent/agent.py
```

- `hostname: null` → machine ka apna hostname use hota hai
- No NVIDIA GPU / testing? → `python agent.py --demo` (fake GPUs)
- Env overrides: `GPU_AGENT_SERVER`, `GPU_AGENT_TOKEN`, `GPU_AGENT_INTERVAL`, `GPU_AGENT_HOSTNAME`

## 3. Server migration (boss ka scenario) 🔁

Aaj ek hi main server hai; kal boss kisi aur machine pe shift karna chahe —
teen tarike, sabse clean pehla:

1. **DNS name (recommended):** agents me IP ki jagah
   `ws://gpu-hub.company.local:8765/ws/agent` daalo. Server change hone pe
   sirf DNS record naye server pe point karo — **agents ko haath bhi nahi
   lagana padega**, wo auto-reconnect kar lenge.
2. **Failover list:** `server_urls` ek list hai —
   `["ws://old-server:8765/ws/agent", "ws://new-server:8765/ws/agent"]`.
   Purana server band hote hi agents khud naye pe chale jayenge.
3. **One-line edit:** `config.json` me URL badlo, agent restart karo. Bas.

New server pe bas `server.py` + `static/` copy karo, `pip install aiohttp`,
run karo — hub **stateless** hai, koi database/config migrate nahi karna.

## 4. Run as a service (auto-start)

**Linux (systemd)** — `/etc/systemd/system/gpu-agent.service`:
```ini
[Unit]
Description=GPU Utilz Agent
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 /opt/gpu-utilz/agent/agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now gpu-agent
```
(Same pattern for the hub with `server.py`.)

**Windows:** Task Scheduler → "At startup" → `python C:\gpu-utilz\agent\agent.py`

## 5. Files

| Path | Kya hai |
|---|---|
| `server/server.py` | Main hub — agents se data leta hai, dashboards ko broadcast karta hai |
| `server/static/index.html` | Dark tactical HUD dashboard — operator profile selection (Netflix-style, 6 default + custom callsigns), live load bars, sparklines, temp/power telemetry |
| `agent/agent.py` | Fetching agent — nvidia-smi + RAM → WebSocket push |
| `agent/config.json` | Agent config (server URL list, token, interval) |

## Operator profiles

Dashboard kholte hi **SELECT OPERATOR** screen aati hai (Netflix-profile style) —
6 built-in callsigns (GHOST, VIPER, REAPER, NOVA, WRAITH, TITAN) + apna custom
callsign register kar sakte ho. Selection browser me save rehta hai (localStorage),
to har banda apne browser se apni profile se enter karta hai. Header ke
**SWITCH OPERATOR** button se profile badal sakte ho.

## Notes

- Agents reconnect automatically with exponential backoff (max 30s).
- A server with no data for 8s is marked **OFFLINE** (config: `GPU_MONITOR_OFFLINE_AFTER`).
- Dashboard bhi auto-reconnect karta hai — hub restart hone pe khud jud jayega.
- `nvidia-smi` fail ho (driver issue etc.) to card pe error dikhega, RAM phir bhi aata rahega.
