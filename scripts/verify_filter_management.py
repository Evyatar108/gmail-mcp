from __future__ import annotations

import argparse
import uuid

from gmail_mcp.gmail_client import GmailClientFactory
from gmail_mcp.errors import GmailApiError
from gmail_mcp.operations import GmailOperations


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a reversible live Gmail label/filter verification."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Acknowledge that this creates and removes temporary Gmail settings.",
    )
    args = parser.parse_args()
    if not args.yes:
        raise SystemExit("Pass --yes to run the live reversible verification.")

    factory = GmailClientFactory()
    operations = GmailOperations(factory)
    suffix = uuid.uuid4().hex[:12]
    label_name = f"MCP Verification {suffix}"
    impossible_sender = f"mcp-verification-{suffix}@example.com"
    label_id: str | None = None
    filter_id: str | None = None
    created_filter_id: str | None = None
    cleanup_errors: list[str] = []

    try:
        label = operations.create_label(label_name)
        label_id = str(label["id"])

        preview = operations.create_filter(
            from_address=impossible_sender,
            add_label_ids=[label_id],
        )
        created = operations.create_filter(
            from_address=impossible_sender,
            add_label_ids=[label_id],
            confirmation=str(preview["confirmation"]),
        )
        filter_id = str(created["filter"]["id"])
        created_filter_id = filter_id

        listed = operations.list_filters()["filters"]
        if not any(item["id"] == filter_id for item in listed):
            raise RuntimeError("Temporary Gmail filter was not returned by list.")

        delete_preview = operations.delete_filter(filter_id)
        operations.delete_filter(
            filter_id,
            confirmation=str(delete_preview["confirmation"]),
        )
        filter_id = None
    finally:
        service = factory.get_service()
        if filter_id:
            try:
                factory.execute(
                    service.users().settings().filters().delete(
                        userId="me", id=filter_id
                    )
                )
            except GmailApiError as exc:
                if "404" not in str(exc):
                    cleanup_errors.append(str(exc))
        if label_id:
            try:
                factory.execute(
                    service.users().labels().delete(
                        userId="me", id=label_id
                    )
                )
            except GmailApiError as exc:
                if "404" not in str(exc):
                    cleanup_errors.append(str(exc))

    filters = operations.list_filters()["filters"]
    labels = operations.list_labels()["labels"]
    if any(item["id"] == created_filter_id for item in filters):
        raise RuntimeError("Temporary Gmail filter remains after cleanup.")
    if any(item["name"] == label_name for item in labels):
        raise RuntimeError("Temporary Gmail label remains after cleanup.")
    if cleanup_errors:
        raise RuntimeError("Cleanup reported errors: " + "; ".join(cleanup_errors))
    print("Live Gmail label/filter verification passed and cleaned up.")


if __name__ == "__main__":
    main()
