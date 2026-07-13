from pathlib import Path

import json
import os
from unittest.mock import MagicMock

import pytest

from gmail_mcp.auth import (
    authorize,
    configure_public_client,
    get_status,
    relaxed_token_scope_validation,
)
from gmail_mcp.config import (
    GMAIL_MODIFY_SCOPE,
    GMAIL_SETTINGS_BASIC_SCOPE,
    REQUESTED_SCOPES,
    Settings,
)
from gmail_mcp.credential_store import CredentialStore, TokenRecord
from gmail_mcp.errors import AuthenticationRequiredError
from gmail_mcp.gmail_client import load_client_config


class EmptyBackend:
    def get_password(self, service: str, username: str) -> None:
        return None

    def set_password(self, service: str, username: str, password: str) -> None:
        raise AssertionError("unexpected write")

    def delete_password(self, service: str, username: str) -> None:
        raise AssertionError("unexpected delete")


class RecordBackend(EmptyBackend):
    def __init__(self, record: TokenRecord) -> None:
        self.payload = record.to_json()

    def get_password(self, service: str, username: str) -> str:
        return self.payload


class WritableBackend:
    def __init__(self) -> None:
        self.payload: str | None = None

    def get_password(self, service: str, username: str) -> str | None:
        return self.payload

    def set_password(self, service: str, username: str, password: str) -> None:
        self.payload = password

    def delete_password(self, service: str, username: str) -> None:
        self.payload = None


def test_status_without_credentials_is_actionable(tmp_path: Path) -> None:
    status = get_status(
        settings=Settings(tmp_path / "missing.json"),
        store=CredentialStore(EmptyBackend()),
    )

    assert status.authenticated is False
    assert status.token_valid is False
    assert status.missing_scopes == REQUESTED_SCOPES
    assert "gmail-mcp auth" in status.detail


def test_configure_public_client_writes_secretless_desktop_json(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    client_id = "123456-example.apps.googleusercontent.com"

    result = configure_public_client(client_id, Settings(path))

    assert result == path
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["installed"]["client_id"] == client_id
    assert payload["installed"]["client_secret"] == ""


def test_configure_public_client_can_store_required_secret(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    client_id = "123456-example.apps.googleusercontent.com"

    configure_public_client(client_id, Settings(path), "secret-value")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["installed"]["client_secret"] == "secret-value"


def test_configure_public_client_rejects_invalid_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid"):
        configure_public_client("not-a-client-id", Settings(tmp_path / "credentials.json"))


def test_load_client_config_rejects_web_client(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps(
            {
                "web": {
                    "client_id": "123-example.apps.googleusercontent.com",
                    "client_secret": "secret",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AuthenticationRequiredError, match="invalid"):
        load_client_config(path)


def test_relaxed_scope_validation_restores_missing_environment() -> None:
    os.environ.pop("OAUTHLIB_RELAX_TOKEN_SCOPE", None)

    with relaxed_token_scope_validation():
        assert os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] == "1"

    assert "OAUTHLIB_RELAX_TOKEN_SCOPE" not in os.environ


def test_relaxed_scope_validation_restores_previous_value() -> None:
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "existing"
    try:
        with relaxed_token_scope_validation():
            assert os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] == "1"
        assert os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] == "existing"
    finally:
        os.environ.pop("OAUTHLIB_RELAX_TOKEN_SCOPE", None)


def test_status_reports_missing_filter_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = TokenRecord(
        account_email="user@example.com",
        refresh_token="refresh",
        scopes=(GMAIL_MODIFY_SCOPE,),
    )
    credentials = type(
        "CredentialsStub",
        (),
        {"valid": True, "refresh": lambda self, request: None},
    )()
    monkeypatch.setattr(
        "gmail_mcp.auth.load_client_config",
        lambda path: {
            "client_id": "id",
            "client_secret": "",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
    )
    monkeypatch.setattr(
        "gmail_mcp.auth.credentials_from_record",
        lambda stored, client: credentials,
    )

    status = get_status(
        settings=Settings(tmp_path / "credentials.json"),
        store=CredentialStore(RecordBackend(record)),
    )

    assert status.authenticated is True
    assert status.token_valid is True
    assert status.missing_scopes == (GMAIL_SETTINGS_BASIC_SCOPE,)


def test_authorize_stores_actual_partial_grant_and_restores_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials_path = tmp_path / "credentials.json"
    credentials_path.write_text("{}", encoding="utf-8")
    credentials = type(
        "CredentialsStub",
        (),
        {
            "granted_scopes": [GMAIL_MODIFY_SCOPE],
            "scopes": list(REQUESTED_SCOPES),
            "refresh_token": "refresh",
        },
    )()

    class FlowStub:
        def run_local_server(self, **kwargs: object):
            assert os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] == "1"
            return credentials

    class FactoryStub:
        def __init__(self, settings: Settings, store: object) -> None:
            pass

        def get_service(self) -> MagicMock:
            return MagicMock()

        def execute(self, request: object) -> dict[str, str]:
            return {"emailAddress": "user@example.com"}

    monkeypatch.setattr(
        "gmail_mcp.auth.InstalledAppFlow.from_client_secrets_file",
        lambda path, scopes: FlowStub(),
    )
    monkeypatch.setattr("gmail_mcp.auth.GmailClientFactory", FactoryStub)
    backend = WritableBackend()
    store = CredentialStore(backend)
    os.environ.pop("OAUTHLIB_RELAX_TOKEN_SCOPE", None)

    record = authorize(Settings(credentials_path), store)

    assert record.scopes == (GMAIL_MODIFY_SCOPE,)
    assert store.load() == record
    assert "OAUTHLIB_RELAX_TOKEN_SCOPE" not in os.environ
