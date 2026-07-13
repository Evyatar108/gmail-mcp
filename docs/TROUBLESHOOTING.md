# Troubleshooting

## Google Console opens the wrong account

Append `?authuser=N` or `&authuser=N` to the Console URL. For example:

```text
https://console.cloud.google.com/auth/clients?authuser=1
```

Also verify the selected project. The account index does not automatically
select the intended project.

## Error 403: app is being tested

Add the mailbox address under:

```text
Google Auth Platform → Audience → Test users
```

Then restart `gmail-mcp auth`. A failed browser attempt can leave the loopback
callback waiting; stop that process before starting a fresh attempt.

## I cannot find the required Gmail scopes

Enable the Gmail API first. Then open:

```text
Google Auth Platform → Data Access → Add or remove scopes
```

Search for or manually add:

```text
https://www.googleapis.com/auth/gmail.modify
https://www.googleapis.com/auth/gmail.settings.basic
```

Click **Update**, then **Save**.

## There is no Download JSON button

Google's client UI changes over time. A Desktop client may expose only a Client
ID. Use:

```powershell
.\.venv\Scripts\gmail-mcp.exe configure-client "CLIENT_ID.apps.googleusercontent.com"
```

If Google later rejects token exchange because the client secret is missing,
download the JSON if offered or create/copy a client secret and use
`--prompt-secret`.

## `client_secret is missing`

The selected OAuth client is treated as a confidential/legacy Desktop client.
Obtain the secret without posting it into chat:

```powershell
.\.venv\Scripts\gmail-mcp.exe configure-client "CLIENT_ID.apps.googleusercontent.com" --prompt-secret
```

Alternatively, securely copy the downloaded JSON to
`%APPDATA%\gmail-mcp\credentials.json`.

## `invalid_grant` or reauthentication required

Common causes:

- External OAuth app is still in Testing and the seven-day token expired.
- The user revoked the Google grant.
- The OAuth client or secret changed.
- Google invalidated the refresh token.

Run `gmail-mcp auth` again. Personal Testing grants for these Gmail scopes
expire after seven days. Do not switch to In production as a shortcut; follow
Google's current restricted-scope verification requirements for production use.

## No browser opens

The `auth` command opens a browser; `serve` intentionally does not.

Check that the command is:

```powershell
.\.venv\Scripts\gmail-mcp.exe auth
```

The printed authorization URL can be opened manually if browser launch fails.

## MCP tool says Gmail is not authenticated

Run:

```powershell
.\.venv\Scripts\gmail-mcp.exe status
.\.venv\Scripts\gmail-mcp.exe auth
```

Do not try to authenticate from inside the stdio server.

## Filter tools say `gmail.settings.basic` is missing

Add the scope under **Google Auth Platform → Data Access**, save, then run:

```powershell
.\.venv\Scripts\gmail-mcp.exe auth
```

`gmail-mcp status` lists any `missing_scopes`.

## Copilot cannot see the Gmail tools

```powershell
copilot mcp get gmail --json
```

Confirm the executable path exists and the explicit tool list contains 15
tools. Restart Copilot CLI after registration changes.

## MCP server exits or corrupts protocol output

Anything written to stdout by a stdio server corrupts JSON-RPC. Diagnostics must
go to stderr. Do not add `print()` calls to server or operation paths.

## Windows Unicode console error

PowerShell can fail to print some email text with the legacy code page. For
diagnostic scripts:

```powershell
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
```

The MCP protocol itself uses UTF-8.

## `SSL_CERT_DIR` warning from `uv`

An inherited Anaconda `SSL_CERT_DIR` can point at an empty directory. The Gmail
client explicitly uses `certifi` for Google API TLS. The warning can still
appear during `uv` commands; clear the bad environment variable if package
operations fail.

## Trash failed partway through

The server attempts to untrash messages completed earlier in the batch. If
rollback also fails, the error includes only affected message IDs. Inspect those
IDs in Gmail and restore them manually if necessary.

## Status says the wrong account

Revoke, confirm the intended test user and browser account, then reauthorize:

```powershell
.\.venv\Scripts\gmail-mcp.exe revoke
.\.venv\Scripts\gmail-mcp.exe auth
```

Do not share one WinVault record across multiple mailboxes. Multi-account support
is not implemented.
