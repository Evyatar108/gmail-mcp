# Design decisions

## Local MCP instead of a shell-only Gmail CLI

MCP gives Copilot typed schemas, structured results, annotations, and explicit
tool allowlisting. A small administrative CLI remains for OAuth and lifecycle
operations, but mailbox access is exposed through MCP.

## Generic public repository and private personal configuration

The server code, tests, documentation, and generic skills are publishable.
Mailbox labels, filter criteria, sender addresses, and cleanup preferences are
personal data and live in a separate private repository.

The export format removes Gmail-assigned IDs and OAuth credentials and replaces
the user's own address with placeholders. It still contains third-party contact
PII, so it is not a public or shareable artifact.

The public Git history is intentionally fresh. The original development history
is preserved in a separate private archive because it contains personal machine
paths and author naming that are irrelevant to users.

## Standalone MCP instead of a Copilot plugin

The integration is personal and machine-local. User-level MCP registration is
simpler, keeps the OAuth client configuration out of the repository, and avoids
packaging personal mailbox access into a distributable plugin.

## Custom server instead of `ArtyMcLabin/Gmail-MCP-Server`

The maintained third-party fork was evaluated. It still requires a user-created
Google OAuth client, stores credentials in a local JSON file, defaults to
`gmail.modify,gmail.settings.basic`, and exposes a much larger surface including
direct send, attachment download, filters, and more mutations.

The custom server keeps a smaller curated tool surface, WinVault refresh-token
storage, no attachment content, draft-first sending, state-bound confirmations,
message-only Trash, and protected label/filter checks.

## Custom server instead of Google's remote Gmail MCP

Google's remote endpoint was also evaluated. It requires additional Cloud MCP
service setup and OAuth client configuration, and its documented tool set is
narrower: thread search/read, drafts, and labels. Copilot CLI 1.0.71 documents
remote HTTP servers and headers but not a tested Google OAuth-client flow.

The local server was already working and offers the selected archive, send, and
recoverable Trash behavior.

## Gmail scopes

`gmail.modify` covers mailbox content and label actions without immediate
permanent deletion. Outlook-style filter creation requires the separate
`gmail.settings.basic` scope. The server requests both but exposes only a safe
filter subset with no forwarding or Trash/Spam automation.

## WinVault durable record

Only refresh token, mailbox identity, scopes, and schema version are stored.
Access tokens are intentionally excluded because they are transient and can make
the serialized record exceed Windows Credential Manager limits.

The backend is instantiated as Windows `WinVaultKeyring`; fallback file or
plaintext backends are refused.

## Draft-first sending

Direct send was omitted to create a reviewable object in Gmail before any
delivery. Sending requires a second tool and a fingerprint of current draft
state. The safe-use skill adds a human approval requirement between those calls.

## Message-only Trash

A Gmail thread can gain new messages after preview. Resolving and trashing an
entire mutable thread would risk moving unreviewed mail. The tool therefore
accepts only exact message IDs.

## Confirmation fingerprints

IDs alone do not prove that content stayed unchanged. Send fingerprints bind
draft/message IDs, recipients, subject, and raw content. Trash fingerprints bind
the sorted message identities and preview metadata. The state is fetched again
when executing.

## No attachment content

Attachment download increases filesystem risk, data exfiltration surface,
context volume, and file-type handling complexity. The initial design exposes
metadata only.

## Full-mailbox search default

The user selected full-mailbox access, so search defaults to
`includeSpamTrash=true`. Callers can disable it explicitly.

## Review-driven hardening

Independent plan reviews identified and resolved:

- WinVault record-size risk;
- seven-day Testing refresh-token expiry;
- non-interactive stdio authentication behavior;
- header injection and structured draft requirements;
- stale send/Trash confirmation state;
- privacy disclosure for hosted Copilot processing;
- cross-process revocation behavior;
- Spam/Trash visibility in search.

Implementation review later found that generic label mutation could add `TRASH`
and bypass the confirmation workflow. `TRASH` and `SPAM` are now blocked there
and covered by tests.
