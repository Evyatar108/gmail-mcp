import base64

from gmail_mcp.message_parser import decode_text_bytes, normalize_message


def encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_normalize_message_prefers_plain_text_and_lists_attachments() -> None:
    message = {
        "id": "m1",
        "threadId": "t1",
        "labelIds": ["INBOX"],
        "snippet": "hello",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "Subject", "value": "Tax receipt"},
                {"name": "From", "value": "sender@example.com"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": encoded("plain body")},
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "receipt.pdf",
                    "body": {"attachmentId": "a1", "size": 42},
                },
            ],
        },
    }

    normalized = normalize_message(message, max_body_chars=5, max_attachments=10)

    assert normalized["headers"]["Subject"] == "Tax receipt"
    assert normalized["body"] == "plain"
    assert normalized["body_truncated"] is True
    assert normalized["attachments"][0]["attachment_id"] == "a1"


def test_valid_utf8_wins_over_incorrect_legacy_charset_declaration() -> None:
    raw = "היי אביתר, מס הכנסה".encode("utf-8")

    assert decode_text_bytes(raw, "windows-1255") == "היי אביתר, מס הכנסה"
