from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from gmail_mcp.config import (
    GMAIL_MODIFY_SCOPE,
    GMAIL_SETTINGS_BASIC_SCOPE,
)
from gmail_mcp.credential_store import TokenRecord
from gmail_mcp.errors import AuthenticationRequiredError
from gmail_mcp.operations import GmailOperations


class FakeRequest:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response

    def execute(self, num_retries: int = 0) -> dict[str, object]:
        return self.response


class StubStore:
    def __init__(self, scopes: tuple[str, ...]) -> None:
        self.record = TokenRecord(
            account_email="user@example.com",
            refresh_token="refresh",
            scopes=scopes,
        )

    def load(self) -> TokenRecord:
        return self.record


class FakeFactory:
    def __init__(
        self,
        service: MagicMock,
        scopes: tuple[str, ...] = (
            GMAIL_MODIFY_SCOPE,
            GMAIL_SETTINGS_BASIC_SCOPE,
        ),
    ) -> None:
        self.service = service
        self.store = StubStore(scopes)

    def get_service(self) -> MagicMock:
        return self.service

    def execute(self, request: FakeRequest) -> dict[str, object]:
        return request.execute()


def configure_service(
    service: MagicMock,
    *,
    filters: list[dict[str, object]] | None = None,
) -> tuple[MagicMock, MagicMock]:
    labels_api = service.users.return_value.labels.return_value
    filters_api = service.users.return_value.settings.return_value.filters.return_value
    labels_api.list.return_value = FakeRequest(
        {
            "labels": [
                {"id": "INBOX", "name": "Inbox", "type": "system"},
                {"id": "UNREAD", "name": "Unread", "type": "system"},
                {"id": "STARRED", "name": "Starred", "type": "system"},
                {"id": "IMPORTANT", "name": "Important", "type": "system"},
                {"id": "Label_1", "name": "Receipts", "type": "user"},
            ]
        }
    )
    filters_api.list.return_value = FakeRequest({"filter": filters or []})
    return labels_api, filters_api


def test_create_label_checks_duplicates_and_creates() -> None:
    service = MagicMock()
    labels_api, _ = configure_service(service)
    labels_api.create.return_value = FakeRequest(
        {
            "id": "Label_2",
            "name": "Taxes",
            "type": "user",
            "messageListVisibility": "show",
            "labelListVisibility": "labelShow",
        }
    )
    operations = GmailOperations(FakeFactory(service))

    result = operations.create_label("Taxes")

    assert result["id"] == "Label_2"
    labels_api.create.assert_called_once()


def test_create_label_rejects_existing_name() -> None:
    service = MagicMock()
    labels_api, _ = configure_service(service)
    operations = GmailOperations(FakeFactory(service))

    with pytest.raises(ValueError, match="already exists"):
        operations.create_label(" receipts ")

    labels_api.create.assert_not_called()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"from_address": " ", "archive": True},
        {"subject": "", "mark_read": True},
        {"negated_query": "from:example.com", "star": True},
        {"has_attachment": False, "star": True},
        {"exclude_chats": True, "star": True},
        {"query": "in:anywhere", "archive": True},
        {"size": 100, "star": True},
        {"size_comparison": "larger", "star": True},
    ],
)
def test_create_filter_rejects_broad_or_incomplete_criteria(
    kwargs: dict[str, object],
) -> None:
    operations = GmailOperations(FakeFactory(MagicMock()))

    with pytest.raises(ValueError):
        operations.create_filter(**kwargs)


def test_create_filter_previews_then_executes_once() -> None:
    service = MagicMock()
    _, filters_api = configure_service(service)
    filters_api.create.return_value = FakeRequest(
        {
            "id": "filter-1",
            "criteria": {"from": "receipts@example.com"},
            "action": {
                "addLabelIds": ["Label_1"],
                "removeLabelIds": ["INBOX"],
            },
        }
    )
    operations = GmailOperations(FakeFactory(service))

    preview = operations.create_filter(
        from_address="receipts@example.com",
        add_label_ids=["Label_1"],
        archive=True,
    )

    assert preview["status"] == "confirmation_required"
    assert preview["confirmation"].startswith("CREATE_FILTER ")
    filters_api.create.assert_not_called()

    result = operations.create_filter(
        from_address="receipts@example.com",
        add_label_ids=["Label_1"],
        archive=True,
        confirmation=preview["confirmation"],
    )

    assert result["status"] == "created"
    filters_api.create.assert_called_once()
    with pytest.raises(ValueError, match="already used"):
        operations.create_filter(
            from_address="receipts@example.com",
            add_label_ids=["Label_1"],
            archive=True,
            confirmation=preview["confirmation"],
        )


