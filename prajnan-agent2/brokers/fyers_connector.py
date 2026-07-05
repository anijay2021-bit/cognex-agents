import json
from datetime import datetime, date
from typing import Optional
from loguru import logger

try:
    from fyers_apiv3 import fyersModel
    FYERS_AVAILABLE = True
except ImportError:
    FYERS_AVAILABLE = False

from config.settings import settings

class FyersDataConnector:
    NIFTY     = "NSE:NIFTY50-INDEX"
    BANKNIFTY = "NSE:NIFTYBANK-INDEX"
    VIX       = "NSE:INDIAVIX-INDEX"
    CRUDE     = "MCX:CRUDEOIL-I"
    USDINR    = "NSE:USDINR-I"

    def __init__(self):
        self.client_id   = settings.fyers_client_id
        self.fyers       = None
        self._connected  = False
        self._token_file = "config/fyers_token.json"

    def connect(self) -> bool:
        if not FYERS_AVAILABLE:
            logger.error("fyers-apiv3 not installed")
            return False
        try:
            token = self._load_token()
            if not token:
                logger.warning("No Fyers token found")
                return False
            self.fyers = fyersModel.FyersModel(
                client_id=self.client_id,
                token=token,
                log_path="logs/"
            )
            profile = self.fyers.get_profile()
            if profile.get("s") == "ok":
                logger.success(f"Fyers connected: {profile['data']['name']}")
                self._connected = True
                return True
            else:
                logger.error(f"Fyers auth failed: {profile}")
                return False
        except Exception as e:
            logger.error(f"Fyers connection error: {e}")
            return False

    def _load_token(self) -> Optional[str]:
        try:
            with open(self._token_file) as f:
                data = json.load(f)
                if data.get("date") == str(date.today()):
                    return data.get("token")
                else:
                    logger.warning("Fyers token expired")
        except FileNotFoundError:
            pass
        return None

    def get_quotes(self, symbols: list) -> dict:
        if not self._connected:
            return {}
        try:
            response = self.fyers.quotes({"symbols": ",".join(symbols)})
            if response.get("s") == "ok":
                quotes = {}
                for item in response.get("d", []):
                    sym = item.get("n", "")
                    v   = item.get("v", {})
                    quotes[sym] = {
                        "ltp":     v.get("lp", 0),
                        "change":  v.get("ch", 0),
                        "chg_pct": v.get("chp", 0),
                        "volume":  v.get("volume", 0),
                        "oi":      v.get("oi", 0),
                    }
                return quotes
            return {}
        except Exception as e:
            logger.error(f"get_quotes error: {e}")
            return {}

    def get_option_chain(self, symbol: str, strike_count: int = 10) -> dict:
        if not self._connected:
            return {}
        try:
            data = {"symbol": symbol, "strikecount": strike_count, "timestamp": ""}
            response = self.fyers.optionchain(data=data)
            if response.get("s") != "ok":
                return {}
            chain_data   = response.get("data", {})
            options_list = chain_data.get("optionsChain", [])
            strikes      = {}
            total_ce_oi  = 0
            total_pe_oi  = 0
            for option in options_list:
                strike   = option.get("strikePrice", 0)
                opt_type = option.get("option_type", "")
                entry = {
                    "ltp":   option.get("ltp", 0),
                    "oi":    option.get("oi", 0),
                    "iv":    option.get("iv", 0),
                    "delta": option.get("delta", 0),
                    "theta": option.get("theta", 0),
                }
                if strike not in strikes:
                    strikes[strike] = {}
                strikes[strike][opt_type] = entry
                if opt_type == "CE":
                    total_ce_oi += entry["oi"]
                elif opt_type == "PE":
                    total_pe_oi += entry["oi"]
            pcr      = round(total_pe_oi / total_ce_oi, 3) if total_ce_oi > 0 else 0
            max_pain = self._calculate_max_pain(strikes)
            oi_walls = self._get_oi_walls(strikes)
            return {
                "underlying_price": chain_data.get("underlyingValue", 0),
                "strikes":    strikes,
                "pcr":        pcr,
                "max_pain":   max_pain,
                "ce_wall":    oi_walls["ce_wall"],
                "pe_wall":    oi_walls["pe_wall"],
                "total_ce_oi": total_ce_oi,
                "total_pe_oi": total_pe_oi,
            }
        except Exception as e:
            logger.error(f"option_chain error: {e}")
            return {}

    def _calculate_max_pain(self, strikes: dict) -> float:
        if not strikes:
            return 0.0
        all_strikes = sorted(strikes.keys())
        min_pain = float("inf")
        max_pain_strike = all_strikes[0]
        for expiry_strike in all_strikes:
            total_pain = 0
            for strike in all_strikes:
                ce_oi = strikes[strike].get("CE", {}).get("oi", 0)
                pe_oi = strikes[strike].get("PE", {}).get("oi", 0)
                if expiry_strike > strike:
                    total_pain += ce_oi * (expiry_strike - strike)
                if expiry_strike < strike:
                    total_pain += pe_oi * (strike - expiry_strike)
            if total_pain < min_pain:
                min_pain = total_pain
                max_pain_strike = expiry_strike
        return max_pain_strike

    def _get_oi_walls(self, strikes: dict) -> dict:
        max_ce_oi = max_pe_oi = ce_wall = pe_wall = 0
        for strike, data in strikes.items():
            ce_oi = data.get("CE", {}).get("oi", 0)
            pe_oi = data.get("PE", {}).get("oi", 0)
            if ce_oi > max_ce_oi:
                max_ce_oi = ce_oi
                ce_wall = strike
            if pe_oi > max_pe_oi:
                max_pe_oi = pe_oi
                pe_wall = strike
        return {"ce_wall": ce_wall, "pe_wall": pe_wall}

    def get_full_market_snapshot(self) -> dict:
        logger.info("Fetching live market snapshot...")
        quotes     = self.get_quotes([self.NIFTY, self.BANKNIFTY, self.VIX, self.CRUDE, self.USDINR])
        nifty_spot = quotes.get(self.NIFTY, {}).get("ltp", 0)
        bnf_spot   = quotes.get(self.BANKNIFTY, {}).get("ltp", 0)
        vix        = quotes.get(self.VIX, {}).get("ltp", 0)
        crude      = quotes.get(self.CRUDE, {}).get("ltp", 0)
        usdinr     = quotes.get(self.USDINR, {}).get("ltp", 0)
        nifty_chain = self.get_option_chain(self.NIFTY, strike_count=10)
        bnf_chain   = self.get_option_chain(self.BANKNIFTY, strike_count=10)
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "nifty": {
                "spot":        nifty_spot,
                "pcr":         nifty_chain.get("pcr", 0),
                "max_pain":    nifty_chain.get("max_pain", 0),
                "ce_wall":     nifty_chain.get("ce_wall", 0),
                "pe_wall":     nifty_chain.get("pe_wall", 0),
                "total_ce_oi": nifty_chain.get("total_ce_oi", 0),
                "total_pe_oi": nifty_chain.get("total_pe_oi", 0),
            },
            "banknifty": {
                "spot":     bnf_spot,
                "pcr":      bnf_chain.get("pcr", 0),
                "max_pain": bnf_chain.get("max_pain", 0),
                "ce_wall":  bnf_chain.get("ce_wall", 0),
                "pe_wall":  bnf_chain.get("pe_wall", 0),
            },
            "vix":       vix,
            "crude_oil": crude,
            "usdinr":    usdinr,
        }
        logger.info(
            f"Nifty:{nifty_spot} BNF:{bnf_spot} VIX:{vix} "
            f"PCR:{nifty_chain.get('pcr',0)} MaxPain:{nifty_chain.get('max_pain',0)}"
        )
        return snapshot

fyers_connector = FyersDataConnector()
