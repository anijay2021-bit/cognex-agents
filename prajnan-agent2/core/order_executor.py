"""
COGNEX Agent - Order Executor
Converts strategy signals into AngelOne orders.
Handles both PAPER and LIVE modes.
Also manages stop loss monitoring for open positions.
"""

import time
from datetime import datetime
import pytz
_IST = pytz.timezone('Asia/Kolkata')
def _now_ist():
    return datetime.now(_IST)
from loguru import logger
from core.cognex_api_connector import sync_trade
from config.settings import settings
from brokers.angelone_connector import angelone_connector
from notify.telegram_notifier import telegram
from core.database import SessionLocal, Trade


class OrderExecutor:

    def __init__(self):
        self.open_positions = {}  # symbol -> trade details
        self._load_open_positions()

    def _load_open_positions(self):
        """Reload any OPEN trades from DB into memory on startup (carryforward support)."""
        try:
            from core.database import SessionLocal, Trade
            db = SessionLocal()
            open_trades = db.query(Trade).filter(Trade.status == "OPEN").all()
            db.close()
            for t in open_trades:
                self.open_positions[t.symbol] = {
                    "trade_id":   t.id,
                    "order_id":   t.order_id or "",
                    "entry_price": t.entry_price or 0,
                    "stop_loss":  t.stop_loss_rs or 0,
                    "target":     t.target_rs or 0,
                    "quantity":   t.quantity or 0,
                    "entry_time": t.entry_time,
                    "strategy":   t.strategy_used or "RSI2",
                    "option_type": t.instrument_type or "",
                    "angel_symbol": None,
                    "angel_token": None,
                }
            if open_trades:
                logger.info(f"Reloaded {len(open_trades)} open position(s) from DB: "
                            f"{[t.symbol for t in open_trades]}")
        except Exception as e:
            logger.error(f"Failed to reload open positions: {e}")

    def execute(self, trade: dict) -> bool:
        """
        Execute a trade signal from strategy engine.
        Works in both PAPER and LIVE mode.
        """
        if not trade or trade.get("action") != "TRADE":
            return False

        symbol      = trade.get("symbol", "")
        strike      = trade.get("strike", 0)
        option_type = trade.get("option_type", "")
        entry_price = trade.get("entry_price", 0)
        stop_loss   = trade.get("stop_loss", 0)
        target      = trade.get("target", 0)
        quantity    = trade.get("quantity", 65)
        reasoning   = trade.get("reasoning", "")
        timeframe   = trade.get("timeframe", 1)
        expiry      = trade.get("expiry", "")
        angel_symbol = None
        token = None

        # Check if already in this position
        if symbol in self.open_positions:
            logger.info(f"Already in position: {symbol} — skipping")
            return False

        # Reject zero or invalid entry price
        if entry_price <= 0:
            logger.warning(f"Rejected trade {symbol} — entry price is Rs{entry_price} (zero/invalid)")
            return False

        sync_trade(strategy=trade.get("strategy_used", "UNKNOWN"), symbol=symbol, action="OPENED", pnl=0.0)
        logger.info(
            f"Executing: BUY {symbol} @ Rs{entry_price:.2f} "
            f"SL: Rs{stop_loss:.2f}"
        )

        # Place order
        if settings.is_paper_mode:
            order_result = {
                "status":   True,
                "orderid":  f"PAPER_{int(time.time())}",
                "paper_mode": True
            }
        else:
            # Get AngelOne symbol token
            from brokers.angel_symbols import resolve as _resolve_angel
            from datetime import datetime as _dt2
            _exp = expiry
            if isinstance(_exp, str) and _exp:
                try:
                    _exp = _dt2.strptime(_exp, "%Y-%m-%d").date()
                except Exception:
                    _exp = None
            angel_symbol, token = (None, None)
            if _exp is not None:
                angel_symbol, token = _resolve_angel(strike, _exp, option_type)
            if not token:
                logger.error("LIVE entry aborted: no AngelOne token " + str(strike) + str(option_type))
                telegram.send_message("LIVE entry aborted: no AngelOne token " + str(strike) + str(option_type))
                return False
            # Pre-trade slippage guard: don't chase if the option ran past the cap
            try:
                _cur = angelone_connector.get_ltp("NFO", angel_symbol, token) or 0
            except Exception:
                _cur = 0
            if _cur and entry_price > 0:
                _cap = entry_price * (1 + settings.max_slippage_pct / 100.0)
                if _cur > _cap:
                    logger.warning(f"Entry ABORTED (slippage): {symbol} LTP Rs{_cur:.2f} > cap Rs{_cap:.2f}")
                    telegram.send_message(
                        f"⚠️ <b>Entry skipped — slippage</b>\n{symbol}\n"
                        f"Now Rs{_cur:.2f} > cap Rs{_cap:.2f} ({settings.max_slippage_pct}%)"
                    )
                    return False
            order_result = angelone_connector.place_order(
                symbol     = angel_symbol,
                token      = token,
                qty        = quantity,
                side       = "BUY",
                order_type = "MARKET",
                product    = "INTRADAY"
            )

        if not order_result.get("status"):
            logger.error(f"Order failed: {order_result.get('message')}")
            telegram.send_message(
                f"❌ <b>Order FAILED</b>\n"
                f"{symbol}\n"
                f"Reason: {order_result.get('message', 'Unknown')}"
            )
            return False

        order_id = order_result.get("orderid", "")

        # Confirm the entry actually filled (LIVE): real price, abort on reject, track+alert if ambiguous
        if not settings.is_paper_mode:
            _f = self._confirm_fill(order_id)
            if _f["status"] in ("rejected", "cancelled"):
                logger.error(f"Entry {order_id} {_f['status']} — not tracking {symbol}")
                telegram.send_message(f"❌ <b>Entry {_f['status'].upper()}</b>\n{symbol}\nID: {order_id}")
                return False
            if _f["status"] == "complete" and _f["avg_price"] > 0:
                entry_price = _f["avg_price"]
                logger.info(f"Entry fill confirmed {symbol} @ Rs{entry_price:.2f}")
            else:
                logger.warning(f"Entry {order_id} not confirmed (status={_f['status']}) — tracking; SL will monitor")
                telegram.send_message(f"⚠️ <b>Entry fill unconfirmed</b>\n{symbol} ID {order_id}\nSL will monitor; verify manually")

        # Save to database
        trade_id = self._save_trade(
            symbol, strike, option_type, expiry,
            entry_price, stop_loss, target,
            quantity, order_id, reasoning, timeframe
        )

        # Track open position
        self.open_positions[symbol] = {
            "trade_id":    trade_id,
            "order_id":    order_id,
            "entry_price": entry_price,
            "stop_loss":   stop_loss,
            "target":      target,
            "quantity":    quantity,
            "entry_time":  datetime.now(),
            "strategy":    trade.get("strategy", "RSI2"),
            "option_type": option_type,
            "angel_symbol": angel_symbol,
            "angel_token": token,
        }

        # Send Telegram alert
        mode_tag = "PAPER" if settings.is_paper_mode else "LIVE"
        telegram.send_message(
            f"🎯 <b>{mode_tag} TRADE EXECUTED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"BUY {strike} {option_type} ({expiry})\n"
            f"Entry: Rs{entry_price:.2f}\n"
            f"SL:     Rs{stop_loss:.2f}\n"
            f"Qty:    {quantity} (1 lot)\n"
            f"TF:     {timeframe}min\n"
            f"ID:     {order_id}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>{reasoning[:180]}</i>\n"
            f"{_now_ist().strftime('%d-%b %H:%M IST')}",
        parse_mode='HTML'
        )

        logger.success(f"Trade executed: {order_id}")
        return True

    def monitor_positions(self, fyers_connector=None):
        """Public method — monitors all open positions for SL, target and RSI2 exits"""
        if not self.open_positions:
            return

        # Get Nifty spot for RSI2 exit checks
        nifty_spot = 0
        if fyers_connector and fyers_connector._connected:
            quotes = fyers_connector.get_quotes(["NSE:NIFTY50-INDEX"])
            nifty_spot = quotes.get("NSE:NIFTY50-INDEX", {}).get("ltp", 0)

        # Check RSI2 exits
        from strategies.rsi2_scanner import rsi2_scanner
        for symbol, pos in list(self.open_positions.items()):
            if pos.get("strategy") == "RSI2" and nifty_spot > 0:
                exit_reason = rsi2_scanner.should_exit(pos, nifty_spot)
                if exit_reason:
                    try:
                        quotes = fyers_connector.get_quotes([symbol])
                        ltp = quotes.get(symbol, {}).get("ltp", pos["entry_price"])
                        self._exit_position(symbol, pos, ltp, exit_reason)
                    except Exception as e:
                        logger.error(f"RSI2 exit error {symbol}: {e}")

        # Check SL for all positions
        self._monitor_positions_sl_target(fyers_connector)

    def _monitor_positions_sl_target(self, fyers_connector=None):
        """
        Check open positions against current LTP.
        Exit if SL is hit.
        Call this every minute during market hours.
        """
        if not self.open_positions:
            return

        for symbol, pos in list(self.open_positions.items()):
            try:
                # Current LTP: Fyers first, AngelOne fallback — never silently skip the stop
                ltp = self._option_ltp(symbol, pos, fyers_connector)
                if ltp <= 0:
                    self._sl_blind_alert(symbol)
                    continue

                entry  = pos["entry_price"]
                sl     = pos["stop_loss"]
                target = pos["target"]
                pnl    = (ltp - entry) * pos["quantity"]

                # Check SL hit
                if ltp <= sl:
                    logger.warning(f"SL HIT: {symbol} @ Rs{ltp:.2f}")
                    self._exit_position(symbol, pos, ltp, "SL_HIT")


                else:
                    logger.debug(
                        f"Position: {symbol} LTP={ltp:.2f} "
                        f"PnL=Rs{pnl:.0f} "
                        f"SL={sl:.2f}"
                    )

            except Exception as e:
                logger.error(f"Monitor error {symbol}: {e}")

    def _confirm_fill(self, order_id, retries=6, delay=1.0):
        """Poll the broker order book to classify a fill.
        Returns {status: complete|rejected|cancelled|pending|unknown, avg_price, filled_qty}."""
        import time as _t
        result = {"status": "unknown", "avg_price": 0.0, "filled_qty": 0}
        if not order_id:
            return result
        for _ in range(retries):
            st = angelone_connector.get_order_status(order_id)
            s = (st.get("status") or "").lower()
            if "complete" in s or "executed" in s or "traded" in s:
                return {"status": "complete", "avg_price": st.get("avg_price", 0.0), "filled_qty": st.get("filled_qty", 0)}
            if "reject" in s:
                return {"status": "rejected", "avg_price": 0.0, "filled_qty": 0}
            if "cancel" in s:
                return {"status": "cancelled", "avg_price": 0.0, "filled_qty": 0}
            result["status"] = s or "pending"
            _t.sleep(delay)
        if result["status"] in ("", "unknown", "not_found"):
            result["status"] = "pending"
        return result

    def _option_ltp(self, symbol, pos, fyers_connector=None):
        """Current option LTP: Fyers first, AngelOne fallback. Returns 0.0 if both fail."""
        try:
            if fyers_connector and getattr(fyers_connector, "_connected", False):
                q = fyers_connector.get_quotes([symbol])
                v = q.get(symbol, {}).get("ltp", 0) or 0
                if v > 0:
                    return float(v)
        except Exception as e:
            logger.warning(f"Fyers LTP failed {symbol}: {e}")
        try:
            asym = pos.get("angel_symbol")
            atok = pos.get("angel_token")
            if not (asym and atok):
                from brokers.angel_symbols import resolve as _resolve_angel
                from datetime import datetime as _dt2
                _exp = pos.get("expiry", "")
                if isinstance(_exp, str) and _exp:
                    try:
                        _exp = _dt2.strptime(_exp[:10], "%Y-%m-%d").date()
                    except Exception:
                        _exp = None
                if _exp:
                    asym, atok = _resolve_angel(pos.get("strike", 0) or 0, _exp, pos.get("option_type", ""))
            if asym and atok:
                v = angelone_connector.get_ltp("NFO", asym, atok) or 0
                if v > 0:
                    return float(v)
        except Exception as e:
            logger.warning(f"AngelOne LTP fallback failed {symbol}: {e}")
        return 0.0

    def _sl_blind_alert(self, symbol):
        """Loudly warn (rate-limited) when no price source can value an open position."""
        import time as _t
        last = getattr(self, "_sl_alert_at", {})
        now = _t.time()
        if now - last.get(symbol, 0) > 300:
            logger.error(f"SL BLIND: no LTP for {symbol} from Fyers or AngelOne — stop cannot be checked")
            try:
                telegram.send_message(
                    f"🚨 <b>STOP-LOSS BLIND</b>\n{symbol}\n"
                    f"No live price from Fyers or AngelOne — SL cannot be evaluated. Check the position."
                )
            except Exception:
                pass
            last[symbol] = now
            self._sl_alert_at = last

    def _exit_position(self, symbol: str, pos: dict, exit_price: float, reason: str):
        """Exit a position and update database"""
        try:
            entry  = pos["entry_price"]
            qty    = pos["quantity"]
            pnl    = (exit_price - entry) * qty

            # Place exit order
            if not settings.is_paper_mode:
                angel_symbol = pos.get("angel_symbol")
                token = pos.get("angel_token")
                if not token:
                    logger.error("LIVE exit: no stored AngelOne token for " + str(symbol) + " - square off manually")
                    telegram.send_message("MANUAL EXIT NEEDED: " + str(symbol) + " - no broker token to auto-square-off")
                    return
                _res = angelone_connector.place_order(
                    symbol     = angel_symbol,
                    token      = token,
                    qty        = qty,
                    side       = "SELL",
                    order_type = "MARKET",
                    product    = "INTRADAY"
                )
                if not _res.get("status"):
                    logger.critical(f"EXIT SELL not accepted for {symbol}: {_res.get('message')}")
                    telegram.send_message(f"🚨 <b>EXIT FAILED</b>\n{symbol}\nBroker rejected order — CLOSE MANUALLY")
                    return
                _ef = self._confirm_fill(_res.get("orderid", ""))
                if _ef["status"] in ("rejected", "cancelled"):
                    logger.critical(f"EXIT SELL {_ef['status']} for {symbol}")
                    telegram.send_message(f"🚨 <b>EXIT {_ef['status'].upper()}</b>\n{symbol}\nCLOSE MANUALLY")
                    return
                if _ef["status"] == "complete" and _ef["avg_price"] > 0:
                    exit_price = _ef["avg_price"]
                    pnl = (exit_price - entry) * qty
                elif _ef["status"] not in ("complete",):
                    telegram.send_message(f"⚠️ <b>Exit fill unconfirmed</b>\n{symbol} — verify it squared off")

            # Update database
            db = SessionLocal()
            trade = db.query(Trade).filter(
                Trade.id == pos["trade_id"]
            ).first()
            if trade:
                trade.exit_price = exit_price
                trade.pnl_rs     = pnl
                trade.status     = "CLOSED"
                trade.exit_time  = datetime.utcnow()
                db.commit()
            db.close()

            # Remove from open positions
            del self.open_positions[symbol]

            # Send Telegram alert
            pnl_emoji = "✅" if pnl > 0 else "❌"
            telegram.send_message(
                f"{pnl_emoji} <b>POSITION CLOSED — {reason}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"Symbol: {symbol}\n"
                f"Entry:  Rs{entry:.2f}\n"
                f"Exit:   Rs{exit_price:.2f}\n"
                f"P&L:    Rs{pnl:+.0f}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{_now_ist().strftime('%d-%b %H:%M IST')}"
            )

            logger.info(f"Position closed: {symbol} PnL=Rs{pnl:.0f} ({reason})")
            sync_trade(strategy=pos.get("strategy_used", "UNKNOWN"), symbol=symbol, action="CLOSED", pnl=pnl)

        except Exception as e:
            logger.error(f"Exit position error: {e}")

    def _save_trade(self, symbol, strike, option_type, expiry,
                    entry_price, stop_loss, target, quantity,
                    order_id, reasoning, timeframe) -> int:
        try:
            db = SessionLocal()
            t = Trade(
                symbol          = symbol,
                underlying      = "NIFTY",
                direction       = "BUY",
                instrument_type = option_type,
                strike          = strike,
                quantity        = quantity,
                entry_price     = entry_price,
                stop_loss_rs    = stop_loss,
                target_rs     = target,
                strategy_used   = "RSI2",
                reason          = reasoning,
                mode            = settings.trading_mode,
                status          = "OPEN",
            )
            db.add(t)
            db.commit()
            trade_id = t.id
            db.close()
            return trade_id
        except Exception as e:
            logger.error(f"Save trade error: {e}")
            return 0

    def _get_symbol_token(self, symbol: str) -> str:
        """
        Get AngelOne symbol token for NFO options.
        For now returns empty string — will be populated
        via AngelOne symbol master in Phase 4.
        """
        return ""

    @property
    def position_count(self) -> int:
        return len(self.open_positions)



    def square_off_all(self, connector=None):
        """Exit all open positions at EOD. Called by eod_squareoff()."""
        if not self.open_positions:
            logger.info("square_off_all: no open positions")
            return
        symbols = list(self.open_positions.keys())
        logger.info(f"EOD square-off: closing {len(symbols)} position(s): {symbols}")
        for symbol in symbols:
            pos = self.open_positions.get(symbol)
            if not pos:
                continue
            # Try to get current LTP from connector
            exit_price = pos.get("entry_price", 0.0)
            try:
                if connector is not None and hasattr(connector, "get_ltp"):
                    ltp = connector.get_ltp(symbol)
                    if ltp and ltp > 0:
                        exit_price = ltp
            except Exception as e:
                logger.warning(f"Could not fetch LTP for {symbol}: {e}")
            self._exit_position(symbol, pos, exit_price, "EOD Square-Off")
        logger.info("EOD square-off complete")

order_executor = OrderExecutor()
