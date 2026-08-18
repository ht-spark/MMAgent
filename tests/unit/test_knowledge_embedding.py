from __future__ import annotations

import json

from qdrant_client import QdrantClient

from KnowledgeBase import embedding


class _FakeEmbeddingModel:
    def embed_documents(self, texts: list[str]):
        return [[float(index + 1), 0.5, 0.25] for index, _ in enumerate(texts)]


def test_build_local_qdrant_index_uses_local_chunks(monkeypatch, tmp_path):
    chunk_path = tmp_path / "sentence_window_nodes.jsonl"
    chunk_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "id_": "node-1",
                    "text": "第一句。",
                    "metadata": {
                        "window": "第一句。第二句。",
                        "original_text": "第一句。",
                        "source_file": "reference.md",
                        "source_path": "C:/example/reference.md",
                        "document_id": "document-uuid",
                    },
                },
                ensure_ascii=False,
            )
            for _ in range(2)
        ),
        encoding="utf-8",
    )
    model_path = tmp_path / "embedding_model"
    model_path.mkdir()
    (model_path / "config.json").write_text("{}", encoding="utf-8")
    qdrant_path = tmp_path / "qdrant_db"
    monkeypatch.setattr(
        embedding,
        "_load_huggingface_embedding_model",
        lambda path: _FakeEmbeddingModel(),
    )

    result = embedding.build_local_qdrant_index(chunk_path, model_path, qdrant_path)

    client = QdrantClient(path=str(qdrant_path))
    collection = client.get_collection(result.collection_name)
    points, _ = client.scroll(result.collection_name, limit=10, with_payload=True)
    client.close()
    assert result.indexed_nodes == 2
    assert result.vector_size == 3
    assert collection.config.params.vectors.size == 3
    assert points[0].payload["source_file"] == "reference.md"
    assert points[0].payload["document_id"] == "document-uuid"
    assert result.source_chunk_counts == {"reference.md": 2}

    embedding.delete_document_vectors({"document-uuid"}, qdrant_path)
    client = QdrantClient(path=str(qdrant_path))
    remaining, _ = client.scroll(result.collection_name, limit=10, with_payload=True)
    client.close()
    assert remaining == []
