import os
import sys
import requests
import time
from datetime import date
from thetadata import ThetaClient

def main():
    java_bin_dir = "/Users/aps/projects/Deep ITM Covered Call/data/jdk/jdk-17.0.19+10/Contents/Home/bin"
    os.environ["PATH"] = java_bin_dir + os.path.pathsep + os.environ.get("PATH", "")
    
    with open("creds.txt", 'r') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    email, password = lines[0], lines[1]
    
    print("Launching ThetaClient...", flush=True)
    client = ThetaClient(username=email, passwd=password)
    
    with client.connect():
        print("Connected to terminal socket! Waiting 5 seconds for REST server to initialize...", flush=True)
        time.sleep(5)
        
        # Test port 25510
        print("\n=== Testing Port 25510 ===", flush=True)
        for path in ["/list/expirations?root=TSLA", "/v2/bulk_snapshot/option/quote?root=TSLA&exp=0", "/v3/oracle/expirations?root=TSLA"]:
            url = f"http://127.0.0.1:25510{path}"
            try:
                r = requests.get(url, timeout=5)
                print(f"GET {url} -> Status: {r.status_code}")
                print(f"Response: {r.text[:200]}\n")
            except Exception as e:
                print(f"GET {url} failed: {e}\n")
                
        # Test port 25503
        print("\n=== Testing Port 25503 ===", flush=True)
        for path in ["/list/expirations?root=TSLA", "/v2/bulk_snapshot/option/quote?root=TSLA&exp=0", "/v3/oracle/expirations?root=TSLA"]:
            url = f"http://127.0.0.1:25503{path}"
            try:
                r = requests.get(url, timeout=5)
                print(f"GET {url} -> Status: {r.status_code}")
                print(f"Response: {r.text[:200]}\n")
            except Exception as e:
                print(f"GET {url} failed: {e}\n")

if __name__ == "__main__":
    main()
