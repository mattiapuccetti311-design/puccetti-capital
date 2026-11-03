"""Step 4 of the README: store the Google credentials in the vault (one time, or again to replace them).

    VAULT_ID=vlt_... python add_credentials.py tokens.json

tokens.json is the JSON printed by get_google_token.py. Anthropic stores the values; the agent's sandbox only
ever sees placeholders, and each value is filled in only on requests to Google's token endpoint.
Delete tokens.json afterwards.
"""

import json
import os
import sys

import anthropic

TOKEN_HOST = "oauth2.googleapis.com"


def main() -> None:
    if len(sys.argv) != 2 or not os.getenv("VAULT_ID"):
        sys.exit("usage: VAULT_ID=vlt_... python add_credentials.py tokens.json")
    vault_id = os.environ["VAULT_ID"]
    with open(sys.argv[1]) as f:
        values = json.load(f)

    client = anthropic.Anthropic()
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
        client.beta.vaults.credentials.create(
            vault_id=vault_id,
            display_name=f"mattia-inbox {name}",
            auth={
                "type": "environment_variable",
                "secret_name": name,
                "secret_value": values[name],
                "networking": {"type": "limited", "allowed_hosts": [TOKEN_HOST]},
                # The token request is a form POST, so the values travel in the body.
                "injection_location": {"body": True},
            },
        )
        print(f"stored {name}")


if __name__ == "__main__":
    main()
