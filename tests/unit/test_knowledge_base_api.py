from __future__ import annotations

import asyncio

from KnowledgeBase import upload_file
from server import main
from server.schemas import KnowledgeDocumentsDeleteBody


def test_knowledge_status_lists_archived_documents(monkeypatch, tmp_path):
    """The MVP status endpoint exposes locally archived source documents."""
    documents_root = tmp_path / "documents"
    documents_root.mkdir()
    (documents_root / "reference.md").write_text("reference", encoding="utf-8")
    monkeypatch.setattr(main, "KNOWLEDGE_DOCUMENTS_ROOT", documents_root)
    monkeypatch.setattr("KnowledgeBase.upload_file.DOCUMENTS_ROOT", documents_root)

    status = asyncio.run(main.knowledge_status_endpoint())

    assert status.retrieval_ready is False
    assert [(item.name, item.size_bytes) for item in status.documents] == [
        ("reference.md", 9),
    ]


def test_knowledge_status_prefers_persisted_upload_metadata(monkeypatch, tmp_path):
    """Status restores stable table fields instead of generated Markdown names."""
    documents_root = tmp_path / "documents"
    documents_root.mkdir()
    (documents_root / ".uploads.json").write_text(
        '[{"document_id": 7, "name": "source.pdf", "size_bytes": 12, '
        '"uploaded_at": "2026-08-15T00:00:00+00:00", "upload_success": true, '
        '"output_name": "source.md"}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "KNOWLEDGE_DOCUMENTS_ROOT", documents_root)
    monkeypatch.setattr("KnowledgeBase.upload_file.DOCUMENTS_ROOT", documents_root)

    status = asyncio.run(main.knowledge_status_endpoint())

    assert [(item.id, item.name, item.is_markdown) for item in status.documents] == [
        (7, "source.pdf", False),
    ]


def test_delete_knowledge_documents_endpoint_removes_selected_record(monkeypatch, tmp_path):
    raw_root = tmp_path / "raw"
    documents_root = tmp_path / "documents"
    monkeypatch.setattr(upload_file, "RAW_ROOT", raw_root)
    monkeypatch.setattr(upload_file, "DOCUMENTS_ROOT", documents_root)
    prepared = upload_file.prepare_upload("reference.md", b"# Reference\n")[0]

    result = asyncio.run(
        main.delete_knowledge_documents_endpoint(
            KnowledgeDocumentsDeleteBody(document_ids=[prepared.document_id])
        )
    )

    assert result == {"deleted_ids": [prepared.document_id]}
    assert not prepared.path.exists()
    assert upload_file.list_upload_records() == []
