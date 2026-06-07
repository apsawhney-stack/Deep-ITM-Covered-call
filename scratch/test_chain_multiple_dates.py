import os
import sys
import pandas as pd
from datetime import date, timedelta
from thetadata import ThetaClient, OptionReqType, OptionRight, DateRange
from backtester.data_loader import DataLoader

def test_dates():
    loader = DataLoader(creds_path="creds.txt")
    client = loader.get_client()
    if client is None:
        print("Failed to get client.")
        return
        
    ticker = "TSLA"
    dates_to_test = [
        date(2026, 1, 14),
        date(2026, 1, 15),
        date(2026, 1, 16),
        date(2026, 1, 20),
        date(2026, 1, 21),
        date(2026, 1, 22),
        date(2026, 1, 23),
        date(2026, 1, 26),
    ]
    
    with client.connect():
        for trade_date in dates_to_test:
            print(f"\n--- Testing trade_date: {trade_date} ---")
            try:
                expirations = client.get_expirations(ticker)
                target_expiry = trade_date + timedelta(days=15)
                exp_dates = []
                for e in expirations:
                    if hasattr(e, 'to_pydatetime'):
                        exp_dates.append(e.to_pydatetime().date())
                    elif hasattr(e, 'date'):
                        exp_dates.append(e.date())
                    else:
                        exp_dates.append(e)
                selected_expiry = min(exp_dates, key=lambda d: abs(d - target_expiry))
                strikes = client.get_strikes(ticker, selected_expiry)
                
                # Pick middle strike to test
                strikes_list = [float(s) for s in strikes]
                strike = 400.0 if 400.0 in strikes_list else strikes_list[len(strikes_list)//2]
                
                df = client.get_hist_option(
                    req=OptionReqType.EOD_QUOTE_GREEKS,
                    root=ticker,
                    exp=selected_expiry,
                    strike=strike,
                    right=OptionRight.CALL,
                    date_range=DateRange(trade_date, trade_date)
                )
                print(f"Success for date {trade_date}! Row count: {len(df)}")
            except Exception as e:
                print(f"Failed for date {trade_date}: {e}")

if __name__ == "__main__":
    test_dates()
