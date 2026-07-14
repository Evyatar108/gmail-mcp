import asyncio

from gmail_mcp import server


class FakeOperations:
    def search(self, *args: object, **kwargs: object) -> dict[str, object]:
        return {"messages": [], "args": args, "kwargs": kwargs}


def test_search_tool_forwards_full_mailbox_default() -> None:
    previous = server._operations
    server._operations = FakeOperations()  # type: ignore[assignment]
    try:
        result = asyncio.run(server.gmail_search("from:tax@example.com"))
    finally:
        server._operations = previous

    assert result["args"][-1] is True


def test_expected_tools_are_registered() -> None:
    tools = asyncio.run(server.mcp.list_tools())
    names = {tool.name for tool in tools}

    assert names == {
        "gmail_search",
        "gmail_get_message",
        "gmail_get_thread",
        "gmail_list_labels",
        "gmail_create_label",
        "gmail_list_filters",
        "gmail_create_filter",
        "gmail_delete_filter",
        "gmail_list_attachments",
        "gmail_download_attachment",
        "gmail_modify_labels",
        "gmail_archive",
        "gmail_create_draft",
        "gmail_send_draft",
        "gmail_trash",
        "gmail_untrash",
    }

    by_name = {tool.name: tool for tool in tools}
    assert by_name["gmail_download_attachment"].annotations.destructiveHint is False
    assert by_name["gmail_download_attachment"].annotations.readOnlyHint is False
    assert by_name["gmail_create_filter"].annotations.destructiveHint is True
    assert by_name["gmail_delete_filter"].annotations.destructiveHint is True
