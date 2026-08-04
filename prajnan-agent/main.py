import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import time, signal, schedule, threading
from datetime import datetime
from zoneinfo import ZoneInfo
from loguru import logger
from config.settings import settings
from core.database import init_db
from brokers.fyers_connector import fyers_connector
from notify.telegram_commands import SimpleCommandChecker
from notify.telegram_notifier import telegram
_last_signal_key = None  # dedup: prevents repeat Telegram notifications
from strategies.rsi2_scanner import rsi2_scanner
from dashboard.app import run_dashboard

IST = ZoneInfo("Asia/Kolkata")


class CognexOrchestrator:
    def __init__(self):
        self.running = True
        self.paused = False
        self.cmd_checker = None

    def _is_market_open(self) -> bool:
        now = datetime.now(IST)
        if now.weekday() >= 5:   # Sat=5, Sun=6
            return False
        market_open  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return market_open <= now <= market_close

    def decision_cycle(self):
        try:
            if not self._is_market_open():
                logger.debug("Market closed — skipping decision cycle")
                return

            quotes = fyers_connector.get_quotes([fyers_connector.NIFTY])
            nifty_spot = quotes.get(fyers_connector.NIFTY, {}).get("ltp", 0)
            if not nifty_spot:
                logger.warning("decision_cycle: could not fetch Nifty spot price")
                return

            rsi2_scanner.fyers = fyers_connector.fyers

            # -- ONE-TRADE-AT-A-TIME + EXIT GATE ---------------------------------
            # If RSI2 trade is already open: check exit only, skip new entries
            sig = None
            _open_rsi2 = None
            try:
                from core.database import SessionLocal as _SL_g, Trade as _T_g
                _gdb = _SL_g()
                _open_rsi2 = _gdb.query(_T_g).filter(
                    _T_g.status == 'OPEN', _T_g.strategy_used == 'RSI2'
                ).first()
                _gdb.close()
            except Exception as _ge:
                logger.warning(f"DB open-trade check failed: {_ge}")

            if _open_rsi2:
                # Already holding RSI2 position -- only check exit conditions
                _pos = {
                    "option_type": getattr(_open_rsi2, 'instrument_type', None) or 'CE',
                    "symbol": _open_rsi2.symbol,
                }
                _exit_reason = rsi2_scanner.should_exit(_pos, nifty_spot)
                if _exit_reason:
                    try:
                        _xq = fyers_connector.get_quotes([_open_rsi2.symbol])
                        _xp = _xq.get(_open_rsi2.symbol, {}).get("ltp", 0)
                    except Exception:
                        _xp = 0
                    sig = {
                        "action":        "EXIT",
                        "symbol":        _open_rsi2.symbol,
                        "rsi2":          0,
                        "ema200":        0,
                        "spot":          nifty_spot,
                        "exit_price":    _xp,
                        "reason":        _exit_reason,
                        "strategy_used": "RSI2",
                    }
                    logger.info(f"RSI2 EXIT signal: {_exit_reason} | {_open_rsi2.symbol} @ Rs{_xp:.2f}")
                else:
                    logger.debug(f"RSI2 holding {_open_rsi2.symbol} -- no exit yet")
            else:
                # No open RSI2 trade -- scan for new entry signal
                sig = rsi2_scanner.scan(nifty_spot)


            # Strategy 2 — EMA+OBV (only if RSI2 has no signal)
            if not sig and not _open_rsi2:
                from strategies.ema_obv_scanner import ema_obv_scanner
                ema_obv_scanner.update_fyers(fyers_connector.fyers)
                ema_sig = ema_obv_scanner.scan(spot_price=nifty_spot)
                if ema_sig and ema_sig.get("action") == "BUY":
                    from strategies.options_selector import get_option_details
                    strike  = ema_sig.get("strike", 0)
                    expiry  = ema_sig.get("expiry", "")
                    direction = ema_sig.get("direction", "CE")
                    # Build correct option symbol
                    from utils.expiry_calculator import get_expiry_dates
                    _exp    = get_expiry_dates()
                    _wstr   = _exp["weekly"].strftime("%y%b%d").upper()
                    symbol  = f"NSE:NIFTY{_wstr}{strike}{direction}"
                    # Fetch actual option LTP
                    _quotes = fyers_connector.get_quotes([symbol])
                    ep      = _quotes.get(symbol, {}).get("ltp", 0)
                    if ep <= 0:
                        logger.warning(f"EMA+OBV: Could not fetch LTP for {symbol} — skipping signal")
                        sig = None
                    else:
                        logger.info(f"EMA+OBV: Fetched actual LTP {ep} for {symbol}")
                    sig = {
                        "action":        "TRADE",
                        "strategy":      "EMA_OBV",
                        "symbol":        symbol,
                        "direction":     direction,
                        "strike":        strike,
                        "expiry":        str(expiry),
                        "quantity":      ema_sig.get("quantity", 650),
                        "entry_price":   ep,
                        "target_price":  round(ep * 1.5, 2),
                        "stop_price":    round(ep * 0.70, 2),
                        "rsi2":          ema_sig.get("rsi2", 0),
                        "ema200":        0,
                        "spot":          nifty_spot,
                        "reasoning":     ema_sig.get("reason", "EMA+OBV signal"),
                        "strategy_used": "EMA_OBV"
                    }
                    logger.info(f"EMA+OBV Signal: {sig}")

            if sig:
                logger.info(f"Signal generated: {sig}")
                if sig.get("action")=="TRADE":
                    ep=sig.get("entry_price",0)
                    if ep == 0:  # scanner did not set entry_price -- fetch live LTP from Fyers
                        try:
                            _ltp_q = fyers_connector.get_quotes([sig['symbol']])
                            ep = _ltp_q.get(sig['symbol'], {}).get("ltp", 0)
                            if ep:
                                logger.info(f"LTP fetched for {sig['symbol']}: Rs {ep:.2f}")
                            else:
                                logger.warning(f"LTP fetch returned 0 for {sig['symbol']}")
                        except Exception as _ltp_e:
                            logger.warning(f"Could not fetch LTP for {sig['symbol']}: {_ltp_e}")
                    sig["entry_price"] = ep   # persist fetched LTP so the trade records and the one-trade gate engages
                    ep_str=f"Rs {ep:.2f}" if ep else "N/A"
                    strategy_used=sig.get("strategy_used","RSI2")
                    if strategy_used=="EMA_OBV":
                        msg=(
                            "\U0001f4c8 *EMA+OBV Signal*\n"
                            f"Symbol: {sig['symbol']}\n"
                            f"Direction: {sig['direction']}\n"
                            f"Entry: Rs {ep:.2f}\n"
                            f"Target: Rs {sig.get('target_price',0):.2f} (1.5x)\n"
                            f"Stop: Rs {sig.get('stop_price',0):.2f} (30% loss)\n"
                            f"Spot: {sig['spot']:.0f}\n"
                            f"Reason: {sig['reasoning']}"
                        )
                    else:
                        msg=(
                            "\U0001f4ca *RSI2 Signal*\n"
                            f"Action: {sig['action']}\n"
                            f"Symbol: {sig['symbol']}\n"
                            f"Direction: {sig['direction']}\n"
                            f"Entry Price: {ep_str}\n"
                            f"RSI2: {sig['rsi2']:.2f}  |  EMA200: {sig['ema200']:.0f}\n"
                            f"Spot: {sig['spot']:.0f}\n"
                            f"Reason: {sig['reasoning']}"
                        )
                elif sig.get("action")=="EXIT":
                    msg=(
                        f"\U0001f6d1 *RSI2 EXIT*\n"
                        f"Symbol: {sig['symbol']}\n"
                        f"Exit Price: Rs {sig.get('exit_price',0):.2f}\n"
                        f"RSI2: {sig['rsi2']:.2f}  |  EMA200: {sig['ema200']:.0f}\n"
                        f"Spot: {sig['spot']:.0f}\n"
                        f"Reason: {sig['reason']}"
                    )
                else:
                    msg=f"*RSI2* Action:{sig.get('action')}"
                global _last_signal_key
                _sig_key = (sig.get('symbol'), sig.get('action'), sig.get('direction'))
                if _sig_key == _last_signal_key:
                    logger.info(f"Skipping duplicate signal notification: {_sig_key}")
                else:
                    _last_signal_key = None if sig.get('action') == 'EXIT' else _sig_key
                    telegram.send_message(msg)
                try:
                    from core.database import SessionLocal, Trade as _T
                    from datetime import datetime as _dt
                    _db=SessionLocal()
                    if sig.get('action')=='TRADE':
                        _ep = sig.get('entry_price', 0.0)
                        _already_open = _db.query(_T).filter(
                            _T.status=='OPEN',
                            _T.strategy_used=='RSI2'
                        ).first()
                        if _ep <= 0:
                            logger.warning(f"TRADE SKIPPED: entry_price=0 for {sig['symbol']} — Fyers LTP not ready")
                        elif _already_open:
                            logger.warning(f"TRADE SKIPPED: RSI2 already has open position {_already_open.symbol}")
                        else:
                            _t=_T(symbol=sig['symbol'],instrument_type='OPT',
                                  underlying='NIFTY',strike=float(sig.get('strike',0)),
                                  expiry=sig.get('expiry',''),direction=sig['direction'],
                                  quantity=sig.get('quantity',0),
                                  entry_price=_ep,
                                  entry_time=_dt.utcnow(),status='OPEN',
                                  strategy_used=sig.get('strategy_used','RSI2'),
                                  mode='PAPER' if settings.is_paper_mode else 'LIVE')
                            _db.add(_t); _db.commit()
                    elif sig.get('action')=='EXIT':
                        _ot=_db.query(_T).filter(_T.symbol==sig['symbol'],
                             _T.status=='OPEN').order_by(_T.entry_time.desc()).first()
                        if _ot:
                            _xp=sig.get('exit_price',0)
                            _ot.exit_price=_xp
                            _ot.exit_time=_dt.utcnow()
                            _ot.pnl_rs=round((_xp-(_ot.entry_price or 0))*(_ot.quantity or 0),2)
                            _ot.status='CLOSED'
                            _ot.reason=sig.get('reason','')
                            _db.commit()
                        logger.info(f"TRADE CLOSED DB: {_ot.symbol} pnl=Rs{_ot.pnl_rs}")
                    else:
                        logger.warning(f"EXIT: no OPEN trade in DB for {sig.get('symbol','')}")
                    try:
                        from strategies.rsi2_scanner import rsi2_scanner as _rs2
                        _rs2.active_signal = None
                    except Exception:
                        pass
                    _db.close()
                except Exception as _e: logger.error(f'DB trade error: {_e}')
            else:
                logger.info(f"decision_cycle: no signal. Nifty spot={nifty_spot:.0f}")

        except Exception as e:
            logger.error(f"decision_cycle error: {e}")

    def _run_telegram_listener(self):
        logger.info("\U0001f916 Connecting to Telegram...")
        try:
            self.cmd_checker = SimpleCommandChecker(orchestrator=self)
            while True:
                self.cmd_checker.check_commands()
                time.sleep(3)
        except Exception as e:
            logger.error(f"Telegram listener error: {e}")

    def start(self):
        logger.info("\U0001f680 Prajñān Agent Starting...")
        init_db()
        threading.Thread(target=run_dashboard, args=(9090,), daemon=True).start()
        threading.Thread(target=self._run_telegram_listener, daemon=True).start()

        from brokers.fyers_auto_auth import is_token_valid, send_auth_reminder
        if not is_token_valid():
            logger.warning("Fyers token expired — sending auth reminder")
            send_auth_reminder()

        fyers_connector.connect()

        # STARTUP: restore active_signal from last OPEN trade in DB
        try:
            from core.database import SessionLocal, Trade as _T
            _db = SessionLocal()
            _open = _db.query(_T).filter(_T.status == "OPEN").order_by(_T.entry_time.desc()).first()
            if _open:
                _opt = "CE" if (_open.symbol or "").endswith("CE") else "PE"
                rsi2_scanner.active_signal = {"option_type": _opt, "symbol": _open.symbol}
                logger.info(f"STARTUP: Restored active_signal {_opt} {_open.symbol}")
            _db.close()
        except Exception as _e:
            logger.error(f"STARTUP restore error: {_e}")

        # Register the decision cycle job
        schedule.every(settings.decision_cycle_minutes).minutes.do(self.decision_cycle)
        schedule.every().day.at("09:55").do(self.eod_squareoff)  # 15:25 IST EOD square-off
        logger.info(
            f"\u23f0 Decision cycle scheduled every "
            f"{settings.decision_cycle_minutes} minutes"
        )
        logger.info("\u2705 Prajñān Agent is running")
        _mode_str = "\U0001f4dd PAPER" if settings.is_paper_mode else "\U0001f534 LIVE"
        telegram.send_message(
            f"\U0001f680 Prajñān Agent Started\n"
            f"Mode: {_mode_str}\n"
            "Strategies: RSI2 + EMA+OBV\n"
            "Data: Fyers | Exec: AngelOne\n"
            "Account: Kiran (r14592)\n"
            "I am watching the markets!"
        )
        from risk.risk_guard import risk_guard as _rg
        if _rg.is_emergency_stopped():
            self.paused = True
            logger.critical('EMERGENCY STOP flag present at startup - starting PAUSED')
        while self.running:
            try:
                if _rg.is_emergency_stopped():
                    self.paused = True
                if not self.paused:
                    schedule.run_pending()
                time.sleep(1)
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                time.sleep(5)

    def eod_squareoff(self):
        """Force-close any OPEN positions at end of day (15:25 IST)."""
        try:
            from core.database import SessionLocal, Trade as _T
            from datetime import datetime as _dt
            _db = SessionLocal()
            open_trades = _db.query(_T).filter(_T.status == "OPEN").all()
            if not open_trades:
                _db.close(); logger.info("EOD square-off: no open positions"); return
            for _t in open_trades:
                try:
                    _q = fyers_connector.get_quotes([_t.symbol])
                    _xp = _q.get(_t.symbol, {}).get("ltp", 0) or (_t.entry_price or 0)
                except Exception:
                    _xp = _t.entry_price or 0
                _t.exit_price = _xp
                _t.exit_time = _dt.utcnow()
                _t.pnl_rs = round((_xp - (_t.entry_price or 0)) * (_t.quantity or 0), 2)
                _t.status = "CLOSED"
                _t.reason = "EOD square-off"
                telegram.send_message(f"EOD Square-Off: {_t.symbol} exit Rs{_xp:.2f} pnl Rs{_t.pnl_rs:.0f}")
            _db.commit(); _db.close()
            try:
                rsi2_scanner.active_signal = None
            except Exception:
                pass
            logger.info(f"EOD square-off closed {len(open_trades)} position(s)")
        except Exception as _e:
            logger.error(f"EOD square-off error: {_e}")

    def shutdown(self):
        self.running = False
        logger.info("Shutdown complete.")


def _handle_signal(sig, frame):
    logger.info(f"Signal {sig} received — shutting down")
    orchestrator.shutdown()


if __name__ == "__main__":
    orchestrator = CognexOrchestrator()
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    orchestrator.start()
