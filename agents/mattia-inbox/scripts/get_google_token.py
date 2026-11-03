"""Step 2 of the README: run once on your own computer to get a Google refresh token.

    pip install google-auth-oauthlib
    python get_google_token.py path/to/client_secret.json

A browser window opens: sign in with mattiapuccetti311@gmail.com and allow access.
The script prints the three values that add_credentials.py needs. Don't commit them or share them.
"""

import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",          # read, label, draft, send, move to spam
    "https://www.googleapis.com/auth/gmail.settings.basic",  # create "block sender" filters
    "https://www.googleapis.com/auth/calendar.events",       # create tentative events
]


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python get_google_token.py path/to/client_secret.json")
    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not creds.refresh_token:
        sys.exit("Google returned no refresh token - remove the app's access at myaccount.google.com/permissions and retry.")
    print(json.dumps(
        {
            "GOOGLE_CLIENT_ID": creds.client_id,
            "GOOGLE_CLIENT_SECRET": creds.client_secret,
            "GOOGLE_REFRESH_TOKEN": creds.refresh_token,
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
