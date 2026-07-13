from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import certifi
import httplib2
import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from gmail_mcp.config import GMAIL_MODIFY_SCOPE, Settings
from gmail_mcp.credential_store import CredentialStore, TokenRecord
from gmail_mcp.errors import AuthenticationRequiredError, GmailApiError


def load_client_config(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise AuthenticationRequiredError(
            f"OAuth client file not found at {path}. Download a Google Desktop app "
            "credential and run `gmail-mcp auth`."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        client = data.get("installed")
        if not isinstance(client, dict):
            raise KeyError("installed")
        return {
            "client_id": str(client["client_id"]),
            "client_secret": str(client.get("client_secret", "")),
            "token_uri": str(client.get("token_uri", "https://oauth2.googleapis.com/token")),
        }
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AuthenticationRequiredError(
            f"OAuth client file at {path} is invalid."
        ) from exc


def credentials_from_record(
    record: TokenRecord,
    client: dict[str, str],
) -> Credentials:
    return Credentials(
        token=None,
        refresh_token=record.refresh_token,
        token_uri=client["token_uri"],
        client_id=client["client_id"],
        client_secret=client["client_secret"],
        scopes=list(record.scopes),
    )


class GmailClientFactory:
    def __init__(
        self,
        settings: Settings | None = None,
        store: CredentialStore | None = None,
    ) -> None:
        self.settings = settings or Settings.from_environment()
        self.store = store or CredentialStore()
        self._lock = threading.RLock()
        self._record_fingerprint: str | None = None
        self._credentials: Credentials | None = None
        self._service: Resource | None = None

    def get_service(self) -> Resource:
        with self._lock:
            record = self.store.load()
            if record is None:
                self._clear_cache()
                raise AuthenticationRequiredError(
                    "Gmail is not authenticated. Run `gmail-mcp auth`."
                )

            fingerprint = record.fingerprint
            if fingerprint != self._record_fingerprint:
                self._rebuild(record)

            assert self._credentials is not None
            assert self._service is not None
            if not self._credentials.valid:
                self._refresh(record)

            current = self.store.load()
            expected_fingerprint = self._record_fingerprint
            if current is None or current.fingerprint != expected_fingerprint:
                self._clear_cache()
                raise AuthenticationRequiredError(
                    "Gmail authorization changed or was revoked. Run `gmail-mcp auth`."
                )
            return self._service

    def _rebuild(self, record: TokenRecord) -> None:
        client = load_client_config(self.settings.client_secrets_path)
        credentials = credentials_from_record(record, client)
        http = httplib2.Http(
            timeout=self.settings.http_timeout_seconds,
            ca_certs=certifi.where(),
        )
        authorized_http = AuthorizedHttp(credentials, http=http)
        service = build(
            "gmail",
            "v1",
            http=authorized_http,
            cache_discovery=False,
            num_retries=0,
        )
        self._record_fingerprint = record.fingerprint
        self._credentials = credentials
        self._service = service

    def _refresh(self, record: TokenRecord) -> None:
        assert self._credentials is not None
        try:
            session = requests.Session()
            session.verify = certifi.where()
            self._credentials.refresh(Request(session=session))
        except RefreshError as exc:
            self._clear_cache()
            raise AuthenticationRequiredError(
                "Gmail authorization expired or was revoked. Run `gmail-mcp auth`."
            ) from exc
        if self._credentials.refresh_token not in (None, record.refresh_token):
            self.store.save(
                TokenRecord(
                    account_email=record.account_email,
                    refresh_token=self._credentials.refresh_token,
                    scopes=record.scopes,
                )
            )
            self._record_fingerprint = self.store.load().fingerprint  # type: ignore[union-attr]

    def execute(self, request: Any) -> dict[str, Any]:
        with self._lock:
            try:
                return request.execute(num_retries=self.settings.api_retries)
            except HttpError as exc:
                status = getattr(exc.resp, "status", "unknown")
                reason = getattr(exc, "reason", None) or "Gmail API request failed"
                raise GmailApiError(f"Gmail API error {status}: {reason}.") from exc
            except (TimeoutError, OSError) as exc:
                raise GmailApiError(f"Gmail API transport error: {exc}.") from exc

    def _clear_cache(self) -> None:
        self._record_fingerprint = None
        self._credentials = None
        self._service = None
