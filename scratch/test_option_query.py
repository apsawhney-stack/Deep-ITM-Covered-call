import os
import sys
from datetime import date, timedelta
from thetadata import ThetaClient, OptionReqType, OptionRight, DateRange

def test_option():
    java_bin_dir = "/Users/aps/projects/Deep ITM Covered Call/data/jdk/jdk-17.0.19+10/Contents/Home/bin"
    os.environ["PATH"] = java_bin_dir + os.path.pathsep + os.environ.get("PATH", "")
    
    with open("creds.txt", 'r') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    email, password = lines[0], lines[1]
    
    client = ThetaClient(username=email, passwd=password)
    with client.connect():
        print("Connected! Fetching expirations for TSLA...")
        expirations = client.get_expirations("TSLA")
        # Print all expirations to see the range
        print(f"Total expirations found: {len(expirations)}")
        # Let's find expirations in 2025 or 2026
        recent_exps = [e for e in expirations if hasattr(e, 'year') and e.year in (2025, 2026)]
        if not recent_exps:
            # Try to get the latest one
            recent_exps = list(expirations[-10:])
        print(f"Recent expirations: {recent_exps[:5]}")
        
        target_exp = recent_exps[0]
        if hasattr(target_exp, 'to_pydatetime'):
            target_exp = target_exp.to_pydatetime().date()
        elif hasattr(target_exp, 'date'):
            target_exp = target_exp.date()
            
        print(f"Fetching strikes for recent expiration {target_exp}...")
        strikes = client.get_strikes("TSLA", target_exp)
        print(f"First few strikes: {list(strikes[:5])}")
        
        # Pick a strike that is highly likely to be active, like 150.0
        target_strike = 150.0
        # Query dates before expiration
        start_q = target_exp - timedelta(days=30)
        end_q = target_exp - timedelta(days=25)
        print(f"Fetching historical EOD for TSLA CALL at strike {target_strike} and expiry {target_exp} from {start_q} to {end_q}...")
        df = client.get_hist_option(
            req=OptionReqType.EOD,
            root="TSLA",
            exp=target_exp,
            strike=target_strike,
            right=OptionRight.CALL,
            date_range=DateRange(start_q, end_q)
        )
        print("Success! Columns:")
        print(df.columns)
        print("Data:")
        print(df)

if __name__ == "__main__":
    test_option()
