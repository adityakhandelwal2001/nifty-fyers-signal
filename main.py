import os
import pandas as pd
import pandas_ta as ta
from fastapi import FastAPI, BackgroundTasks
from fyers_apiv3 import fyersModel

app = FastAPI(title="Fyers Institutional Signal & Execution Engine")

# Load Environment Variables from Render
CLIENT_ID = os.getenv("FYERS_CLIENT_ID", "HHU4NGXBX2-100")
ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN")

# Initialize Fyers Model
fyers = fyersModel.FyersModel(
    client_id=CLIENT_ID, 
    token=ACCESS_TOKEN, 
    is_async=False, 
    log_path=""
)

# -------------------------------------------------------------------
# 1. OPTION CHAIN OI MICROSTRUCTURE VALIDATOR
# -------------------------------------------------------------------
def validate_oi_microstructure(signal_type: str, symbol: str = "NSE:NIFTY50-INDEX") -> bool:
    """
    Validates institutional support via Option Chain Open Interest (OI) analysis.
    """
    try:
        data = {"symbol": symbol, "strikecount": 10, "timestamp": ""}
        response = fyers.optionchain(data=data)
        
        if response.get("code") != 200 or "data" not in response:
            print("Failed to fetch option chain data:", response)
            return False

        options_data = response["data"]["optionsChain"]
        df = pd.DataFrame(options_data)

        # Separate Call (CE) and Put (PE) data
        ce_df = df[df["option_type"] == "CE"]
        pe_df = df[df["option_type"] == "PE"]

        total_ce_oi_change = ce_df["chg_oi"].sum()
        total_pe_oi_change = pe_df["chg_oi"].sum()

        # Calculate Put-Call Ratio (PCR) based on Change in OI
        pcr_oi_change = total_pe_oi_change / total_ce_oi_change if total_ce_oi_change != 0 else 1.0

        print(f"--- OI ANALYSIS ---")
        print(f"Total CE Change in OI: {total_ce_oi_change}")
        print(f"Total PE Change in OI: {total_pe_oi_change}")
        print(f"PCR (Change in OI): {pcr_oi_change:.2f}")

        # Institutional Filter Conditions:
        if signal_type == "BUY":
            # For LONG: Put Writing (Support) must significantly exceed Call Writing
            if pcr_oi_change >= 1.25:
                print(">>> OI CONFIRMED: Strong Institutional Put Writing (Bullish Support).")
                return True
            else:
                print(">>> OI REJECTED: Lack of Put Writing support for Long trade.")
                return False

        elif signal_type == "SELL":
            # For SHORT: Call Writing (Resistance) must dominate Put Writing
            if pcr_oi_change <= 0.75:
                print(">>> OI CONFIRMED: Strong Institutional Call Writing (Bearish Resistance).")
                return True
            else:
                print(">>> OI REJECTED: Lack of Call Writing resistance for Short trade.")
                return False

    except Exception as e:
        print(f"Error in OI validation: {str(e)}")
        return False

# -------------------------------------------------------------------
# 2. AUTOMATED ORDER EXECUTION ENGINE
# -------------------------------------------------------------------
def execute_fyers_order(option_symbol: str, side: int, qty: int = 50):
    """
    Executes Market Order directly via Fyers API v3.
    side: 1 for BUY, -1 for SELL
    """
    order_data = {
        "symbol": option_symbol,
        "qty": qty,
        "type": 2,          # Market Order
        "side": side,       # 1: Buy, -1: Sell
        "productType": "INTRADAY",
        "limitPrice": 0,
        "stopPrice": 0,
        "validity": "DAY",
        "disclosedQty": 0,
        "offlineOrder": False
    }
    
    response = fyers.place_order(data=order_data)
    print("--- ORDER EXECUTION RESPONSE ---", response)
    return response

# -------------------------------------------------------------------
# 3. CORE STRATEGY & ENGINE APIS
# -------------------------------------------------------------------
def run_trading_engine_cycle():
    """
    Core loop: Calculates technical indicators, checks OI, and executes trades.
    """
    # Example Technical Strategy: Fetch Nifty Spot 5-min candles
    hist_data = {
        "symbol": "NSE:NIFTY50-INDEX",
        "resolution": "5",
        "date_format": "0",
        "range_from": "1696118400",
        "range_to": "1790000000",
        "cont_flag": "1"
    }
    
    candles = fyers.history(data=hist_data)
    if candles.get("code") == 200 and "candles" in candles:
        df = pd.DataFrame(candles["candles"], columns=["timestamp", "open", "high", "low", "close", "volume"])
        
        # Calculate Technical Indicators (e.g., EMA Crossover)
        df["EMA_9"] = ta.ema(df["close"], length=9)
        df["EMA_21"] = ta.ema(df["close"], length=21)
        
        latest = df.iloc[-1]
        previous = df.iloc[-2]

        # Trigger Signal Logic
        signal = None
        if previous["EMA_9"] <= previous["EMA_21"] and latest["EMA_9"] > latest["EMA_21"]:
            signal = "BUY"
        elif previous["EMA_9"] >= previous["EMA_21"] and latest["EMA_9"] < latest["EMA_21"]:
            signal = "SELL"

        print(f"Technical Indicator Check complete. Signal: {signal}")

        if signal:
            # Filter signal against live Fyers Option Chain OI Microstructure
            is_valid = validate_oi_microstructure(signal_type=signal)
            
            if is_valid:
                # Replace with target ATM Option Contract Symbol logic
                target_option = "NSE:NIFTY24OCT25000CE" if signal == "BUY" else "NSE:NIFTY24OCT25000PE"
                execute_fyers_order(option_symbol=target_option, side=1, qty=50)

@app.get("/")
def root():
    return {"status": "Live", "engine": "Native Python Fyers Signal Validator"}

@app.post("/webhook-trigger")
def process_signal(background_tasks: BackgroundTasks):
    """
    Endpoint for triggering strategy verification and execution cycles.
    """
    background_tasks.add_task(run_trading_engine_cycle)
    return {"status": "Accepted", "message": "Signal cycle queued for processing."}

