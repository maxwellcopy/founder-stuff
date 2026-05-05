#!/usr/bin/env python3
"""One-time Google OAuth helper. Run with no args to get the URL, then run
with the redirect URL as the argument to save the token."""
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from google_auth_oauthlib.flow import InstalledAppFlow

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
BASE_DIR = Path(__file__).parent
GOOGLE_CREDS_FILE = BASE_DIR / "google_credentials.json"
GOOGLE_TOKEN_FILE = BASE_DIR / "google_token.json"

flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDS_FILE), GMAIL_SCOPES)
flow.redirect_uri = "http://localhost"

if len(sys.argv) == 1:
    auth_url, _ = flow.oauth2session.authorization_url(
        "https://accounts.google.com/o/oauth2/auth",
        access_type="offline",
        prompt="consent",
    )
    print("\nOpen this URL in your browser:\n")
    print(auth_url)
    print("\nAfter approving, paste the full redirect URL back here.")
else:
    redirect_url = sys.argv[1]
    code = parse_qs(urlparse(redirect_url).query)["code"][0]
    flow.fetch_token(code=code)
    with open(GOOGLE_TOKEN_FILE, "w") as f:
        f.write(flow.credentials.to_json())
    print("Token saved! Gmail access is authorized.")
