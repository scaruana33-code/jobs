"""Run once on your own computer to get a Gmail refresh token.

Usage:  python scripts/get_refresh_token.py client_secret.json
Prints GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN to save as GitHub secrets.
"""
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nGOOGLE_CLIENT_ID=" + creds.client_id)
print("GOOGLE_CLIENT_SECRET=" + creds.client_secret)
print("GOOGLE_REFRESH_TOKEN=" + creds.refresh_token)
