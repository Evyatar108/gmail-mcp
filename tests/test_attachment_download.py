import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import gmail_mcp.operations as operations_module
from gmail_mcp.config import MAX_ATTACHMENT_DOWNLOAD_BYTES
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


def configure_attachment(
    service: MagicMock,
    *,
    attachment_id: str = "a1",
    filename: str = "report.pdf",
    size: int = 3,
    data: str | None = None,
    include_attachment_id: bool = True,
) -> tuple[MagicMock, MagicMock]:
    messages = service.users.return_value.messages.return_value
    body: dict[str, object] = {"size": size}
    if include_attachment_id:
        body["attachmentId"] = attachment_id
    else:
        body["data"] = base64.urlsafe_b64encode(b"abc").decode()
    messages.get.return_value = FakeRequest(
        {
            "id": "m1",
            "payload": {
                "parts": [
                    {
                        "partId": "1",
                        "mimeType": "application/pdf",
                        "filename": filename,
                        "headers": [
                            {
                                "name": "Content-Disposition",
                                "value": 'attachment; filename="report.pdf"',
                            }
                        ],
                        "body": body,
                    }
                ]
            },
        }
    )
    attachments = messages.attachments.return_value
    attachments.get.return_value = FakeRequest(
        {
            "data": data
            if data is not None
            else base64.urlsafe_b64encode(b"abc").decode().rstrip("="),
            "size": size,
        }
    )
    return messages, attachments


def test_download_attachment_writes_exact_bytes_and_uses_long_id(
    tmp_path: Path,
) -> None:
    service = MagicMock()
    attachment_id = "a" * 600
    messages, attachments = configure_attachment(
        service,
        attachment_id=attachment_id,
    )
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    result = operations.download_attachment(
        "m1",
        "1",
        str(tmp_path),
    )

    target = tmp_path / "report.pdf"
    assert target.read_bytes() == b"abc"
    assert result["path"] == str(target.resolve())
    assert result["size"] == 3
    messages.get.assert_called_once_with(userId="me", id="m1", format="full")
    attachments.get.assert_called_once_with(
        userId="me",
        messageId="m1",
        id=attachment_id,
    )


def test_download_attachment_rejects_data_only_parts(
    tmp_path: Path,
) -> None:
    service = MagicMock()
    _, attachments = configure_attachment(
        service,
        include_attachment_id=False,
    )
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="inline/data-only"):
        operations.download_attachment("m1", "1", str(tmp_path))

    attachments.get.assert_not_called()


def test_download_attachment_rejects_unknown_part_id(tmp_path: Path) -> None:
    service = MagicMock()
    _, attachments = configure_attachment(service)
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="MIME part ID"):
        operations.download_attachment("m1", "2", str(tmp_path))

    attachments.get.assert_not_called()


def test_download_attachment_rejects_metadata_oversize_before_fetch(
    tmp_path: Path,
) -> None:
    service = MagicMock()
    _, attachments = configure_attachment(service, size=4)
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="metadata size"):
        operations.download_attachment("m1", "1", str(tmp_path), max_bytes=3)

    attachments.get.assert_not_called()


@pytest.mark.parametrize("max_bytes", [0, MAX_ATTACHMENT_DOWNLOAD_BYTES + 1])
def test_download_attachment_rejects_invalid_max_before_api(
    tmp_path: Path,
    max_bytes: int,
) -> None:
    service = MagicMock()
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="max_bytes"):
        operations.download_attachment("m1", "1", str(tmp_path), max_bytes)

    service.users.assert_not_called()


def test_download_attachment_rejects_encoded_data_that_cannot_fit(
    tmp_path: Path,
) -> None:
    service = MagicMock()
    configure_attachment(service, size=0, data="AAAAA")
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="cannot fit"):
        operations.download_attachment("m1", "1", str(tmp_path), max_bytes=3)


def test_download_attachment_rejects_malformed_base64url(tmp_path: Path) -> None:
    service = MagicMock()
    configure_attachment(service, size=0, data="AAA$")
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="malformed base64url"):
        operations.download_attachment("m1", "1", str(tmp_path), max_bytes=3)


def test_download_attachment_allows_exact_decoded_limit(tmp_path: Path) -> None:
    service = MagicMock()
    configure_attachment(
        service,
        size=3,
        data=base64.urlsafe_b64encode(b"abc").decode().rstrip("="),
    )
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    result = operations.download_attachment("m1", "1", str(tmp_path), max_bytes=3)

    assert result["size"] == 3


