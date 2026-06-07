import os
import sys
from datetime import date, timedelta
from thetadata import ThetaClient, OptionReqType, OptionRight, DateRange

def test_greeks():
    java_bin_dir = "/Users/aps/projects/Deep ITM Covered Call/data/jdk/jdk-17.0.19+10/Contents/Home/bin"
    os.environ["PATH"] = java_bin_dir + os.path.pathsep + os.environ.get("PATH", "")
    
    with open("creds.txt", 'r') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    email, password = lines[0], lines[1]
    
    client = ThetaClient(username=email, passwd=password)
    with client.connect():
        # Using 2025-01-03 strike 150.0 TSLA CALL from 2024-12-04 to 2024-12-09
        target_exp = date(2025, 1, 3)
        target_strike = 150.0
        start_q = date(2024, 12, 4)
        end_q = date(2024, 12, 9)
        
        for req_type in [OptionReqType.EOD_QUOTE_GREEKS, OptionReqType.GREEKS, OptionReqType.QUOTE]:
            print(f"\n======================================")
            print(f"Testing OptionReqType: {req_type.name}")
            try:
                df = client.get_hist_option(
                    req=req_type,
                    root="TSLA",
                    exp=target_exp,
                    strike=target_strike,
                    right=OptionRight.CALL,
                    date_range=DateRange(start_q, end_q)
                )
                print(f"Success for {req_type.name}!")
                print("Columns:")
                print(df.columns)
                print("First row of data:")
                print(df.iloc[0] if not df.empty else "Empty DataFrame")
            except Exception as e:
                print(f"Failed for {req_type.name}: {e}")

if __name__ == "__main__":
    test_greeks()
