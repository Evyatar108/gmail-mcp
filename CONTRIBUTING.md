# Contributing

Gmail MCP is a Windows-first personal Gmail connector. Contributions should
preserve the safety boundaries in `SECURITY.md` and `AGENTS.md`.

## Development

```powershell
git clone https://github.com/Evyatar108/gmail-mcp.git
Set-Location gmail-mcp
uv sync --locked
uv run pytest
uv build
```

## Requirements

- Do not commit OAuth JSON, tokens, mailbox exports, scan databases, or personal
  filter configurations.
- Keep permanent delete, automatic forwarding, and unsafe filter actions out of
  the MCP surface.
- Add tests and update documentation for behavior, scope, tool, or storage
  changes.
- Use example.com, example.org, or example.net for every test email address.

Open a focused pull request that explains the user-visible behavior and safety
impact.
