import os
import sys
from datetime import date
from thetadata import ThetaClient, OptionReqType, OptionRight, DateRange
from backtester.data_loader import DataLoader

def test_debug():
    loader = DataLoader(creds_path="creds.txt")
    client = loader.get_client()
    if client is None:
        print("Failed to get client.")
        return
        
    symbol = "TSLA250808C00280000"
    print(f"Testing debug queries for {symbol} on FULL date range...")
    
    root = "TSLA"
    expiry_date = date(2025, 8, 8)
    strike = 280.0
    right = OptionRight.CALL
    start_date = date(2025, 7, 25)
    end_date = date(2025, 8, 8)
    
    with client.connect():
        # Test 1: Try standard socket API with EOD_QUOTE_GREEKS for the FULL range
        print("\n--- Test 1: Standard Socket API (EOD_QUOTE_GREEKS, FULL RANGE) ---")
        try:
            df = client.get_hist_option(
                req=OptionReqType.EOD_QUOTE_GREEKS,
                root=root,
                exp=expiry_date,
                strike=strike,
                right=right,
                date_range=DateRange(start_date, end_date)
            )
            print("Socket EOD_QUOTE_GREEKS Full Range Success! Row count:", len(df))
            print(df.head(2))
        except Exception as e:
            print("Socket EOD_QUOTE_GREEKS Full Range Failed:", e)
            
        # Test 2: Try REST API with EOD_QUOTE_GREEKS for the FULL range
        print("\n--- Test 2: REST API (EOD_QUOTE_GREEKS, FULL RANGE) ---")
        try:
            df = client.get_hist_option_REST(
                req=OptionReqType.EOD_QUOTE_GREEKS,
                root=root,
                exp=expiry_date,
                strike=strike,
                right=right,
                date_range=DateRange(start_date, end_date)
            )
            print("REST EOD_QUOTE_GREEKS Full Range Success! Row count:", len(df))
            print(df.head(2))
        except Exception as e:
            print("REST EOD_QUOTE_GREEKS Full Range Failed:", e)

if __name__ == "__main__":
    test_debug()
