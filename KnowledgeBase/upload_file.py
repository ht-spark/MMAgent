"""Prepare uploaded knowledge documents as Markdown sources.

Raw uploads are retained under ``KnowledgeBase/raw``. Markdown files ready for
later chunking and embedding are written under ``KnowledgeBase/documents``.
"""
from __future__ import annotations

import hashlib
import io
import os
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


KNOWLEDGE_ROOT = Path(__file__).resolve().parent
RAW_ROOT = KNOWLEDGE_ROOT / "raw"
DOCUMENTS_ROOT = KNOWLEDGE_ROOT / "documents"
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown"}
TEXT_EXTENSIONS = {".txt"}
MINERU_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg"}
MAX_ARCHIVE_FILES = 100
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


class KnowledgePreparationError(RuntimeError):
    """Raised when an uploaded document cannot be prepared."""


@dataclass(frozen=True)
class PreparedDocument:
    """One Markdown document ready for the later embedding pipeline."""

    name: str
    path: Path
    source_name: str


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
                json={"files": [{"name": source.name, "md5": digest}]},
            )
            file_info = _first_mapping(upload_info, "file_urls", "files")
            upload_url = str(file_info.get("url") or file_info.get("upload_url") or "")
            data_id = str(file_info.get("data_id") or file_info.get("id") or "")
            if not upload_url or not data_id:
                raise KnowledgePreparationError("MinerU 未返回上传地址或文件标识")

            response = client.put(upload_url, content=file_bytes, timeout=120.0)
            response.raise_for_status()
            task_data = self._request_json(
                client,
                "POST",
                "/api/v4/extract/task",
                json={
                    "files": [{"data_id": data_id, "filename": source.name}],
                    "options": {"enable_formula": True, "enable_table": True},
                },
            )
            task_id = str(task_data.get("task_id") or task_data.get("id") or "")
            if not task_id:
                raise KnowledgePreparationError("MinerU 未返回转换任务标识")

            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                task = self._request_json(client, "GET", f"/api/v4/extract/task/{task_id}")
                state = str(task.get("state") or task.get("status") or "").lower()
                if state in {"done", "success", "succeeded"}:
                    return self._download_markdown(client, task)
                if state in {"failed", "error"}:
                    raise KnowledgePreparationError(
                        f"MinerU 转换失败: {task.get('error') or task.get('message') or state}"
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


def prepare_upload(
    filename: str,
    content: bytes,
    *,
    mineru_api_key: str | None = None,
    mineru_base_url: str | None = None,
) -> list[PreparedDocument]:
    """Archive one uploaded file or ZIP and prepare Markdown documents.

    Args:
        filename: Browser-provided filename.
        content: Raw file bytes.
        mineru_api_key: Request-scoped MinerU key; falls back to ``MINERU_API_KEY``.
        mineru_base_url: Optional MinerU API origin.
    """
    safe_name = Path(filename).name
    if not safe_name or not content:
        raise KnowledgePreparationError("上传文件不能为空")

    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    DOCUMENTS_ROOT.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_ROOT / safe_name
    raw_path.write_bytes(content)

    if raw_path.suffix.lower() == ".zip":
        return _prepare_archive(raw_path, mineru_api_key, mineru_base_url)
    return [_prepare_file(raw_path, safe_name, mineru_api_key, mineru_base_url)]


def _prepare_archive(
    archive_path: Path,
    api_key: str | None,
    base_url: str | None,
) -> list[PreparedDocument]:
    prepared: list[PreparedDocument] = []
    with zipfile.ZipFile(archive_path) as archive:
        members = [member for member in archive.infolist() if not member.is_dir()]
        total_size = sum(member.file_size for member in members)
        if len(members) > MAX_ARCHIVE_FILES or total_size > MAX_ARCHIVE_BYTES:
            raise KnowledgePreparationError("压缩包超过知识库导入限制")
        for member in members:
            name = Path(member.filename).name
            if not name:
                continue
            extracted = RAW_ROOT / f"{archive_path.stem}_{name}"
            extracted.write_bytes(archive.read(member))
            prepared.append(_prepare_file(extracted, member.filename, api_key, base_url))
    if not prepared:
        raise KnowledgePreparationError("压缩包中没有可处理的文件")
    return prepared


def _prepare_file(
    raw_path: Path,
    source_name: str,
    api_key: str | None,
    base_url: str | None,
) -> PreparedDocument:
    extension = raw_path.suffix.lower()
    output_name = f"{raw_path.stem}.md"
    output_path = DOCUMENTS_ROOT / output_name

    if extension in MARKDOWN_EXTENSIONS:
        output_path.write_bytes(raw_path.read_bytes())
    elif extension in TEXT_EXTENSIONS:
        output_path.write_text(raw_path.read_text(encoding="utf-8"), encoding="utf-8")
    elif extension in MINERU_EXTENSIONS:
        key = api_key or os.getenv("MINERU_API_KEY")
        if not key:
            raise KnowledgePreparationError("请先在 API 管理中配置 MinerU Token")
        markdown = MinerUClient(key, base_url or "https://mineru.net").convert_to_markdown(raw_path)
        output_path.write_text(markdown, encoding="utf-8")
    else:
        raise KnowledgePreparationError(f"不支持的知识库文件类型: {extension or '无扩展名'}")

    return PreparedDocument(name=output_name, path=output_path, source_name=source_name)


def _first_mapping(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value[0]
    raise KnowledgePreparationError("MinerU 返回上传文件信息无效")
