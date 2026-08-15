from __future__ import annotations

import json

from KnowledgeBase.chunk_embedding import (
    build_sentence_window_nodes,
    chunk_knowledge_documents,
)


def test_sentence_window_chunking_loads_only_markdown(tmp_path):
    documents_root = tmp_path / "documents"
    documents_root.mkdir()
    (documents_root / "reference.md").write_text(
        "First sentence. Second sentence. Third sentence.",
        encoding="utf-8",
    )
    (documents_root / "ignored.txt").write_text("not prepared markdown", encoding="utf-8")
    (documents_root / ".uploads.json").write_text("[]", encoding="utf-8")

    nodes = build_sentence_window_nodes(documents_root, window_size=1)

    assert len(nodes) == 3
    assert {node.metadata["source_file"] for node in nodes} == {"reference.md"}
    assert all("window" in node.metadata for node in nodes)
    assert all("original_text" in node.metadata for node in nodes)


def test_chunk_knowledge_documents_writes_jsonl_nodes(tmp_path):
    documents_root = tmp_path / "documents"
    chunks_root = tmp_path / "chunks"
    documents_root.mkdir()
    (documents_root / "reference.md").write_text(
        "One sentence. Another sentence.", encoding="utf-8"
    )

    output_path = chunk_knowledge_documents(documents_root, chunks_root, window_size=1)

    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert output_path.name == "sentence_window_nodes.jsonl"
    assert len(rows) == 2
    assert rows[0]["metadata"]["source_file"] == "reference.md"
