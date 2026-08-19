"""Prepare uploaded knowledge documents as Markdown sources.

Raw uploads are retained under ``KnowledgeBase/raw``. Markdown files ready for
later chunking and embedding are written under ``KnowledgeBase/documents``.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import time
import zipfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx


KNOWLEDGE_ROOT = Path(__file__).resolve().parent
RAW_ROOT = KNOWLEDGE_ROOT / "raw"
DOCUMENTS_ROOT = KNOWLEDGE_ROOT / "documents"
UPLOAD_MANIFEST_NAME = ".uploads.json"
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown"}
TEXT_EXTENSIONS = {".txt"}
MINERU_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg"}
MAX_ARCHIVE_FILES = 500
MAX_ARCHIVE_BYTES = 500 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 200 * 1024 * 1024


class KnowledgePreparationError(RuntimeError):
    """Raised when an uploaded document cannot be prepared."""


@dataclass(frozen=True)
class PreparedDocument:
    """One document archived for the knowledge base; Markdown conversion is optional."""

    document_id: str
    name: str
    path: Path
    source_name: str
    uploaded_at: str
    source_size_bytes: int
    raw_name: str
    is_markdown: bool
    is_conversion: bool


@dataclass(frozen=True)
class UploadRecord:
    """Persisted metadata displayed by the knowledge-base upload table."""

    document_id: str
    name: str
    size_bytes: int
    uploaded_at: str
    upload_success: bool
    raw_name: str
    output_name: str
    is_markdown: bool
    is_conversion: bool


def list_upload_records() -> list[UploadRecord]:
    """Return persisted upload metadata in upload order.

    The manifest lives beside generated Markdown files, allowing a restarted
    server to restore the table shown by the existing frontend. Invalid
    metadata is ignored so it cannot prevent new uploads.
    """
    manifest_path = DOCUMENTS_ROOT / UPLOAD_MANIFEST_NAME
    if not manifest_path.exists():
        return []
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []

    records: list[UploadRecord] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            records.append(
                UploadRecord(
                    document_id=str(item["document_id"]),
                    name=str(item["name"]),
                    size_bytes=int(item["size_bytes"]),
                    uploaded_at=str(item["uploaded_at"]),
                    upload_success=bool(item["upload_success"]),
                    raw_name=str(item.get("raw_name") or _legacy_raw_name(item)),
                    output_name=str(item["output_name"]),
                    is_markdown=bool(
                        item.get(
                            "is_markdown",
                            Path(str(item["name"])).suffix.lower() in MARKDOWN_EXTENSIONS,
                        )
                    ),
                    is_conversion=bool(item.get("is_conversion", False)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return records


def reconcile_conversion_records() -> list[UploadRecord]:
    """Restore conversion metadata when an existing Markdown output is found.

    Older conversion runs could write the Markdown file without updating the
    upload manifest.  The workflow uses the manifest to decide whether a
    document can proceed to chunking, so reconcile that persisted state with
    the generated file before exposing document status.
    """
    records = list_upload_records()
    reconciled: list[UploadRecord] = []
    changed = False

    for record in records:
        if record.is_markdown or record.is_conversion:
            reconciled.append(record)
            continue

        output_name = Path(record.output_name).with_suffix(".md").name
        output_path = DOCUMENTS_ROOT / output_name
        if output_path.is_file():
            reconciled.append(
                replace(record, output_name=output_name, is_conversion=True)
            )
            changed = True
        else:
            reconciled.append(record)

    if changed:
        _write_upload_records(reconciled)
    return reconciled


def delete_upload_records(document_ids: set[str]) -> list[str]:
    """Delete selected source files, generated Markdown, and table records.

    Only manifest paths located directly under the raw or documents folders
    are eligible. This prevents malformed metadata from deleting files outside
    the knowledge base.
    """
    if not document_ids:
        return []

    migrate_legacy_document_ids()
    existing = list_upload_records()
    selected = [record for record in existing if record.document_id in document_ids]
    if not selected:
        return []

    paths = {
        _raw_document_path(record.raw_name)
        for record in selected
        if record.raw_name
    } | {
        _document_output_path(record.output_name)
        for record in selected
    }
    for path in paths:
        if path.exists() and not path.is_file():
            raise KnowledgePreparationError(f"知识库文件路径无效：{path.name}")

    for path in paths:
        if path.exists():
            path.unlink()

    _write_upload_records(
        [record for record in existing if record.document_id not in document_ids]
    )
    return [record.document_id for record in selected]


class MinerUClient:
    """Minimal client for the MinerU asynchronous extraction API."""

    def __init__(self, api_key: str, base_url: str = "https://mineru.net") -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def convert_to_markdown(self, source: Path) -> str:
        """Upload one source file to MinerU and return its extracted Markdown."""
        file_bytes = source.read_bytes()
        digest = hashlib.md5(file_bytes).hexdigest()
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            upload_info = self._request_json(
                client,
                "POST",
                "/api/v4/file-urls/batch",
                json={
                    "files": [{"name": source.name, "data_id": digest}],
                    "model_version": "vlm",
                    "enable_formula": True,
                    "enable_table": True,
                },
            )
            batch_id = str(upload_info.get("batch_id") or "")
            upload_url = _first_string(upload_info, "file_urls", "files")
            if not batch_id or not upload_url:
                raise KnowledgePreparationError("MinerU 未返回批次标识或上传地址")

            response = client.put(upload_url, content=file_bytes, timeout=120.0)
            response.raise_for_status()

            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                batch_result = self._request_json(
                    client,
                    "GET",
                    f"/api/v4/extract-results/batch/{batch_id}",
                )
                task = _first_mapping(batch_result, "extract_result")
                state = str(task.get("state") or task.get("status") or "").lower()
                if state in {"done", "success", "succeeded"}:
                    return self._download_markdown(client, task)
                if state in {"failed", "error"}:
                    raise KnowledgePreparationError(
                        f"MinerU 转换失败: {task.get('err_msg') or task.get('error') or task.get('message') or state}"
                    )
                time.sleep(2)
        raise KnowledgePreparationError("MinerU 转换超时（10 分钟）")

    def _request_json(self, client: httpx.Client, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = client.request(method, f"{self._base_url}{path}", headers=self._headers, **kwargs)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise KnowledgePreparationError("MinerU 返回格式无效")
        if payload.get("code") not in (None, 0, 200):
            raise KnowledgePreparationError(str(payload.get("msg") or payload.get("message") or "MinerU 请求失败"))
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise KnowledgePreparationError("MinerU 返回数据无效")
        return data

    def _download_markdown(self, client: httpx.Client, task: dict[str, Any]) -> str:
        result = task.get("result") if isinstance(task.get("result"), dict) else task
        markdown = result.get("markdown") or result.get("md_content")
        if isinstance(markdown, str) and markdown.strip():
            return markdown

        archive_url = str(result.get("full_zip_url") or result.get("zip_url") or "")
        if not archive_url:
            raise KnowledgePreparationError("MinerU 未返回 Markdown 或结果压缩包")
        response = client.get(archive_url, timeout=120.0)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            markdown_files = [name for name in archive.namelist() if Path(name).suffix.lower() in MARKDOWN_EXTENSIONS]
            if not markdown_files:
                raise KnowledgePreparationError("MinerU 结果压缩包不包含 Markdown")
            return archive.read(markdown_files[0]).decode("utf-8")


def prepare_upload(filename: str, content: bytes) -> list[PreparedDocument]:
    """Archive one uploaded file or ZIP; Markdown conversion happens separately.

    Args:
        filename: Browser-provided filename.
        content: Raw file bytes.
    """
    safe_name = Path(filename).name
    if not safe_name or not content:
        raise KnowledgePreparationError("上传文件不能为空")

    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    DOCUMENTS_ROOT.mkdir(parents=True, exist_ok=True)
    uploaded_at = datetime.now(timezone.utc).isoformat()
    raw_path = _available_path(RAW_ROOT / safe_name)
    raw_path.write_bytes(content)

    if raw_path.suffix.lower() == ".zip":
        prepared = _prepare_archive(raw_path)
    else:
        prepared = [_prepare_file(raw_path, safe_name)]
    return _persist_upload_records(prepared, uploaded_at)


def _prepare_archive(archive_path: Path) -> list[PreparedDocument]:
    prepared: list[PreparedDocument] = []
    skipped: list[str] = []
    with zipfile.ZipFile(archive_path) as archive:
        members = [member for member in archive.infolist() if not member.is_dir()]
        for member in members:
            name = Path(member.filename).name
            if not name:
                continue
            if member.file_size > MAX_SINGLE_FILE_BYTES:
                skipped.append(f"{name}（{member.file_size // 1024 // 1024}MB 超过单文件上限）")
                continue
            try:
                extracted = _available_path(RAW_ROOT / f"{archive_path.stem}_{name}")
                extracted.write_bytes(archive.read(member))
                prepared.append(_prepare_file(extracted, member.filename))
            except KnowledgePreparationError as exc:
                skipped.append(f"{name}（{exc}）")
    if not prepared:
        if skipped:
            raise KnowledgePreparationError(
                f"压缩包中所有文件均无法处理：{'; '.join(skipped[:5])}"
            )
        raise KnowledgePreparationError("压缩包中没有可处理的文件")
    return prepared


def _prepare_file(raw_path: Path, source_name: str) -> PreparedDocument:
    extension = raw_path.suffix.lower()
    is_markdown = extension in MARKDOWN_EXTENSIONS
    needs_conversion = extension in MINERU_EXTENSIONS
    output_name = f"{raw_path.stem}.md"

    if is_markdown or extension in TEXT_EXTENSIONS:
        output_path = _available_path(DOCUMENTS_ROOT / output_name)
        if is_markdown:
            output_path.write_bytes(raw_path.read_bytes())
        else:
            output_path.write_text(raw_path.read_text(encoding="utf-8"), encoding="utf-8")
        is_conversion = True
    elif needs_conversion:
        output_path = raw_path
        is_conversion = False
    else:
        raise KnowledgePreparationError(f"不支持的知识库文件类型: {extension or '无扩展名'}")

    return PreparedDocument(
        document_id="",
        name=output_path.name,
        path=output_path,
        source_name=Path(source_name).name,
        uploaded_at="",
        source_size_bytes=raw_path.stat().st_size,
        raw_name=raw_path.name,
        is_markdown=is_markdown,
        is_conversion=is_conversion,
    )


def _available_path(path: Path) -> Path:
    """Return ``path`` or a numbered sibling without overwriting an upload."""
    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise KnowledgePreparationError(f"无法为文件分配安全存储路径：{path.name}")


def _persist_upload_records(
    prepared_documents: list[PreparedDocument], uploaded_at: str
) -> list[PreparedDocument]:
    """Assign permanent UUIDs and append metadata after conversion succeeds."""
    migrate_legacy_document_ids()
    existing = list_upload_records()
    assigned = [
        replace(document, document_id=str(uuid4()), uploaded_at=uploaded_at)
        for document in prepared_documents
    ]
    manifest_records = [
        {
            "document_id": record.document_id,
            "name": record.name,
            "size_bytes": record.size_bytes,
            "uploaded_at": record.uploaded_at,
            "upload_success": record.upload_success,
            "output_name": record.output_name,
            "is_markdown": record.is_markdown,
            "is_conversion": record.is_conversion,
        }
        for record in existing
    ] + [
        {
            "document_id": document.document_id,
            "name": document.source_name,
            "size_bytes": document.source_size_bytes,
            "uploaded_at": document.uploaded_at,
            "upload_success": True,
            "raw_name": document.raw_name,
            "output_name": document.name,
            "is_markdown": document.is_markdown,
            "is_conversion": document.is_conversion,
        }
        for document in assigned
    ]
    _write_upload_records_payload(manifest_records)
    return assigned


def _document_output_path(output_name: str) -> Path:
    """Resolve one generated Markdown path and reject traversal attempts."""
    if Path(output_name).name != output_name:
        raise KnowledgePreparationError("知识库文件路径无效")
    root = DOCUMENTS_ROOT.resolve()
    output_path = (DOCUMENTS_ROOT / output_name).resolve()
    if output_path.parent != root:
        raise KnowledgePreparationError("知识库文件路径超出允许范围")
    return output_path


def _raw_document_path(raw_name: str) -> Path:
    """Resolve one archived source path and reject traversal attempts."""
    if Path(raw_name).name != raw_name:
        raise KnowledgePreparationError("知识库原始文件路径无效")
    root = RAW_ROOT.resolve()
    raw_path = (RAW_ROOT / raw_name).resolve()
    if raw_path.parent != root:
        raise KnowledgePreparationError("知识库原始文件路径超出允许范围")
    return raw_path


def convert_documents(
    document_ids: set[str],
    *,
    mineru_api_key: str | None = None,
    mineru_base_url: str | None = None,
) -> tuple[list[str], list[str]]:
    """Convert selected non-Markdown documents to Markdown via MinerU.

    Returns:
        A tuple of (converted_document_ids, failed_messages).
    """
    if not document_ids:
        return [], []

    migrate_legacy_document_ids()
    records = list_upload_records()
    id_to_record = {record.document_id: record for record in records}
    selected = [id_to_record[id] for id in document_ids if id in id_to_record]

    key = mineru_api_key or os.getenv("MINERU_API_KEY")
    if not key:
        raise KnowledgePreparationError("请先在 API 管理中配置 MinerU Token")

    client = MinerUClient(key, mineru_base_url or "https://mineru.net")
    converted: list[str] = []
    failed: list[str] = []

    for index, record in enumerate(records):
        if record.document_id not in document_ids:
            continue
        if record.is_conversion or record.is_markdown:
            continue
        # ``output_name`` is the archived raw filename until conversion finishes.
        # ZIP members are prefixed with the archive stem to avoid collisions,
        # while ``name`` remains the original filename shown in the UI.
        raw_path = RAW_ROOT / record.output_name
        if not raw_path.exists():
            failed.append(f"{record.name}（原始文件不存在）")
            continue
        try:
            markdown = client.convert_to_markdown(raw_path)
            output_name = f"{raw_path.stem}.md"
            output_path = _available_path(DOCUMENTS_ROOT / output_name)
            output_path.write_text(markdown, encoding="utf-8")
            converted.append(record.document_id)
            records[index] = replace(record, output_name=output_path.name, is_conversion=True)
        except KnowledgePreparationError as exc:
            failed.append(f"{record.name}（{exc}）")
            continue

    if converted:
        _write_upload_records(records)

    return converted, failed


def _write_upload_records(records: list[UploadRecord]) -> None:
    """Persist upload records after a deletion."""
    _write_upload_records_payload(
        [
            {
                "document_id": record.document_id,
                "name": record.name,
                "size_bytes": record.size_bytes,
                "uploaded_at": record.uploaded_at,
                "upload_success": record.upload_success,
                "raw_name": record.raw_name,
                "output_name": record.output_name,
                "is_markdown": record.is_markdown,
                "is_conversion": record.is_conversion,
            }
            for record in records
        ]
    )


def _legacy_raw_name(record: dict[str, Any]) -> str:
    """Infer the raw filename for manifests created before ``raw_name`` existed."""
    output_name = str(record.get("output_name") or "")
    if not bool(record.get("is_conversion")):
        return output_name

    expected_stem = Path(output_name).stem
    if not RAW_ROOT.exists() or not expected_stem:
        return ""
    matches = [
        path.name
        for path in RAW_ROOT.iterdir()
        if path.is_file() and path.stem == expected_stem
    ]
    return matches[0] if len(matches) == 1 else ""


def _write_upload_records_payload(records: list[dict[str, Any]]) -> None:
    """Write a JSON manifest for the upload table."""
    DOCUMENTS_ROOT.mkdir(parents=True, exist_ok=True)
    (DOCUMENTS_ROOT / UPLOAD_MANIFEST_NAME).write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def migrate_legacy_document_ids() -> None:
    """Replace legacy numeric or duplicate upload IDs with permanent UUIDs."""
    manifest_path = DOCUMENTS_ROOT / UPLOAD_MANIFEST_NAME
    if not manifest_path.exists():
        return
    try:
        records = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(records, list):
        return

    seen: set[str] = set()
    changed = False
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            document_id = str(UUID(str(record.get("document_id", ""))))
        except (AttributeError, TypeError, ValueError):
            document_id = str(uuid4())
        if document_id in seen:
            document_id = str(uuid4())
        seen.add(document_id)
        if record.get("document_id") != document_id:
            record["document_id"] = document_id
            changed = True
    if changed:
        _write_upload_records_payload(records)


def _first_mapping(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value[0]
    raise KnowledgePreparationError("MinerU 返回上传文件信息无效")


def _first_string(payload: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty URL string from a MinerU response field."""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list) and value and isinstance(value[0], str):
            return value[0]
    return ""
