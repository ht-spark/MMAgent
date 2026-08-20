from __future__ import annotations

import asyncio
import io
import json
import time

from fastapi import HTTPException
from fastapi import UploadFile
from KnowledgeBase import upload_file
from server import main
from server.schemas import BrainstormRequest, KnowledgeDocumentsDeleteBody
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


def test_knowledge_status_recovers_conversion_state_from_markdown_output(monkeypatch, tmp_path):
    """Existing converted Markdown makes its source document eligible for chunking."""
    documents_root = tmp_path / "documents"
    documents_root.mkdir()
    (documents_root / "source.md").write_text("# Converted", encoding="utf-8")
    (documents_root / ".uploads.json").write_text(
        '[{"document_id": "document-id", "name": "source.pdf", "size_bytes": 12, '
        '"uploaded_at": "2026-08-15T00:00:00+00:00", "upload_success": true, '
        '"output_name": "source.pdf", "is_markdown": false, "is_conversion": false}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "KNOWLEDGE_DOCUMENTS_ROOT", documents_root)
    monkeypatch.setattr("KnowledgeBase.upload_file.DOCUMENTS_ROOT", documents_root)

    status = asyncio.run(main.knowledge_status_endpoint())

    assert status.documents[0].is_conversion is True
    assert '"output_name": "source.md"' in (documents_root / ".uploads.json").read_text(encoding="utf-8")


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


def test_brainstorm_endpoint_returns_retrieved_sources(monkeypatch):
    """The inspiration endpoint exposes the local retrieval result to the UI."""
    chunk = type(
        "Chunk",
        (),
        {
            "source_file": "reference.md",
            "document_id": "document-uuid",
            "context": "与问题相关的知识片段",
            "text": "用于生成回答的实际分块",
        },
    )()
    compression_llm = object()
    retrieval_llms: list[object] = []
    monkeypatch.setattr(main, "_active_discussion_llm", lambda: compression_llm)
    monkeypatch.setattr(
        main,
        "retrieve_knowledge",
        lambda _, **kwargs: retrieval_llms.append(kwargs["llm"]) or [chunk],
    )
    generated: list[object] = []
    monkeypatch.setattr(
        main,
        "_generate_discussion_answer",
        lambda message, history, chunks, llm: generated.extend([message, history, chunks, llm]) or "基于资料的回答。",
    )
    monkeypatch.setattr(main, "save_discussion_message", lambda *_: "discussion-uuid")

    result = asyncio.run(main.brainstorm_endpoint(BrainstormRequest(message="如何建模？")))

    assert result.message == "基于资料的回答。"
    assert result.discussion_id == "discussion-uuid"
    assert generated[0] == "如何建模？"
    assert generated[2] == [chunk]
    assert generated[3] is compression_llm
    assert retrieval_llms == [compression_llm]
    assert result.sources[0].model_dump() == {
        "source_file": "reference.md",
        "document_id": "document-uuid",
        "content": "与问题相关的知识片段",
    }


def test_brainstorm_stream_endpoint_yields_tokens_and_saves_on_completion(monkeypatch):
    """Streaming discussion sends source, token, and completion events in order."""
    monkeypatch.setattr(main, "_active_discussion_llm", lambda: object())
    monkeypatch.setattr(main, "retrieve_knowledge", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "_stream_discussion_answer", lambda *_args: iter(["逐段", "回答"]))
    saved: list[object] = []
    monkeypatch.setattr(main, "save_discussion_message", lambda *args: saved.append(args) or "discussion-uuid")

    response = asyncio.run(main.brainstorm_stream_endpoint(message="如何建模？", files=None))

    async def consume() -> list[str]:
        return [part async for part in response.body_iterator]

    events = [json.loads(item) for item in asyncio.run(consume())]

    assert events == [
        {"type": "sources", "sources": []},
        {"type": "token", "content": "逐段"},
        {"type": "token", "content": "回答"},
        {"type": "done", "discussion_id": "discussion-uuid"},
    ]
    assert saved[0][2] == "逐段回答"


def test_prepare_discussion_attachments_extracts_markdown(monkeypatch):
    """A Markdown attachment is passed to the discussion model as text context."""
    upload = UploadFile(filename="notes.md", file=io.BytesIO("# 建模笔记".encode("utf-8")))

    attachments = asyncio.run(main._prepare_discussion_attachments([upload]))

    assert attachments == [{"kind": "text", "name": "notes.md", "content": "# 建模笔记"}]


def test_brainstorm_endpoint_uses_llm_when_knowledge_is_empty(monkeypatch):
    """An empty retrieval result falls back to the selected discussion LLM."""
    monkeypatch.setattr(main, "_active_discussion_llm", lambda: object())
    monkeypatch.setattr(main, "retrieve_knowledge", lambda _, **kwargs: [])
    monkeypatch.setattr(main, "_generate_discussion_answer", lambda *_: "可以直接讨论建模方案。")
    monkeypatch.setattr(main, "save_discussion_message", lambda *_: "discussion-uuid")

    result = asyncio.run(main.brainstorm_endpoint(BrainstormRequest(message="如何建模？")))

    assert result.message == "可以直接讨论建模方案。"
    assert result.discussion_id == "discussion-uuid"
    assert result.sources == []


def test_brainstorm_endpoint_returns_timeout_when_retrieval_stalls(monkeypatch):
    """A slow compression or retrieval call must not leave the UI waiting forever."""
    monkeypatch.setattr(main, "_active_discussion_llm", lambda: object())
    monkeypatch.setattr(main, "BRAINSTORM_RETRIEVAL_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(main, "retrieve_knowledge", lambda *_args, **_kwargs: time.sleep(0.02))

    try:
        asyncio.run(main.brainstorm_endpoint(BrainstormRequest(message="如何建模？")))
    except HTTPException as exc:
        assert exc.status_code == 504
        assert exc.detail == "知识库检索与上下文压缩超时，请稍后重试。"
    else:
        raise AssertionError("Expected a retrieval timeout")


def test_discussion_answer_passes_retrieved_window_to_llm_and_hides_thinking(monkeypatch):
    """RAG answers use the retained node's complete window as context."""
    prompts: list[list[tuple[str, str]]] = []

    class FakeLlm:
        def invoke(self, messages):
            prompts.append(messages)
            return type("Response", (), {"content": "<think>hidden</think>可执行的建模建议。"})()

    chunk = type(
        "Chunk",
        (),
        {"source_file": "reference.md", "text": "实际分块内容", "context": "完整窗口上下文"},
    )()
    monkeypatch.setattr(main, "_active_discussion_llm", lambda: FakeLlm())

    answer = main._generate_discussion_answer("如何建模？", [], [chunk], FakeLlm())

    assert answer == "可执行的建模建议。"
    assert "完整窗口上下文" in prompts[0][-1][1]


def test_brainstorm_discussion_endpoints_restore_saved_messages(monkeypatch):
    """Saved discussions can be listed and loaded for continued chat."""
    discussion = {
        "id": "discussion-uuid",
        "title": "如何建模？",
        "updated_at": "2026-08-18T00:00:00+00:00",
        "messages": [{"role": "user", "content": "如何建模？", "sources": []}],
    }
    monkeypatch.setattr(main, "list_discussions", lambda: [discussion])
    monkeypatch.setattr(main, "get_discussion", lambda _: discussion)

    summaries = asyncio.run(main.list_brainstorm_discussions_endpoint())
    restored = asyncio.run(main.get_brainstorm_discussion_endpoint("discussion-uuid"))

    assert summaries[0].title == "如何建模？"
    assert restored.messages[0].content == "如何建模？"
