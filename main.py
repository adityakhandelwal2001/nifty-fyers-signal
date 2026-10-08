import os
import math
from datetime import datetime, date, timedelta
import pandas as pd
import pandas_ta as ta
from fastapi import FastAPI, BackgroundTasks
from fyers_apiv3 import fyersModel

app = FastAPI(title="Nifty Institutional Quantitative Engine")

CLIENT_ID = os.getenv("FYERS_CLIENT_ID", "HHU4NGXBX2-100")
ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN")

fyers = fyersModel.FyersModel(
    client_id=CLIENT_ID, 
    token=ACCESS_TOKEN, 
    is_async=False, 
    log_path=""
)

# -------------------------------------------------------------------
# 1. DYNAMIC SYMBOL & OPTION CHAIN SELECTOR
# -------------------------------------------------------------------
def get_active_nifty_expiry_symbol(spot_price: float, option_type: str) -> str:
    """
    Finds nearest 50-strike ATM option and formats Fyers v3 symbol format.
    """
    atm_strike = int(round(spot_price / 50.0) * 50)
    
    # Calculate current or next Thursday
    today = date.today()
    days_until_thursday = (3 - today.weekday()) % 7
    expiry_date = today + timedelta(days=days_until_thursday)
    
    # Format: NSE:NIFTYYYMNDDSTRIKECE/PE
    # Example: NSE:NIFTY26OCT25000CE
    symbol = f"NSE:NIFTY{expiry_date.strftime('%y%b').upper()}{atm_strike}{option_type}"
    return symbol, atm_strike

# -------------------------------------------------------------------
# 2. INSTITUTIONAL OI MICROSTRUCTURE VALIDATOR
# -------------------------------------------------------------------
def validate_institutional_oi(signal_type: str, atm_strike: int) -> bool:
    try:
        data = {"symbol": "NSE:NIFTY50-INDEX", "strikecount": 10, "timestamp": ""}
        response = fyers.optionchain(data=data)
        
        if response.get("code") != 200 or "data" not in response:
            print("Failed to fetch option chain:", response)
            return False

        chain = pd.DataFrame(response["data"]["optionsChain"])
        
        # Focus on +/- 5 strikes around ATM
        relevant_strikes = [atm_strike + (i * 50) for i in range(-5, 6)]
        filtered_chain = chain[chain["strike_price"].isin(relevant_strikes)]

        ce_df = filtered_chain[filtered_chain["option_type"] == "CE"]
        pe_df = filtered_chain[filtered_chain["option_type"] == "PE"]

        ce_oi_chg = ce_df["chg_oi"].sum()
        pe_oi_chg = pe_df["chg_oi"].sum()

        pcr_chg = pe_oi_chg / ce_oi_chg if ce_oi_chg > 0 else 1.0

        # Maximum Call OI Strike (Major Wall)
        max_ce_oi_strike = ce_df.loc[ce_df['oi'].idxmax()]['strike_price'] if not ce_df.empty else 0

        print(f"[OI CHECK] PE Chg: {pe_oi_chg} | CE Chg: {ce_oi_chg} | PCR Chg: {pcr_chg:.2f}")

        if signal_type == "BUY_CALL":
            # Require Put writing > Call writing AND not directly below heavy Call Wall
            if pcr_chg >= 1.40 and (max_ce_oi_strike - atm_strike) > 50:
                print(">>> OI VALIDATED: Heavy Put Support confirmed.")
                return True
            else:
                print(">>> OI REJECTED: Low Put writing or Call Wall Resistance headwind.")
                return False

        elif signal_type == "BUY_PUT":
            # Require Call writing > Put writing
            if pcr_chg <= 0.71:
                print(">>> OI VALIDATED: Heavy Call Resistance confirmed.")
                return True
            else:
                print(">>> OI REJECTED: Lack of Call writing dominance.")
                return False

    except Exception as e:
        print(f"Error in OI validation: {str(e)}")
        return False

