import os
import sys
import requests
import json
from datetime import date
from thetadata import ThetaClient

def test_rest_api():
    java_bin_dir = "/Users/aps/projects/Deep ITM Covered Call/data/jdk/jdk-17.0.19+10/Contents/Home/bin"
    os.environ["PATH"] = java_bin_dir + os.path.pathsep + os.environ.get("PATH", "")
    
    with open("creds.txt", 'r') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    email, password = lines[0], lines[1]
    
    client = ThetaClient(username=email, passwd=password)
    with client.connect():
        print("Connected to terminal! Now inspecting REST endpoints...")
        
        # Test basic REST endpoints
        base_url = "http://127.0.0.1:25510"
        
        print("\nTesting /list/expirations:")
        try:
            r = requests.get(f"{base_url}/list/expirations", params={"root": "TSLA"})
            print("Status:", r.status_code)
            print("Response:", r.text[:200])
        except Exception as e:
            print("Failed /list/expirations:", e)
            
        print("\nTesting /v2/bulk_snapshot/option/quote:")
        try:
            # Try to get the bulk snapshot for TSLA expirations
            r = requests.get(f"{base_url}/v2/bulk_snapshot/option/quote", params={"root": "TSLA", "exp": "0"})
            print("Status:", r.status_code)
            print("Response:", r.text[:200])
        except Exception as e:
            print("Failed bulk snapshot:", e)

        print("\nTesting /hist/option/eod_quote_greeks:")
        try:
            # Let's see if we can get list of all endpoints by hitting a random path to get a 404 or list of routes
            r = requests.get(f"{base_url}/random_path_to_trigger_404")
            print("404 Status:", r.status_code)
            print("404 Response:", r.text[:500])
        except Exception as e:
            print("Failed 404 test:", e)

if __name__ == "__main__":
    test_rest_api()
