import os
import sys
from datetime import date
from thetadata import ThetaClient, StockReqType, DateRange

def test_stock():
    java_bin_dir = "/Users/aps/projects/Deep ITM Covered Call/data/jdk/jdk-17.0.19+10/Contents/Home/bin"
    os.environ["PATH"] = java_bin_dir + os.path.pathsep + os.environ.get("PATH", "")
    
    with open("creds.txt", 'r') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    email, password = lines[0], lines[1]
    
    client = ThetaClient(username=email, passwd=password)
    with client.connect():
        print("Connected! Querying TSLA stock EOD...")
        df = client.get_hist_stock(
            req=StockReqType.EOD,
            root="TSLA",
            date_range=DateRange(date(2026, 5, 1), date(2026, 5, 8))
        )
        print("Success! Columns:")
        print(df.columns)
        print("Data:")
        print(df)

if __name__ == "__main__":
    test_stock()
