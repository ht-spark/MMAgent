"""Hybrid retrieval for the local knowledge base.

The retrieval path intentionally starts with the user's original question: dense
and BM25 recall each return up to 50 candidates, reciprocal-rank fusion keeps
the best five, and an optional LLM filter compresses the final context. 
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

try:
    from .embedding import COLLECTION_NAME, MODEL_PATH, QDRANT_PATH, _load_huggingface_embedding_model
except ImportError:  # Allows ``python KnowledgeBase/main.py`` as well.
    from embedding import COLLECTION_NAME, MODEL_PATH, QDRANT_PATH, _load_huggingface_embedding_model


RECALL_LIMIT = 50
FINAL_LIMIT = 5
RRF_K = 60
COMPRESSION_PREVIEW_LENGTH = 6000   #限制每个候选 chunk 在交给 LLMChainFilter 做压缩筛选时的文本长度


@dataclass(frozen=True)
class RetrievedChunk:
    """One chunk selected by the hybrid retrieval pipeline."""

    point_id: str | int
    text: str
    context: str
    source_file: str
    source_path: str
    document_id: str
    dense_rank: int | None
    bm25_rank: int | None
    rrf_score: float


def retrieve(
    question: str,
    *,
    model: Any | None = None,
    llm: Any | None = None,
    qdrant_path: Path = QDRANT_PATH,
    collection_name: str = COLLECTION_NAME,
) -> list[RetrievedChunk]:
    """Retrieve relevant chunks for a user question without HyDE.

    Args:
        question: The user's original question.
        model: Optional embedding model, mainly useful for callers and tests.
        llm: Optional task LLM. When supplied, it filters the fused chunks with
            ``LLMChainFilter`` as the compression stage.
        qdrant_path: Path of the persistent local Qdrant instance.
        collection_name: Qdrant collection containing indexed chunks.

    Returns:
        At most five chunks ranked by reciprocal-rank fusion and optionally
        filtered by the LLM compression stage.

    Raises:
        ValueError: If the question is blank or the collection is unavailable.
    """
    normalized_question = question.strip()
    if not normalized_question:
        raise ValueError("检索问题不能为空")

    embedding_model = model or _load_huggingface_embedding_model(MODEL_PATH)
    query_vector = _embed_query(embedding_model, normalized_question)
    client = QdrantClient(path=str(qdrant_path))
    try:
        if not client.collection_exists(collection_name):
            raise ValueError("知识库尚未建立向量索引")
        dense_hits = _dense_recall(client, collection_name, query_vector)
        bm25_hits = _bm25_recall(
            normalized_question,
            _scroll_payloads(client, collection_name),
        )
    finally:
        client.close()

    fused = _fuse_by_rrf(dense_hits, bm25_hits)
    return _compress_with_llm(normalized_question, fused, llm) if llm else fused


def _embed_query(model: Any, question: str) -> list[float]:
    """Embed one query with the same BGE model used for indexing."""
    if hasattr(model, "embed_query"):
        vector = model.embed_query(question)
    else:
        vector = model.embed_documents([question])[0]
    if not vector:
        raise RuntimeError("嵌入模型未返回查询向量")
    return [float(value) for value in vector]


def _dense_recall(
    client: QdrantClient,
    collection_name: str,
    query_vector: list[float],
) -> list[tuple[str | int, dict[str, Any]]]:
    """Recall the top dense candidates from Qdrant."""
    try:
        response = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=RECALL_LIMIT,
            with_payload=True,
        )
        points = response.points
    except AttributeError:
        points = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=RECALL_LIMIT,
            with_payload=True,
        )
    return [
        (point.id, dict(point.payload or {}))
        for point in points
    ]


def _scroll_payloads(
    client: QdrantClient,
    collection_name: str,
) -> list[tuple[str | int, dict[str, Any]]]:
    """Read payloads from Qdrant for the BM25 branch."""
    offset: str | int | None = None
    records: list[tuple[str | int, dict[str, Any]]] = []
    while True:
        points, offset = client.scroll(
            collection_name=collection_name,
            offset=offset,
            limit=RECALL_LIMIT,
            with_payload=True,
            with_vectors=False,
        )
        records.extend((point.id, dict(point.payload or {})) for point in points)
        if offset is None:
            return records


def _bm25_recall(
    question: str,
    records: list[tuple[str | int, dict[str, Any]]],
) -> list[tuple[str | int, dict[str, Any]]]:
    """Rank stored chunk text with a small dependency-free BM25 implementation."""
    query_tokens = _tokenize(question)
    tokenized_records = [
        _tokenize(str(payload.get("text") or "")) for _, payload in records
    ]
    if not query_tokens or not any(tokenized_records):
        return []

    document_frequency: Counter[str] = Counter()
    for tokens in tokenized_records:
        document_frequency.update(set(tokens))
    average_length = sum(map(len, tokenized_records)) / len(tokenized_records)
    query_terms = Counter(query_tokens)
    scored: list[tuple[float, int]] = []
    for index, tokens in enumerate(tokenized_records):
        if not tokens:
            continue
        frequencies = Counter(tokens)
        score = 0.0
        for term, query_count in query_terms.items():
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            inverse_frequency = math.log(
                1 + (len(records) - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * len(tokens) / average_length)
            score += query_count * inverse_frequency * frequency * 2.5 / denominator
        if score > 0:
            scored.append((score, index))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [records[index] for _, index in scored[:RECALL_LIMIT]]


def _tokenize(text: str) -> list[str]:
    """Tokenize Latin words and individual CJK characters for local BM25."""
    return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text.lower())


def _fuse_by_rrf(
    dense_hits: list[tuple[str | int, dict[str, Any]]],
    bm25_hits: list[tuple[str | int, dict[str, Any]]],
) -> list[RetrievedChunk]:
    """Fuse dense and BM25 rankings with reciprocal-rank fusion."""
    ranking: dict[str | int, dict[str, Any]] = {}
    for rank, (point_id, payload) in enumerate(dense_hits, start=1):
        ranking.setdefault(point_id, {"payload": payload, "dense_rank": None, "bm25_rank": None})
        ranking[point_id]["dense_rank"] = rank
    for rank, (point_id, payload) in enumerate(bm25_hits, start=1):
        ranking.setdefault(point_id, {"payload": payload, "dense_rank": None, "bm25_rank": None})
        ranking[point_id]["bm25_rank"] = rank

    chunks: list[RetrievedChunk] = []
    for point_id, entry in ranking.items():
        dense_rank = entry["dense_rank"]
        bm25_rank = entry["bm25_rank"]
        score = sum(1 / (RRF_K + rank) for rank in (dense_rank, bm25_rank) if rank)
        payload = entry["payload"]
        text = str(payload.get("text") or "")
        chunks.append(
            RetrievedChunk(
                point_id=point_id,
                text=text,
                context=str(payload.get("window") or text),
                source_file=str(payload.get("source_file") or ""),
                source_path=str(payload.get("source_path") or ""),
                document_id=str(payload.get("document_id") or ""),
                dense_rank=dense_rank,
                bm25_rank=bm25_rank,
                rrf_score=score,
            )
        )
    return sorted(chunks, key=lambda chunk: (-chunk.rrf_score, str(chunk.point_id)))[:FINAL_LIMIT]


def _compress_with_llm(
    question: str,
    chunks: list[RetrievedChunk],
    llm: Any,
) -> list[RetrievedChunk]:
    """Filter RRF results with LangChain Classic's ``LLMChainFilter``."""
    from langchain_classic.retrievers.document_compressors import LLMChainFilter
    from langchain_core.documents import Document

    if not chunks:
        return []
    try:
        documents = [
            Document(
                page_content=chunk.text[:COMPRESSION_PREVIEW_LENGTH],
                metadata={"retrieval_index": index},
            )
            for index, chunk in enumerate(chunks)
        ]
        retained = LLMChainFilter.from_llm(llm).compress_documents(
            documents,
            question,
        )
    except Exception:  # noqa: BLE001
        return chunks
    return [chunks[document.metadata["retrieval_index"]] for document in retained]


if __name__ == "__main__":
    user_question = input("请输入检索问题：").strip()
    for chunk in retrieve(user_question):
        print(f"[{chunk.rrf_score:.4f}] {chunk.source_file}: {chunk.context}")
