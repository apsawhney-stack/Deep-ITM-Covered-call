import os
import sys
from datetime import date, timedelta
from thetadata import ThetaClient, OptionReqType, OptionRight, DateRange
from backtester.data_loader import DataLoader

def test_day_by_day():
    loader = DataLoader(creds_path="creds.txt")
    client = loader.get_client()
    if client is None:
        print("Failed to get client.")
        return
        
    symbol = "TSLA250808C00280000"
    print(f"Testing day-by-day queries for {symbol}...")
    
    root = "TSLA"
    expiry_date = date(2025, 8, 8)
    strike = 280.0
    right = OptionRight.CALL
    
    # Generate list of dates between 2025-07-25 and 2025-08-08
    start_date = date(2025, 7, 25)
    end_date = date(2025, 8, 8)
    curr = start_date
    dates = []
    while curr <= end_date:
        dates.append(curr)
        curr += timedelta(days=1)
        
    with client.connect():
        for d in dates:
            # Skip weekends for option trading EOD data
            if d.weekday() >= 5:
                continue
                
            print(f"\nQuerying date: {d} ({d.strftime('%A')})")
            try:
                df = client.get_hist_option(
                    req=OptionReqType.EOD_QUOTE_GREEKS,
                    root=root,
                    exp=expiry_date,
                    strike=strike,
                    right=right,
                    date_range=DateRange(d, d)
                )
                print(f"Success! Row count: {len(df)}")
                if len(df) > 0:
                    print(df[['DataType.DATE', 'DataType.BID', 'DataType.ASK', 'DataType.DELTA']])
            except Exception as e:
                print(f"Failed for date {d}: {e}")

if __name__ == "__main__":
    test_day_by_day()
