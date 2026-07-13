---
name: gmail-mcp-setup
description: >-
  Install, configure, share, diagnose, reauthorize, or uninstall the Windows
  Gmail MCP server for GitHub Copilot CLI. Use whenever a user asks how to set
  up Gmail MCP, create or install a Google OAuth Desktop client, use a trusted
  shared test app, fix missing tools/scopes, or move the connector to another PC.
  Never request OAuth JSON, client secrets, refresh tokens, or authorization
  codes through chat.
---

# Set up Gmail MCP safely

## Install

From the cloned repository:

```powershell
.\scripts\setup-copilot.ps1
```

## OAuth

Recommend a user-owned Google Desktop OAuth app. Follow
`docs/OAUTH-SETUP.md`, then:

```powershell
.\scripts\install-oauth-client.ps1 -Path C:\Downloads\client_secret.json
.\.venv\Scripts\gmail-mcp.exe auth
.\.venv\Scripts\gmail-mcp.exe status
```

Do not ask the user to paste OAuth JSON, a secret, refresh token, or login code
into chat.

## Shared test app

Only use with invited users personally known to the app owner. Explain:

- the owner must add the colleague as a test user;
- OAuth JSON is transferred out-of-band;
- the colleague's refresh token remains local;
- the owner controls the client and scopes;
- Testing requires reauthorization every seven days.

Never describe this as a public shared OAuth service.

## Diagnose

```powershell
copilot mcp get gmail --json
.\.venv\Scripts\gmail-mcp.exe status
```

Restart Copilot CLI after registration changes.

## Uninstall

```powershell
.\scripts\uninstall-copilot.ps1
.\.venv\Scripts\gmail-mcp.exe revoke
```

The first command removes only Copilot registration. `revoke` removes the Google
grant and WinVault record.
