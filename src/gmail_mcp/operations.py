from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import secrets
import threading
import time
import unicodedata
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses
from html import escape
from pathlib import Path
from typing import Any, Iterable

from gmail_mcp.config import (
    DEFAULT_ATTACHMENTS,
    DEFAULT_MAX_BODY_CHARS,
    DEFAULT_SEARCH_RESULTS,
    DEFAULT_THREAD_MESSAGES,
    FILTER_CONFIRMATION_TTL_SECONDS,
    GMAIL_SETTINGS_BASIC_SCOPE,
    MAX_ATTACHMENTS,
    MAX_ATTACHMENT_DOWNLOAD_BYTES,
    MAX_BODY_CHARS,
    MAX_DRAFT_BODY_CHARS,
    MAX_FILTER_ADDRESS_CHARS,
    MAX_FILTER_QUERY_CHARS,
    MAX_FILTER_SIZE_BYTES,
    MAX_MUTATION_MESSAGES,
    MAX_PENDING_CONFIRMATIONS,
    MAX_RECIPIENTS,
    MAX_SEARCH_RESULTS,
    MAX_SUBJECT_CHARS,
    MAX_THREAD_MESSAGES,
)
from gmail_mcp.errors import AuthenticationRequiredError, GmailApiError
from gmail_mcp.gmail_client import GmailClientFactory
from gmail_mcp.message_parser import (
    find_attachment_part,
    headers_from_payload,
    normalize_message,
)


METADATA_HEADERS = ["From", "To", "Cc", "Bcc", "Subject", "Date", "Message-ID", "References"]
PROTECTED_LABEL_IDS = {"TRASH", "SPAM"}
SAFE_FILTER_SYSTEM_ADD_IDS = {"STARRED"}
SAFE_FILTER_SYSTEM_REMOVE_IDS = {"INBOX", "UNREAD"}
LABEL_LIST_VISIBILITIES = {"labelShow", "labelShowIfUnread", "labelHide"}
MESSAGE_LIST_VISIBILITIES = {"show", "hide"}
FILTER_SIZE_COMPARISONS = {"smaller", "larger"}
MAX_LABEL_NAME_CHARS = 225
MAX_ATTACHMENT_FILENAME_CHARS = 240
WINDOWS_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


@dataclass(frozen=True)
class PendingFilterConfirmation:
    action: str
    account_email: str
    credential_fingerprint: str
    scopes: tuple[str, ...]
    payload_fingerprint: str
    label_metadata: tuple[tuple[str, str, str], ...]
    filter_id: str | None
    resource_fingerprint: str | None
    created_at: float
    expires_at: float


