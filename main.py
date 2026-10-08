import os
import requests
import pandas as pd
import pandas_ta as ta
from fastapi import FastAPI, BackgroundTasks, HTTPException
from dhanhq import dhanhq

app = FastAPI(title="Nifty Automated Signal Engine (Dhan)")

# =====================================================================
# CONFIGURATION & ENVIRONMENT VARIABLES
# =====================================================================
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")

# Nifty 50 Constants
NIFTY_SECURITY_ID = "13"       # Dhan Index Security ID for Nifty 50
NIFTY_LOT_SIZE = 65            # Nifty 50 Lot Size (Units)

# Global Dhan Client Instance
dhan = dhanhq(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)

# =====================================================================
# AUTOMATIC TOKEN RENEWAL SYSTEM
# =====================================================================
def auto_renew_token():
    """
    Calls Dhan's /v2/RenewToken endpoint to refresh active token for another 24 hours.
    """
    global DHAN_ACCESS_TOKEN, dhan
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
            dhan = dhanhq(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
            print("✅ [DHAN AUTOMATION] Access token automatically renewed for 24 hours.")
        else:
            print(f"⚠️ [DHAN RENEWAL FAILED] Response: {data}")
    except Exception as e:
        print(f"❌ [DHAN RENEWAL ERROR] {str(e)}")

# =====================================================================
# TRADING ENGINE CYCLE LOGIC
# =====================================================================
def run_trading_engine_cycle():
    print("\n--- [DHAN ENGINE] STRATEGY CYCLE STARTED ---")
    
    # 1. Attempt token renewal before data fetching
    auto_renew_token()

    try:
        # 2. Fetch Intraday 5-Min Market Data from Dhan
        res = dhan.intraday_minute_data(
            security_id=NIFTY_SECURITY_ID,
            exchange_segment="IDX_I",
            instrument_type="INDEX"
        )

        if not res or res.get("status") != "success" or "data" not in res:
            print(f"❌ [DATA FETCH FAILED] Response: {res}")
            return

        # 3. Format DataFrame
        df = pd.DataFrame(res["data"])
        if "start_Time" in df.columns:
            df["datetime"] = pd.to_datetime(df["start_Time"])
        df = df.sort_values("datetime").reset_index(drop=True)

        if len(df) < 30:
            print("⚠️ [INSUFFICIENT CANDLES] Waiting for more historical candles...")
            return

        # 4. Calculate Technical Indicators
        df["EMA_9"] = ta.ema(df["close"], length=9)
        df["EMA_21"] = ta.
