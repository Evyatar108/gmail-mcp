from __future__ import annotations

import json
import re
from typing import Any, Iterable


SCHEMA_VERSION = 1
SYSTEM_LABEL_NAMES = {
    "INBOX",
    "UNREAD",
    "STARRED",
}


def build_organization_export(
    labels: list[dict[str, Any]],
    filters: list[dict[str, Any]],
    account_email: str,
    aliases: Iterable[str] = (),
) -> dict[str, Any]:
    user_labels = sorted(
        (
            {
                "name": str(label["name"]),
                "message_list_visibility": label.get("message_list_visibility"),
                "label_list_visibility": label.get("label_list_visibility"),
            }
            for label in labels
            if label.get("type") == "user"
        ),
        key=lambda item: item["name"].casefold(),
    )
    label_names = {
        str(label["id"]): str(label["name"])
        for label in labels
        if label.get("type") == "user"
    }
    replacements = _address_replacements(account_email, aliases)

    exported_filters: list[dict[str, Any]] = []
    for filter_resource in filters:
        action = filter_resource.get("action") or {}
        if action.get("has_forward_action"):
            raise ValueError(
                "Organization export refuses filters with forwarding actions."
            )
        if not filter_resource.get("safe_to_delete"):
            raise ValueError(
                "Organization export refuses filters outside the safe action subset."
            )

        add_labels = [
            _label_name(label_id, label_names)
            for label_id in action.get("add_label_ids", [])
        ]
        remove_labels = [
            _label_name(label_id, label_names)
            for label_id in action.get("remove_label_ids", [])
        ]
        exported_filters.append(
            {
                "criteria": _replace_addresses(
                    filter_resource.get("criteria") or {},
                    replacements,
                ),
                "actions": {
                    "add_labels": sorted(add_labels, key=str.casefold),
                    "remove_labels": sorted(remove_labels, key=str.casefold),
                },
            }
        )

    exported_filters.sort(
        key=lambda item: json.dumps(
            item,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "privacy": {
            "classification": "private",
            "contains_third_party_contact_data": True,
            "contains_google_resource_ids": False,
            "contains_oauth_credentials": False,
        },
        "placeholders": sorted(replacements.values()),
        "labels": user_labels,
        "filters": exported_filters,
    }


def _label_name(label_id: str, label_names: dict[str, str]) -> str:
    if label_id in SYSTEM_LABEL_NAMES:
        return label_id
    try:
        return label_names[label_id]
    except KeyError as exc:
        raise ValueError(f"Unknown Gmail label ID in filter: {label_id}.") from exc


def _address_replacements(
    account_email: str,
    aliases: Iterable[str],
) -> dict[str, str]:
    addresses = [account_email, *aliases]
    replacements: dict[str, str] = {}
    for index, address in enumerate(addresses):
        normalized = address.strip()
        if not normalized:
            continue
        placeholder = (
            "${ACCOUNT_EMAIL}"
            if index == 0
            else f"${{ACCOUNT_ALIAS_{index}}}"
        )
        replacements[normalized.casefold()] = placeholder
    return replacements


def _replace_addresses(
    value: Any,
    replacements: dict[str, str],
) -> Any:
    if isinstance(value, dict):
        return {
            key: _replace_addresses(item, replacements)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_addresses(item, replacements) for item in value]
    if not isinstance(value, str):
        return value

    result = value
    address_character = r"A-Za-z0-9.!#$%&'*+/=?^_`{|}~@-"
    for address, placeholder in replacements.items():
        pattern = (
            rf"(?<![{address_character}])"
            rf"{re.escape(address)}"
            rf"(?![{address_character}])"
        )
        result = re.sub(
            pattern,
            lambda _: placeholder,
            result,
            flags=re.IGNORECASE,
        )
    return result
