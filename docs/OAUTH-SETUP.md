# Google OAuth setup

Gmail MCP requires a Google **Desktop app** OAuth client with:

```text
https://www.googleapis.com/auth/gmail.modify
https://www.googleapis.com/auth/gmail.settings.basic
```

These are restricted Gmail scopes. Personal use should remain in Google Auth
Platform **Testing** unless you complete Google's current production
verification requirements.

## Recommended: create your own app

1. Create or select a Google Cloud project.
2. Enable the Gmail API.
3. Configure Google Auth Platform:
   - Audience: External
   - Publishing status: Testing
   - Add your Gmail address as a test user
4. Under Data Access, add both scopes shown above.
5. Create an OAuth client with application type **Desktop app**.
6. Download the JSON immediately.
7. Install it locally:

   ```powershell
   .\scripts\install-oauth-client.ps1 -Path C:\Downloads\client_secret.json
   ```

8. Authorize:

   ```powershell
   .\.venv\Scripts\gmail-mcp.exe auth
   ```

Testing grants for these scopes expire after seven days. Re-run `auth` when
`status` reports that reauthorization is required.

The advanced `configure-client` command can construct Desktop client JSON from
a client ID and optional securely prompted secret, but installing the downloaded
JSON is the recommended path.

## Optional: use a trusted person's dedicated test app

This is only appropriate for a small number of users personally known to and
trusted by the Google Cloud project owner. It is not a public OAuth service.

Use a separate Testing Google Cloud project and Desktop client created solely
for sharing. Do not reuse the owner's personal or development client.

The owner must:

1. Add your Google address as a test user.
2. Confirm the app requests only the documented scopes.
3. Transfer the Desktop OAuth JSON through a trusted encrypted channel or
   password manager.

You then install and authorize it using the same commands as above.

Security boundaries:

- The Desktop client identifies the app; it does not grant mailbox access.
- Installed apps cannot keep a client secret confidential. Google OAuth policy
  nevertheless states that client credentials must never be committed to
  publicly available code repositories. Embedding the same values directly in
  public source is not an exception.
- Your refresh token stays in your own Windows Credential Manager.
- The project owner controls the OAuth client and can rotate or delete it.
- The owner may receive project-level authorization or usage telemetry.
- Testing grants expire after seven days and the project has a 100-test-user
  limit.
- Email selected through MCP may be sent to your configured Copilot hosted
  service according to your Copilot plan and settings.

Transfer the Desktop JSON through an encrypted, access-controlled one-to-one
channel or password manager. Private transfer reduces public indexing, bot
scraping, app-identity reuse, and shared-client disablement risk; it is not a
cryptographic secrecy boundary.

Create your own app if you want independent control.

## Production use

Do not treat **In production** as a shortcut around Testing expiry. Public or
multi-user use of restricted Gmail scopes must follow Google's current OAuth
verification, privacy, demonstration, and security requirements.
