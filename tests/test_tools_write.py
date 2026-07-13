import base64
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from unittest.mock import MagicMock

import pytest

from gmail_mcp.operations import GmailOperations


class FakeRequest:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response

    def execute(self, num_retries: int = 0) -> dict[str, object]:
        return self.response


class FakeFactory:
    def __init__(self, service: MagicMock) -> None:
        self.service = service

    def get_service(self) -> MagicMock:
        return self.service

    def execute(self, request: FakeRequest) -> dict[str, object]:
        return request.execute()


def raw_draft() -> str:
    message = EmailMessage()
    message["To"] = "recipient@example.com"
    message["Subject"] = "Review me"
    message.set_content("Draft body")
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


def test_send_requires_exact_state_bound_confirmation() -> None:
    service = MagicMock()
    drafts = service.users.return_value.drafts.return_value
    draft = {
        "id": "d1",
        "message": {"id": "m1", "raw": raw_draft()},
    }
    drafts.get.return_value = FakeRequest(draft)
    drafts.send.return_value = FakeRequest({"id": "sent1", "threadId": "t1"})
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    preview = operations.send_draft("d1")

    assert preview["status"] == "confirmation_required"
    assert preview["confirmation"].startswith("SEND d1 ")
    drafts.send.assert_not_called()

    result = operations.send_draft("d1", str(preview["confirmation"]))

    assert result["status"] == "sent"
    drafts.send.assert_called_once()


def test_trash_requires_preview_and_exact_message_set() -> None:
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    metadata = {
        "id": "m1",
        "internalDate": "1",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "Subject", "value": "Receipt"},
                {"name": "Date", "value": "today"},
                {"name": "Message-ID", "value": "<m1@example.com>"},
            ]
        },
    }
    messages.get.return_value = FakeRequest(metadata)
    messages.trash.return_value = FakeRequest({"id": "m1"})
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    preview = operations.trash(["m1"])

    assert preview["status"] == "confirmation_required"
    assert preview["confirmation"].startswith("TRASH ")
    messages.trash.assert_not_called()

    result = operations.trash(["m1"], str(preview["confirmation"]))

    assert result == {"status": "trashed", "message_ids": ["m1"], "count": 1}


def test_draft_rejects_header_injection() -> None:
    operations = GmailOperations(FakeFactory(MagicMock()))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="CR or LF"):
        operations.create_draft(
            to=["recipient@example.com"],
            subject="Hello\r\nBcc: attacker@example.com",
            body="body",
        )


def test_rtl_draft_adds_escaped_html_alternative() -> None:
    service = MagicMock()
    drafts = service.users.return_value.drafts.return_value
    drafts.create.return_value = FakeRequest(
        {"id": "d1", "message": {"id": "m1", "threadId": "t1"}}
    )
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    result = operations.create_draft(
        to=["recipient@example.com"],
        subject="בדיקה",
        body='שלום <script>alert("x")</script>',
        rtl=True,
    )

    raw = drafts.create.call_args.kwargs["body"]["message"]["raw"]
    parsed = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
    html = parsed.get_body(preferencelist=("html",)).get_content()
    assert 'dir="rtl"' in html
    assert "text-align: right" in html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert result["rtl"] is True


@pytest.mark.parametrize("label_id", ["TRASH", "SPAM"])
def test_generic_label_tool_cannot_bypass_protected_flows(label_id: str) -> None:
    service = MagicMock()
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Protected labels"):
        operations.modify_labels(["m1"], add_label_ids=[label_id])

    service.users.return_value.messages.return_value.batchModify.assert_not_called()
