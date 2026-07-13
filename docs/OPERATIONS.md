# Setup and operations

## Prerequisites

- Windows with Python 3.12, `uv`, and GitHub Copilot CLI.
- A Google account with Gmail.
- A Google Cloud project controlled by the operator.

## Google Cloud setup

### 1. Select the correct Google account and project

Google Console pages can open under the wrong signed-in account. The URL query
`authuser=N` selects the Nth signed-in Google account, for example:

```text
https://console.cloud.google.com/apis/library/gmail.googleapis.com?authuser=1
```

Account selection and project selection are separate. Confirm both before
enabling APIs or creating OAuth clients.

### 2. Enable the Gmail API

Open the Gmail API library page and click **Enable**:

```text
https://console.cloud.google.com/apis/library/gmail.googleapis.com
```

### 3. Configure Google Auth Platform

Under **Google Auth Platform**:

1. **Branding**: set an app name and support/contact email.
2. **Audience**: choose External for a personal Gmail account.
3. **Test users**: add the exact mailbox address that will authorize the app.
4. **Data Access → Add or remove scopes**: add:

   ```text
   https://www.googleapis.com/auth/gmail.modify
   https://www.googleapis.com/auth/gmail.settings.basic
   ```

5. Save the scope changes.

If the mailbox is not listed as a test user, Google returns:

```text
Error 403: access_denied
The app is currently being tested and can only be accessed by developer-approved testers.
```

### 4. Create a Desktop OAuth client

Create a client under **Google Auth Platform → Clients** with application type
**Desktop app**.

Google's UI varies:

- If a JSON download is available, download it immediately.
- If only a public Client ID is shown, configure it locally:

  ```powershell
  .\.venv\Scripts\gmail-mcp.exe configure-client "CLIENT_ID.apps.googleusercontent.com"
  ```

- If token exchange reports `client_secret is missing`, the client requires a
  secret. Download the client JSON or create/copy a secret, then use:

  ```powershell
  .\.venv\Scripts\gmail-mcp.exe configure-client "CLIENT_ID.apps.googleusercontent.com" --prompt-secret
  ```

  The prompt does not echo the secret.

If a JSON file was downloaded, place it at:

```text
%APPDATA%\gmail-mcp\credentials.json
```

Restrict the file to the Windows user and remove duplicate copies from Downloads.

### 5. Personal-use publishing status

Google recommends keeping a personal restricted-scope app in **Testing** and
adding the mailbox as a test user. Testing grants, including refresh tokens,
expire after seven days, so periodic reauthorization is expected.

Moving to In production can trigger restricted-scope verification, scope
justification, a demo video, and potentially a security assessment. Do not start
that process for this personal connector unless public distribution is intended.

## Install and register

```powershell
git clone https://github.com/Evyatar108/gmail-mcp.git
Set-Location gmail-mcp
.\scripts\setup-copilot.ps1
```

## Authorize

```powershell
.\scripts\install-oauth-client.ps1 -Path C:\Downloads\client_secret.json
.\.venv\Scripts\gmail-mcp.exe auth
.\.venv\Scripts\gmail-mcp.exe status
```

Expected status properties:

- `authenticated: true`
- `token_valid: true`
- `backend: keyring.backends.Windows.WinVaultKeyring`
- scopes include `https://www.googleapis.com/auth/gmail.modify`
- scopes include `https://www.googleapis.com/auth/gmail.settings.basic`
- `missing_scopes` is empty

`scripts\setup-copilot.ps1` registers the exact tool allowlist. Inspect it with:

```powershell
copilot mcp get gmail --json
```

The user configuration should contain only the executable path, `serve`
argument, and explicit tool list. It must not contain Google tokens or secrets.

After changing the MCP registration or installing the skill, restart Copilot CLI
if the current session does not discover the change.

## Install the safe-use skill

```powershell
.\scripts\install-user-skill.ps1
```

This copies all `skills\*\SKILL.md` files to:

```text
%USERPROFILE%\.copilot\skills\<skill-name>\SKILL.md
```

## Routine commands

```powershell
# Validate OAuth without displaying tokens
.\.venv\Scripts\gmail-mcp.exe status

# Update dependencies exactly from the lock file
uv sync --locked

# Run tests and build distributions
uv run pytest
uv build

# Reversible live Gmail label/filter verification
uv run python scripts\verify_filter_management.py --yes

# Inspect Copilot registration
copilot mcp get gmail --json
```

## Reauthorization

Run `auth` again when `status` reports `invalid_grant`, expired/revoked access,
or missing credentials:

```powershell
.\.venv\Scripts\gmail-mcp.exe auth
```

## Revoke and uninstall

```powershell
.\.venv\Scripts\gmail-mcp.exe revoke
.\scripts\uninstall-copilot.ps1
```

Optionally remove the local OAuth client file:

```powershell
Remove-Item "$env:APPDATA\gmail-mcp\credentials.json"
```

Revocation cannot cancel an already in-flight request.

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `GMAIL_MCP_CLIENT_SECRETS` | `%APPDATA%\gmail-mcp\credentials.json` | Alternate OAuth client JSON path |
| `GMAIL_MCP_HTTP_TIMEOUT` | `20` | Positive HTTP timeout in seconds |
| `GMAIL_MCP_API_RETRIES` | `3` | Google API retry count, 0-10 |

The setup script writes the required absolute Windows path into Copilot's local
MCP configuration.
