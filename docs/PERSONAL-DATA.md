# Personal data boundaries

## Generic public repository

Allowed:

- source code and synthetic tests;
- generic documentation and skills;
- reserved example-domain email addresses.

Forbidden:

- OAuth JSON, client identifiers copied from a real project, and tokens;
- primary Gmail address or aliases;
- mailbox content, headers, snippets, or attachments;
- personal label/filter configuration;
- sender inventories and scan databases;
- tax, financial, health, government, or account records;
- machine-specific user paths.

## Organization exports

`scripts/export-organization.py` removes Gmail resource IDs and replaces the
primary account and configured aliases with placeholders. It still contains
third-party sender addresses, domains, subjects, and personal organization
choices.

Treat every organization export as **private PII**:

- store it only in a private repository;
- do not attach it to public issues;
- do not paste it into public chat;
- do not assume "safe export" means publishable.

The default export path is `%APPDATA%\gmail-mcp`, outside the source repository.

## OAuth credentials

- Desktop OAuth JSON lives under `%APPDATA%\gmail-mcp`.
- Refresh tokens live in Windows Credential Manager.
- Access tokens live in memory.
- None of these belong in either the public repo or personal-configuration repo.
