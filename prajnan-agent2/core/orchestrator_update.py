# This patches the decision cycle to use live Fyers data
import sys
sys.path.insert(0, '.')

from brokers.fyers_connector import fyers_connector

# Test Fyers connection
print("Connecting to Fyers...")
ok = fyers_connector.connect()
if ok:
    print("Fyers connected successfully")
    snapshot = fyers_connector.get_full_market_snapshot()
    print(f"Nifty: {snapshot['nifty']['spot']}")
    print(f"BankNifty: {snapshot['banknifty']['spot']}")
    print(f"VIX: {snapshot['vix']}")
    print(f"PCR: {snapshot['nifty']['pcr']}")
    print(f"MaxPain: {snapshot['nifty']['max_pain']}")
    print(f"CE Wall: {snapshot['nifty']['ce_wall']}")
    print(f"PE Wall: {snapshot['nifty']['pe_wall']}")
    print(f"Crude: {snapshot['crude_oil']}")
    print(f"USD/INR: {snapshot['usdinr']}")
else:
    print("Fyers connection failed")
