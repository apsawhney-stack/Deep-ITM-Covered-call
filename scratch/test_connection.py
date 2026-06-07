import sys
import os
from thetadata import ThetaClient
from datetime import date

def test_connection():
    creds_path = "creds.txt"
    if not os.path.exists(creds_path):
        print(f"Error: {creds_path} not found.")
        sys.exit(1)
        
    with open(creds_path, 'r') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
        
    if len(lines) < 2:
        print("Error: credentials file has fewer than 2 lines.")
        sys.exit(1)
        
    email = lines[0]
    password = lines[1]
    
    print(f"Attempting to connect to ThetaData with email: {email}")
    try:
        # standard signature is username and passwd
        client = ThetaClient(username=email, passwd=password)
        print("Successfully created ThetaClient instance.")
        
        # Try a simple connection test by fetching some historical data
        print("Testing EOD Options Chain retrieval for TSLA on 2026-06-01...")
        chain = client.options_chain_eod(
            symbol="TSLA",
            date=date(2026, 6, 1)
        )
        print(f"Successfully retrieved options chain! Number of contracts: {len(chain)}")
        print("First few rows:")
        print(chain.head(5))
        print("\nConnection is FULLY WORKING!")
    except Exception as e:
        print(f"\nConnection failed: {e}")

if __name__ == "__main__":
    test_connection()
