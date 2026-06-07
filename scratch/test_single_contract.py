import os
from datetime import date
from backtester.data_loader import DataLoader

def test_single():
    loader = DataLoader(creds_path="creds.txt")
    client = loader.get_client()
    if client is None:
        print("Failed to get client.")
        return
        
    symbol = "TSLA250808C00280000"
    print(f"Testing history retrieval for {symbol}...")
    try:
        df = loader.get_option_contract_history(
            option_symbol=symbol,
            start_date=date(2025, 7, 25),
            end_date=date(2025, 8, 8)
        )
        print("Result height:", df.height)
        print(df.head(5))
    except Exception as e:
        print("Error details:", e)

if __name__ == "__main__":
    test_single()