class GmailOperations:
    def __init__(self, factory: GmailClientFactory | None = None) -> None:
        self.factory = factory or GmailClientFactory()
        self._pending_filter_confirmations: dict[str, PendingFilterConfirmation] = {}
        self._pending_filter_lock = threading.Lock()

    def search(
        self,
        query: str,
        page_size: int = DEFAULT_SEARCH_RESULTS,
        page_token: str | None = None,
        include_spam_trash: bool = True,
    ) -> dict[str, Any]:
        page_size = _bounded(page_size, 1, MAX_SEARCH_RESULTS, "page_size")
        service = self.factory.get_service()
        request = service.users().messages().list(
            userId="me",
            q=query or None,
            maxResults=page_size,
            pageToken=page_token,
            includeSpamTrash=include_spam_trash,
        )
        result = self.factory.execute(request)
        summaries = [self._message_summary(service, item["id"]) for item in result.get("messages", [])]
        return {
            "messages": summaries,
            "next_page_token": result.get("nextPageToken"),
            "result_size_estimate": result.get("resultSizeEstimate", len(summaries)),
            "include_spam_trash": include_spam_trash,
        }

    def get_message(
        self,
        message_id: str,
        max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
        max_attachments: int = DEFAULT_ATTACHMENTS,
    ) -> dict[str, Any]:
        max_body_chars = _bounded(max_body_chars, 0, MAX_BODY_CHARS, "max_body_chars")
        max_attachments = _bounded(max_attachments, 0, MAX_ATTACHMENTS, "max_attachments")
        service = self.factory.get_service()
        message = self.factory.execute(
            service.users().messages().get(userId="me", id=_id(message_id), format="full")
        )
        return normalize_message(message, max_body_chars, max_attachments)

    def get_thread(
        self,
        thread_id: str,
        max_messages: int = DEFAULT_THREAD_MESSAGES,
        max_body_chars_per_message: int = 10_000,
    ) -> dict[str, Any]:
        max_messages = _bounded(max_messages, 1, MAX_THREAD_MESSAGES, "max_messages")
        max_body_chars_per_message = _bounded(
            max_body_chars_per_message, 0, MAX_BODY_CHARS, "max_body_chars_per_message"
        )
        service = self.factory.get_service()
        thread = self.factory.execute(
            service.users().threads().get(userId="me", id=_id(thread_id), format="full")
        )
        messages = thread.get("messages", [])
        normalized = [
            normalize_message(item, max_body_chars_per_message, DEFAULT_ATTACHMENTS)
            for item in messages[:max_messages]
        ]
        return {
            "id": thread.get("id"),
            "history_id": thread.get("historyId"),
            "messages": normalized,
            "messages_truncated": len(messages) > max_messages,
        }

    def list_labels(self) -> dict[str, Any]:
        service = self.factory.get_service()
        result = self.factory.execute(service.users().labels().list(userId="me"))
        labels = sorted(
            (
                {
                    "id": label.get("id"),
                    "name": label.get("name"),
                    "type": label.get("type"),
                    "message_list_visibility": label.get("messageListVisibility"),
                    "label_list_visibility": label.get("labelListVisibility"),
                }
                for label in result.get("labels", [])
            ),
            key=lambda item: (str(item["type"]), str(item["name"]).lower()),
        )
        return {"labels": labels}

    def create_label(
        self,
        name: str,
        message_list_visibility: str = "show",
        label_list_visibility: str = "labelShow",
    ) -> dict[str, Any]:
        normalized_name = _label_name(name)
        if message_list_visibility not in MESSAGE_LIST_VISIBILITIES:
            raise ValueError(
                "message_list_visibility must be 'show' or 'hide'."
            )
        if label_list_visibility not in LABEL_LIST_VISIBILITIES:
            raise ValueError(
                "label_list_visibility must be labelShow, labelShowIfUnread, "
                "or labelHide."
            )
        service = self.factory.get_service()
        labels = self._label_catalog(service)
        duplicate = next(
            (
                label
                for label in labels.values()
                if str(label.get("name", "")).casefold()
                == normalized_name.casefold()
            ),
            None,
        )
        if duplicate:
            raise ValueError(
                f"Gmail label already exists: {duplicate.get('name')} "
                f"({duplicate.get('id')})."
            )
        created = self.factory.execute(
            service.users().labels().create(
                userId="me",
                body={
                    "name": normalized_name,
                    "messageListVisibility": message_list_visibility,
                    "labelListVisibility": label_list_visibility,
                },
            )
        )
        return {
            "id": created.get("id"),
            "name": created.get("name"),
            "type": created.get("type"),
            "message_list_visibility": created.get("messageListVisibility"),
            "label_list_visibility": created.get("labelListVisibility"),
        }

    def list_filters(self) -> dict[str, Any]:
        service = self.factory.get_service()
        labels = self._label_catalog(service)
        result = self.factory.execute(
            service.users().settings().filters().list(userId="me")
        )
        filters = [
            self._filter_preview(item, labels)
            for item in result.get("filter", [])
        ]
        filters.sort(key=lambda item: str(item.get("id", "")))
        return {"filters": filters}

    def create_filter(
        self,
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
        criteria, action = _normalize_filter_definition(
            from_address=from_address,
            to_address=to_address,
            subject=subject,
            query=query,
            negated_query=negated_query,
            has_attachment=has_attachment,
            exclude_chats=exclude_chats,
            size=size,
            size_comparison=size_comparison,
            add_label_ids=add_label_ids,
            archive=archive,
            mark_read=mark_read,
            star=star,
        )
        payload_fingerprint = _fingerprint(
            {"criteria": criteria, "action": action}
        )

        if confirmation is not None:
            pending = self._consume_filter_confirmation(
                confirmation, "create_filter"
            )
            if pending.payload_fingerprint != payload_fingerprint:
                raise ValueError(
                    "Filter inputs changed after preview. Request a new preview."
                )
            record = self._credential_record(GMAIL_SETTINGS_BASIC_SCOPE)
            self._verify_pending_credential(pending, record)
            service = self.factory.get_service()
            labels = self._label_catalog(service)
            label_metadata = self._validate_filter_labels(action, labels)
            if label_metadata != pending.label_metadata:
                raise ValueError(
                    "Referenced Gmail labels changed after preview. "
                    "Request a new preview."
                )
            self._reject_duplicate_filter(service, criteria, action)
            try:
                created = self.factory.execute(
                    service.users().settings().filters().create(
                        userId="me",
                        body={"criteria": criteria, "action": action},
                    )
                )
            except GmailApiError as exc:
                if "400" in str(exc) or "409" in str(exc):
                    raise GmailApiError(
                        "Gmail rejected the filter; an equivalent filter may "
                        "already exist."
                    ) from exc
                raise
            return {
                "status": "created",
                "filter": self._filter_preview(created, labels),
            }

        record = self._credential_record(GMAIL_SETTINGS_BASIC_SCOPE)
        service = self.factory.get_service()
        labels = self._label_catalog(service)
        label_metadata = self._validate_filter_labels(action, labels)
        self._reject_duplicate_filter(service, criteria, action)
        token = self._store_filter_confirmation(
            prefix="CREATE_FILTER",
            action="create_filter",
            record=record,
            payload_fingerprint=payload_fingerprint,
            label_metadata=label_metadata,
        )
        return {
            "status": "confirmation_required",
            "action": "create_filter",
            "preview": {
                "criteria": criteria,
                "action": _redact_filter_action(action),
            },
            "confirmation": token,
            "expires_in_seconds": FILTER_CONFIRMATION_TTL_SECONDS,
        }

    def delete_filter(
        self,
        filter_id: str,
        confirmation: str | None = None,
    ) -> dict[str, Any]:
        normalized_id = _id(filter_id)
        if confirmation is not None:
            pending = self._consume_filter_confirmation(
                confirmation, "delete_filter"
            )
            if pending.filter_id != normalized_id:
                raise ValueError(
                    "Filter ID changed after preview. Request a new preview."
                )
            record = self._credential_record(GMAIL_SETTINGS_BASIC_SCOPE)
            self._verify_pending_credential(pending, record)
            service = self.factory.get_service()
            labels = self._label_catalog(service)
            current = self._get_filter(service, normalized_id)
            self._require_safe_existing_filter(current, labels)
            if _fingerprint(_canonical_filter(current)) != pending.resource_fingerprint:
                raise ValueError(
                    "The Gmail filter changed after preview. Request a new preview."
                )
            self.factory.execute(
                service.users().settings().filters().delete(
                    userId="me", id=normalized_id
                )
            )
            return {"status": "deleted", "filter_id": normalized_id}

        record = self._credential_record(GMAIL_SETTINGS_BASIC_SCOPE)
        service = self.factory.get_service()
        labels = self._label_catalog(service)
        current = self._get_filter(service, normalized_id)
        self._require_safe_existing_filter(current, labels)
        resource_fingerprint = _fingerprint(_canonical_filter(current))
        token = self._store_filter_confirmation(
            prefix=f"DELETE_FILTER {normalized_id}",
            action="delete_filter",
            record=record,
            payload_fingerprint=resource_fingerprint,
            label_metadata=(),
            filter_id=normalized_id,
            resource_fingerprint=resource_fingerprint,
        )
        return {
            "status": "confirmation_required",
            "action": "delete_filter",
            "preview": self._filter_preview(current, labels),
            "confirmation": token,
            "expires_in_seconds": FILTER_CONFIRMATION_TTL_SECONDS,
        }

    def list_attachments(
        self,
        message_id: str,
        max_items: int = DEFAULT_ATTACHMENTS,
    ) -> dict[str, Any]:
        message = self.get_message(message_id, max_body_chars=0, max_attachments=max_items)
        return {
            "message_id": message["id"],
            "attachments": message["attachments"],
            "attachments_truncated": message["attachments_truncated"],
        }

    def download_attachment(
        self,
        message_id: str,
        part_id: str,
        destination_directory: str,
        max_bytes: int = MAX_ATTACHMENT_DOWNLOAD_BYTES,
    ) -> dict[str, Any]:
        normalized_message_id = _id(message_id)
        max_bytes = _bounded(
            max_bytes,
            1,
            MAX_ATTACHMENT_DOWNLOAD_BYTES,
            "max_bytes",
        )
        destination = _resolved_destination_directory(destination_directory)

        service = self.factory.get_service()
        message = self.factory.execute(
            service.users().messages().get(
                userId="me",
                id=normalized_message_id,
                format="full",
            )
        )
        attachment = find_attachment_part(message.get("payload") or {}, part_id)
        if attachment is None:
            raise ValueError("MIME part ID was not found in this message.")
        attachment_id = attachment.get("attachment_id")
        if not isinstance(attachment_id, str) or not attachment_id:
            raise ValueError(
                "The selected MIME part is inline/data-only and has no downloadable "
                "Gmail attachment ID."
            )

        advertised_size = int(attachment.get("size", 0))
        if advertised_size > max_bytes:
            raise ValueError(
                f"Attachment metadata size {advertised_size} exceeds max_bytes {max_bytes}."
            )

        filename = _safe_attachment_filename(
            str(attachment.get("filename") or ""),
            f"{normalized_message_id}:{part_id}",
        )
        target = (destination / filename).resolve(strict=False)
        if target.parent != destination:
            raise ValueError("Attachment filename resolves outside destination_directory.")
        if target.exists():
            raise ValueError(f"Destination file already exists: {target}")

        response = self.factory.execute(
            service.users().messages().attachments().get(
                userId="me",
                messageId=normalized_message_id,
                id=attachment_id,
            )
        )
        encoded = response.get("data")
        if not isinstance(encoded, str):
            raise ValueError("Gmail attachment response did not contain base64url data.")
        compact_encoded = "".join(encoded.split())
        max_encoded_chars = 4 * ((max_bytes + 2) // 3)
        if len(compact_encoded) > max_encoded_chars:
            raise ValueError(
                f"Encoded attachment data cannot fit within max_bytes {max_bytes}."
            )
        if len(compact_encoded) % 4 == 1:
            raise ValueError("Gmail attachment response contained malformed base64url data.")
        padded = compact_encoded + ("=" * (-len(compact_encoded) % 4))
        try:
            content = base64.b64decode(
                padded.encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
        except (binascii.Error, UnicodeEncodeError) as exc:
            raise ValueError(
                "Gmail attachment response contained malformed base64url data."
            ) from exc
        if len(content) > max_bytes:
            raise ValueError(
                f"Decoded attachment size {len(content)} exceeds max_bytes {max_bytes}."
            )

        try:
            with _open_new_attachment_file(target) as output:
                try:
                    created_path = _opened_file_path(output)
                    if created_path != target:
                        raise OSError("Destination changed during file creation.")
                    written = output.write(content)
                    if written != len(content):
                        raise OSError(
                            f"Short write: wrote {written} of {len(content)} bytes."
                        )
                except OSError:
                    try:
                        _mark_open_file_for_deletion(output)
                    except OSError as cleanup_exc:
                        raise OSError(
                            "Attachment write failed and handle cleanup also failed."
                        ) from cleanup_exc
                    raise
        except FileExistsError as exc:
            raise ValueError(f"Destination file already exists: {target}") from exc
        except OSError as exc:
            raise ValueError(f"Unable to write attachment to {target}: {exc}") from exc

        return {
            "message_id": normalized_message_id,
            "part_id": part_id,
            "attachment_id": attachment_id,
            "filename": filename,
            "mime_type": attachment.get("mime_type"),
            "content_disposition": attachment.get("content_disposition"),
            "size": len(content),
            "path": str(target),
        }

    def modify_labels(
        self,
        message_ids: list[str],
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        ids = _ids(message_ids)
        add = _labels(add_label_ids or [])
        remove = _labels(remove_label_ids or [])
        if not add and not remove:
            raise ValueError("At least one label must be added or removed.")
        protected = sorted((set(add) | set(remove)) & PROTECTED_LABEL_IDS)
        if protected:
            raise ValueError(
                f"Protected labels must use dedicated tools and cannot be modified here: {protected}."
            )
        overlap = sorted(set(add) & set(remove))
        if overlap:
            raise ValueError(f"Labels cannot be added and removed together: {overlap}.")
        service = self.factory.get_service()
        self.factory.execute(
            service.users().messages().batchModify(
                userId="me",
                body={"ids": ids, "addLabelIds": add, "removeLabelIds": remove},
            )
        )
        return {
            "modified_count": len(ids),
            "message_ids": ids,
            "added_label_ids": add,
            "removed_label_ids": remove,
        }

    def archive(self, message_ids: list[str]) -> dict[str, Any]:
        return self.modify_labels(message_ids, remove_label_ids=["INBOX"])

    def create_draft(
        self,
        to: list[str],
        subject: str | None,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to_message_id: str | None = None,
        rtl: bool = False,
    ) -> dict[str, Any]:
        recipients = {
            "To": _recipients(to, "to"),
            "Cc": _recipients(cc or [], "cc"),
            "Bcc": _recipients(bcc or [], "bcc"),
        }
        total_recipients = sum(len(values) for values in recipients.values())
        if total_recipients == 0:
            raise ValueError("At least one recipient is required.")
        if total_recipients > MAX_RECIPIENTS:
            raise ValueError(f"A draft may contain at most {MAX_RECIPIENTS} recipients.")
        if len(body) > MAX_DRAFT_BODY_CHARS:
            raise ValueError(f"Draft body exceeds {MAX_DRAFT_BODY_CHARS} characters.")

        service = self.factory.get_service()
        source: dict[str, Any] | None = None
        thread_id: str | None = None
        if reply_to_message_id:
            source = self.factory.execute(
                service.users().messages().get(
                    userId="me",
                    id=_id(reply_to_message_id),
                    format="metadata",
                    metadataHeaders=METADATA_HEADERS,
                )
            )
            thread_id = str(source.get("threadId") or "")
            source_headers = headers_from_payload(source.get("payload") or {})
            source_message_id = source_headers.get("Message-ID")
            source_subject = source_headers.get("Subject", "")
            if not source_message_id or not thread_id:
                raise ValueError("Source message lacks threading metadata.")
            if subject is None:
                subject = source_subject if source_subject.lower().startswith("re:") else f"Re: {source_subject}"
            elif _base_subject(subject) != _base_subject(source_subject):
                raise ValueError("Reply subject must remain compatible with the source thread.")
        subject = _header(subject or "", "subject", MAX_SUBJECT_CHARS)

        message = EmailMessage()
        for header, values in recipients.items():
            if values:
                message[header] = ", ".join(values)
        message["Subject"] = subject
        if source:
            source_headers = headers_from_payload(source.get("payload") or {})
            source_message_id = source_headers["Message-ID"]
            references = source_headers.get("References", "").split()
            if source_message_id not in references:
                references.append(source_message_id)
            message["In-Reply-To"] = source_message_id
            message["References"] = " ".join(references)
        message.set_content(body)
        if rtl:
            escaped_body = escape(body).replace("\n", "<br>\n")
            message.add_alternative(
                '<div dir="rtl" style="text-align: right;">'
                f"{escaped_body}</div>",
                subtype="html",
            )

        raw = base64.urlsafe_b64encode(message.as_bytes(policy=policy.SMTP)).decode("ascii")
        gmail_message: dict[str, Any] = {"raw": raw}
        if thread_id:
            gmail_message["threadId"] = thread_id
        draft = self.factory.execute(
            service.users().drafts().create(userId="me", body={"message": gmail_message})
        )
        return {
            "draft_id": draft.get("id"),
            "message_id": (draft.get("message") or {}).get("id"),
            "thread_id": (draft.get("message") or {}).get("threadId"),
            "recipients": recipients,
            "subject": subject,
            "rtl": rtl,
        }

    def send_draft(self, draft_id: str, confirmation: str | None = None) -> dict[str, Any]:
        service = self.factory.get_service()
        state = self._draft_state(service, _id(draft_id))
        expected = f"SEND {state['draft_id']} {state['fingerprint']}"
        if confirmation != expected:
            return {
                "status": "confirmation_required",
                "action": "send_draft",
                "preview": {
                    "draft_id": state["draft_id"],
                    "recipients": state["recipients"],
                    "subject": state["subject"],
                },
                "confirmation": expected,
            }
        sent = self.factory.execute(
            service.users().drafts().send(userId="me", body={"id": state["draft_id"]})
        )
        return {
            "status": "sent",
            "message_id": sent.get("id"),
            "thread_id": sent.get("threadId"),
            "label_ids": sent.get("labelIds", []),
        }

    def trash(self, message_ids: list[str], confirmation: str | None = None) -> dict[str, Any]:
        ids = _ids(message_ids, maximum=20)
        service = self.factory.get_service()
        state = self._trash_state(service, ids)
        expected = f"TRASH {state['fingerprint']}"
        if confirmation != expected:
            return {
                "status": "confirmation_required",
                "action": "trash_messages",
                "preview": state["messages"],
                "message_ids": ids,
                "confirmation": expected,
            }

        trashed: list[str] = []
        try:
            for message_id in ids:
                self.factory.execute(
                    service.users().messages().trash(userId="me", id=message_id)
                )
                trashed.append(message_id)
        except GmailApiError as exc:
            rollback_failures: list[str] = []
            for message_id in reversed(trashed):
                try:
                    self.factory.execute(
                        service.users().messages().untrash(userId="me", id=message_id)
                    )
                except GmailApiError:
                    rollback_failures.append(message_id)
            if rollback_failures:
                raise GmailApiError(
                    f"Trash failed after {len(trashed)} messages; rollback also failed for "
                    f"{rollback_failures}. Inspect these messages in Gmail."
                ) from exc
            raise GmailApiError("Trash failed; completed changes were rolled back.") from exc
        return {"status": "trashed", "message_ids": trashed, "count": len(trashed)}

    def untrash(self, message_ids: list[str]) -> dict[str, Any]:
        ids = _ids(message_ids)
        service = self.factory.get_service()
        restored: list[str] = []
        for message_id in ids:
            try:
                self.factory.execute(
                    service.users().messages().untrash(userId="me", id=message_id)
                )
                restored.append(message_id)
            except GmailApiError as exc:
                raise GmailApiError(
                    f"Untrash stopped after restoring {len(restored)} messages. "
                    f"Restored IDs: {restored}."
                ) from exc
        return {"status": "restored", "message_ids": restored, "count": len(restored)}

    def _message_summary(self, service: Any, message_id: str) -> dict[str, Any]:
        message = self.factory.execute(
            service.users().messages().get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=METADATA_HEADERS,
            )
        )
        return {
            "id": message.get("id"),
            "thread_id": message.get("threadId"),
            "label_ids": message.get("labelIds", []),
            "snippet": message.get("snippet", ""),
            "headers": headers_from_payload(message.get("payload") or {}),
        }

    def _draft_state(self, service: Any, draft_id: str) -> dict[str, Any]:
        draft = self.factory.execute(
            service.users().drafts().get(userId="me", id=draft_id, format="raw")
        )
        gmail_message = draft.get("message") or {}
        raw_value = str(gmail_message.get("raw") or "")
        if not raw_value:
            raise ValueError("Draft has no raw message content.")
        raw = _decode_raw(raw_value)
        parsed = BytesParser(policy=policy.default).parsebytes(raw)
        recipients = {
            name.lower(): sorted(
                address.lower()
                for _, address in getaddresses(parsed.get_all(name, []))
                if address
            )
            for name in ("To", "Cc", "Bcc")
        }
        if not any(recipients.values()):
            raise ValueError("Draft has no valid recipients.")
        canonical = {
            "draft_id": draft.get("id"),
            "message_id": gmail_message.get("id"),
            "recipients": recipients,
            "subject": str(parsed.get("Subject", "")),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
        }
        fingerprint = hashlib.sha256(
            json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        return {
            **canonical,
            "fingerprint": fingerprint,
        }

    def _trash_state(self, service: Any, message_ids: list[str]) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        for message_id in message_ids:
            message = self.factory.execute(
                service.users().messages().get(
                    userId="me",
                    id=message_id,
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date", "Message-ID"],
                )
            )
            labels = list(message.get("labelIds", []))
            if "TRASH" in labels:
                raise ValueError(f"Message {message_id} is already in Trash.")
            headers = headers_from_payload(message.get("payload") or {})
            messages.append(
                {
                    "id": message_id,
                    "from": headers.get("From", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                    "message_id_header": headers.get("Message-ID", ""),
                    "internal_date": message.get("internalDate"),
                }
            )
        messages.sort(key=lambda item: item["id"])
        fingerprint = hashlib.sha256(
            json.dumps(messages, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        return {"messages": messages, "fingerprint": fingerprint}

    def _credential_record(self, required_scope: str | None = None):
        record = self.factory.store.load()
        if record is None:
            raise AuthenticationRequiredError(
                "Gmail is not authenticated. Run `gmail-mcp auth`."
            )
        if required_scope and required_scope not in record.scopes:
            raise AuthenticationRequiredError(
                f"Gmail authorization lacks {required_scope}. Add the scope in "
                "Google Auth Platform and run `gmail-mcp auth` again."
            )
        return record

    def _verify_pending_credential(
        self,
        pending: PendingFilterConfirmation,
        record: Any,
    ) -> None:
        if (
            pending.account_email != record.account_email
            or pending.credential_fingerprint != record.fingerprint
            or pending.scopes != tuple(sorted(record.scopes))
        ):
            raise AuthenticationRequiredError(
                "Gmail authorization changed after preview. Request a new preview."
            )

    def _store_filter_confirmation(
        self,
        prefix: str,
        action: str,
        record: Any,
        payload_fingerprint: str,
        label_metadata: tuple[tuple[str, str, str], ...],
        filter_id: str | None = None,
        resource_fingerprint: str | None = None,
    ) -> str:
        now = time.monotonic()
        token = f"{prefix} {secrets.token_urlsafe(24)}"
        pending = PendingFilterConfirmation(
            action=action,
            account_email=record.account_email,
            credential_fingerprint=record.fingerprint,
            scopes=tuple(sorted(record.scopes)),
            payload_fingerprint=payload_fingerprint,
            label_metadata=label_metadata,
            filter_id=filter_id,
            resource_fingerprint=resource_fingerprint,
            created_at=now,
            expires_at=now + FILTER_CONFIRMATION_TTL_SECONDS,
        )
        with self._pending_filter_lock:
            self._evict_pending_locked(now)
            if len(self._pending_filter_confirmations) >= MAX_PENDING_CONFIRMATIONS:
                oldest = min(
                    self._pending_filter_confirmations,
                    key=lambda item: self._pending_filter_confirmations[item].created_at,
                )
                self._pending_filter_confirmations.pop(oldest, None)
            self._pending_filter_confirmations[token] = pending
        return token

    def _consume_filter_confirmation(
        self,
        token: str,
        expected_action: str,
    ) -> PendingFilterConfirmation:
        now = time.monotonic()
        with self._pending_filter_lock:
            self._evict_pending_locked(now)
            pending = self._pending_filter_confirmations.pop(token, None)
        if pending is None:
            raise ValueError(
                "Filter confirmation is invalid, expired, or already used. "
                "Request a new preview."
            )
        if pending.action != expected_action:
            raise ValueError(
                "Filter confirmation does not match this action. "
                "Request a new preview."
            )
        return pending

    def _evict_pending_locked(self, now: float) -> None:
        expired = [
            token
            for token, pending in self._pending_filter_confirmations.items()
            if pending.expires_at <= now
        ]
        for token in expired:
            self._pending_filter_confirmations.pop(token, None)

    def _label_catalog(self, service: Any) -> dict[str, dict[str, Any]]:
        result = self.factory.execute(service.users().labels().list(userId="me"))
        return {
            str(label.get("id")): label
            for label in result.get("labels", [])
            if label.get("id")
        }

    def _validate_filter_labels(
        self,
        action: dict[str, Any],
        labels: dict[str, dict[str, Any]],
    ) -> tuple[tuple[str, str, str], ...]:
        metadata: list[tuple[str, str, str]] = []
        for label_id in action.get("addLabelIds", []):
            if label_id in SAFE_FILTER_SYSTEM_ADD_IDS:
                continue
            label = labels.get(label_id)
            if not label:
                raise ValueError(f"Unknown Gmail label ID: {label_id}.")
            if label.get("type") != "user":
                raise ValueError(
                    f"Only user labels may be added by filters: {label_id}."
                )
            metadata.append(
                (
                    label_id,
                    str(label.get("name", "")),
                    str(label.get("type", "")),
                )
            )
        return tuple(sorted(metadata))

    def _reject_duplicate_filter(
        self,
        service: Any,
        criteria: dict[str, Any],
        action: dict[str, Any],
    ) -> None:
        expected = _canonical_filter({"criteria": criteria, "action": action})
        result = self.factory.execute(
            service.users().settings().filters().list(userId="me")
        )
        if any(
            _canonical_filter(item) == expected
            for item in result.get("filter", [])
        ):
            raise ValueError("An equivalent Gmail filter already exists.")

    def _get_filter(self, service: Any, filter_id: str) -> dict[str, Any]:
        try:
            return self.factory.execute(
                service.users().settings().filters().get(
                    userId="me", id=filter_id
                )
            )
        except GmailApiError as exc:
            if "404" in str(exc):
                raise ValueError(f"Gmail filter not found: {filter_id}.") from exc
            raise

    def _require_safe_existing_filter(
        self,
        filter_resource: dict[str, Any],
        labels: dict[str, dict[str, Any]],
    ) -> None:
        action = filter_resource.get("action") or {}
        if action.get("forward"):
            raise ValueError(
                "Filters with forwarding must be managed manually in Gmail settings."
            )
        add_ids = set(action.get("addLabelIds", []))
        remove_ids = set(action.get("removeLabelIds", []))
        unsafe_add = {
            label_id
            for label_id in add_ids
            if label_id not in SAFE_FILTER_SYSTEM_ADD_IDS
            and (
                label_id not in labels
                or labels[label_id].get("type") != "user"
            )
        }
        unsafe_remove = remove_ids - SAFE_FILTER_SYSTEM_REMOVE_IDS
        if unsafe_add or unsafe_remove:
            raise ValueError(
                "This filter contains actions outside the MCP safe subset and "
                "must be managed manually in Gmail settings."
            )

    def _filter_preview(
        self,
        filter_resource: dict[str, Any],
        labels: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        action = filter_resource.get("action") or {}
        return {
            "id": filter_resource.get("id"),
            "criteria": filter_resource.get("criteria") or {},
            "action": _redact_filter_action(action),
            "safe_to_delete": _is_safe_filter_action(action, labels),
        }


def _bounded(value: int, minimum: int, maximum: int, name: str) -> int:
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _resolved_destination_directory(value: str) -> Path:
    requested = Path(value).expanduser()
    if not requested.is_absolute():
        raise ValueError("destination_directory must be an absolute path.")
    try:
        resolved = requested.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"destination_directory does not exist: {requested}") from exc
    if not resolved.is_dir():
        raise ValueError(f"destination_directory is not a directory: {resolved}")
    return resolved


def _safe_attachment_filename(filename: str, fallback_key: str) -> str:
    normalized = unicodedata.normalize("NFKC", filename)
    basename = normalized.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(
        "_"
        if character in '<>:"/\\|?*' or unicodedata.category(character).startswith("C")
        else character
        for character in basename
    ).strip()
    cleaned = cleaned.rstrip(" .")
    if not cleaned:
        digest = hashlib.sha256(fallback_key.encode("utf-8")).hexdigest()[:12]
        cleaned = f"attachment-{digest}"

    reserved_stem = cleaned.split(".", 1)[0].upper()
    if reserved_stem in WINDOWS_RESERVED_FILENAMES:
        cleaned = f"_{cleaned}"

    if _utf16_code_units(cleaned) > MAX_ATTACHMENT_FILENAME_CHARS:
        original_suffix = Path(cleaned).suffix
        suffix = _truncate_utf16(original_suffix, 20)
        stem_source = (
            cleaned[: -len(original_suffix)] if original_suffix else cleaned
        )
        stem_limit = MAX_ATTACHMENT_FILENAME_CHARS - _utf16_code_units(suffix)
        stem = _truncate_utf16(stem_source, stem_limit).rstrip(" .")
        cleaned = f"{stem}{suffix}"
    return cleaned


def _utf16_code_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _truncate_utf16(value: str, max_units: int) -> str:
    units = 0
    characters: list[str] = []
    for character in value:
        character_units = _utf16_code_units(character)
        if units + character_units > max_units:
            break
        characters.append(character)
        units += character_units
    return "".join(characters)


def _opened_file_path(output: Any) -> Path:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    get_final_path = ctypes.WinDLL(
        "kernel32",
        use_last_error=True,
    ).GetFinalPathNameByHandleW
    get_final_path.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    get_final_path.restype = wintypes.DWORD

    handle = msvcrt.get_osfhandle(output.fileno())
    required = get_final_path(handle, None, 0, 0)
    if required == 0:
        error = ctypes.get_last_error()
        raise OSError(error, "Unable to resolve opened attachment path.")
    buffer = ctypes.create_unicode_buffer(required + 1)
    written = get_final_path(handle, buffer, len(buffer), 0)
    if written == 0 or written >= len(buffer):
        error = ctypes.get_last_error()
        raise OSError(error, "Unable to resolve opened attachment path.")

    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = f"\\\\{value[8:]}"
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value).resolve(strict=True)


def _open_new_attachment_file(path: Path) -> Any:
    import ctypes
    import msvcrt
    import os
    from ctypes import wintypes

    create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE

    generic_write = 0x40000000
    delete_access = 0x00010000
    create_new = 1
    file_attribute_normal = 0x00000080
    handle = create_file(
        str(path),
        generic_write | delete_access,
        0,
        None,
        create_new,
        file_attribute_normal,
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        if error in {80, 183}:
            raise FileExistsError(error, "Destination file already exists.", str(path))
        raise OSError(error, "Unable to create attachment file.", str(path))

    try:
        descriptor = msvcrt.open_osfhandle(
            handle,
            os.O_BINARY | os.O_WRONLY,
        )
    except OSError:
        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)
        raise
    return os.fdopen(descriptor, "wb", buffering=0)


def _mark_open_file_for_deletion(output: Any) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class FileDispositionInfo(ctypes.Structure):
        _fields_ = [("delete_file", wintypes.BOOL)]

    set_file_information = ctypes.WinDLL(
        "kernel32",
        use_last_error=True,
    ).SetFileInformationByHandle
    set_file_information.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    set_file_information.restype = wintypes.BOOL

    handle = msvcrt.get_osfhandle(output.fileno())
    disposition = FileDispositionInfo(True)
    if not set_file_information(
        handle,
        4,
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        error = ctypes.get_last_error()
        raise OSError(error, "Unable to mark partial attachment for deletion.")


def _label_name(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Label name must not be blank.")
    if len(normalized) > MAX_LABEL_NAME_CHARS:
        raise ValueError(
            f"Label name exceeds {MAX_LABEL_NAME_CHARS} characters."
        )
    if any(unicodedata.category(character) == "Cc" for character in normalized):
        raise ValueError("Label name must not contain control characters.")
    return normalized


def _optional_filter_text(
    value: str | None,
    name: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters.")
    if any(unicodedata.category(character) == "Cc" for character in normalized):
        raise ValueError(f"{name} must not contain control characters.")
    return normalized


def _normalize_filter_definition(
    *,
    from_address: str | None,
    to_address: str | None,
    subject: str | None,
    query: str | None,
    negated_query: str | None,
    has_attachment: bool | None,
    exclude_chats: bool | None,
    size: int | None,
    size_comparison: str | None,
    add_label_ids: list[str] | None,
    archive: bool,
    mark_read: bool,
    star: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_from = _optional_filter_text(
        from_address, "from_address", MAX_FILTER_ADDRESS_CHARS
    )
    normalized_to = _optional_filter_text(
        to_address, "to_address", MAX_FILTER_ADDRESS_CHARS
    )
    normalized_subject = _optional_filter_text(
        subject, "subject", MAX_FILTER_ADDRESS_CHARS
    )
    normalized_query = _optional_filter_text(
        query, "query", MAX_FILTER_QUERY_CHARS
    )
    normalized_negated_query = _optional_filter_text(
        negated_query, "negated_query", MAX_FILTER_QUERY_CHARS
    )

    if (size is None) != (size_comparison is None):
        raise ValueError(
            "size and size_comparison must be provided together."
        )
    if size is not None:
        if size < 1 or size > MAX_FILTER_SIZE_BYTES:
            raise ValueError(
                f"size must be between 1 and {MAX_FILTER_SIZE_BYTES}."
            )
        if size_comparison not in FILTER_SIZE_COMPARISONS:
            raise ValueError(
                "size_comparison must be 'smaller' or 'larger'."
            )

    positive_criteria = any(
        (
            normalized_from,
            normalized_to,
            normalized_subject,
            normalized_query,
            size is not None,
        )
    )
    if not positive_criteria:
        raise ValueError(
            "A filter requires a positive narrowing criterion: from, to, "
            "subject, query, or size comparison."
        )
    if (archive or mark_read) and not any(
        (normalized_from, normalized_to, normalized_subject)
    ):
        raise ValueError(
            "Filters that archive or mark read require from, to, or subject."
        )

    criteria: dict[str, Any] = {}
    if normalized_from:
        criteria["from"] = normalized_from
    if normalized_to:
        criteria["to"] = normalized_to
    if normalized_subject:
        criteria["subject"] = normalized_subject
    if normalized_query:
        criteria["query"] = normalized_query
    if normalized_negated_query:
        criteria["negatedQuery"] = normalized_negated_query
    if has_attachment is not None:
        criteria["hasAttachment"] = has_attachment
    if exclude_chats is not None:
        criteria["excludeChats"] = exclude_chats
    if size is not None:
        criteria["size"] = size
        criteria["sizeComparison"] = size_comparison

    user_label_ids = _labels(add_label_ids or [])
    protected = sorted(set(user_label_ids) & PROTECTED_LABEL_IDS)
    if protected:
        raise ValueError(
            f"Protected labels cannot be used in filters: {protected}."
        )
    add_ids = list(user_label_ids)
    remove_ids: list[str] = []
    if star:
        add_ids.append("STARRED")
    if archive:
        remove_ids.append("INBOX")
    if mark_read:
        remove_ids.append("UNREAD")
    add_ids = sorted(set(add_ids))
    remove_ids = sorted(set(remove_ids))
    if not add_ids and not remove_ids:
        raise ValueError("A filter requires at least one action.")

    action: dict[str, Any] = {}
    if add_ids:
        action["addLabelIds"] = add_ids
    if remove_ids:
        action["removeLabelIds"] = remove_ids
    return criteria, action


def _canonical_filter(filter_resource: dict[str, Any]) -> dict[str, Any]:
    criteria = {
        key: value
        for key, value in sorted((filter_resource.get("criteria") or {}).items())
        if value is not None and value != ""
    }
    raw_action = filter_resource.get("action") or {}
    action: dict[str, Any] = {}
    if raw_action.get("addLabelIds"):
        action["addLabelIds"] = sorted(set(raw_action["addLabelIds"]))
    if raw_action.get("removeLabelIds"):
        action["removeLabelIds"] = sorted(set(raw_action["removeLabelIds"]))
    if raw_action.get("forward"):
        action["forward"] = str(raw_action["forward"]).casefold()
    return {"criteria": criteria, "action": action}


def _redact_filter_action(action: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if action.get("addLabelIds"):
        result["add_label_ids"] = sorted(set(action["addLabelIds"]))
    if action.get("removeLabelIds"):
        result["remove_label_ids"] = sorted(set(action["removeLabelIds"]))
    result["has_forward_action"] = bool(action.get("forward"))
    return result


def _is_safe_filter_action(
    action: dict[str, Any],
    labels: dict[str, dict[str, Any]],
) -> bool:
    if action.get("forward"):
        return False
    add_ids = set(action.get("addLabelIds", []))
    remove_ids = set(action.get("removeLabelIds", []))
    if remove_ids - SAFE_FILTER_SYSTEM_REMOVE_IDS:
        return False
    return all(
        label_id in SAFE_FILTER_SYSTEM_ADD_IDS
        or (
            label_id in labels
            and labels[label_id].get("type") == "user"
        )
        for label_id in add_ids
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _id(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 256 or not re.fullmatch(r"[A-Za-z0-9_-]+", normalized):
        raise ValueError("Invalid Gmail resource ID.")
    return normalized


def _ids(values: Iterable[str], maximum: int = MAX_MUTATION_MESSAGES) -> list[str]:
    ids = sorted({_id(value) for value in values})
    if not ids:
        raise ValueError("At least one message ID is required.")
    if len(ids) > maximum:
        raise ValueError(f"At most {maximum} message IDs are allowed.")
    return ids


def _labels(values: Iterable[str]) -> list[str]:
    labels = sorted({value.strip() for value in values if value.strip()})
    if len(labels) > 100:
        raise ValueError("At most 100 labels are allowed.")
    if any(len(label) > 256 for label in labels):
        raise ValueError("Invalid label ID.")
    return labels


def _recipients(values: Iterable[str], field: str) -> list[str]:
    result: list[str] = []
    for value in values:
        safe = _header(value, field, 500)
        parsed = getaddresses([safe])
        if len(parsed) != 1 or not parsed[0][1] or "@" not in parsed[0][1]:
            raise ValueError(f"Invalid {field} recipient: {value!r}.")
        result.append(safe)
    return result


def _header(value: str, field: str, maximum: int) -> str:
    if "\r" in value or "\n" in value:
        raise ValueError(f"{field} must not contain CR or LF characters.")
    if len(value) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters.")
    return value.strip()


def _base_subject(value: str) -> str:
    subject = value.strip()
    while True:
        stripped = re.sub(r"^(re|fwd?)\s*:\s*", "", subject, flags=re.IGNORECASE)
        if stripped == subject:
            return subject.casefold()
        subject = stripped.strip()


def _decode_raw(value: str) -> bytes:
    padded = value + ("=" * (-len(value) % 4))
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("Draft raw message is invalid.") from exc
