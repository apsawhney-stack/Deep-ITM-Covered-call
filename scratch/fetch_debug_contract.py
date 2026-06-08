import os
from datetime import date
from backtester.data_loader import DataLoader

def main():
    loader = DataLoader(creds_path="creds.txt")
    loader.is_mock = False
    
    symbol = "TSLA260223C00400000"
    start_date = date(2026, 1, 22)
    end_date = date(2026, 2, 23)
    
    print(f"Fetching history for {symbol} from {start_date} to {end_date}...")
    try:
        df = loader.get_option_contract_history(symbol, start_date, end_date)
        print("Success! Return DataFrame height:", df.height)
        if df.height > 0:
            print("Date range in fetched data:", df['date'].min(), "to", df['date'].max())
            print(df.head())
    except Exception as e:
        print("Error fetching contract history:", e)

if __name__ == "__main__":
    main()
