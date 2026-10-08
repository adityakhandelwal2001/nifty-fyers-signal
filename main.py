import os
import requests
import pandas as pd
import pandas_ta as ta
from fastapi import FastAPI, BackgroundTasks
from dhanhq import dhanhq, DhanContext

app = FastAPI(title="Nifty Institutional Quant Engine (Dhan)")

# =====================================================================
# CONFIGURATION & CREDENTIALS
# =====================================================================
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")

# Nifty 50 Trading Parameters
NIFTY_SECURITY_ID = "13"       # Dhan Security ID for Nifty 50 Index
NIFTY_LOT_SIZE = 65            # 1 Lot = 65 Units

# Initialize Dhan Client using updated DhanContext
dhan_context = DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
dhan = dhanhq(dhan_context)

# =====================================================================
# AUTOMATIC TOKEN RENEWAL
# =====================================================================
def auto_renew_token():
    """Keeps the engine running indefinitely by renewing access tokens."""
    global DHAN_ACCESS_TOKEN, dhan, dhan_context
    url = "https://api.dhan.co/v2/RenewToken"
    headers = {
        "access-token": DHAN_ACCESS_TOKEN,
        "dhanClientId": DHAN_CLIENT_ID
    }
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        if response.status_code == 200 and "accessToken" in data:
            DHAN_ACCESS_TOKEN = data["accessToken"]
            dhan_context = DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
            dhan = dhanhq(dhan_context)
            print("✅ [AUTH] Token automatically renewed for next 24 Hours.")
        else:
            print(f"⚠️ [AUTH WARNING] Renewal response: {data}")
    except Exception as e:
        print(f"❌ [AUTH ERROR] Token renewal failed: {str(e)}")

# =====================================================================
# QUANTITATIVE STRATEGY EXECUTION ENGINE
# =====================================================================
def run_trading_engine_cycle():
    print("\n--- [QUANT ENGINE] INITIATING STRATEGY CYCLE ---")
    auto_renew_token()

    try:
        # 1. Fetch 5-Minute Intraday Data
        res = dhan.intraday_minute_data(
            security_id=NIFTY_SECURITY_ID,
            exchange_segment="IDX_I",
            instrument_type="INDEX"
        )

        if not res or res.get("status") != "success" or "data" not in res:
            print(f"❌ [DATA ERROR] Could not fetch market data: {res}")
            return

        df = pd.DataFrame(res["data"])
        if "start_Time" in df.columns:
            df["datetime"] = pd.to_datetime(df["start_Time"])
        df = df.sort_values("datetime").reset_index(drop=True)

        if len(df) < 50:
            print("⚠️ [INSUFFICIENT CANDLES] Need at least 50 historical candles.")
            return

        # 2. Indicator Calculation Matrix
        df["EMA_9"] = ta.ema(df["close"], length=9)
        df["EMA_21"] = ta.ema(df["close"], length=21)
        df["EMA_50"] = ta.ema(df["close"], length=50)        # Trend Filter
        df["RSI"] = ta.rsi(df["close"], length=14)            # Momentum Filter
        df["VWAP"] = ta.vwap(df["high"], df["low"], df["close"], df["volume"]) # Institutional Value
        df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)     # Volatility Filter
        df["ATR_SMA"] = ta.sma(df["ATR"], length=14)

        st = ta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3)
        df["ST_DIR"] = st["SUPERTd_10_3.0"]

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        spot_price = curr["close"]

        # Log Metrics
        print(f"📊 Spot: {spot_price:.2f} | VWAP: {curr['VWAP']:.2f} | 50 EMA: {curr['EMA_50']:.2f}")
        print(f"📈 RSI: {curr['RSI']:.2f} | Current ATR: {curr['ATR']:.2f} (Avg: {curr['ATR_SMA']:.2f})")

        # 3. Execution Verification Logic
        signal = None

        # Check Volatility Expansion First
        is_volatility_sufficient = curr["ATR"] >= (curr["ATR_SMA"] * 0.90)

        if not is_volatility_sufficient:
            print("🛑 [REJECTED] Volatility (ATR) too low. Market is in theta-decay zone.")
            return

        # INSTITUTIONAL CALL BUY SIGNAL RULES:
        if (curr["close"] > curr["VWAP"] and 
            curr["close"] > curr["EMA_50"] and 
            curr["ST_DIR"] == 1 and
            prev["EMA_9"] <= prev["EMA_21"] and curr["EMA_9"] > curr["EMA_21"] and
            52 <= curr["RSI"] <= 68):
            signal = "BUY_CALL"

        # INSTITUTIONAL PUT BUY SIGNAL RULES:
        elif (curr["close"] < curr["VWAP"] and 
              curr["close"] < curr["EMA_50"] and 
              curr["ST_DIR"] == -1 and
              prev["EMA_9"] >= prev["EMA_21"] and curr["EMA_9"] < curr["EMA_21"] and
              32 <= curr["RSI"] <= 48):
            signal = "BUY_PUT"

        if not signal:
            print("😴 [NO SIGNAL] Market noise detected. Capital preserved.")
            return

        # 4. Strike Selection & Paper Order Execution
        atm_strike = round(spot_price / 50) * 50
        option_type = "CE" if signal == "BUY_CALL" else "PE"

        print(f"\n🚀 🔥 [HIGH-CONFIDENCE TRADE TRIGGERED]: {signal}")
        print(f"🎯 Contract Selected: NIFTY {atm_strike} {option_type}")
        print(f"✅ [PAPER TRADE SIMULATED] Bought {NIFTY_LOT_SIZE} units.")

    except Exception as e:
        print(f"❌ [ENGINE ERROR] Exception during execution cycle: {str(e)}")

# =====================================================================
# FASTAPI ENDPOINTS
# =====================================================================
@app.get("/")
def root():
    return {"status": "Dhan Institutional Quant Engine Active"}

@app.post("/webhook-trigger")
def cron_webhook_trigger(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_trading_engine_cycle)
    return {"status": "Engine cycle launched in background."}

