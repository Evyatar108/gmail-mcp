from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_SETTINGS_BASIC_SCOPE = (
    "https://www.googleapis.com/auth/gmail.settings.basic"
)
REQUESTED_SCOPES = (GMAIL_MODIFY_SCOPE, GMAIL_SETTINGS_BASIC_SCOPE)
DEFAULT_MAX_BODY_CHARS = 20_000
MAX_BODY_CHARS = 50_000
DEFAULT_SEARCH_RESULTS = 20
MAX_SEARCH_RESULTS = 50
DEFAULT_THREAD_MESSAGES = 20
MAX_THREAD_MESSAGES = 50
DEFAULT_ATTACHMENTS = 50
MAX_ATTACHMENTS = 100
MAX_MUTATION_MESSAGES = 100
MAX_RECIPIENTS = 50
MAX_SUBJECT_CHARS = 998
MAX_DRAFT_BODY_CHARS = 200_000
MAX_FILTER_ADDRESS_CHARS = 500
MAX_FILTER_QUERY_CHARS = 2_048
MAX_FILTER_SIZE_BYTES = 2_147_483_647
FILTER_CONFIRMATION_TTL_SECONDS = 600
MAX_PENDING_CONFIRMATIONS = 100


@dataclass(frozen=True)
class Settings:
    client_secrets_path: Path
    http_timeout_seconds: float = 20.0
    api_retries: int = 3

    @classmethod
    def from_environment(cls) -> Settings:
        configured = os.environ.get("GMAIL_MCP_CLIENT_SECRETS")
        if configured:
            path = Path(configured).expanduser()
        else:
            app_data = os.environ.get("APPDATA")
            if not app_data:
                raise RuntimeError("APPDATA is not set; cannot locate Gmail OAuth credentials.")
            path = Path(app_data) / "gmail-mcp" / "credentials.json"

        timeout = float(os.environ.get("GMAIL_MCP_HTTP_TIMEOUT", "20"))
        retries = int(os.environ.get("GMAIL_MCP_API_RETRIES", "3"))
        if timeout <= 0:
            raise ValueError("GMAIL_MCP_HTTP_TIMEOUT must be positive.")
        if retries < 0 or retries > 10:
            raise ValueError("GMAIL_MCP_API_RETRIES must be between 0 and 10.")
        return cls(path.resolve(), timeout, retries)
