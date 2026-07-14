# Gmail MCP

[![CI](https://github.com/Evyatar108/gmail-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Evyatar108/gmail-mcp/actions/workflows/ci.yml)

Local Gmail tools for GitHub Copilot CLI, backed by Google's official Gmail API.

This project is a standalone local **MCP server**, not a Copilot plugin. Copilot
starts it as a user-configured stdio process.

> [!IMPORTANT]
> OAuth credentials and direct Gmail API traffic remain on this PC, but email
> content returned by MCP tools may be sent to GitHub Copilot's hosted model
> services. Do not use this integration if mailbox content must never leave the
> computer.

## Documentation

- [Windows quickstart](docs/QUICKSTART.md)
- [Google OAuth setup](docs/OAUTH-SETUP.md)
- [Sharing with another user](docs/SHARING.md)
- [Personal data boundaries](docs/PERSONAL-DATA.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Tool reference](docs/TOOLS.md)
- [Security model](SECURITY.md)
- [Setup and operations](docs/OPERATIONS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Design decisions and alternatives](docs/DESIGN-DECISIONS.md)
- [Change history](CHANGELOG.md)
- [Agent and contributor guidance](AGENTS.md)
- [Safe Gmail skill](skills/gmail-mcp/SKILL.md)

## Safety model

- Requests `gmail.modify` for mailbox actions and `gmail.settings.basic` for
  filter management, never the permanent-delete `https://mail.google.com/`
  scope.
- Sending is draft-first. `gmail_send_draft` returns a state-bound confirmation
  token before it can send.
- Deletion accepts message IDs only and moves them to recoverable Gmail Trash.
- OAuth refresh tokens are stored in Windows Credential Manager. Access tokens
  remain in memory.
- Write tools are marked as mutating/destructive for Copilot confirmations.
  Keep confirmations enabled and do not use `/allow-all` with this server.
- Persistent filters cannot forward mail or automate Trash/Spam actions.
- Attachment download is explicit, bounded to 25 MiB, writes only to an existing
  absolute local directory, and never overwrites a file.

## Google Cloud setup

See [Setup and operations](docs/OPERATIONS.md) for the complete Google Cloud
workflow, including multiple-account selection, test users, scope setup, missing
JSON downloads, client-secret compatibility, publishing, and cleanup.

## Quick start

```powershell
git clone https://github.com/Evyatar108/gmail-mcp.git
Set-Location gmail-mcp
.\scripts\setup-copilot.ps1
.\scripts\install-oauth-client.ps1 -Path C:\Downloads\client_secret.json
.\.venv\Scripts\gmail-mcp.exe auth
.\.venv\Scripts\gmail-mcp.exe status
```

Authorization opens the system browser, requests offline access, verifies the
authenticated account and granted scopes, and stores the refresh token in
Windows Credential Manager.

`setup-copilot.ps1` registers the exact 16-tool allowlist using the cloned
repository's absolute executable path and installs the three public safety/setup
skills.

The server is non-interactive. If authorization is absent or revoked, Gmail
tools return an error directing you to run `gmail-mcp auth`; the stdio server
never launches a browser.

## Typical flow

1. Search: `Use gmail_search to find receipts from last month.`
2. Read: `Use gmail_get_message for message ID ...`
3. Download: select attachment metadata, then save that exact attachment to an
   existing absolute directory with `gmail_download_attachment`.
4. Draft: `Create a draft reply, but do not send it.`
5. Send: call `gmail_send_draft` without confirmation to receive the exact
   preview token, review it, then call again with that token.
6. Trash: call `gmail_trash` without confirmation to receive the exact preview
   token, review the listed message IDs, then call again with that token.
7. Rules: create a label, preview a safe filter, then approve the native
   destructive-tool prompt before filter creation or deletion.

Gmail Trash retention is time-limited. `gmail_untrash` works only while Gmail
still retains the message.

For complete schemas, limits, and confirmation behavior, see
[Tool reference](docs/TOOLS.md).

## Credential status and revocation

```powershell
.\.venv\Scripts\gmail-mcp.exe status
.\.venv\Scripts\gmail-mcp.exe revoke
```

Revocation removes the Google grant and then deletes the WinVault entry.
Already in-flight Google requests cannot be cancelled, and an issued access
token may remain accepted briefly after revocation. Each new tool call rechecks
WinVault and fails closed once the record is removed or changed.

## Development

```powershell
uv run pytest
uv build
```

Install or refresh all three public Gmail skills:

```powershell
.\scripts\install-user-skill.ps1
```