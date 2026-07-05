from flask import Flask, render_template_string, jsonify
from datetime import datetime, date
import logging
from loguru import logger

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>COGNEX Agent Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: -apple-system, system-ui, sans-serif; background: #0a0a0a; color: #fff; margin: 0; padding: 15px; }
        h1 { font-size: 20px; font-weight: 700; margin: 0 0 15px 0; color: #00d4ff; text-align: center; }
        .subtitle { color: #666; font-size: 13px; text-align: center; margin-bottom: 20px; }
        .card { background: #111; border: 1px solid #222; border-radius: 12px; padding: 15px; margin-bottom: 15px; }
        h2 { font-size: 12px; font-weight: 600; text-transform: uppercase; color: #444; margin: 0 0 12px 0; letter-spacing: 0.5px; }
        .stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .stat { background: #00000033; padding: 10px; border-radius: 8px; border: 1px solid #ffffff05; }
        .stat-label { font-size: 11px; color: #666; margin-bottom: 4px; }
        .stat-value { font-size: 16px; font-weight: 700; }
        .green { color: #00e676; } .red { color: #ff5252; } .blue { color: #00d4ff; } .yellow { color: #ffd600; }
        .trade-card { background: #000; border: 1px solid #ffffff08; border-radius: 8px; padding: 10px; margin-bottom: 8px; }
        .trade-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
        .trade-symbol { font-weight: 600; font-size: 14px; }
        .trade-pnl { font-weight: 600; font-size: 14px; }
        .trade-details { color: #888; font-size: 12px; line-height: 1.6; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 600; }
        .badge-open { background: #1a3a1a; color: #00e676; }
        .badge-closed { background: #2a1a1a; color: #ff5252; }
        .market-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #1a1a1a; }
        .market-row:last-child { border-bottom: none; }
        .market-label { color: #888; font-size: 13px; }
        .market-value { font-size: 13px; font-weight: 500; }
        .refresh-btn { width: 100%; padding: 12px; background: #00d4ff22; border: 1px solid #00d4ff44; color: #00d4ff; border-radius: 8px; font-size: 14px; cursor: pointer; margin-top: 8px; }
        .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
        .dot-green { background: #00e676; }
        .dot-red { background: #ff5252; }
        .last-update { color: #444; font-size: 11px; text-align: center; margin-top: 12px; }
    </style>
</head>
<body>
    <h1>? COGNEX Agent</h1>
    <div class="subtitle" id="mode-badge">Loading...</div>

    <div class="card">
        <h2>Today P&L</h2>
        <div class="stat-grid">
            <div class="stat">
                <div class="stat-label">Net P&L</div>
                <div class="stat-value" id="net-pnl">--</div>
            </div>
            <div class="stat">
                <div class="stat-label">Trades</div>
                <div class="stat-value blue" id="total-trades">--</div>
            </div>
            <div class="stat">
                <div class="stat-label">Winning</div>
                <div class="stat-value green" id="winning">--</div>
            </div>
            <div class="stat">
                <div class="stat-label">Losing</div>
                <div class="stat-value red" id="losing">--</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h2>Live Market</h2>
        <div id="market-data">Loading...</div>
    </div>

    <div class="card">
        <h2>Trades</h2>
        <div id="trades-list">Loading...</div>
    </div>

    <button class="refresh-btn" onclick="loadData()">? Refresh</button>
    <div class="last-update" id="last-update"></div>

    <script>
        async function loadData() {
            try {
                const r = await fetch("/api/dashboard");
                const d = await r.json();

                // P&L
                const pnl = d.pnl;
                const pnlEl = document.getElementById("net-pnl");
                pnlEl.textContent = "Rs" + (pnl >= 0 ? "+" : "") + pnl.toFixed(0);
                pnlEl.className = "stat-value " + (pnl >= 0 ? "green" : "red");
                document.getElementById("total-trades").textContent = d.total;
                document.getElementById("winning").textContent = d.winning;
                document.getElementById("losing").textContent = d.losing;
                document.getElementById("mode-badge").textContent =
                    d.mode + " | VIX: " + d.vix;

                // Market
                let mktHtml = "";
                for (const [k, v] of Object.entries(d.market)) {
                    mktHtml += `<div class="market-row">
                        <span class="market-label">${k}</span>
                        <span class="market-value">${v}</span>
                    </div>`;
                }
                document.getElementById("market-data").innerHTML = mktHtml || "No data";

                // Trades
                let tradesHtml = "";
                if (d.trades.length === 0) {
                    tradesHtml = "<div style='color:#666;text-align:center;padding:20px'>No trades today</div>";
                } else {
                    for (const t of d.trades) {
                        const pnlClass = t.pnl > 0 ? "green" : (t.pnl < 0 ? "red" : "yellow");
                        const pnlStr = t.pnl !== 0 ? "Rs" + (t.pnl >= 0 ? "+" : "") + t.pnl.toFixed(0) : "Open";
                        tradesHtml += `<div class="trade-card">
                            <div class="trade-header">
                                <span class="trade-symbol">${t.symbol}</span>
                                <span class="trade-pnl ${pnlClass}">${pnlStr}</span>
                            </div>
                            <div class="trade-details">
                                ${t.direction} @ Rs${t.entry} | ${t.time}<br>
                                SL: Rs${t.sl} | Target: Rs${t.target || "--"}<br>
                                <span class="badge ${t.status === "OPEN" ? "badge-open" : "badge-closed"}">${t.status}</span>
                            </div>
                        </div>`;
                    }
                }
                document.getElementById("trades-list").innerHTML = tradesHtml;
                document.getElementById("last-update").textContent =
                    "Updated: " + new Date().toLocaleTimeString("en-IN");

            } catch(e) {
                console.error(e);
            }
        }

        loadData();
        setInterval(loadData, 30000);
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)

@app.route("/api/dashboard")
def api_dashboard():
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from core.database import SessionLocal, Trade
        from config.settings import settings

        db = SessionLocal()
        today = str(date.today())
        trades = db.query(Trade).filter(Trade.entry_time >= today).all()
        db.close()

        total   = len(trades)
        winning = len([t for t in trades if (t.pnl_rs or 0) > 0])
        losing  = len([t for t in trades if (t.pnl_rs or 0) < 0])
        pnl     = sum(t.pnl_rs or 0 for t in trades)

        market = {}
        try:
            from brokers.fyers_connector import fyers_connector
            if fyers_connector._connected:
                snap = fyers_connector.get_full_market_snapshot()
                market = {
                    "Nifty":     "{:,.2f}".format(snap.get("nifty", {}).get("spot", 0)),
                    "BankNifty": "{:,.2f}".format(snap.get("banknifty", {}).get("spot", 0)),
                    "VIX":       "{:.2f}".format(snap.get("vix", 0)),
                    "PCR":       "{:.3f}".format(snap.get("nifty", {}).get("pcr", 0)),
                }
                vix = snap.get("vix", 0)
            else:
                vix = 0
        except Exception:
            vix = 0

        trade_list = []
        for t in trades:
            trade_list.append({
                "symbol":    t.symbol or "",
                "direction": t.direction or "BUY",
                "entry":     round(t.entry_price or 0, 2),
                "sl":        round(t.stop_loss_rs or 0, 2),
                "target":    round(getattr(t, "target_rs", 0) or 0, 2),
                "pnl":       round(t.pnl_rs or 0, 2),
                "status":    t.status or "OPEN",
                "time":      t.entry_time.strftime("%H:%M") if t.entry_time else "--",
            })

        return jsonify({
            "total":   total,
            "winning": winning,
            "losing":  losing,
            "pnl":     round(pnl, 2),
            "vix":     vix,
            "mode":    settings.trading_mode,
            "market":  market,
            "trades":  trade_list,
            "date":    today,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def run_dashboard(port=8080):
    logger.info(f"Starting web dashboard on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    run_dashboard()
