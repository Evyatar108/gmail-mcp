from __future__ import annotations

from functools import partial
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from gmail_mcp.errors import GmailMcpError
from gmail_mcp.operations import GmailOperations


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
MUTATING = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
DESTRUCTIVE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)

mcp = FastMCP(
    "gmail",
    instructions=(
        "Local Gmail tools. Email content returned by these tools may be sent to "
        "Copilot's hosted model service. Sending requires a draft and state-bound "
        "confirmation. Deletion moves explicit message IDs to Trash only. "
        "Persistent filter creation and deletion require preview plus native "
        "destructive-tool approval."
    ),
    log_level="WARNING",
)
_operations: GmailOperations | None = None


def get_operations() -> GmailOperations:
    global _operations
    if _operations is None:
        _operations = GmailOperations()
    return _operations


async def _call(method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        operation = getattr(get_operations(), method)
        return await anyio.to_thread.run_sync(partial(operation, *args, **kwargs))
    except (GmailMcpError, ValueError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def gmail_search(
    query: str,
    page_size: int = 20,
    page_token: str | None = None,
    include_spam_trash: bool = True,
) -> dict[str, Any]:
    """Search the full Gmail mailbox using Gmail query syntax."""
    return await _call("search", query, page_size, page_token, include_spam_trash)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def gmail_get_message(
    message_id: str,
    max_body_chars: int = 20_000,
    max_attachments: int = 50,
) -> dict[str, Any]:
    """Get a bounded normalized Gmail message."""
    return await _call("get_message", message_id, max_body_chars, max_attachments)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def gmail_get_thread(
    thread_id: str,
    max_messages: int = 20,
    max_body_chars_per_message: int = 10_000,
) -> dict[str, Any]:
    """Get a bounded Gmail thread."""
    return await _call(
        "get_thread", thread_id, max_messages, max_body_chars_per_message
    )


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def gmail_list_labels() -> dict[str, Any]:
    """List Gmail system and user labels."""
    return await _call("list_labels")


@mcp.tool(annotations=MUTATING, structured_output=True)
async def gmail_create_label(
    name: str,
    message_list_visibility: str = "show",
    label_list_visibility: str = "labelShow",
) -> dict[str, Any]:
    """Create a user label with Gmail UI visibility settings."""
    return await _call(
        "create_label",
        name,
        message_list_visibility,
        label_list_visibility,
    )


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def gmail_list_filters() -> dict[str, Any]:
    """List Gmail filters while redacting forwarding addresses."""
    return await _call("list_filters")


@mcp.tool(annotations=DESTRUCTIVE, structured_output=True)
async def gmail_create_filter(
    from_address: str | None = None,
    to_address: str | None = None,
    subject: str | None = None,
    query: str | None = None,
    negated_query: str | None = None,
    has_attachment: bool | None = None,
    exclude_chats: bool | None = None,
    size: int | None = None,
    size_comparison: str | None = None,
    add_label_ids: list[str] | None = None,
    archive: bool = False,
    mark_read: bool = False,
    star: bool = False,
    confirmation: str | None = None,
) -> dict[str, Any]:
    """Preview or create a safe persistent Gmail filter."""
    return await _call(
        "create_filter",
        from_address,
        to_address,
        subject,
        query,
        negated_query,
        has_attachment,
        exclude_chats,
        size,
        size_comparison,
        add_label_ids,
        archive,
        mark_read,
        star,
        confirmation,
    )


@mcp.tool(annotations=DESTRUCTIVE, structured_output=True)
async def gmail_delete_filter(
    filter_id: str,
    confirmation: str | None = None,
) -> dict[str, Any]:
    """Preview or delete a safe-subset Gmail filter."""
    return await _call("delete_filter", filter_id, confirmation)


@mcp.tool(annotations=READ_ONLY, structured_output=True)
async def gmail_list_attachments(
    message_id: str,
    max_items: int = 50,
) -> dict[str, Any]:
    """List attachment metadata without downloading attachment content."""
    return await _call("list_attachments", message_id, max_items)


@mcp.tool(annotations=MUTATING, structured_output=True)
async def gmail_modify_labels(
    message_ids: list[str],
    add_label_ids: list[str] | None = None,
    remove_label_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Add or remove Gmail labels from explicit message IDs."""
    return await _call(
        "modify_labels", message_ids, add_label_ids, remove_label_ids
    )


@mcp.tool(annotations=MUTATING, structured_output=True)
async def gmail_archive(message_ids: list[str]) -> dict[str, Any]:
    """Archive explicit message IDs by removing the INBOX label."""
    return await _call("archive", message_ids)


@mcp.tool(annotations=MUTATING, structured_output=True)
async def gmail_create_draft(
    to: list[str],
    body: str,
    subject: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    reply_to_message_id: str | None = None,
    rtl: bool = False,
) -> dict[str, Any]:
    """Create a structured draft with optional safe RTL HTML; this never sends."""
    return await _call(
        "create_draft", to, subject, body, cc, bcc, reply_to_message_id, rtl
    )


@mcp.tool(annotations=DESTRUCTIVE, structured_output=True)
async def gmail_send_draft(
    draft_id: str,
    confirmation: str | None = None,
) -> dict[str, Any]:
    """Preview or send an existing draft using the exact returned confirmation."""
    return await _call("send_draft", draft_id, confirmation)


@mcp.tool(annotations=DESTRUCTIVE, structured_output=True)
async def gmail_trash(
    message_ids: list[str],
    confirmation: str | None = None,
) -> dict[str, Any]:
    """Preview or move explicit message IDs to Gmail Trash."""
    return await _call("trash", message_ids, confirmation)


@mcp.tool(annotations=MUTATING, structured_output=True)
async def gmail_untrash(message_ids: list[str]) -> dict[str, Any]:
    """Restore explicit message IDs from Gmail Trash."""
    return await _call("untrash", message_ids)


def run() -> None:
    mcp.run(transport="stdio")
