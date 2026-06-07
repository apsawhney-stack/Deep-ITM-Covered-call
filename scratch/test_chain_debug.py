import os
import sys
import pandas as pd
from datetime import date, timedelta
from thetadata import ThetaClient, OptionReqType, OptionRight, DateRange
from backtester.data_loader import DataLoader

def test_chain_debug():
    loader = DataLoader(creds_path="creds.txt")
    client = loader.get_client()
    if client is None:
        print("Failed to get client.")
        return
        
    ticker = "TSLA"
    trade_date = date(2026, 1, 21)
    target_dte = 15
    
    # Load stock price
    filepath = os.path.join("data", f"{ticker}_daily.parquet")
    stock_close = 200.0
    if os.path.exists(filepath):
        stock_db = pd.read_parquet(filepath)
        stock_db['Date'] = pd.to_datetime(stock_db['Date']).dt.date
        day_row = stock_db[stock_db['Date'] == trade_date]
        if not day_row.empty:
            stock_close = float(day_row['Close'].values[0])
        else:
            stock_close = float(stock_db.iloc[-1]['Close'])
            
    print(f"Stock close on {trade_date}: {stock_close}")
    
    with client.connect():
        print("\n1. Fetching expirations...")
        expirations = client.get_expirations(ticker)
        print("Total expirations found:", len(expirations))
        
        # Closest to DTE=15
        target_expiry = trade_date + timedelta(days=target_dte)
        exp_dates = []
        for e in expirations:
            if hasattr(e, 'to_pydatetime'):
                exp_dates.append(e.to_pydatetime().date())
            elif hasattr(e, 'date'):
                exp_dates.append(e.date())
            else:
                exp_dates.append(e)
                
        selected_expiry = min(exp_dates, key=lambda d: abs(d - target_expiry))
        print(f"Selected expiry: {selected_expiry} (DTE: {(selected_expiry - trade_date).days})")
        
        print("\n2. Fetching strikes...")
        strikes = client.get_strikes(ticker, selected_expiry)
        print("Total strikes found:", len(strikes))
        
        filtered_strikes = [float(s) for s in strikes if 0.8 * stock_close <= float(s) <= 1.2 * stock_close]
        print(f"Filtered strikes ({len(filtered_strikes)} of {len(strikes)}): {filtered_strikes}")
        
        print("\n3. Testing EOD Quote Greeks fetch for first strike...")
        if filtered_strikes:
            strike = filtered_strikes[0]
            try:
                df = client.get_hist_option(
                    req=OptionReqType.EOD_QUOTE_GREEKS,
                    root=ticker,
                    exp=selected_expiry,
                    strike=strike,
                    right=OptionRight.CALL,
                    date_range=DateRange(trade_date, trade_date)
                )
                print("EOD Greeks Query Result:")
                print(df)
            except Exception as e:
                print("EOD Greeks Query Failed:", e)

if __name__ == "__main__":
    test_chain_debug()
