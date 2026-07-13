import json

import pytest

from gmail_mcp.organization_export import build_organization_export


LABELS = [
    {
        "id": "Label_1",
        "name": "Finance",
        "type": "user",
        "message_list_visibility": "show",
        "label_list_visibility": "labelShow",
    },
    {
        "id": "INBOX",
        "name": "Inbox",
        "type": "system",
    },
]


def test_export_removes_ids_and_replaces_account_addresses() -> None:
    result = build_organization_export(
        labels=LABELS,
        filters=[
            {
                "id": "filter-secret-id",
                "criteria": {
                    "query": (
                        "to:user@example.com "
                        "deliveredto:alias@example.net "
                        "from:sender@example.org"
                    )
                },
                "action": {
                    "add_label_ids": ["Label_1"],
                    "remove_label_ids": ["INBOX"],
                    "has_forward_action": False,
                },
                "safe_to_delete": True,
            }
        ],
        account_email="user@example.com",
        aliases=["alias@example.net"],
    )

    serialized = json.dumps(result)
    assert "filter-secret-id" not in serialized
    assert "Label_1" not in serialized
    assert "user@example.com" not in serialized
    assert "alias@example.net" not in serialized
    assert "${ACCOUNT_EMAIL}" in serialized
    assert "${ACCOUNT_ALIAS_1}" in serialized
    assert "sender@example.org" in serialized
    assert result["filters"][0]["actions"] == {
        "add_labels": ["Finance"],
        "remove_labels": ["INBOX"],
    }


def test_export_rejects_forwarding_filter() -> None:
    with pytest.raises(ValueError, match="forwarding"):
        build_organization_export(
            labels=LABELS,
            filters=[
                {
                    "criteria": {"from": "sender@example.org"},
                    "action": {"has_forward_action": True},
                    "safe_to_delete": False,
                }
            ],
            account_email="user@example.com",
        )


def test_export_is_deterministic() -> None:
    filters = [
        {
            "criteria": {"from": "b@example.org"},
            "action": {
                "add_label_ids": ["Label_1"],
                "has_forward_action": False,
            },
            "safe_to_delete": True,
        },
        {
            "criteria": {"from": "a@example.org"},
            "action": {
                "add_label_ids": ["Label_1"],
                "has_forward_action": False,
            },
            "safe_to_delete": True,
        },
    ]

    first = build_organization_export(
        LABELS, filters, "user@example.com"
    )
    second = build_organization_export(
        LABELS, list(reversed(filters)), "user@example.com"
    )

    assert first == second


def test_export_does_not_replace_address_inside_longer_address() -> None:
    result = build_organization_export(
        labels=LABELS,
        filters=[
            {
                "criteria": {
                    "query": (
                        "from:prefixuser@example.com "
                        "to:<user@example.com>"
                    )
                },
                "action": {
                    "add_label_ids": ["Label_1"],
                    "has_forward_action": False,
                },
                "safe_to_delete": True,
            }
        ],
        account_email="user@example.com",
    )

    query = result["filters"][0]["criteria"]["query"]
    assert "prefixuser@example.com" in query
    assert "to:<${ACCOUNT_EMAIL}>" in query
