import os
import sys
from datetime import date
from thetadata import ThetaClient, OptionReqType, OptionRight, DateRange

def test_connection():
    # 1. Prepend our portable java bin path to PATH
    java_bin_dir = "/Users/aps/projects/Deep ITM Covered Call/data/jdk/jdk-17.0.19+10/Contents/Home/bin"
    os.environ["PATH"] = java_bin_dir + os.path.pathsep + os.environ.get("PATH", "")
    
    print(f"Set PATH to include Java. Testing if 'java' is found: {os.popen('which java').read().strip()}")
    
    # 2. Load credentials
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
        print("Successfully created ThetaClient instance. Connecting...")
        with client.connect():
            print("Successfully connected!")
            
            # Check if we can fetch something simple
            print("Testing a small query...")
            # Let's inspect methods of ThetaClient or try a simple call.
            # For example, get_expirations
            expirations = client.get_expirations(root="TSLA")
            print(f"Expirations for TSLA (first 5): {expirations[:5]}")
        
    except Exception as e:
        print(f"\nConnection failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_connection()
