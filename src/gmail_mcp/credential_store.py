from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Protocol

from keyring.backends.Windows import WinVaultKeyring

from gmail_mcp.config import GMAIL_MODIFY_SCOPE
from gmail_mcp.errors import CredentialStoreError


SERVICE_NAME = "gmail-mcp"
RECORD_NAME = "gmail-oauth"
RECORD_VERSION = 1
CREDENTIAL_BLOB_LIMIT_BYTES = 2560
CREDENTIAL_BLOB_SAFETY_BYTES = 2400


class PasswordBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


@dataclass(frozen=True)
class TokenRecord:
    account_email: str
    refresh_token: str
    scopes: tuple[str, ...]
    version: int = RECORD_VERSION

    def to_json(self) -> str:
        return json.dumps(
            {
                "account_email": self.account_email,
                "refresh_token": self.refresh_token,
                "scopes": sorted(set(self.scopes)),
                "version": self.version,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, payload: str) -> TokenRecord:
        try:
            data = json.loads(payload)
            record = cls(
                account_email=str(data["account_email"]),
                refresh_token=str(data["refresh_token"]),
                scopes=tuple(str(scope) for scope in data["scopes"]),
                version=int(data["version"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CredentialStoreError("Stored Gmail credentials are malformed.") from exc

        if record.version != RECORD_VERSION:
            raise CredentialStoreError(
                f"Unsupported Gmail credential record version: {record.version}."
            )
        if not record.account_email or not record.refresh_token:
            raise CredentialStoreError("Stored Gmail credentials are incomplete.")
        if GMAIL_MODIFY_SCOPE not in record.scopes:
            raise CredentialStoreError("Stored Gmail credentials lack gmail.modify.")
        return record

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


class CredentialStore:
    def __init__(self, backend: PasswordBackend | None = None) -> None:
        self._backend = backend or self._windows_backend()

    @staticmethod
    def _windows_backend() -> WinVaultKeyring:
        try:
            backend = WinVaultKeyring()
            if backend.priority <= 0:
                raise CredentialStoreError("Windows Credential Manager is unavailable.")
            return backend
        except Exception as exc:
            if isinstance(exc, CredentialStoreError):
                raise
            raise CredentialStoreError(
                "Windows Credential Manager is unavailable; refusing fallback storage."
            ) from exc

    @property
    def backend_name(self) -> str:
        return f"{type(self._backend).__module__}.{type(self._backend).__name__}"

    def load(self) -> TokenRecord | None:
        try:
            payload = self._backend.get_password(SERVICE_NAME, RECORD_NAME)
        except Exception as exc:
            raise CredentialStoreError("Unable to read Windows Credential Manager.") from exc
        return TokenRecord.from_json(payload) if payload else None

    def save(self, record: TokenRecord) -> None:
        normalized = replace(record, scopes=tuple(sorted(set(record.scopes))))
        payload = normalized.to_json()
        encoded_size = len(payload.encode("utf-16-le"))
        if encoded_size > CREDENTIAL_BLOB_SAFETY_BYTES:
            raise CredentialStoreError(
                "Gmail credential record is too large for safe WinVault storage "
                f"({encoded_size}/{CREDENTIAL_BLOB_LIMIT_BYTES} bytes)."
            )
        try:
            self._backend.set_password(SERVICE_NAME, RECORD_NAME, payload)
        except Exception as exc:
            raise CredentialStoreError("Unable to write Windows Credential Manager.") from exc

    def delete(self) -> bool:
        if self.load() is None:
            return False
        try:
            self._backend.delete_password(SERVICE_NAME, RECORD_NAME)
        except Exception as exc:
            raise CredentialStoreError("Unable to delete Windows Credential Manager entry.") from exc
        return True