@pytest.mark.parametrize("destination", ["relative", "missing"])
def test_download_attachment_requires_existing_absolute_directory(
    tmp_path: Path,
    destination: str,
) -> None:
    service = MagicMock()
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]
    value = destination if destination == "relative" else str(tmp_path / destination)

    with pytest.raises(ValueError, match="destination_directory"):
        operations.download_attachment("m1", "1", value)

    service.users.assert_not_called()


def test_download_attachment_sanitizes_reserved_traversal_filename(
    tmp_path: Path,
) -> None:
    service = MagicMock()
    configure_attachment(service, filename=r"..\CON.txt")
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    result = operations.download_attachment("m1", "1", str(tmp_path))

    target = Path(str(result["path"]))
    assert target.parent == tmp_path.resolve()
    assert target.name == "_CON.txt"
    assert target.read_bytes() == b"abc"


def test_download_attachment_uses_deterministic_empty_name_fallback(
    tmp_path: Path,
) -> None:
    service = MagicMock()
    configure_attachment(service, filename="..")
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    result = operations.download_attachment("m1", "1", str(tmp_path))

    assert str(result["filename"]).startswith("attachment-")
    assert Path(str(result["path"])).parent == tmp_path.resolve()


def test_download_attachment_limits_filename_by_utf16_units(tmp_path: Path) -> None:
    service = MagicMock()
    configure_attachment(service, filename=f"{'😀' * 240}.pdf")
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    result = operations.download_attachment("m1", "1", str(tmp_path))

    filename = str(result["filename"])
    assert len(filename.encode("utf-16-le")) // 2 <= 240
    assert filename.endswith(".pdf")
    assert Path(str(result["path"])).exists()


def test_download_attachment_refuses_existing_sanitized_target(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "_CON.txt"
    existing.write_bytes(b"existing")
    service = MagicMock()
    _, attachments = configure_attachment(service, filename="CON.txt")
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="already exists"):
        operations.download_attachment("m1", "1", str(tmp_path))

    assert existing.read_bytes() == b"existing"
    attachments.get.assert_not_called()


def test_download_attachment_removes_partial_file_on_write_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MagicMock()
    configure_attachment(service)
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]
    target = (tmp_path / "report.pdf").resolve()
    original_open = Path.open

    class FailingFile:
        def __enter__(self) -> "FailingFile":
            self.handle = original_open(target, "xb")
            return self

        def write(self, content: bytes) -> None:
            self.handle.write(content[:1])
            raise OSError("disk failure")

        def __exit__(self, *args: object) -> None:
            self.handle.close()

    monkeypatch.setattr(
        operations_module,
        "_open_new_attachment_file",
        lambda path: FailingFile(),
    )
    monkeypatch.setattr(
        operations_module,
        "_opened_file_path",
        lambda output: target,
    )
    monkeypatch.setattr(
        operations_module,
        "_mark_open_file_for_deletion",
        lambda output: (output.handle.close(), target.unlink()),
    )

    with pytest.raises(ValueError, match="Unable to write attachment"):
        operations.download_attachment("m1", "1", str(tmp_path))

    assert not target.exists()


def test_download_attachment_rejects_directory_swap_after_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MagicMock()
    configure_attachment(service)
    operations = GmailOperations(FakeFactory(service))  # type: ignore[arg-type]
    target = (tmp_path / "report.pdf").resolve()
    outside_directory = tmp_path / "outside"
    outside_directory.mkdir()
    outside_target = (outside_directory / "report.pdf").resolve()
    original_open = Path.open

    monkeypatch.setattr(
        operations_module,
        "_open_new_attachment_file",
        lambda path: original_open(outside_target, "xb"),
    )
    monkeypatch.setattr(
        operations_module,
        "_opened_file_path",
        lambda output: outside_target,
    )
    monkeypatch.setattr(
        operations_module,
        "_mark_open_file_for_deletion",
        lambda output: (output.close(), outside_target.unlink()),
    )

    with pytest.raises(ValueError, match="Destination changed"):
        operations.download_attachment("m1", "1", str(tmp_path))

    assert not target.exists()
    assert not outside_target.exists()
