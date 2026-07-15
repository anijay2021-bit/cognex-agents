# COGNEX Agents

Algorithmic trading agents for NSE (Nifty options + equity swing), deployed on a GCP VM
(`cognex-agent`, asia-south1-a) and monitored through a FastAPI dashboard.

> Personal project - not investment advice. Trades real money when set to LIVE. Use at your own risk.

## Agents

| Agent | Service | Account / Broker | Strategy | Mode |
|---|---|---|---|---|
| Prajnan | `prajnan-agent` | Kiran (Fyers data + AngelOne exec) | RSI2 + EMA/OBV intraday options, Calendar spreads | LIVE |
| Prajnan2 | `prajnan-agent2` | Father (AngelOne only) | RSI2 weekly ATM options | LIVE |
| Nitin | `nitin-agent` | Kiran (Fyers data) | Swing setups: flag, base-ONP-pullback, DTL breakout, VCP | PAPER |
| Trishul | `trishul-agent` | Kiran (Fyers data + AngelOne) | Mean reversion scanner (SMA10 stretch + RSI2) | PAPER (service disabled) |

## Repository layout

```
cognex-dashboard/    FastAPI monitoring API + web UI (port 8000, localhost, basic auth)
prajnan-agent/       Main live agent (strategies/, core/, brokers/, config/)
prajnan-agent2/      Father's account agent
nitin-agent/         Swing trading agent (EOD scan 18:30 IST)
trishul-agent/       Mean reversion scanner
```

Deployment: each folder is copied to `~/` on the VM and run as a systemd service
(`Restart=always`, enabled at boot). The repo is the source of truth; deployed copies
must stay in sync with `main`.

## Dashboard

- `GET /api/agents/` - status of all agents (systemd state, pid, memory)
- `GET /api/config/` - strategy parameters; params with `file_map` are read from and
  written to the agent source files, and the agent is `systemctl try-restart`ed on save
- `GET /api/data/*` - trades, P&L, signals; `GET /api/live/*` - live-mode toggles
- Basic auth via `DASH_USER` / `DASH_PASS` in `~/cognex-dashboard/.env`; bound to 127.0.0.1

As of 2026-07-15, 49 of 65 dashboard params are file-linked - editing them in the
dashboard changes the running agent. The remaining 16 mirror code defaults.

## Configuration & secrets

- Per-agent settings: `<agent>/config/settings.py` (tunables) + `.env` (credentials)
- Broker tokens: `<agent>/config/fyers_token.json` (chmod 600, gitignored)
- Never commit credentials. `.gitignore` covers `.env`, tokens, telegram config, DBs, logs.

## Operations

```bash
systemctl status prajnan-agent            # health
sudo journalctl -u prajnan-agent -f       # live logs
sudo systemctl restart cognex-dashboard   # after dashboard code changes
cd ~/cognex-agents && git pull            # then copy changed files to ~/<agent>/ and restart
```

Risk guards: daily loss caps, VIX ceiling, market-hours gates (09:15-15:15 IST entries),
EOD square-off, emergency-stop flags.

## Key times (IST)

- Prajnan entries: 09:15-15:15, EOD square-off 15:14
- Calendar roll: exit 15:24 / enter 15:26 on expiry days; monthly exit 15:24
- Nitin: EOD scan 18:30 Mon-Fri, monitors every 15 min in market hours
- Trishul: scans every 15 min 09:15-15:15 (when enabled)
