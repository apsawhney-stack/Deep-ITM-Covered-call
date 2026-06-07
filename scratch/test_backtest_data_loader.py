import os
import sys
from datetime import date
from backtester.data_loader import DataLoader

def test_data_loader():
    # Make sure we don't fall back to mock mode
    loader = DataLoader(creds_path="creds.txt")
    print(f"DataLoader running in mock mode? {loader.is_mock}")
    
    # 1. Test get_options_chain
    trade_date = date(2025, 6, 2)
    print(f"\nTesting get_options_chain on {trade_date}...")
    chain = loader.get_options_chain(ticker="TSLA", trade_date=trade_date, target_dte=30)
    print("Options Chain Result Type:", type(chain))
    if chain is not None:
        print("Columns:", chain.columns)
        print("Rows count:", len(chain))
        print("First 5 rows:")
        print(chain.head(5))
    else:
        print("Failed to retrieve options chain.")
        
    # 2. Test get_option_contract_history
    if chain is not None and len(chain) > 0:
        opt_symbol = chain['symbol'][len(chain)//2]
        print(f"\nTesting get_option_contract_history for {opt_symbol}...")
        history = loader.get_option_contract_history(
            option_symbol=opt_symbol,
            start_date=trade_date,
            end_date=date(2025, 6, 5)
        )
        print("History Result Type:", type(history))
        if history is not None:
            print("Columns:", history.columns)
            print("Rows count:", len(history))
            print("History data:")
            print(history)
        else:
            print("Failed to retrieve option history.")

if __name__ == "__main__":
    test_data_loader()
