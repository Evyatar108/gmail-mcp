from __future__ import annotations

import base64
from email.header import decode_header, make_header
from html.parser import HTMLParser
from typing import Any


SELECTED_HEADERS = (
    "From",
    "To",
    "Cc",
    "Bcc",
    "Subject",
    "Date",
    "Message-ID",
    "In-Reply-To",
    "References",
)


def decode_base64url(value: str) -> bytes:
    padded = value + ("=" * (-len(value) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def decode_header_value(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeError):
        return value


def headers_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    wanted = {name.lower(): name for name in SELECTED_HEADERS}
    result: dict[str, str] = {}
    for item in payload.get("headers", []):
        name = str(item.get("name", ""))
        canonical = wanted.get(name.lower())
        if canonical:
            result[canonical] = decode_header_value(str(item.get("value", "")))
    return result


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())


def decode_text_bytes(raw: bytes, declared_charset: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(declared_charset, errors="replace")


def extract_body(payload: dict[str, Any], max_chars: int) -> tuple[str, bool]:
    plain: list[str] = []
    html: list[str] = []

    def visit(part: dict[str, Any]) -> None:
        mime_type = str(part.get("mimeType", "")).lower()
        body = part.get("body") or {}
        data = body.get("data")
        if data and mime_type in {"text/plain", "text/html"}:
            charset = "utf-8"
            for header in part.get("headers", []):
                if str(header.get("name", "")).lower() == "content-type":
                    value = str(header.get("value", ""))
                    marker = "charset="
                    if marker in value.lower():
                        charset = value.lower().split(marker, 1)[1].split(";", 1)[0].strip("\"' ")
            decoded = decode_text_bytes(decode_base64url(str(data)), charset)
            (plain if mime_type == "text/plain" else html).append(decoded)
        for child in part.get("parts", []):
            visit(child)

    visit(payload)
    body = "\n\n".join(plain).strip()
    if not body and html:
        body = html_to_text("\n".join(html))
    truncated = len(body) > max_chars
    return body[:max_chars], truncated


def list_attachments(payload: dict[str, Any], max_items: int) -> tuple[list[dict[str, Any]], bool]:
    attachments: list[dict[str, Any]] = []

    def visit(part: dict[str, Any]) -> None:
        if len(attachments) >= max_items:
            return
        body = part.get("body") or {}
        filename = str(part.get("filename", ""))
        attachment_id = body.get("attachmentId")
        if filename or attachment_id:
            attachments.append(
                {
                    "part_id": part.get("partId"),
                    "attachment_id": attachment_id,
                    "filename": filename,
                    "mime_type": part.get("mimeType"),
                    "size": int(body.get("size", 0)),
                }
            )
        for child in part.get("parts", []):
            visit(child)

    visit(payload)
    return attachments, len(attachments) >= max_items


def normalize_message(
    message: dict[str, Any],
    max_body_chars: int,
    max_attachments: int,
) -> dict[str, Any]:
    payload = message.get("payload") or {}
    body, body_truncated = extract_body(payload, max_body_chars)
    attachments, attachments_truncated = list_attachments(payload, max_attachments)
    return {
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "history_id": message.get("historyId"),
        "internal_date": message.get("internalDate"),
        "label_ids": message.get("labelIds", []),
        "snippet": message.get("snippet", ""),
        "headers": headers_from_payload(payload),
        "body": body,
        "body_truncated": body_truncated,
        "attachments": attachments,
        "attachments_truncated": attachments_truncated,
    }
