"""Split prepared knowledge-base Markdown into sentence-window nodes.

This module is deliberately limited to loading and chunking documents. The
embedding model and vector-store writes belong to the subsequent pipeline
stage, so this output remains reusable regardless of the chosen vector store.
"""
from __future__ import annotations

import json
from pathlib import Path

from llama_index.core import Document
from llama_index.core.node_parser import SentenceWindowNodeParser
from llama_index.core.schema import BaseNode


KNOWLEDGE_ROOT = Path(__file__).resolve().parent
DOCUMENTS_ROOT = KNOWLEDGE_ROOT / "documents"
CHUNKS_ROOT = KNOWLEDGE_ROOT / "chunks"
DEFAULT_WINDOW_SIZE = 5
NODE_OUTPUT_NAME = "sentence_window_nodes.jsonl"
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown"}


def load_markdown_documents(documents_root: Path = DOCUMENTS_ROOT) -> list[Document]:
    """Load prepared Markdown files from the knowledge-base documents folder.

    Args:
        documents_root: Folder containing Markdown generated during upload.

    Returns:
        LlamaIndex documents, each carrying its source filename and path.
    """
    if not documents_root.exists():
        return []

    documents: list[Document] = []
    for path in sorted(documents_root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.suffix.lower() not in MARKDOWN_EXTENSIONS:
            continue
        documents.append(
            Document(
                text=path.read_text(encoding="utf-8"),
                metadata={
                    "source_file": path.name,
                    "source_path": str(path.resolve()),
                },
            )
        )
    return documents


def build_sentence_window_nodes(
    documents_root: Path = DOCUMENTS_ROOT,
    *,
    window_size: int = DEFAULT_WINDOW_SIZE,
) -> list[BaseNode]:
    """Split prepared Markdown with LlamaIndex ``SentenceWindowNodeParser``.

    Args:
        documents_root: Folder containing prepared Markdown documents.
        window_size: Number of neighbouring sentences retained on each node.

    Returns:
        Sentence-level nodes with ``window`` and ``original_text`` metadata.

    Raises:
        ValueError: If ``window_size`` is not a positive integer.
    """
    if window_size < 1:
        raise ValueError("window_size 必须为正整数")

    documents = load_markdown_documents(documents_root)
    if not documents:
        return []

    parser = SentenceWindowNodeParser.from_defaults(
        window_size=window_size,
        window_metadata_key="window",
        original_text_metadata_key="original_text",
    )
    return parser.get_nodes_from_documents(documents)


def write_sentence_window_nodes(
    nodes: list[BaseNode],
    chunks_root: Path = CHUNKS_ROOT,
) -> Path:
    """Persist nodes as JSON Lines for the embedding and vector-store stage.

    Args:
        nodes: Nodes returned by :func:`build_sentence_window_nodes`.
        chunks_root: Destination directory for the reusable node artifact.

    Returns:
        The JSONL output path. An empty node list creates an empty file.
    """
    chunks_root.mkdir(parents=True, exist_ok=True)
    output_path = chunks_root / NODE_OUTPUT_NAME
    with output_path.open("w", encoding="utf-8") as output:
        for node in nodes:
            output.write(json.dumps(node.to_dict(), ensure_ascii=False))
            output.write("\n")
    return output_path


def chunk_knowledge_documents(
    documents_root: Path = DOCUMENTS_ROOT,
    chunks_root: Path = CHUNKS_ROOT,
    *,
    window_size: int = DEFAULT_WINDOW_SIZE,
) -> Path:
    """Build and persist sentence-window nodes for all prepared documents.

    Args:
        documents_root: Source folder of prepared Markdown files.
        chunks_root: Destination folder for the JSONL node artifact.
        window_size: Number of neighbouring sentences in each context window.

    Returns:
        Path to the generated JSONL node artifact.
    """
    nodes = build_sentence_window_nodes(documents_root, window_size=window_size)
    return write_sentence_window_nodes(nodes, chunks_root)


if __name__ == "__main__":
    output = chunk_knowledge_documents()
    print(f"已生成句子窗口切分结果：{output}")
