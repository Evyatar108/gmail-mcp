from __future__ import annotations

import os
import json
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import certifi
import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

from gmail_mcp.config import (
    GMAIL_MODIFY_SCOPE,
    REQUESTED_SCOPES,
    Settings,
)
from gmail_mcp.credential_store import CredentialStore, TokenRecord
from gmail_mcp.errors import AuthenticationRequiredError, GmailApiError
from gmail_mcp.gmail_client import (
    GmailClientFactory,
    credentials_from_record,
    load_client_config,
)


@dataclass(frozen=True)
class AuthStatus:
    authenticated: bool
    account_email: str | None
    scopes: tuple[str, ...]
    backend: str
    client_secrets_path: str
    client_secrets_present: bool
    token_valid: bool
    missing_scopes: tuple[str, ...]
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def configure_public_client(
    client_id: str,
    settings: Settings | None = None,
    client_secret: str = "",
) -> Path:
    settings = settings or Settings.from_environment()
    normalized = client_id.strip()
    if not re.fullmatch(
        r"[0-9]+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com",
        normalized,
    ):
        raise ValueError("Invalid Google Desktop OAuth client ID.")
    payload = {
        "installed": {
            "client_id": normalized,
            "client_secret": client_secret.strip(),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    settings.client_secrets_path.parent.mkdir(parents=True, exist_ok=True)
    settings.client_secrets_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return settings.client_secrets_path


@contextmanager
def relaxed_token_scope_validation():
    key = "OAUTHLIB_RELAX_TOKEN_SCOPE"
    previous = os.environ.get(key)
    os.environ[key] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def authorize(
    settings: Settings | None = None,
    store: CredentialStore | None = None,
) -> TokenRecord:
    settings = settings or Settings.from_environment()
    store = store or CredentialStore()
    if not settings.client_secrets_path.is_file():
        raise AuthenticationRequiredError(
            f"OAuth client file not found at {settings.client_secrets_path}."
        )

    os.environ["SSL_CERT_FILE"] = certifi.where()
    flow = InstalledAppFlow.from_client_secrets_file(
        str(settings.client_secrets_path),
        scopes=list(REQUESTED_SCOPES),
    )
    with relaxed_token_scope_validation():
        credentials = flow.run_local_server(
            host="localhost",
            port=0,
            open_browser=True,
            timeout_seconds=300,
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
    granted = set(credentials.granted_scopes or credentials.scopes or ())
    if GMAIL_MODIFY_SCOPE not in granted:
        raise AuthenticationRequiredError("Google did not grant the required gmail.modify scope.")
    if not credentials.refresh_token:
        raise AuthenticationRequiredError(
            "Google did not return a refresh token. Revoke the app grant and retry auth."
        )

    temporary = TokenRecord(
        account_email="pending",
        refresh_token=credentials.refresh_token,
        scopes=tuple(sorted(granted)),
    )
    factory = GmailClientFactory(settings=settings, store=_SingleRecordStore(temporary, store))
    service = factory.get_service()
    profile = factory.execute(service.users().getProfile(userId="me"))
    account_email = str(profile.get("emailAddress", "")).strip()
    if not account_email:
        raise AuthenticationRequiredError("Unable to verify the authenticated Gmail account.")

    record = TokenRecord(
        account_email=account_email,
        refresh_token=credentials.refresh_token,
        scopes=tuple(sorted(granted)),
    )
    store.save(record)
    return record


def get_status(
    settings: Settings | None = None,
    store: CredentialStore | None = None,
) -> AuthStatus:
    settings = settings or Settings.from_environment()
    store = store or CredentialStore()
    record = store.load()
    if record is None:
        return AuthStatus(
            authenticated=False,
            account_email=None,
            scopes=(),
            backend=store.backend_name,
            client_secrets_path=str(settings.client_secrets_path),
            client_secrets_present=settings.client_secrets_path.is_file(),
            token_valid=False,
            missing_scopes=REQUESTED_SCOPES,
            detail="Not authenticated. Run `gmail-mcp auth`.",
        )

    missing_scopes = tuple(sorted(set(REQUESTED_SCOPES) - set(record.scopes)))
    try:
        client = load_client_config(settings.client_secrets_path)
        credentials = credentials_from_record(record, client)
        session = requests.Session()
        session.verify = certifi.where()
        credentials.refresh(Request(session=session))
        valid = credentials.valid
        detail = "Authenticated." if valid else "Token refresh did not produce a valid token."
    except (AuthenticationRequiredError, RefreshError) as exc:
        valid = False
        detail = f"Reauthentication required: {exc}"

    return AuthStatus(
        authenticated=True,
        account_email=record.account_email,
        scopes=record.scopes,
        backend=store.backend_name,
        client_secrets_path=str(settings.client_secrets_path),
        client_secrets_present=settings.client_secrets_path.is_file(),
        token_valid=valid,
        missing_scopes=missing_scopes,
        detail=detail,
    )


def revoke(
    store: CredentialStore | None = None,
) -> bool:
    store = store or CredentialStore()
    record = store.load()
    if record is None:
        return False

    response = requests.post(
        "https://oauth2.googleapis.com/revoke",
        params={"token": record.refresh_token},
        timeout=20,
        verify=certifi.where(),
    )
    if response.status_code != 200:
        raise GmailApiError(
            f"Google token revocation failed with HTTP {response.status_code}; "
            "the local credential was retained."
        )
    store.delete()
    return True


class _SingleRecordStore:
    def __init__(self, record: TokenRecord, real_store: CredentialStore) -> None:
        self._record = record
        self.backend_name = real_store.backend_name

    def load(self) -> TokenRecord:
        return self._record

    def save(self, record: TokenRecord) -> None:
        self._record = record
