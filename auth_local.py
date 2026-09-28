"""
Run this ONCE locally to generate token.json
Usage: python auth_local.py
"""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/gmail.readonly"]

print("Starting OAuth flow...")
print("A browser will open. Log in with your Google account.")
print()

flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
creds = flow.run_local_server(port=0)

with open("token.json", "w") as f:
    f.write(creds.to_json())

print()
print("✅ token.json created successfully!")
print("Upload this file to Railway as a secret file.")
