from __future__ import annotations

import io
import json
import zipfile
from dataclasses import replace
from uuid import UUID

from KnowledgeBase import upload_file


class _FakeResponse:
    def __init__(self, payload=None, content: bytes = b""):
        self._payload = payload
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeMinerUClient:
    def __init__(self, result_archive: bytes):
        self.request_paths: list[str] = []
        self.uploads: list[tuple[str, bytes]] = []
        self._result_archive = result_archive

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def request(self, method, url, **kwargs):
        self.request_paths.append(url)
        if url.endswith("/api/v4/file-urls/batch"):
            return _FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "batch_id": "batch-1",
                        "file_urls": ["https://upload.example/document"],
                    },
                }
            )
        if url.endswith("/api/v4/extract-results/batch/batch-1"):
            return _FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "extract_result": [
                            {
                                "state": "done",
                                "full_zip_url": "https://result.example/document.zip",
                            }
                        ]
                    },
                }
            )
        raise AssertionError(f"unexpected MinerU request: {method} {url}")

    def put(self, url, content, **kwargs):
        self.uploads.append((url, content))
        return _FakeResponse()

    def get(self, url, **kwargs):
        assert url == "https://result.example/document.zip"
        return _FakeResponse(content=self._result_archive)


def test_mineru_client_uses_current_batch_upload_protocol(monkeypatch, tmp_path):
    source = tmp_path / "reference.pdf"
    source.write_bytes(b"pdf-content")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as result:
        result.writestr("auto/reference.md", "# Parsed\n")
    fake_client = _FakeMinerUClient(archive.getvalue())
    monkeypatch.setattr(upload_file.httpx, "Client", lambda **kwargs: fake_client)

    markdown = upload_file.MinerUClient("token").convert_to_markdown(source)

    assert markdown == "# Parsed\n"
    assert fake_client.uploads == [("https://upload.example/document", b"pdf-content")]
    assert any(path.endswith("/api/v4/extract-results/batch/batch-1") for path in fake_client.request_paths)
    assert not any(path.endswith("/api/v4/extract/task") for path in fake_client.request_paths)


def test_prepare_markdown_upload(monkeypatch, tmp_path):
    raw_root = tmp_path / "raw"
    documents_root = tmp_path / "documents"
    monkeypatch.setattr(upload_file, "RAW_ROOT", raw_root)
    monkeypatch.setattr(upload_file, "DOCUMENTS_ROOT", documents_root)

    prepared = upload_file.prepare_upload("reference.md", b"# Reference\n")

    assert [item.name for item in prepared] == ["reference.md"]
    assert (documents_root / "reference.md").read_text(encoding="utf-8") == "# Reference\n"
    assert str(UUID(prepared[0].document_id)) == prepared[0].document_id
    assert prepared[0].source_name == "reference.md"
    assert upload_file.list_upload_records()[0].name == "reference.md"


def test_prepare_zip_upload_expands_each_source(monkeypatch, tmp_path):
    raw_root = tmp_path / "raw"
    documents_root = tmp_path / "documents"
    monkeypatch.setattr(upload_file, "RAW_ROOT", raw_root)
    monkeypatch.setattr(upload_file, "DOCUMENTS_ROOT", documents_root)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("notes/a.md", "# A\n")
        bundle.writestr("notes/b.txt", "B\n")

    prepared = upload_file.prepare_upload("bundle.zip", archive.getvalue())

    assert {item.name for item in prepared} == {"bundle_a.md", "bundle_b.md"}
    assert (documents_root / "bundle_a.md").read_text(encoding="utf-8") == "# A\n"
    assert (documents_root / "bundle_b.md").read_text(encoding="utf-8") == "B\n"


