from __future__ import annotations

import argparse
import getpass
import json
import sys

from gmail_mcp.auth import authorize, configure_public_client, get_status, revoke
from gmail_mcp.config import REQUESTED_SCOPES
from gmail_mcp.errors import GmailMcpError
from gmail_mcp.server import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gmail-mcp",
        description="Local Gmail MCP server for GitHub Copilot CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    configure = subparsers.add_parser(
        "configure-client",
        help="Create the local Desktop OAuth JSON from a Google client ID.",
    )
    configure.add_argument("client_id", help="Desktop OAuth client ID.")
    configure.add_argument(
        "--prompt-secret",
        action="store_true",
        help="Securely prompt for a client secret without echoing it.",
    )
    subparsers.add_parser("auth", help="Authorize Gmail in the system browser.")
    subparsers.add_parser("status", help="Check local Gmail authorization.")
    subparsers.add_parser("revoke", help="Revoke Google access and remove local credentials.")
    subparsers.add_parser("serve", help="Run the stdio MCP server.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "configure-client":
            secret = (
                getpass.getpass("Google OAuth client secret: ")
                if args.prompt_secret
                else ""
            )
            path = configure_public_client(args.client_id, client_secret=secret)
            print(f"Configured Google Desktop OAuth client at: {path}")
        elif args.command == "auth":
            record = authorize()
            print(f"Authorized Gmail account: {record.account_email}")
            missing = sorted(set(REQUESTED_SCOPES) - set(record.scopes))
            if missing:
                print(
                    "Authorization completed without optional scopes: "
                    + ", ".join(missing),
                    file=sys.stderr,
                )
        elif args.command == "status":
            print(json.dumps(get_status().to_dict(), indent=2, sort_keys=True))
        elif args.command == "revoke":
            removed = revoke()
            print("Gmail authorization revoked." if removed else "No Gmail authorization found.")
        elif args.command == "serve":
            run()
    except (GmailMcpError, ValueError, OSError) as exc:
        print(f"gmail-mcp: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
