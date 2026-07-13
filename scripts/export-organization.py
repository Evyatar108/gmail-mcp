from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from gmail_mcp.credential_store import CredentialStore
from gmail_mcp.operations import GmailOperations
from gmail_mcp.organization_export import build_organization_export


def main() -> None:
    default_output = (
        Path(os.environ["APPDATA"])
        / "gmail-mcp"
        / "organization-export.json"
    )
    parser = argparse.ArgumentParser(
        description=(
            "Export labels and safe filters without Gmail resource IDs. "
            "The result contains private third-party contact data."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help=f"Output path (default: {default_output})",
    )
    parser.add_argument(
        "--alias",
        action="append",
        default=[],
        help="Additional mailbox alias to replace with a placeholder.",
    )
    args = parser.parse_args()

    operations = GmailOperations()
    record = CredentialStore().load()
    if record is None:
        raise SystemExit("Gmail is not authenticated.")

    document = build_organization_export(
        labels=operations.list_labels()["labels"],
        filters=operations.list_filters()["filters"],
        account_email=record.account_email,
        aliases=args.alias,
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "WARNING: organization export contains private third-party contact data.",
        file=sys.stderr,
    )
    print(f"Exported private Gmail organization to {output}")


if __name__ == "__main__":
    main()
