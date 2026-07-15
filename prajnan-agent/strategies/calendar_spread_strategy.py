"""
calendar_spread_strategy.py
----------------------------
Nifty Calendar Spread Strategy — CARRY FORWARD positions.

Lifecycle:
  Monthly expiry day 15:24 → exit all current positions
  Monthly expiry day 15:26 → enter new month (buy monthly CE+PE, sell next weekly CE+PE)
  Each weekly expiry day 15:24 → exit weekly legs
  Each weekly expiry day 15:26 → sell next weekly CE+PE (carry forward)
  Last weekly before monthly expiry 15:26 → sell monthly contract as the weekly leg
  Monthly expiry day 15:24 → exit everything, strategy ends

All positions: CARRYFORWARD (not intraday)
SL check: candle close basis (5-min default, configurable)
State persisted to JSON for crash recovery.

Depends on: strategies/options_selector.py, brokers/fyers_connector.py
"""

import json
import logging
import os
import datetime
from typing import Optional

from strategies.options_selector import (
    select_calendar_legs,
    get_nearest_weekly_expiry,
    get_next_monthly_expiry,
    get_straddle_symbols,
    get_atm_strike,
    get_nifty_spot,
    adjust_for_holiday,
    _last_tuesday_of_month,
    _today_ist,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

STATE_FILE          = os.path.expanduser("~/prajnan-agent/config/calendar_state.json")
BUY_SL_PERCENT      = 5.0       # % drop from hedge buy entry triggers buy SL
LOTS                = 10         # 10 lots = 650 qty
LOT_SIZE            = 65         # Nifty lot size

WEEKLY_EXIT_TIME    = "15:24"    # IST — exit weekly legs on expiry day
ENTRY_TIME          = "15:26"    # IST — enter new positions after exit
MONTHLY_EXIT_TIME   = "15:24"    # IST — exit all on monthly expiry day

SL_CANDLE_TF        = 10          # minutes — candle TF for SL check
SL_CHECK_MODE       = "candle_close"   # "candle_close" or "ltp"
PRODUCT_TYPE        = "CARRYFORWARD"   # Fyers product type for all orders


# ─────────────────────────────────────────────
# STATES
# ─────────────────────────────────────────────

class LegState:
    IDLE    = "IDLE"
    SOLD    = "SOLD"
    BOUGHT  = "BOUGHT"
    EXITED  = "EXITED"


class StrategyPhase:
    NOT_STARTED  = "NOT_STARTED"
    ACTIVE       = "ACTIVE"
    LAST_WEEK    = "LAST_WEEK"    # weekly sell = monthly contract
    COMPLETED    = "COMPLETED"


# ─────────────────────────────────────────────
# STRATEGY CLASS
# ─────────────────────────────────────────────

class CalendarSpreadStrategy:

    def __init__(self, fyers, paper_trading: bool = True):
        self.fyers         = fyers
        self.paper_trading = paper_trading
        self.state         = self._empty_state()
        self._load_state()

    # ── State ──────────────────────────────────────────────────────────────

    def _empty_state(self) -> dict:
        return {
            "phase":           StrategyPhase.NOT_STARTED,
            "atm_strike":      None,
            "weekly_expiry":   None,
            "monthly_expiry":  None,
            "lots":            LOTS,
            "lot_size":        LOT_SIZE,
            "buy_legs": {
                "CE": {"symbol": None, "entry_price": None, "order_id": None, "state": LegState.IDLE},
                "PE": {"symbol": None, "entry_price": None, "order_id": None, "state": LegState.IDLE},
            },
            "sell_legs": {
                "CE": {"symbol": None, "entry_price": None, "order_id": None,
                       "state": LegState.IDLE, "combined_sl": None,
                       "hedge_entry_price": None, "hedge_order_id": None},
                "PE": {"symbol": None, "entry_price": None, "order_id": None,
                       "state": LegState.IDLE, "combined_sl": None,
                       "hedge_entry_price": None, "hedge_order_id": None},
            },
            "combined_entry_price": None,
            "created_date":    str(_today_ist()),
            "last_updated":    None,
        }

    def _save_state(self):
        self.state["last_updated"] = datetime.datetime.now().isoformat()
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(self.state, f, indent=2, default=str)
        logger.info(f"State saved → {STATE_FILE}")

    def _load_state(self):
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                saved = json.load(f)
            # Resume if monthly expiry hasn't passed yet
            monthly = saved.get("monthly_expiry")
            if monthly and datetime.date.fromisoformat(monthly) >= _today_ist():
                self.state = saved
                logger.info(f"Resumed state — phase: {self.state['phase']}, monthly: {monthly}")
            else:
                logger.info("State file expired — starting fresh.")
        else:
            logger.info("No state file — starting fresh.")

    # ── Entry (15:26 on expiry day) ────────────────────────────────────────

    def enter(self):
        """
        Called at 15:26 on monthly expiry day.
        Buys next monthly straddle + sells next weekly straddle.
        All positions are CARRYFORWARD.
        """
        if self.state["phase"] != StrategyPhase.NOT_STARTED:
            logger.warning(f"enter() called but phase={self.state['phase']} — skipping.")
            return

        logger.info("=== CALENDAR SPREAD: ENTERING NEW MONTH ===")

        legs            = select_calendar_legs(self.fyers)
        atm             = legs["atm_strike"]
        weekly_expiry   = legs["weekly_expiry"]
        monthly_expiry  = legs["monthly_expiry"]
        qty             = LOT_SIZE * LOTS

        self.state["atm_strike"]    = atm
        self.state["weekly_expiry"] = weekly_expiry
        self.state["monthly_expiry"]= monthly_expiry

        # 1. BUY monthly straddle (carry forward)
        for otype in ["CE", "PE"]:
            symbol = legs["buy_legs"][otype]
            price  = self._get_ltp(symbol)
            oid    = self._place_order(symbol, "BUY", qty, price)
            self.state["buy_legs"][otype].update({
                "symbol":      symbol,
                "entry_price": price,
                "order_id":    oid,
                "state":       LegState.BOUGHT,
            })
            logger.info(f"BUY monthly {otype}: {symbol} @ ₹{price}")

        # 2. SELL next weekly straddle (carry forward)
        ce_price = pe_price = None
        for otype in ["CE", "PE"]:
            symbol = legs["sell_legs"][otype]
            price  = self._get_ltp(symbol)
            oid    = self._place_order(symbol, "SELL", qty, price)
            self.state["sell_legs"][otype].update({
                "symbol":      symbol,
                "entry_price": price,
                "order_id":    oid,
                "state":       LegState.SOLD,
                "combined_sl": None,
            })
            logger.info(f"SELL weekly {otype}: {symbol} @ ₹{price}")
            if otype == "CE": ce_price = price
            else:             pe_price = price

        # 3. Combined SL = CE_sold_price + PE_sold_price
        combined = round(ce_price + pe_price, 2)
        self.state["combined_entry_price"] = combined
        for otype in ["CE", "PE"]:
            self.state["sell_legs"][otype]["combined_sl"] = combined

        self.state["phase"] = StrategyPhase.ACTIVE
        self._save_state()

        logger.info(f"Entry complete. Combined SL: ₹{combined}")
        self._telegram(
            f"📅 *Calendar Spread ENTERED*\n"
            f"Strike: {atm}\n"
            f"BUY  {legs['buy_legs']['CE']} + {legs['buy_legs']['PE']}\n"
            f"SELL {legs['sell_legs']['CE']} + {legs['sell_legs']['PE']}\n"
            f"Combined SL: ₹{combined}\n"
            f"Weekly expiry : {weekly_expiry}\n"
            f"Monthly expiry: {monthly_expiry}\n"
            f"Mode: {'PAPER' if self.paper_trading else 'LIVE'}"
        )

    # ── Weekly exit 15:24 ──────────────────────────────────────────────────

    def exit_weekly_legs(self):
        """
        Called at 15:24 on weekly expiry day.
        Exits all weekly sell legs regardless of buy/sell state.
        """
        if self.state["phase"] not in (StrategyPhase.ACTIVE, StrategyPhase.LAST_WEEK):
            return

        logger.info("=== WEEKLY EXIT: Squaring off weekly legs ===")
        qty = self.state["lot_size"] * self.state["lots"]

        for otype in ["CE", "PE"]:
            leg = self.state["sell_legs"][otype]
            if leg["state"] == LegState.SOLD:
                price = self._get_ltp(leg["symbol"])
                self._place_order(leg["symbol"], "BUY", qty, price)
                logger.info(f"Covered SELL {otype}: {leg['symbol']} @ ₹{price}")
            elif leg["state"] == LegState.BOUGHT:
                price = self._get_ltp(leg["symbol"])
                self._place_order(leg["symbol"], "SELL", qty, price)
                logger.info(f"Exited BUY hedge {otype}: {leg['symbol']} @ ₹{price}")
            leg["state"] = LegState.EXITED

        self._save_state()
        self._telegram("⏹ *Weekly legs squared off*")

    # ── Weekly roll 15:26 ──────────────────────────────────────────────────

    def roll_weekly(self):
        """
        Called at 15:26 on weekly expiry day.
        Sells next weekly straddle.
        If next weekly == monthly expiry → sells monthly contract as weekly leg.
        """
        if self.state["phase"] not in (StrategyPhase.ACTIVE, StrategyPhase.LAST_WEEK):
            return

        logger.info("=== WEEKLY ROLL: Selling next weekly ===")
        qty            = self.state["lot_size"] * self.state["lots"]
        atm            = self.state["atm_strike"]
        monthly_expiry = datetime.date.fromisoformat(self.state["monthly_expiry"])
        next_weekly    = get_nearest_weekly_expiry()

        # Last week: next weekly IS the monthly expiry
        is_last_week = (next_weekly == monthly_expiry)
        sell_expiry  = monthly_expiry if is_last_week else next_weekly

        if is_last_week:
            logger.info("Last week — selling MONTHLY contract as weekly leg.")
            self.state["phase"] = StrategyPhase.LAST_WEEK

        new_symbols = get_straddle_symbols(sell_expiry, atm)
        ce_price = pe_price = None

        for otype in ["CE", "PE"]:
            symbol = new_symbols[otype]
            price  = self._get_ltp(symbol)
            oid    = self._place_order(symbol, "SELL", qty, price)
            self.state["sell_legs"][otype] = {
                "symbol":            symbol,
                "entry_price":       price,
                "order_id":          oid,
                "state":             LegState.SOLD,
                "combined_sl":       None,
                "hedge_entry_price": None,
                "hedge_order_id":    None,
            }
            logger.info(f"SELL {otype}: {symbol} @ ₹{price}")
            if otype == "CE": ce_price = price
            else:             pe_price = price

        combined = round(ce_price + pe_price, 2)
        self.state["combined_entry_price"] = combined
        for otype in ["CE", "PE"]:
            self.state["sell_legs"][otype]["combined_sl"] = combined

        self.state["weekly_expiry"] = sell_expiry.isoformat()
        self._save_state()

        label = "Monthly-as-Weekly" if is_last_week else "Weekly"
        logger.info(f"Roll done. {label}: {sell_expiry}, SL: ₹{combined}")
        self._telegram(
            f"🔁 *{label} Roll*\n"
            f"SELL {new_symbols['CE']} + {new_symbols['PE']}\n"
            f"New SL: ₹{combined} | Expiry: {sell_expiry}"
        )

    # ── Monthly exit 15:24 on monthly expiry day ───────────────────────────

    def exit_all(self):
        """
        Called at 15:24 on monthly expiry day.
        Exits ALL positions — buy legs + sell legs. Strategy ends.
        """
        logger.info("=== MONTHLY EXIT: Squaring off ALL positions ===")
        qty = self.state["lot_size"] * self.state["lots"]

        for otype in ["CE", "PE"]:
            leg = self.state["sell_legs"][otype]
            if leg["state"] == LegState.SOLD:
                price = self._get_ltp(leg["symbol"])
                self._place_order(leg["symbol"], "BUY", qty, price)
                logger.info(f"Covered SELL {otype}: {leg['symbol']} @ ₹{price}")
            elif leg["state"] == LegState.BOUGHT:
                price = self._get_ltp(leg["symbol"])
                self._place_order(leg["symbol"], "SELL", qty, price)
                logger.info(f"Exited BUY hedge {otype}: {leg['symbol']} @ ₹{price}")
            leg["state"] = LegState.EXITED

        for otype in ["CE", "PE"]:
            leg = self.state["buy_legs"][otype]
            if leg["state"] == LegState.BOUGHT:
                price = self._get_ltp(leg["symbol"])
                self._place_order(leg["symbol"], "SELL", qty, price)
                leg["state"] = LegState.EXITED
                logger.info(f"Exited BUY monthly {otype}: {leg['symbol']} @ ₹{price}")

        self.state["phase"] = StrategyPhase.COMPLETED
        self._save_state()
        logger.info("All positions exited. Month complete.")
        self._telegram("✅ *Calendar Spread: All positions exited. Month complete.*")

    # ── SL Monitor ─────────────────────────────────────────────────────────

    def check_sl(self):
        """Called every 5-min candle close. Checks SL, runs hedge loop."""
        if self.state["phase"] not in (StrategyPhase.ACTIVE, StrategyPhase.LAST_WEEK):
            return
        for otype in ["CE", "PE"]:
            leg = self.state["sell_legs"][otype]
            if leg["state"] == LegState.SOLD:
                self._check_sell_sl(otype, leg)
            elif leg["state"] == LegState.BOUGHT:
                self._check_buy_sl(otype, leg)

    def _check_sell_sl(self, otype, leg):
        ltp = self._get_ltp(leg["symbol"])
        if ltp >= leg["combined_sl"]:
            logger.info(f"SELL SL HIT {otype}: {ltp} >= {leg['combined_sl']}")
            self._exit_sell_enter_hedge(otype, leg)

    def _check_buy_sl(self, otype, leg):
        ltp      = self._get_ltp(leg["symbol"])
        sl_price = round(leg["hedge_entry_price"] * (1 - BUY_SL_PERCENT / 100), 2)
        if ltp <= sl_price:
            logger.info(f"BUY hedge SL HIT {otype}: {ltp} <= {sl_price}")
            self._exit_hedge_enter_sell(otype, leg)

    def _exit_sell_enter_hedge(self, otype, leg):
        qty    = self.state["lot_size"] * self.state["lots"]
        symbol = leg["symbol"]
        self._place_order(symbol, "BUY", qty, self._get_ltp(symbol))
        hedge_price = self._get_ltp(symbol)
        oid         = self._place_order(symbol, "BUY", qty, hedge_price)
        sl_price    = round(hedge_price * (1 - BUY_SL_PERCENT / 100), 2)
        leg.update({"state": LegState.BOUGHT, "hedge_entry_price": hedge_price, "hedge_order_id": oid})
        self._save_state()
        self._telegram(f"🔄 *Hedge SELL→BUY* ({otype})\n{symbol} @ ₹{hedge_price}\nSL: ₹{sl_price}")

    def _exit_hedge_enter_sell(self, otype, leg):
        qty    = self.state["lot_size"] * self.state["lots"]
        symbol = leg["symbol"]
        self._place_order(symbol, "SELL", qty, self._get_ltp(symbol))
        new_price = self._get_ltp(symbol)
        oid       = self._place_order(symbol, "SELL", qty, new_price)
        leg.update({"state": LegState.SOLD, "entry_price": new_price, "order_id": oid,
                    "hedge_entry_price": None, "hedge_order_id": None})
        self._save_state()
        self._telegram(f"🔄 *Hedge BUY→SELL* ({otype})\n{symbol} @ ₹{new_price}\nSL: ₹{leg['combined_sl']}")

    # ── Expiry helpers ─────────────────────────────────────────────────────

    def is_on_weekly_expiry(self) -> bool:
        return str(_today_ist()) == self.state.get("weekly_expiry", "")

    def is_on_monthly_expiry(self) -> bool:
        return str(_today_ist()) == self.state.get("monthly_expiry", "")

    # ── Order + LTP ────────────────────────────────────────────────────────

    def _get_ltp(self, symbol: str) -> float:
        response = self.fyers.quotes({"symbols": symbol})
        if response.get("code") != 200:
            raise RuntimeError(f"LTP fetch failed for {symbol}: {response}")
        return float(response["d"][0]["v"]["lp"])

    def _place_order(self, symbol: str, side: str, qty: int, price: float) -> Optional[str]:
        if self.paper_trading:
            oid = f"PAPER-{side}-{symbol[-8:]}-{datetime.datetime.now().strftime('%H%M%S')}"
            logger.info(f"[PAPER] {side} {qty} x {symbol} @ ₹{price} | {oid}")
            return oid
        order_data = {
            "symbol":       symbol,
            "qty":          qty,
            "type":         2,
            "side":         1 if side == "BUY" else -1,
            "productType":  PRODUCT_TYPE,
            "limitPrice":   0,
            "stopPrice":    0,
            "validity":     "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }
        response = self.fyers.place_order(order_data)
        if response.get("code") != 200:
            raise RuntimeError(f"Order failed: {response}")
        oid = response.get("id", "unknown")
        logger.info(f"[LIVE] {side} {qty} x {symbol} | {PRODUCT_TYPE} | {oid}")
        return oid

    def _telegram(self, message: str):
        try:
            from core.telegram_handler import send_telegram_message
            send_telegram_message(message, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Telegram: {e}")

    def get_status(self) -> dict:
        return {
            "phase":         self.state["phase"],
            "atm_strike":    self.state["atm_strike"],
            "weekly_expiry": self.state["weekly_expiry"],
            "monthly_expiry":self.state["monthly_expiry"],
            "combined_sl":   self.state["combined_entry_price"],
            "product_type":  PRODUCT_TYPE,
            "lots":          LOTS,
            "sell_legs":     {o: {"symbol": l["symbol"], "state": l["state"], "sl": l["combined_sl"]}
                              for o, l in self.state["sell_legs"].items()},
            "buy_legs":      {o: {"symbol": l["symbol"], "state": l["state"], "entry": l["entry_price"]}
                              for o, l in self.state["buy_legs"].items()},
        }
