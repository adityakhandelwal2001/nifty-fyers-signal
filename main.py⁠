from fastapi import FastAPI, BackgroundTasks, HTTPException
from fyers_apiv3 import fyersModel
import requests
import pandas as pd
import os

app = FastAPI(title="Fyers-uTrade Institutional Signal Engine")

FYERS_CLIENT_ID = os.getenv("FYERS_CLIENT_ID", "YOUR_APP_ID-100")
FYERS_ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN", "YOUR_DAILY_ACCESS_TOKEN")
UTRADE_WEBHOOK_URL = os.getenv("UTRADE_WEBHOOK_URL", "https://api.utradealgos.com/v1/webhook/YOUR_TOKEN")

fyers = fyersModel.FyersModel(
    client_id=FYERS_CLIENT_ID,
    token=FYERS_ACCESS_TOKEN,
    is_async=False,
    log_path=""
)

def evaluate_fyers_microstructure(signal_type: str) -> bool:
    data = {
        "symbol": "NSE:NIFTY50-INDEX",
        "strikecount": 5,
        "timestamp": ""
    }
    
    try:
        response = fyers.optionchain(data=data)
        if response.get("s") == "ok":
            chain_data = pd.DataFrame(response['data']['optionsChain'])
            ce_oi_change = chain_data[chain_data['option_type'] == 'CE']['oi_change'].sum()
            pe_oi_change = chain_data[chain_data['option_type'] == 'PE']['oi_change'].sum()
            
            if signal_type == "BUY_CALL":
                return ce_oi_change < 0 and pe_oi_change > 0
            elif signal_type == "BUY_PUT":
                return pe_oi_change < 0 and ce_oi_change > 0
    except Exception as e:
        print(f"Error fetching Fyers Option Chain: {e}")
        return False
        
    return False

@app.post("/webhook-trigger")
def process_signal(data: dict, background_tasks: BackgroundTasks):
    signal = data.get("signal")
    is_valid = evaluate_fyers_microstructure(signal)
    
    if is_valid:
        payload = {
            "action": "ENTER",
            "position": "call" if signal == "BUY_CALL" else "put",
            "quantity": 2
        }
        requests.post(UTRADE_WEBHOOK_URL, json=payload)
        return {"status": "SUCCESS", "message": f"{signal} verified by Fyers OI & triggered on uTrade"}
    
    return {"status": "BLOCKED", "message": f"{signal} blocked due to adverse OI"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
