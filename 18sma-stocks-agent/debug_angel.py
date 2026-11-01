"""Diagnostics: python debug_angel.py  (prints raw Angel One responses for one stock)."""
import sys, json, datetime as dt, requests
import main as m

A = m.Angel(m.ENV)
print("login", A.login())
inst = json.load(open(m.INST_FILE))
sym = sys.argv[1] if len(sys.argv) > 1 else "TCS"
tok = inst["eq"][sym]
print(sym, "token", tok)
I = m.IST
r = requests.post(A.HOST + "/rest/secure/angelbroking/market/v1/quote/",
                  json={"mode": "LTP", "exchangeTokens": {"NSE": [str(tok)]}}, headers=A._hdr(), timeout=20)
print("QUOTE", r.status_code, r.text[:300])
now = m.now_ist()
for days in (1, 3, 6):
    frm = (now - dt.timedelta(days=days)).replace(hour=9, minute=15)
    r = requests.post(A.HOST + "/rest/secure/angelbroking/historical/v1/getCandleData",
                      json={"exchange": "NSE", "symboltoken": str(tok), "interval": "FIFTEEN_MINUTE",
                            "fromdate": frm.strftime("%Y-%m-%d %H:%M"), "todate": now.strftime("%Y-%m-%d %H:%M")},
                      headers=A._hdr(), timeout=20)
    print("CANDLES from", frm.strftime("%Y-%m-%d %H:%M"), r.status_code, r.text[:260])
