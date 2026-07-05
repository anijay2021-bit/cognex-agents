"""AngelOne NFO symbol/token resolver via public scrip master. (H3)"""
import os, time, json, requests
from loguru import logger

_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
_CACHE = "/tmp/angel_scripmaster.json"
_MAXAGE = 12 * 3600
_data = None
_loaded_at = 0

def _load():
    global _data, _loaded_at
    if _data is not None and (time.time() - _loaded_at) < _MAXAGE:
        return _data
    try:
        if os.path.exists(_CACHE) and (time.time() - os.path.getmtime(_CACHE)) < _MAXAGE:
            with open(_CACHE) as f:
                _data = json.load(f)
        else:
            r = requests.get(_URL, timeout=60); r.raise_for_status()
            _data = r.json()
            with open(_CACHE, "w") as f:
                json.dump(_data, f)
        _loaded_at = time.time()
        logger.info(f"AngelScrip: loaded {len(_data)} rows")
    except Exception as e:
        logger.error(f"AngelScrip load error: {e}")
        _data = _data or []
    return _data

def resolve(strike, expiry_date, option_type, name="NIFTY"):
    """Return (tradingsymbol, token) for an NFO option, or (None, None)."""
    try:
        exp = expiry_date.strftime("%d%b%Y").upper()
        opt = option_type.upper()
        want = int(round(float(strike))) * 100
        for x in _load():
            if x.get("exch_seg") != "NFO" or x.get("name") != name:
                continue
            if x.get("expiry") != exp:
                continue
            sym = x.get("symbol", "")
            if not sym.endswith(opt):
                continue
            try:
                if int(round(float(x.get("strike", 0)))) != want:
                    continue
            except Exception:
                continue
            return sym, x.get("token")
        logger.warning(f"AngelScrip: no match {name} {strike} {exp} {opt}")
        return None, None
    except Exception as e:
        logger.error(f"AngelScrip resolve error: {e}")
        return None, None
