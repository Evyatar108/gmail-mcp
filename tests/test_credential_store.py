import json

import pytest

from gmail_mcp.config import GMAIL_MODIFY_SCOPE
from gmail_mcp.credential_store import CredentialStore, TokenRecord
from gmail_mcp.errors import CredentialStoreError


class FakeBackend:
    def __init__(self) -> None:
        self.value: str | None = None

    def get_password(self, service: str, username: str) -> str | None:
        return self.value

    def set_password(self, service: str, username: str, password: str) -> None:
        self.value = password

    def delete_password(self, service: str, username: str) -> None:
        self.value = None


def test_round_trip_stores_only_durable_fields() -> None:
    backend = FakeBackend()
    store = CredentialStore(backend)
    record = TokenRecord(
        account_email="user@example.com",
        refresh_token="refresh",
        scopes=(GMAIL_MODIFY_SCOPE,),
    )

    store.save(record)

    assert store.load() == record
    payload = json.loads(backend.value or "{}")
    assert "token" not in payload
    assert payload["refresh_token"] == "refresh"


def test_oversized_record_fails_before_backend_write() -> None:
    backend = FakeBackend()
    store = CredentialStore(backend)
    record = TokenRecord(
        account_email="user@example.com",
        refresh_token="x" * 1300,
        scopes=(GMAIL_MODIFY_SCOPE,),
    )

    with pytest.raises(CredentialStoreError, match="too large"):
        store.save(record)

    assert backend.value is None


def test_malformed_record_fails_closed() -> None:
    backend = FakeBackend()
    backend.value = '{"version":1}'

    with pytest.raises(CredentialStoreError, match="malformed"):
        CredentialStore(backend).load()
