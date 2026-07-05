COGNEX TRADING SYSTEM - MASTER REFERENCE
Last updated: 2026-04-22
Read this file at the start of every new session.

=======================================================================
1. GCP VMs
=======================================================================

PRIMARY VM   : cognex-agent
  Zone       : asia-south1-a
  External IP: 34.47.221.138
  SSH URL    : https://ssh.cloud.google.com/v2/ssh/projects/project-b4c38271-1ac4-4035-857/zones/asia-south1-a/instances/cognex-agent
  Contents:
    cognex-agent2/  <- ACTIVE V2 Python trading agent (USE THIS)
    cognex-agent/   <- OLD V1 Python agent (INACTIVE, do NOT start)
    Cognexalgo/     <- C# desktop app (passive, not in cron)

SECONDARY VM : nifty-rsi2-scanner
  Zone       : asia-south1-c
  SSH URL    : https://ssh.cloud.google.com/v2/ssh/projects/project-b4c38271-1ac4-4035-857/zones/asia-south1-c/instances/nifty-rsi2-scanner
  Status     : Secondary scanner VM (not primary trading VM)

=======================================================================
2. ACTIVE STRATEGY - V2 (cognex-agent2)
=======================================================================

Strategy   : RSI2 + SMA200
Instrument : NIFTY options (CE / PE)
Timeframe  : 5-minute clock-aligned candles
Quantity   : 650 shares = 10 lots
Expiry     : Monthly
Broker     : Fyers
Mode       : Set in config/.env -> TRADING_MODE=PAPER or LIVE

Entry logic:
  Spot above SMA200 -> buy CE when RSI2 oversold
  Spot below SMA200 -> buy PE when RSI2 overbought
  Candles aligned to clock: 09:15, 09:20, 09:25 ...

Risk checks ACTIVE (risk/risk_guard.py):
  - Market hours (09:15-15:30 IST)
  - Daily loss limit
  - Position count limit
  - Capital / margin check
  - Per-trade loss limit

Risk checks DISABLED:
  - VIX ceiling check (commented out in risk/risk_guard.py line 24)
    To re-enable: remove the # from:  # self.check_vix(vix),
    VIX ceiling value: 20.0 (vix_ceiling field in config/settings.py)

=======================================================================
3. CRON SCHEDULE (cognex-agent VM, all times UTC, Mon-Fri)
=======================================================================

15 3  * * 1-5   = 08:45 IST  Fyers auth reminder -> Telegram message
45 3  * * 1-5   = 09:15 IST  Start RSI2 strategy via run_rsi2.sh
05 10 * * 1-5   = 15:35 IST  pkill -f python3 (stop all)

Commands: crontab -l  (view)  |  crontab -e  (edit)

=======================================================================
4. FYERS DAILY AUTH FLOW
=======================================================================

Step 1 - 08:45 IST (automatic):
  fyers_auto_auth.py sends Telegram:
  "Fyers Action Required - Please login and paste URL back"
  with a clickable login link.

Step 2 - Before 09:15 IST (MANUAL - YOU MUST DO THIS):
  1. Click login link in Telegram
  2. Complete Fyers OAuth in browser
  3. Copy the redirect URL from browser address bar
  4. Reply to Telegram bot: FYERS_AUTH [full redirect url]

Step 3 (automatic):
  Bot extracts auth code, generates token.
  Token saved to: config/fyers_token.json

Step 4 - 09:15 IST (automatic):
  run_rsi2.sh checks token exists, starts strategy_engine.py
  If token missing: strategy does NOT start. Check Telegram.

=======================================================================
5. KEY FILE PATHS (all on cognex-agent VM)
=======================================================================

ROOT DIR   : /home/anijay2021/cognex-agent2/

