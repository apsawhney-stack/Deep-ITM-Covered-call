import time
import requests
import pandas as pd
from datetime import date

# Target test parameters
SYMBOL = "TSLA"
EXPIRATION = "20240621"  # June 21, 2024 expiry
DATE = "20240613"        # June 13, 2024 trade date
REST_PORT = 25510        # Default Theta Terminal REST port

def test_sequential_query():
    print("\n--- Starting Sequential Strike Query (Legacy Mode) ---")
    # Sample list of 15 strikes to simulate a smaller chain (ITM to OTM)
    strikes = [150.0, 155.0, 160.0, 162.5, 165.0, 167.5, 170.0, 172.5, 175.0, 177.5, 180.0, 182.5, 185.0, 190.0, 195.0]
    
    start_time = time.time()
    success_count = 0
    
    for strike in strikes:
        # Construct the URL for a single contract EOD quote/greeks query
        url = f"http://127.0.0.1:{REST_PORT}/v3/option/history/greeks/all"
        params = {
            'symbol': SYMBOL,
            'expiration': EXPIRATION,
            'date': DATE,
            'strike': f"{strike:.2f}",
            'right': 'call',
            'interval': '1h'  # Hourly interval to reduce data size
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200:
                success_count += 1
        except Exception as e:
            print(f"Error querying strike {strike}: {e}")
            
    end_time = time.time()
    elapsed = end_time - start_time
    print(f"Sequential queries: Queried {len(strikes)} strikes individually.")
    print(f"Successes: {success_count}/{len(strikes)}")
    print(f"Total Time Elapsed: {elapsed:.3f} seconds (Avg: {elapsed/len(strikes):.3f}s per request)")
    return elapsed

def test_wildcard_query():
    print("\n--- Starting Wildcard Bulk Query (v3 Optimized Mode) ---")
    
    start_time = time.time()
    
    # Construct the URL with wildcard strike="*"
    url = f"http://127.0.0.1:{REST_PORT}/v3/option/history/greeks/all"
    params = {
        'symbol': SYMBOL,
        'expiration': EXPIRATION,
        'date': DATE,
        'strike': '*',      # Fetch ALL strikes in one call
        'right': 'call',
        'interval': '1h'
    }
    
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            # Convert to DataFrame to count unique strikes returned
            df = pd.DataFrame(data)
            unique_strikes = df['strike'].nunique() if 'strike' in df.columns else 0
            end_time = time.time()
            elapsed = end_time - start_time
            print(f"Wildcard query: Retrieved data for {unique_strikes} strikes in a single request.")
            print(f"Total Time Elapsed: {elapsed:.3f} seconds")
            return elapsed
        else:
            print(f"Failed to query wildcard. Status code: {r.status_code}, Response: {r.text}")
    except Exception as e:
        print(f"Error making wildcard query: {e}")
        
    return None

if __name__ == '__main__':
    print("==============================================================")
    # Warning check
    print("WARNING: Ensure the main parameter sweep task (task-2799) is ")
    print("not running before executing this test, to prevent 429 limits.")
    print("==============================================================")
    
    confirm = input("Has the main task finished running? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("Aborting. Please run this after the main task finishes.")
        exit(0)
        
    seq_time = test_sequential_query()
    wildcard_time = test_wildcard_query()
    
    if seq_time and wildcard_time:
        improvement = (seq_time - wildcard_time) / seq_time * 100
        print("\n==============================================================")
        print("                     POC PERFORMANCE LEAP                     ")
        print("==============================================================")
        print(f"Legacy Sequential Time: {seq_time:.3f} seconds")
        print(f"Optimized Wildcard Time: {wildcard_time:.3f} seconds")
        print(f"Performance Speedup:    {improvement:.2f}% faster")
        print(f"Request Count Reduced from {len(requests.get.__code__.co_varnames)} to 1.")
        print("==============================================================")
