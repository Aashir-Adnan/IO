"""Google OAuth for memory sync (loopback flow, `drive.appdata` scope only).

The refresh token — never the password — is kept in the OS keychain. The user
signs in in their own browser; IO never sees their credentials. Setup steps for
the Google Cloud OAuth client are in .claude/knowledge/memory-sync.md."""
from __future__ import annotations

SCOPES = ["https://www.googleapis.com/auth/drive.appdata"]
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_SERVICE, _USER = "io-assistant", "google-drive-refresh-token"


def _client_config(client_id: str, client_secret: str) -> dict:
    return {"installed": {
        "client_id": client_id, "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": _TOKEN_URI, "redirect_uris": ["http://localhost"]}}


def sign_in(client_id: str, client_secret: str):
    """Open the browser for consent (blocks until done); returns Credentials."""
    if not client_id or not client_secret:
        raise RuntimeError("Set [sync] client_id and client_secret in config.local.toml first "
                           "(see .claude/knowledge/memory-sync.md).")
    import keyring
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(_client_config(client_id, client_secret), SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent",
                                  open_browser=True)
    if not creds.refresh_token:
        raise RuntimeError("Google returned no refresh token; revoke IO's access at "
                           "myaccount.google.com/permissions and sign in again.")
    keyring.set_password(_SERVICE, _USER, creds.refresh_token)
    return creds


def load(client_id: str, client_secret: str):
    """Credentials from the stored refresh token, or None if not signed in."""
    import keyring
    from google.oauth2.credentials import Credentials

    token = keyring.get_password(_SERVICE, _USER)
    if not token:
        return None
    return Credentials(None, refresh_token=token, token_uri=_TOKEN_URI,
                       client_id=client_id, client_secret=client_secret, scopes=SCOPES)


def clear() -> None:
    import keyring

    try:
        keyring.delete_password(_SERVICE, _USER)
    except keyring.errors.PasswordDeleteError:
        pass


def build_service(creds):
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)
