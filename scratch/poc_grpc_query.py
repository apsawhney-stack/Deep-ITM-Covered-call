import time
from datetime import date
from thetadata import ThetaClient

def main():
    print("==============================================================")
    print("         gRPC NATIVE PYTHON CLIENT POC BENCHMARK              ")
    print("==============================================================")
    
    # Initialize client (will search for creds.txt in current directory)
    print("Initializing native gRPC ThetaClient...")
    try:
        client = ThetaClient()
        print("ThetaClient successfully initialized.")
    except Exception as e:
        print(f"Failed to initialize ThetaClient: {e}")
        return

    # Test parameters
    SYMBOL = "TSLA"
    EXPIRATION = date(2024, 6, 21)
    TRADE_DATE = date(2024, 6, 13)

    # 1. Bulk Greeks query using option_history_greeks_eod with strike="*"
    print("\n--- Testing option_history_greeks_eod with strike='*' (Wildcard EOD Chain Query) ---")
    start_time = time.time()
    try:
        df_chain = client.option_history_greeks_eod(
            symbol=SYMBOL,
            expiration=EXPIRATION,
            start_date=TRADE_DATE,
            end_date=TRADE_DATE,
            strike="*",
            right="call",
            strike_range=15
        )
        elapsed = time.time() - start_time
        print(f"SUCCESS: gRPC Wildcard EOD Chain Query completed in {elapsed:.3f} seconds.")
        print(f"Data type: {type(df_chain)}")
        print(f"Number of rows: {len(df_chain)}")
        print("\nFirst 5 rows of chain:")
        print(df_chain.head(5))
    except Exception as e:
        print(f"FAILURE: Wildcard EOD Chain Query failed: {e}")

    # 2. Historical Greeks for a single contract over a date range
    print("\n--- Testing option_history_greeks_eod (Contract History Query) ---")
    START_DATE = date(2024, 6, 3)
    END_DATE = date(2024, 6, 20)
    STRIKE = "175" # Strike 175.00
    
    start_time = time.time()
    try:
        df_hist = client.option_history_greeks_eod(
            symbol=SYMBOL,
            expiration=EXPIRATION,
            start_date=START_DATE,
            end_date=END_DATE,
            strike=STRIKE,
            right="call"
        )
        elapsed = time.time() - start_time
        print(f"SUCCESS: gRPC Contract History Query completed in {elapsed:.3f} seconds.")
        print(f"Data type: {type(df_hist)}")
        print(f"Number of rows: {len(df_hist)}")
        print("\nFirst 5 rows of contract history:")
        print(df_hist.head(5))
    except Exception as e:
        print(f"FAILURE: Contract History Query failed: {e}")

if __name__ == "__main__":
    main()
