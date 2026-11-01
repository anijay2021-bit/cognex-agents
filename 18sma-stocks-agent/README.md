# 18SMA-Stocks agent

Scans the NSE F&O stocks in `fno_lot_sizes.csv` on the 15-min timeframe (Angel One data). When a candle
closes above / below its 18 SMA it sends a Telegram alert for the ATM CALL / PUT (option price, TGT, SL),
then tracks the signal (paper) until target / stop-loss / square-off.

* Stocks priced below `min_price` (default Rs 100) are skipped (pre-check on the day's first scan).
* Settings (`settings.json`, edited from the dashboard page `/stocks18.html`): lots, intraday / carry-forward,
  TGT and SL as percent or absolute Rs from the option BUY price, min price, signal mode (cross / always).
* Credentials: `config/.env` (ANGELONE_API_KEY, ANGELONE_CLIENT_ID, ANGELONE_PASSWORD, ANGELONE_TOTP_SECRET,
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID). Not committed.
* Angel One request budget: one candle call per eligible stock per 15-min scan (~0.4 s apart, limit is 3/s),
  quotes batched 50 per call.
* Run: `venv/bin/python main.py` (systemd unit `18sma-stocks-agent.service`).
* Dashboard wiring: `cognex-dashboard/routers/stocks18.py`, `static/stocks18.html`, `patch_dashboard.py`.
