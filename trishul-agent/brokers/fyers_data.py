import json
import pandas as pd
from datetime import date, timedelta
from fyers_apiv3 import fyersModel
import sys
sys.path.insert(0, '/home/anijay2021/trishul-agent')
from config.settings import FYERS_CLIENT_ID

def get_fyers_client():
    with open('/home/anijay2021/trishul-agent/config/fyers_token.json') as f:
        data = json.load(f)
    token = data['token']
    fyers = fyersModel.FyersModel(
        client_id=FYERS_CLIENT_ID,
        token=token,
        log_path="/home/anijay2021/trishul-agent/logs/"
    )
    return fyers

def fetch_candles(symbol, resolution, days=20):
    fyers     = get_fyers_client()
    today     = date.today()
    from_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    to_date   = today.strftime("%Y-%m-%d")
    data = {
        "symbol":      symbol,
        "resolution":  resolution,
        "date_format": "1",
        "range_from":  from_date,
        "range_to":    to_date,
        "cont_flag":   "1"
    }
    response = fyers.history(data=data)
    if response.get('s') != 'ok':
        raise Exception(f"Fyers error: {response}")
    df = pd.DataFrame(
        response['candles'],
        columns=['timestamp','open','high','low','close','volume']
    )
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
    df.set_index('timestamp', inplace=True)
    return df
