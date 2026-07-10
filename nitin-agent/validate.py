"""Validate every watchlist symbol against Fyers quotes; print invalid ones."""
import json, sys, time
from fyers_apiv3 import fyersModel

CLIENT_ID = "FX2G3F1GB9-100"
TOKEN = "/home/anijay2021/prajnan-agent/config/fyers_token.json"
fy = fyersModel.FyersModel(token=json.load(open(TOKEN))["token"],
                           is_async=False, client_id=CLIENT_ID, log_path="")
syms = [l.strip() for l in open(sys.argv[1])
        if l.strip() and not l.startswith("#")]
ok, bad = set(), []
for i in range(0, len(syms), 40):
    chunk = syms[i:i + 40]
    r = fy.quotes({"symbols": ",".join(chunk)})
    for q in r.get("d", []):
        if q.get("s") == "ok" and q.get("v", {}).get("lp") is not None:
            ok.add(q["n"])
    time.sleep(0.3)
bad = [s for s in syms if s not in ok]
print(f"total={len(syms)} valid={len(ok)} invalid={len(bad)}")
for b in bad:
    print("INVALID:", b)
