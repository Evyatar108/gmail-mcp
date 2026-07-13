# Sharing with another user

The public repository contains code, tests, generic documentation, and generic
skills only. It must not contain:

- OAuth client JSON;
- Gmail addresses or aliases;
- refresh/access tokens;
- mailbox scan databases;
- personal label/filter exports;
- private sender lists.

## Recommended handoff

1. Send the colleague the public repository URL.
2. Have them run `scripts\setup-copilot.ps1`.
3. Have them create their own Google Desktop OAuth client by following
   `docs\OAUTH-SETUP.md`.
4. Have them authorize their own Gmail account.

## Trusted shared test app

If using a shared test app instead:

- create a dedicated Google Cloud project and Desktop client solely for sharing;
  never reuse the owner's personal or development client;
- add the colleague explicitly as a Google Auth Platform test user;
- transfer OAuth JSON through an encrypted, access-controlled password manager
  or one-to-one channel;
- never place client credentials in public source control, packages containing
  public source, issues, logs, or public chat;
- explain the seven-day reauthorization requirement;
- explain that the owner controls the client and scopes;
- do not advertise or distribute the shared client publicly.

## Personal organization

Label/filter organization is mailbox-specific. Use:

```powershell
uv run python scripts\export-organization.py --output C:\private\organization.json
```

The output contains third-party contact addresses and belongs only in a private
repository. It is a reference/backup; this project does not automatically apply
an organization export.