def test_convert_zip_member_uses_its_archived_raw_filename(monkeypatch, tmp_path):
    """ZIP members keep their collision-safe raw filename for later conversion."""
    raw_root = tmp_path / "raw"
    documents_root = tmp_path / "documents"
    monkeypatch.setattr(upload_file, "RAW_ROOT", raw_root)
    monkeypatch.setattr(upload_file, "DOCUMENTS_ROOT", documents_root)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("papers/a.pdf", b"pdf-content")
    prepared = upload_file.prepare_upload("bundle.zip", archive.getvalue())
    converted_paths: list[str] = []

    class FakeConverter:
        def __init__(self, *_args, **_kwargs):
            pass

        def convert_to_markdown(self, path):
            converted_paths.append(path.name)
            return "# Parsed\n"

    monkeypatch.setattr(upload_file, "MinerUClient", FakeConverter)
    converted, failed = upload_file.convert_documents(
        {prepared[0].document_id},
        mineru_api_key="token",
    )

    assert converted == [prepared[0].document_id]
    assert failed == []
    assert converted_paths == ["bundle_a.pdf"]


def test_repeated_uploads_keep_distinct_ids_and_source_names(monkeypatch, tmp_path):
    raw_root = tmp_path / "raw"
    documents_root = tmp_path / "documents"
    monkeypatch.setattr(upload_file, "RAW_ROOT", raw_root)
    monkeypatch.setattr(upload_file, "DOCUMENTS_ROOT", documents_root)

    first = upload_file.prepare_upload("reference.md", b"# First\n")
    second = upload_file.prepare_upload("reference.md", b"# Second\n")

    ids = [item.document_id for item in first + second]
    assert len(set(ids)) == 2
    assert all(str(UUID(document_id)) == document_id for document_id in ids)
    assert [item.name for item in first + second] == ["reference.md", "reference_2.md"]
    assert [record.name for record in upload_file.list_upload_records()] == [
        "reference.md",
        "reference.md",
    ]


def test_delete_upload_records_removes_selected_source_and_markdown(monkeypatch, tmp_path):
    raw_root = tmp_path / "raw"
    documents_root = tmp_path / "documents"
    monkeypatch.setattr(upload_file, "RAW_ROOT", raw_root)
    monkeypatch.setattr(upload_file, "DOCUMENTS_ROOT", documents_root)
    first = upload_file.prepare_upload("first.md", b"# First\n")[0]
    second = upload_file.prepare_upload("second.md", b"# Second\n")[0]

    deleted = upload_file.delete_upload_records({first.document_id})

    assert deleted == [first.document_id]
    assert not first.path.exists()
    assert not (raw_root / "first.md").exists()
    assert second.path.exists()
    assert (raw_root / "second.md").exists()
    assert [record.document_id for record in upload_file.list_upload_records()] == [
        second.document_id,
    ]


def test_delete_upload_records_removes_converted_source_and_markdown(monkeypatch, tmp_path):
    raw_root = tmp_path / "raw"
    documents_root = tmp_path / "documents"
    monkeypatch.setattr(upload_file, "RAW_ROOT", raw_root)
    monkeypatch.setattr(upload_file, "DOCUMENTS_ROOT", documents_root)
    prepared = upload_file.prepare_upload("reference.pdf", b"PDF")[0]
    converted_path = documents_root / "reference.md"
    converted_path.write_text("# Converted\n", encoding="utf-8")
    record = upload_file.list_upload_records()[0]
    upload_file._write_upload_records([
        replace(record, output_name=converted_path.name, is_conversion=True)
    ])

    deleted = upload_file.delete_upload_records({prepared.document_id})

    assert deleted == [prepared.document_id]
    assert not (raw_root / "reference.pdf").exists()
    assert not converted_path.exists()
    assert upload_file.list_upload_records() == []


def test_migrate_legacy_document_ids_replaces_numeric_and_duplicate_ids(monkeypatch, tmp_path):
    documents_root = tmp_path / "documents"
    documents_root.mkdir()
    monkeypatch.setattr(upload_file, "DOCUMENTS_ROOT", documents_root)
    (documents_root / ".uploads.json").write_text(
        '[{"document_id": 1}, {"document_id": 1}]', encoding="utf-8"
    )

    upload_file.migrate_legacy_document_ids()

    records = json.loads(
        (documents_root / ".uploads.json").read_text(encoding="utf-8")
    )
    ids = [record["document_id"] for record in records]
    assert len(set(ids)) == 2
    assert all(str(UUID(document_id)) == document_id for document_id in ids)