LAUNCHER   : run_rsi2.sh                        <- cron entry point
MAIN       : main.py                            <- scheduler + loop
STRATEGY   : strategies/strategy_engine.py      <- RSI2+SMA200 engine
SCANNER    : strategies/rsi2_scanner.py         <- signal logic
RISK       : risk/risk_guard.py                 <- risk checks (VIX disabled line 24)
AUTH       : brokers/fyers_auto_auth.py         <- daily Telegram auth
FYERS API  : brokers/fyers_connector.py         <- Fyers API wrapper
SETTINGS   : config/settings.py                 <- all config fields & defaults
ENV FILE   : config/.env                        <- secrets + TRADING_MODE override
TOKEN      : config/fyers_token.json            <- daily OAuth token (auto-written)
DB         : cognex_agent.db                    <- SQLite trade history
DASHBOARD  : dashboard/app.py                   <- web dashboard

LOGS:
  logs/rsi2_scanner_vix_removed.log  <- main live strategy output
  logs/rsi2_auto.log                 <- cron launcher messages
  logs/fyersApi.log                  <- Fyers API call log
  logs/fyersRequests.log             <- raw HTTP request log
  logs/agent.log                     <- general agent log

=======================================================================
6. DIRECTORY STRUCTURE
=======================================================================

cognex-agent2/
  backtest/      rsi2_backtest.py, rsi2_multiexit_backtest.py, result CSVs
  brokers/       angelone_connector.py, fyers_auth.py,
                 fyers_auto_auth.py, fyers_connector.py
  config/        .env, .env.example, fyers_token.json, settings.py
  core/          agent_brain.py, cognex_api_connector.py, database.py,
                 orchestrator_update.py, order_executor.py
  dashboard/     app.py
  logs/          (see section 5)
  news/          news_scout.py
  notify/        telegram_commands.py, telegram_handler.py, telegram_notifier.py
  risk/          risk_guard.py
  strategies/    strategy_engine.py, rsi2_scanner.py
  venv/          Python virtualenv (do not modify)
  main.py
  run_rsi2.sh
  requirements.txt
  cognex_agent.db
  README.md      <- this file

=======================================================================
7. TELEGRAM BOT
=======================================================================

Bot token : config/.env -> TELEGRAM_BOT_TOKEN=...
Chat ID   : config/.env -> TELEGRAM_CHAT_ID=...
Command   : FYERS_AUTH [redirect_url]   (complete daily login)

=======================================================================
8. INACTIVE / STOPPED COMPONENTS
=======================================================================

cognex-agent (V1):
  Path   : /home/anijay2021/cognex-agent/
  Status : NOT in cron. DO NOT restart. Superseded by V2.

Calendar Spread:
  Status : Removed from cron. Code on disk but not scheduled.

VIX ceiling check:
  Status : DISABLED. Commented out in risk/risk_guard.py line 24.
  Re-enable by removing # from:  # self.check_vix(vix),
  Ceiling value: 20.0 (can change in config/settings.py or .env)

=======================================================================
9. COMMON COMMANDS
=======================================================================

# Check if strategy is running
ps aux | grep python3

# View live log
tail -f ~/cognex-agent2/logs/rsi2_scanner_vix_removed.log

# View crontab
crontab -l

# Check token file
ls -la ~/cognex-agent2/config/fyers_token.json

# Manually start strategy
cd ~/cognex-agent2 && ./run_rsi2.sh

# Stop all strategies
pkill -f python3

# Check trading mode (PAPER or LIVE)
grep TRADING_MODE ~/cognex-agent2/config/.env

=======================================================================
10. IMPORTANT NOTES
=======================================================================

- V2 is fully independent of V1. PYTHONPATH is set to . (V2 only).
- All relative file paths in V2 resolve from /home/anijay2021/cognex-agent2/
- Fyers token expires nightly. Re-auth required every trading morning.
- Auth window: 08:45 IST (reminder) to 09:15 IST (strategy start).
- Trading mode defaults to PAPER. Set TRADING_MODE=LIVE in .env for live.
- All cron times in UTC. India offset: UTC+5:30.