# -------------------------------------------------------------------
# 3. ADVANCED MULTI-TIMEFRAME TECHNICAL ANALYSIS
# -------------------------------------------------------------------
def evaluate_technical_strategy():
    try:
        # Fetch 5-Minute Candles for Execution
        hist_payload = {
            "symbol": "NSE:NIFTY50-INDEX",
            "resolution": "5",
            "date_format": "0",
            "range_from": str(int((datetime.now() - timedelta(days=5)).timestamp())),
            "range_to": str(int(datetime.now().timestamp())),
            "cont_flag": "1"
        }
        
        res = fyers.history(data=hist_payload)
        if res.get("code") != 200 or "candles" not in res:
            return None, 0.0

        candles = res["candles"]
        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
        
        # Calculate Indicators
        df["EMA_9"] = ta.ema(df["close"], length=9)
        df["EMA_21"] = ta.ema(df["close"], length=21)
        df["RSI"] = ta.rsi(df["close"], length=14)
        df["VWAP"] = ta.vwap(df["high"], df["low"], df["close"], df["volume"])
        
        # Supertrend (10, 3)
        st = ta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3)
        df["ST_DIRECTION"] = st["SUPERTd_10_3.0"]

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        spot_price = latest["close"]

        print(f"[TECH CHECK] Spot: {spot_price} | RSI: {latest['RSI']:.1f} | EMA9: {latest['EMA_9']:.1f} | VWAP: {latest['VWAP']:.1f}")

        # Long Strategy Condition
        if (latest["close"] > latest["VWAP"] and
            latest["ST_DIRECTION"] == 1 and
            prev["EMA_9"] <= prev["EMA_21"] and latest["EMA_9"] > latest["EMA_21"] and
            50 <= latest["RSI"] <= 70):
            return "BUY_CALL", spot_price

        # Short Strategy Condition
        elif (latest["close"] < latest["VWAP"] and
              latest["ST_DIRECTION"] == -1 and
              prev["EMA_9"] >= prev["EMA_21"] and latest["EMA_9"] < latest["EMA_21"] and
              30 <= latest["RSI"] <= 50):
            return "BUY_PUT", spot_price

        return None, spot_price

    except Exception as e:
        print(f"Error evaluating technical strategy: {str(e)}")
        return None, 0.0

# -------------------------------------------------------------------
# 4. EXECUTION PIPELINE
# -------------------------------------------------------------------
def run_trading_engine_cycle():
    print(f"\n--- STRATEGY CYCLE TRIGGERED AT {datetime.now()} ---")
    
    signal, spot_price = evaluate_technical_strategy()
    if not signal:
        print("No Technical Signal detected. Standing by.")
        return

    print(f"Technical Signal Fired: {signal} at Nifty Spot {spot_price}")

    option_type = "CE" if signal == "BUY_CALL" else "PE"
    option_symbol, atm_strike = get_active_nifty_expiry_symbol(spot_price, option_type)

    # OI Microstructure Guard
    is_oi_confirmed = validate_institutional_oi(signal_type=signal, atm_strike=atm_strike)
    
    if is_oi_confirmed:
        print(f"CONFIRMED: Executing Market Order for {option_symbol}")
        
        # Single Lot Execution (65 Units for Nifty Options)
        order_data = {
            "symbol": option_symbol,
            "qty": 65,
            "type": 2,          # Market Order
            "side": 1,          # Buy Option Contract
            "productType": "INTRADAY",
            "limitPrice": 0,
            "stopPrice": 0,
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False
        }
        
        order_res = fyers.place_order(data=order_data)
        print("Order Placement Response:", order_res)

@app.get("/")
def root():
    return {"status": "Live", "engine": "Institutional Quantitative Fyers Engine"}

@app.post("/webhook-trigger")
def trigger_engine(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_trading_engine_cycle)
    return {"status": "Processing", "timestamp": str(datetime.now())}


