# Windows quickstart

## Prerequisites

- Windows 10 or later.
- [Git](https://git-scm.com/).
- [uv](https://docs.astral.sh/uv/).
- [GitHub Copilot CLI](https://docs.github.com/copilot/how-tos/use-copilot-agents/use-copilot-cli).
- A Google account with Gmail.

## Install

```powershell
git clone https://github.com/Evyatar108/gmail-mcp.git
Set-Location gmail-mcp
.\scripts\setup-copilot.ps1
```

The setup script creates `.venv`, installs locked dependencies, and registers
the exact 16-tool allowlist with Copilot CLI. It also installs the public
`gmail-mcp`, `gmail-mcp-setup`, and `gmail-inbox-organizer` skills.

## Configure Google OAuth

Follow [OAuth setup](OAUTH-SETUP.md). After downloading a Desktop OAuth JSON:

```powershell
.\scripts\install-oauth-client.ps1 -Path C:\Downloads\client_secret.json
.\.venv\Scripts\gmail-mcp.exe auth
.\.venv\Scripts\gmail-mcp.exe status
```

`status` should show:

- `authenticated: true`
- `token_valid: true`
- no `missing_scopes`
- the WinVault credential backend

## Use

Restart Copilot CLI if the tools are not visible, then ask:

```text
List my Gmail labels.
Search for five recent messages from example.org.
Create a draft, but do not send it.
```

Read `SECURITY.md` before enabling write actions.
