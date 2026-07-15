import pandas_ta as ta
import pandas as pd
import sys
sys.path.insert(0, '/home/anijay2021/trishul-agent')
from brokers.fyers_data import fetch_candles

from config.settings import (RSI2_OVERSOLD, RSI2_OVERBOUGHT, REQUIRE_GREEN_CANDLE,
    REQUIRE_RED_CANDLE, VOLUME_FILTER, VOLUME_MULT)

def get_signals():
    try:
        # Daily candles for 200 EMA — need 300 days to ensure 200 valid EMAs
        daily = fetch_candles("NSE:NIFTY50-INDEX", "D", days=300)
        daily['ema200'] = ta.ema(daily['close'], length=200)

        spot_now   = daily['close'].iloc[-1]
        ema200     = daily['ema200'].iloc[-1]

        if pd.isna(ema200):
            print(f"EMA200 not ready yet. Rows: {len(daily)}")
            return None, spot_now, 0

        trend_up   = spot_now > ema200
        trend_down = spot_now < ema200

        # 15-min candles for entry signals
        intraday = fetch_candles("NSE:NIFTY50-INDEX", "15", days=15)
        intraday['sma10'] = ta.sma(intraday['close'], length=10)
        intraday['rsi2']  = ta.rsi(intraday['close'], length=2)

        last       = intraday.iloc[-1]
        prev       = intraday.iloc[-2]
        sma10      = last['sma10']
        rsi2       = last['rsi2']
        close      = last['close']

        if pd.isna(sma10) or pd.isna(rsi2):
            print(f"Indicators not ready. SMA10: {sma10} RSI2: {rsi2}")
            return None, spot_now, 0

        stretched_down = close < sma10
        oversold       = rsi2 < RSI2_OVERSOLD
        confirm_green  = (prev['close'] > prev['open']) if REQUIRE_GREEN_CANDLE else True

        stretched_up   = close > sma10
        overbought     = rsi2 > RSI2_OVERBOUGHT
        confirm_red    = (prev['close'] < prev['open']) if REQUIRE_RED_CANDLE else True

        avg_vol        = intraday['volume'].rolling(20).mean().iloc[-2]
        normal_volume  = (prev['volume'] < avg_vol * VOLUME_MULT) if VOLUME_FILTER else True

        print(f"Spot: {spot_now:.0f} | EMA200: {ema200:.0f} | SMA10: {sma10:.0f} | RSI2: {rsi2:.1f}")
        print(f"Trend: {'UP' if trend_up else 'DOWN'} | Stretched: {'DOWN' if stretched_down else 'UP' if stretched_up else 'NO'}")

        if trend_up and stretched_down and oversold and confirm_green:
            return 'CE', spot_now, rsi2
        elif trend_down and stretched_up and overbought and confirm_red and normal_volume:
            return 'PE', spot_now, rsi2
        else:
            return None, spot_now, rsi2

    except Exception as e:
        print(f"Signal error: {e}")
        return None, 0, 0