def test_create_filter_rejects_system_label() -> None:
    service = MagicMock()
    configure_service(service)
    operations = GmailOperations(FakeFactory(service))

    with pytest.raises(ValueError, match="Only user labels"):
        operations.create_filter(
            from_address="sender@example.com",
            add_label_ids=["IMPORTANT"],
        )


def test_create_filter_requires_settings_scope() -> None:
    operations = GmailOperations(
        FakeFactory(MagicMock(), scopes=(GMAIL_MODIFY_SCOPE,))
    )

    with pytest.raises(AuthenticationRequiredError, match="settings.basic"):
        operations.create_filter(
            from_address="sender@example.com",
            star=True,
        )


def test_list_filters_redacts_forwarding_address() -> None:
    service = MagicMock()
    configure_service(
        service,
        filters=[
            {
                "id": "filter-forward",
                "criteria": {"from": "sender@example.com"},
                "action": {"forward": "secret@example.net"},
            }
        ],
    )
    operations = GmailOperations(FakeFactory(service))

    result = operations.list_filters()

    action = result["filters"][0]["action"]
    assert action["has_forward_action"] is True
    assert "secret@example.net" not in str(result)
    assert result["filters"][0]["safe_to_delete"] is False


def test_delete_filter_rejects_forwarding_filter() -> None:
    service = MagicMock()
    _, filters_api = configure_service(service)
    filters_api.get.return_value = FakeRequest(
        {
            "id": "filter-forward",
            "criteria": {"from": "sender@example.com"},
            "action": {"forward": "secret@example.net"},
        }
    )
    operations = GmailOperations(FakeFactory(service))

    with pytest.raises(ValueError, match="forwarding"):
        operations.delete_filter("filter-forward")

    filters_api.delete.assert_not_called()


def test_delete_filter_rejects_stale_preview() -> None:
    service = MagicMock()
    _, filters_api = configure_service(service)
    filters_api.get.side_effect = [
        FakeRequest(
            {
                "id": "filter-1",
                "criteria": {"from": "sender@example.com"},
                "action": {"addLabelIds": ["Label_1"]},
            }
        ),
        FakeRequest(
            {
                "id": "filter-1",
                "criteria": {"from": "changed@example.com"},
                "action": {"addLabelIds": ["Label_1"]},
            }
        ),
    ]
    operations = GmailOperations(FakeFactory(service))

    preview = operations.delete_filter("filter-1")

    with pytest.raises(ValueError, match="changed after preview"):
        operations.delete_filter(
            "filter-1",
            confirmation=preview["confirmation"],
        )
    filters_api.delete.assert_not_called()


def test_filter_confirmation_is_atomic_one_time() -> None:
    service = MagicMock()
    operations = GmailOperations(FakeFactory(service))
    record = operations.factory.store.load()
    token = operations._store_filter_confirmation(
        prefix="CREATE_FILTER",
        action="create_filter",
        record=record,
        payload_fingerprint="payload",
        label_metadata=(),
    )

    def consume() -> str:
        try:
            operations._consume_filter_confirmation(token, "create_filter")
            return "success"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: consume(), range(2)))

    assert sorted(results) == ["rejected", "success"]


def test_filter_confirmation_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MagicMock()
    operations = GmailOperations(FakeFactory(service))
    record = operations.factory.store.load()
    monkeypatch.setattr("gmail_mcp.operations.time.monotonic", lambda: 100.0)
    token = operations._store_filter_confirmation(
        prefix="CREATE_FILTER",
        action="create_filter",
        record=record,
        payload_fingerprint="payload",
        label_metadata=(),
    )
    monkeypatch.setattr("gmail_mcp.operations.time.monotonic", lambda: 1_000.0)

    with pytest.raises(ValueError, match="expired"):
        operations._consume_filter_confirmation(token, "create_filter")
