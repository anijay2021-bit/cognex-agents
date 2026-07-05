import os
import sys
from dotenv import load_dotenv

# Add the project root to sys.path
sys.path.insert(0, os.getcwd())

from brokers.fyers_auto_auth import refresh_fyers_token

print("--- Starting Force Token Refresh ---")
try:
    token_path = "config/fyers_token.json"
    if os.path.exists(token_path):
        os.remove(token_path)
        print(f"Removed old token at {token_path}")
    
    result = refresh_fyers_token()
    print(f"Refresh call returned: {result}")
    
    if os.path.exists(token_path):
        print(f"SUCCESS: New token created at {token_path}")
        print(f"Modified time: {os.path.getmtime(token_path)}")
    else:
        print("FAILURE: Token file was not created.")
except Exception as e:
    print(f"ERROR during refresh: {str(e)}")
