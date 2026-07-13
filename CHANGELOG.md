# Changelog

## Unreleased

- Added Windows CI, private vulnerability reporting guidance, and automatic
  installation of public Gmail skills during setup.
- Sanitized package metadata and paths for public sharing.
- Added portable Windows setup/uninstall and secure Desktop OAuth JSON install.
- Added private organization export with account-address placeholders.
- Added public setup and Inbox-organization skills plus sharing/privacy docs.
- Added Gmail user-label creation and safe filter list/create/delete tools.
- Added `gmail.settings.basic` OAuth migration with partial-grant reporting.
- Added one-time expiring filter previews, forwarding redaction, broad-rule
  rejection, unsafe-filter deletion protection, and reversible live verification.
- Expanded the Gmail safe-use skill with RTL self-review and individual provider
  outreach rules.
- Added safe right-to-left draft rendering using escaped, generated HTML with a
  plain-text fallback.
- Prefer valid UTF-8 message bytes over incorrect legacy charset declarations,
  fixing mojibake in older Hebrew email.
- Added architecture, security, operations, tool-reference, troubleshooting, and
  design-decision documentation.
- Added repository agent instructions and a safe Gmail MCP skill.
- Added a repeatable user-skill installer.

## 0.1.0 - 2026-07-12

- Added a local Python stdio MCP server with 11 explicit Gmail tools.
- Added Gmail search, bounded message/thread reads, labels, archive, drafts,
  draft sending, Trash, and untrash.
- Added state-bound previews for sending and Trash.
- Added message-only Trash with rollback and protected `TRASH`/`SPAM` labels.
- Added WinVault refresh-token storage and memory-only access tokens.
- Added Desktop OAuth setup, status, revocation, secretless client support, and
  secure client-secret prompting.
- Added bounded MIME parsing, attachment metadata, TLS configuration, timeouts,
  retries, and async offloading.
- Added tests, package build configuration, Copilot CLI registration, and live
  read/reversible-write verification.
