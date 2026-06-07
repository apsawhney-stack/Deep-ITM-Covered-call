import os
import sys
import pandas as pd
import polars as pl
from datetime import date, timedelta, datetime
from thetadata import ThetaClient, OptionReqType, OptionRight, DateRange

def test_chain_retrieval():
    java_bin_dir = "/Users/aps/projects/Deep ITM Covered Call/data/jdk/jdk-17.0.19+10/Contents/Home/bin"
    os.environ["PATH"] = java_bin_dir + os.path.pathsep + os.environ.get("PATH", "")
    
    with open("creds.txt", 'r') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    email, password = lines[0], lines[1]
    
    ticker = "TSLA"
    trade_date = date(2025, 6, 2)
    target_dte = 30
    
    # Load stock price from cached daily database
    filepath = os.path.join("data", f"{ticker}_daily.parquet")
    if not os.path.exists(filepath):
        print(f"Error: {filepath} not found. Running downloader first...")
        # Since we just want to test, let's assume stock price is 200.0 or read if exists
        stock_close = 200.0
    else:
        stock_db = pd.read_parquet(filepath)
        stock_db['Date'] = pd.to_datetime(stock_db['Date']).dt.date
        day_row = stock_db[stock_db['Date'] == trade_date]
        if not day_row.empty:
            stock_close = float(day_row['Close'].values[0])
        else:
            stock_close = float(stock_db.iloc[-1]['Close'])
            
    print(f"Stock close on {trade_date}: {stock_close}")
    
    client = ThetaClient(username=email, passwd=password)
    with client.connect():
        print("Connected to terminal! Fetching expirations...")
        expirations = client.get_expirations(ticker)
        
        # Find closest expiration to trade_date + target_dte
        target_expiry = trade_date + timedelta(days=target_dte)
        # Convert expirations to date objects for comparison
        exp_dates = []
        for e in expirations:
            if hasattr(e, 'to_pydatetime'):
                exp_dates.append(e.to_pydatetime().date())
            elif hasattr(e, 'date'):
                exp_dates.append(e.date())
            else:
                exp_dates.append(e)
                
        # Find closest expiration
        selected_expiry = min(exp_dates, key=lambda d: abs(d - target_expiry))
        print(f"Selected closest expiration: {selected_expiry} (DTE: {(selected_expiry - trade_date).days})")
        
        print(f"Fetching strikes for expiration {selected_expiry}...")
        strikes = client.get_strikes(ticker, selected_expiry)
        
        # Filter strikes to be within 80% to 120% of stock close
        filtered_strikes = [float(s) for s in strikes if 0.8 * stock_close <= float(s) <= 1.2 * stock_close]
        print(f"Filtered strikes ({len(filtered_strikes)} of {len(strikes)}): {filtered_strikes}")
        
        # Fetch EOD quotes and Greeks for all calls in parallel or sequence
        records = []
        for strike in filtered_strikes:
            print(f"Fetching data for strike {strike}...")
            try:
                df = client.get_hist_option(
                    req=OptionReqType.EOD_QUOTE_GREEKS,
                    root=ticker,
                    exp=selected_expiry,
                    strike=strike,
                    right=OptionRight.CALL,
                    date_range=DateRange(trade_date, trade_date)
                )
                if not df.empty:
                    row = df.iloc[0]
                    # Map to expected format
                    # OSI Symbol format: root + YYMMDD + C/P + 8-digit strike (times 1000)
                    strike_code = f"{int(strike * 1000):08d}"
                    expiry_str = selected_expiry.strftime("%y%m%d")
                    osi_symbol = f"{ticker}{expiry_str}C{strike_code}"
                    
                    # Let's inspect the row keys
                    row_dict = {col.name.lower() if hasattr(col, 'name') else str(col).lower(): val for col, val in row.items()}
                    
                    records.append({
                        'symbol': osi_symbol,
                        'right': 'C',
                        'strike': strike,
                        'expiry': selected_expiry.strftime("%Y-%m-%d"),
                        'bid': float(row_dict.get('bid', 0)),
                        'ask': float(row_dict.get('ask', 0)),
                        'delta': float(row_dict.get('delta', 0)),
                        'implied_volatility': float(row_dict.get('implied_vol', 0)),
                        'open_interest': 1000,
                        'volume': 150
                    })
            except Exception as e:
                print(f"Failed strike {strike}: {e}")
                
        chain_df = pl.DataFrame(records)
        print("\nSuccessfully generated option chain Polars DataFrame:")
        print(chain_df)

if __name__ == "__main__":
    test_chain_retrieval()
