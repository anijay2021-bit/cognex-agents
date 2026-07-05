import json
import sys
import urllib.parse
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import settings

try:
    from fyers_apiv3 import fyersModel
    FYERS_AVAILABLE = True
except ImportError:
    FYERS_AVAILABLE = False

def generate_auth_url():
    session = fyersModel.SessionModel(
        client_id=settings.fyers_client_id,
        secret_key=settings.fyers_secret_key,
        redirect_uri=settings.fyers_redirect_uri,
        response_type="code",
        grant_type="authorization_code"
    )
    return session.generate_authcode()

def get_token_from_redirect(redirect_url):
    parsed = urllib.parse.urlparse(redirect_url)
    params = urllib.parse.parse_qs(parsed.query)
    auth_code = params.get("auth_code", [None])[0]
    if not auth_code:
        raise ValueError("No auth_code found in redirect URL")
    session = fyersModel.SessionModel(
        client_id=settings.fyers_client_id,
        secret_key=settings.fyers_secret_key,
        redirect_uri=settings.fyers_redirect_uri,
        response_type="code",
        grant_type="authorization_code"
    )
    session.set_token(auth_code)
    response = session.generate_token()
    if response.get("s") == "ok":
        token = response["access_token"]
        token_path = Path(__file__).parent.parent / "config" / "fyers_token.json"
        with open(token_path, "w") as f:
            json.dump({"token": token, "date": str(date.today())}, f)
        print(f"Fyers token saved for {date.today()}")
        return token
    else:
        raise Exception(f"Token generation failed: {response}")

def interactive_auth():
    if not FYERS_AVAILABLE:
        print("Install fyers-apiv3: pip install fyers-apiv3")
        return
    print("\n" + "="*60)
    print("FYERS DAILY AUTHENTICATION")
    print("="*60)
    print("\nStep 1: Open this URL in your browser:")
    print()
    auth_url = generate_auth_url()
    print(f"  {auth_url}")
    print()
    print("Step 2: Login to Fyers with your credentials")
    print("Step 3: After login, copy the FULL redirect URL from browser")
    print("        (starts with: https://trade.fyers.in/...)")
    print()
    redirect_url = input("Step 4: Paste the redirect URL here: ").strip()
    try:
        token = get_token_from_redirect(redirect_url)
        print(f"\nAuthentication successful!")
        print(f"Token valid for today: {date.today()}")
    except Exception as e:
        print(f"\nAuthentication failed: {e}")

if __name__ == "__main__":
    interactive_auth()
