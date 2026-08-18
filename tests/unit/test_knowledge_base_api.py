from __future__ import annotations

import asyncio

from KnowledgeBase import upload_file
from server import main
from server.schemas import KnowledgeDocumentsDeleteBody
from KnowledgeBase.embedding import IndexBuildResult


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
        ("7", "source.pdf", False),
    ]


def test_delete_knowledge_documents_endpoint_removes_selected_record(monkeypatch, tmp_path):
    raw_root = tmp_path / "raw"
    documents_root = tmp_path / "documents"
    monkeypatch.setattr(upload_file, "RAW_ROOT", raw_root)
    monkeypatch.setattr(upload_file, "DOCUMENTS_ROOT", documents_root)
    prepared = upload_file.prepare_upload("reference.md", b"# Reference\n")[0]
    deleted_vector_ids: set[str] = set()
    refreshed_metadata: dict[str, str] = {}
    monkeypatch.setattr(main, "delete_document_vectors", lambda ids: deleted_vector_ids.update(ids))
    monkeypatch.setattr(
        main,
        "chunk_knowledge_documents",
        lambda **kwargs: refreshed_metadata.update(kwargs["document_ids_by_source"]),
    )

    result = asyncio.run(
        main.delete_knowledge_documents_endpoint(
            KnowledgeDocumentsDeleteBody(document_ids=[prepared.document_id])
        )
    )

    assert result == {"deleted_ids": [prepared.document_id]}
    assert not prepared.path.exists()
    assert upload_file.list_upload_records() == []
    assert deleted_vector_ids == {prepared.document_id}
    assert refreshed_metadata == {}


def test_chunk_embed_endpoint_returns_actual_index_counts(monkeypatch, tmp_path):
    documents_root = tmp_path / "documents"
    documents_root.mkdir()
    monkeypatch.setattr(upload_file, "DOCUMENTS_ROOT", documents_root)
    prepared = upload_file.prepare_upload("reference.md", b"# Reference\n")[0]
    def chunk_documents():
        assert main._get_knowledge_processing_progress().stage == "chunking"
        return tmp_path / "nodes.jsonl"

    def build_index():
        assert main._get_knowledge_processing_progress().stage == "embedding"
        return IndexBuildResult(
            collection_name="knowledge_chunks",
            indexed_nodes=3,
            vector_size=512,
            qdrant_path=tmp_path / "qdrant_db",
            source_chunk_counts={prepared.name: 3},
        )

    monkeypatch.setattr(main, "chunk_knowledge_documents", lambda **kwargs: chunk_documents())
    monkeypatch.setattr(
        main,
        "build_local_qdrant_index",
        build_index,
    )

    result = asyncio.run(main.chunk_and_embed_knowledge_endpoint())

    assert result.chunks_indexed == 3
    assert result.vector_size == 512
    assert result.document_chunks == {prepared.document_id: 3}
    assert main._get_knowledge_processing_progress().stage == "done"
