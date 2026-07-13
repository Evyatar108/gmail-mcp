class GmailMcpError(RuntimeError):
    """Base error for expected Gmail MCP failures."""


class AuthenticationRequiredError(GmailMcpError):
    """The user must run the interactive auth command."""


class CredentialStoreError(GmailMcpError):
    """The credential store is unavailable or unsafe."""


class GmailApiError(GmailMcpError):
    """A Gmail API request failed."""
