import os
import sys
import time
from datetime import date
from thetadata import ThetaClient, OptionReqType, OptionRight, DateRange

def main():
    java_bin_dir = "/Users/aps/projects/Deep ITM Covered Call/data/jdk/jdk-17.0.19+10/Contents/Home/bin"
    os.environ["PATH"] = java_bin_dir + os.path.pathsep + os.environ.get("PATH", "")
    
    with open("creds.txt", 'r') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    email, password = lines[0], lines[1]
    
    print("Launching ThetaClient...", flush=True)
    client = ThetaClient(username=email, passwd=password)
    
    with client.connect():
        print("Connected! Waiting 5 seconds...", flush=True)
        time.sleep(5)
        
        # Test expirations REST
        print("\n--- Testing get_expirations_REST ---", flush=True)
        try:
            exps = client.get_expirations_REST("TSLA")
            print(f"Expirations: count={len(exps)}, type={type(exps)}")
            print(f"First 5: {exps[:5]}")
        except Exception as e:
            print("Failed get_expirations_REST:", e)
            
        # Test strikes REST
        print("\n--- Testing get_strikes_REST ---", flush=True)
        try:
            strikes = client.get_strikes_REST("TSLA", date(2025, 7, 3))
            print(f"Strikes: count={len(strikes)}, type={type(strikes)}")
            print(f"First 5: {strikes[:5]}")
        except Exception as e:
            print("Failed get_strikes_REST:", e)
            
        # Test historical option REST
        print("\n--- Testing get_hist_option_REST ---", flush=True)
        try:
            dr = DateRange(date(2025, 6, 2), date(2025, 6, 5))
            df = client.get_hist_option_REST(
                req=OptionReqType.EOD_QUOTE_GREEKS,
                root="TSLA",
                exp=date(2025, 7, 3),
                strike=345.0,
                right=OptionRight.CALL,
                date_range=dr
            )
            print(f"DataFrame: shape={df.shape}, type={type(df)}")
            print("Columns:", list(df.columns))
            print(df.head(2))
        except Exception as e:
            print("Failed get_hist_option_REST:", e)

if __name__ == "__main__":
    main()
