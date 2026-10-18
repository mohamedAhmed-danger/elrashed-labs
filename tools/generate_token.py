import sys
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

REPO_ROOT = Path(__file__).resolve().parent.parent
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main():
    creds_path = REPO_ROOT / "credentials.json" if (REPO_ROOT / "credentials.json").exists() else Path("credentials.json")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(creds_path), SCOPES
    )
    creds = flow.run_local_server(port=0)

    token_path = REPO_ROOT / "token.json"
    with open(token_path, "w") as token:
        token.write(creds.to_json())
    print(f"✅ Successfully generated {token_path}!")


if __name__ == "__main__":
    main()
