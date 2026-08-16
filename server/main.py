"""FastAPI 入口。

启动：在项目根目录执行
    uvicorn server.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from server.files import list_figures, resolve_artifact
from KnowledgeBase.chunk import chunk_knowledge_documents
from KnowledgeBase.embedding import build_local_qdrant_index
from KnowledgeBase.upload_file import (
    DOCUMENTS_ROOT as KNOWLEDGE_DOCUMENTS_ROOT,
    KnowledgePreparationError,
    UPLOAD_MANIFEST_NAME,
    delete_upload_records,
    list_upload_records,
    prepare_upload,
)
from server.runs import (
    cancel_run,
    cleanup_stale_runs,
    create_run,
    delete_run,
    execute_run,
    get_pending_budget,
    get_pending_clarification,
    get_run,
    list_runs,
    rename_run,
    submit_budget_decision,
    submit_clarification_decision,
)
from scr.runtime.budget import BudgetType
from server.schemas import (
    BudgetConfirmBody,
    BrainstormRequest,
    CreateRunResponse,
    KnowledgeDocument,
    KnowledgeChunkEmbedResponse,
    KnowledgeDocumentsDeleteBody,
    KnowledgeStatus,
    ModelConfig,
    RunDetail,
    RunSummary,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts"
WEB_DIST = PROJECT_ROOT / "web" / "dist"
API_SETTINGS_PATH = Path(__file__).resolve().parent / "api_settings.json"

app = FastAPI(title="MMAgent Web", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本地单机开发；生产应改为前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 保留后台任务引用，避免被 GC
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _list_knowledge_documents() -> list[KnowledgeDocument]:
    """Return locally archived source documents for the knowledge-base MVP."""
    records = list_upload_records()
    if records:
        return [
            KnowledgeDocument(
                id=record.document_id,
                name=record.name,
                size_bytes=record.size_bytes,
                uploaded_at=record.uploaded_at,
                upload_success=record.upload_success,
                is_markdown=record.is_markdown,
            )
            for record in records
        ]
    if not KNOWLEDGE_DOCUMENTS_ROOT.exists():
        return []
    files = [
        path
        for path in sorted(KNOWLEDGE_DOCUMENTS_ROOT.iterdir(), key=lambda item: item.name.lower())
        if path.is_file() and path.name != UPLOAD_MANIFEST_NAME
    ]
    return [
        KnowledgeDocument(
            id=index + 1,
            name=path.name,
            size_bytes=path.stat().st_size,
            uploaded_at=datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat(),
            upload_success=True,
            is_markdown=path.suffix.lower() in {".md", ".markdown", ".mdown"},
        )
        for index, path in enumerate(files)
    ]


@app.on_event("startup")
async def _on_startup() -> None:
    """启动时清理因服务重启而留下的\"僵尸\"运行（status=running 但无对应后台线程）。"""
    cleaned = cleanup_stale_runs(max_age_seconds=120)
    if cleaned:
        print(f"[startup] cleaned {cleaned} stale running run(s)")


def _read_api_settings() -> dict | None:
    """Load the persisted API settings snapshot, or None when absent/corrupt."""
    if not API_SETTINGS_PATH.exists():
        return None
    try:
        data = json.loads(API_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


@app.get("/api/settings/api")
async def get_api_settings_endpoint() -> dict:
    """Return the locally persisted API settings snapshot.

    ``saved=False`` means nothing has ever been persisted, so the frontend
    keeps its browser cache untouched instead of overwriting it with empties.
    """
    data = _read_api_settings() or {}
    return {
        "saved": bool(data),
        "configs": data.get("configs", []),
        "active_id": data.get("active_id"),
        "external_services": data.get("external_services", {}),
    }


@app.put("/api/settings/api")
async def save_api_settings_endpoint(body: dict) -> dict:
    """Persist the API settings snapshot to a local file (atomic replace)."""
    if not isinstance(body.get("configs"), list):
        raise HTTPException(status_code=422, detail="configs must be a list")
    payload = {
        "configs": body.get("configs", []),
        "active_id": body.get("active_id") if isinstance(body.get("active_id"), str) else None,
        "external_services": body.get("external_services")
        if isinstance(body.get("external_services"), dict)
        else {},
    }
    tmp_path = API_SETTINGS_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(API_SETTINGS_PATH)
    return {"ok": True}


@app.get("/api/knowledge/status", response_model=KnowledgeStatus)
async def knowledge_status_endpoint() -> KnowledgeStatus:
    """Expose the knowledge-base MVP state without claiming retrieval is ready."""
    return KnowledgeStatus(documents=_list_knowledge_documents())


@app.post("/api/knowledge/documents", response_model=list[KnowledgeDocument])
async def upload_knowledge_document_endpoint(
    document: UploadFile = File(..., description="知识库原始文档"),
    mineru_config: str = Form("{}", description="JSON: apiKey/baseUrl"),
) -> list[KnowledgeDocument]:
    """Prepare one uploaded document or ZIP for the later embedding pipeline."""
    filename = Path(document.filename or "knowledge-document").name
    if not filename:
        raise HTTPException(status_code=400, detail="文档名称不能为空")

    content = await document.read()
    try:
        config = json.loads(mineru_config) if mineru_config else {}
        prepared = prepare_upload(
            filename,
            content,
            mineru_api_key=config.get("apiKey"),
            mineru_base_url=config.get("baseUrl"),
        )
    except (ValueError, KnowledgePreparationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return [
        KnowledgeDocument(
            id=item.document_id,
            name=item.source_name,
            size_bytes=item.source_size_bytes,
            uploaded_at=item.uploaded_at,
            upload_success=True,
            is_markdown=item.is_markdown,
        )
        for item in prepared
    ]


@app.delete("/api/knowledge/documents")
async def delete_knowledge_documents_endpoint(
    body: KnowledgeDocumentsDeleteBody,
) -> dict[str, list[int]]:
    """Delete selected prepared knowledge-base documents by their stable IDs."""
    try:
        deleted_ids = delete_upload_records(set(body.document_ids))
    except KnowledgePreparationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not deleted_ids:
        raise HTTPException(status_code=404, detail="未找到可删除的知识库文件")
    return {"deleted_ids": deleted_ids}


@app.post("/api/knowledge/chunk-embed", response_model=KnowledgeChunkEmbedResponse)
async def chunk_and_embed_knowledge_endpoint() -> KnowledgeChunkEmbedResponse:
    """Run local sentence-window chunking and HuggingFace embedding on demand."""
    try:
        result = await asyncio.to_thread(_build_knowledge_vector_index)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    document_chunks = _document_chunk_counts(result.source_chunk_counts)
    return KnowledgeChunkEmbedResponse(
        collection_name=result.collection_name,
        documents_processed=len(document_chunks),
        chunks_indexed=result.indexed_nodes,
        vector_size=result.vector_size,
        document_chunks=document_chunks,
    )


def _build_knowledge_vector_index():
    """Regenerate chunks, then rebuild the local Qdrant collection."""
    chunk_knowledge_documents()
    return build_local_qdrant_index()


def _document_chunk_counts(source_chunk_counts: dict[str, int]) -> dict[int, int]:
    """Map generated Markdown filenames back to stable upload-table IDs."""
    records = list_upload_records()
    if records:
        return {
            record.document_id: source_chunk_counts.get(record.output_name, 0)
            for record in records
        }
    return {
        index + 1: source_chunk_counts.get(document.name, 0)
        for index, document in enumerate(_list_knowledge_documents())
    }


@app.post("/api/knowledge/brainstorm")
async def brainstorm_endpoint(body: BrainstormRequest):
    """Reserve the RAG chat contract until retrieval infrastructure is configured."""
    del body
    raise HTTPException(
        status_code=501,
        detail="知识库检索与对话尚未配置：请先接入 Qdrant、嵌入模型和检索链路。",
    )


@app.post("/api/runs", response_model=CreateRunResponse)
async def create_run_endpoint(
    problem_text: str | None = Form(None, description="任务文本"),
    problem_file: UploadFile | None = File(None, description="任务文件(.md/.txt)"),
    data_files: list[UploadFile] | None = File(None, description="数据附件(可多个)"),
    llm_config: str = Form("{}", description="JSON: provider/api_key/base_url/model"),
    task_name: str | None = Form(None, description="任务名称（用户自定义）"),
):
    """提交一次解题任务（后台异步执行）。"""
    try:
        # 解析模型配置
        try:
            cfg = json.loads(llm_config) if llm_config else {}
            ModelConfig(**cfg)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"llm_config 解析失败: {exc}")

        # 任务：文本优先；其次读取文本文件
        problem = problem_text
        run_id = uuid.uuid4().hex[:8]
        output_dir = ARTIFACTS_ROOT / run_id
        input_dir = output_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        if problem_file is not None and not problem:
            raw = await problem_file.read()
            try:
                problem = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=400,
                    detail="任务文件暂仅支持 UTF-8 文本(.md/.txt)；二进制请改用 problem_text 粘贴或后续版本接入解析。",
                )
            # 存档任务文件
            dest = input_dir / (problem_file.filename or "problem.txt")
            dest.write_bytes(raw)

        if not problem or not problem.strip():
            raise HTTPException(status_code=400, detail="必须提供 problem_text 或 problem_file")

        # 数据附件存档
        data_paths: list[str] = []
        if data_files:
            for uf in data_files:
                if uf is None:
                    continue
                content = await uf.read()
                if not content:
                    continue
                dest = input_dir / (uf.filename or f"data_{len(data_paths)}.bin")
                dest.write_bytes(content)
                data_paths.append(str(dest))

        preview = problem.strip()[:200].replace("\n", " ")
        create_run(run_id, preview, cfg, task_name=task_name)

        task = asyncio.create_task(
            execute_run(
                run_id=run_id,
                problem_text=problem,
                data_paths=data_paths,
                output_dir=str(output_dir),
                model_config=cfg,
            )
        )
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

        return {"run_id": run_id, "status": "queued", "output_dir": str(output_dir)}
    except HTTPException:
        # 已显式构造的 4xx 错误，原样返回
        raise
    except Exception as exc:  # noqa: BLE001
        # 未捕获异常：把完整堆栈打到 stderr，并把异常类型/消息作为 detail 返回，
        # 便于前端和本地终端直接看到根因（仅本地开发用，生产请收敛为通用提示）。
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"server error: {type(exc).__name__}: {exc}",
        )


@app.get("/api/runs", response_model=list[RunSummary])
async def list_runs_endpoint():
    """运行历史列表。"""
    return [RunSummary.from_row(r) for r in list_runs()]


@app.post("/api/runs/cleanup-stale")
async def cleanup_stale_endpoint(max_age_seconds: int = 300):
    """手动把因服务重启而卡在 running/queued 的僵尸任务转为 failed。

    正常情况启动时已自动清理；此接口用于运行中手动触发（无需重启）。
    """
    cleaned = cleanup_stale_runs(max_age_seconds=max_age_seconds)
    return {"cleaned": cleaned}


@app.get("/api/runs/{run_id}", response_model=RunDetail)
async def get_run_endpoint(run_id: str):
    """运行详情（含进度事件与产物清单）。"""
    row = get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run 不存在")
    return RunDetail.from_row(row)


@app.delete("/api/runs/{run_id}")
async def delete_run_endpoint(run_id: str):
    """删除一条运行记录（DB 行 + 产物目录）。"""
    result = delete_run(run_id)
    if not result["deleted"]:
        if result["reason"] == "not_found":
            raise HTTPException(status_code=404, detail="run 不存在")
        raise HTTPException(status_code=409, detail=result["reason"])
    return {"ok": True, "run_id": run_id}


@app.patch("/api/runs/{run_id}/name")
async def rename_run_endpoint(run_id: str, name: str = Form(...)):
    """更新任务名称。"""
    if not rename_run(run_id, name):
        raise HTTPException(status_code=404, detail="run 不存在")
    return {"ok": True, "run_id": run_id, "task_name": name}


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run_endpoint(run_id: str):
    """中断一个正在执行（queued/running）的任务。

    若任务已结束（succeeded/failed/cancelled）则返回 409；
    若仍在执行则设置取消标志，后台线程在下一个节点边界退出并标记 cancelled。
    """
    result = cancel_run(run_id)
    if not result["cancelled"]:
        if result["reason"] == "not_found":
            raise HTTPException(status_code=404, detail="run 不存在")
        raise HTTPException(status_code=409, detail=result["reason"])
    return {"ok": True, "run_id": run_id, "status": "cancelled"}


_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


@app.get("/api/runs/{run_id}/progress/stream")
async def stream_run_progress(run_id: str, after: int = 0):
    """以 SSE 实时推送某个 run 的进度事件（节点级）。

    前端用原生 EventSource 订阅（GET，无 body）。服务端周期性读取注册表，
    把「新增」的 progress 事件逐条推给客户端；run 进入终态后发送 done 并关闭连接。
    相比前端 2s 轮询，这里延迟更低、体验更接近"实时输出建模进度"。

    after 参数：跳过前 N 条已加载的事件，用于断线重连/恢复模式时避免重复。
    """
    if get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run 不存在")

    async def gen():
        sent = max(0, after)
        # 连接建立即回执，便于前端确认订阅成功
        yield f'data: {json.dumps({"type": "subscribed", "run_id": run_id}, ensure_ascii=False)}\n\n'
        while True:
            row = get_run(run_id)
            if row is None:
                yield 'data: {"type":"error","message":"run 不存在"}\n\n'
                return
            events = row.get("progress") or []
            status = row.get("status")
            for ev in events[sent:]:
                yield f"data: {json.dumps({'type': 'event', 'event': ev}, ensure_ascii=False)}\n\n"
            sent = len(events)
            if status in _TERMINAL_STATUSES:
                done = {"type": "done", "status": status, "error": row.get("error")}
                yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"
                return
            # SSE 注释行：保持连接活跃，避免代理/浏览器因空闲断开
            yield ": keep-alive\n\n"
            await asyncio.sleep(0.15)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 关闭反向代理缓冲，确保事件即时下发
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/runs/{run_id}/budget-confirm")
async def confirm_budget_endpoint(run_id: str, body: BudgetConfirmBody):
    """确认某小问的预算覆盖。

    当 run 暂停在 configure_question_budget 节点等待用户确认时，前端弹窗提交：
      - use_defaults=true：沿用默认预算；
      - limits：覆盖当前预算阶段允许调整的项目。
    无待确认请求时返回 409。
    """
    pending = get_pending_budget(run_id)
    if not pending:
        raise HTTPException(status_code=409, detail="当前没有待确认的预算请求")
    decision = None if body.use_defaults else (body.limits or None)
    # 仅保留已定义的、值为正整数的预算项；当前阶段会在后台回调中决定实际采用哪些项。
    if decision:
        decision = {
            key: value
            for key, value in decision.items()
            if key in {
                BudgetType.SEARCH.value,
                BudgetType.CODE_REPAIR.value,
                BudgetType.VALIDATION_ITERATION.value,
                BudgetType.INTAKE_RETRY.value,
                BudgetType.PAPER_REVISION.value,
            }
            and isinstance(value, int)
            and value > 0
        }
    ok = submit_budget_decision(run_id, decision)
    if not ok:
        raise HTTPException(status_code=409, detail="预算请求已被取消或已确认")
    return {"ok": True, "run_id": run_id, "use_defaults": body.use_defaults, "limits": decision}


@app.post("/api/runs/{run_id}/clarification")
async def submit_clarification_endpoint(
    run_id: str,
    action: str = Form(..., description="terminate 或 continue"),
    data_files: list[UploadFile] | None = File(None, description="补充材料(可多个)"),
):
    """G0 硬失败时用户选择终止或上传补充材料继续建模。

    - action=terminate：立即终止本次建模任务。
    - action=continue：上传补充材料后重跑输入摄入。
    无待确认请求时返回 409。
    """
    pending = get_pending_clarification(run_id)
    if not pending:
        raise HTTPException(status_code=409, detail="当前没有待确认的澄清请求")

    new_data_paths: list[str] = []
    if action == "continue" and data_files:
        input_dir = ARTIFACTS_ROOT / run_id / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        for uf in data_files:
            if uf is None:
                continue
            content = await uf.read()
            if not content:
                continue
            dest = input_dir / (uf.filename or f"supplement_{len(new_data_paths)}.bin")
            dest.write_bytes(content)
            new_data_paths.append(str(dest))

    decision = {"action": action, "new_data_paths": new_data_paths}
    ok = submit_clarification_decision(run_id, decision)
    if not ok:
        raise HTTPException(status_code=409, detail="澄清请求已被取消或已确认")
    return {"ok": True, "run_id": run_id, "action": action, "new_files": len(new_data_paths)}


@app.get("/api/runs/{run_id}/paper")
async def get_paper_endpoint(run_id: str):
    """报告 Markdown 文本。"""
    try:
        path = resolve_artifact(run_id, "paper.md")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PlainTextResponse(path.read_text(encoding="utf-8"))


@app.get("/api/runs/{run_id}/figures")
async def get_figures_endpoint(run_id: str):
    """图表文件清单。"""
    if not get_run(run_id):
        raise HTTPException(status_code=404, detail="run 不存在")
    return {"figures": list_figures(run_id)}


@app.get("/api/runs/{run_id}/files/{file_path:path}")
async def download_file_endpoint(run_id: str, file_path: str):
    """下载任意产物文件（安全限制在 artifacts/<run_id>/ 内）。"""
    try:
        target = resolve_artifact(run_id, file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return FileResponse(target)


# ---------------------------------------------------------------------------
# 前端静态托管（若已构建 web/dist）
# ---------------------------------------------------------------------------
if WEB_DIST.exists():
    # 健康检查须在静态托管挂载之前注册，否则会被 "/" 挂载的 StaticFiles 吞掉（返回 404）
    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")
else:

    @app.get("/")
    async def root():
        return {
            "message": "MMAgent Web API 运行中",
            "docs": "/docs",
            "hint": "前端未构建；构建 web 后访问根路径即可使用界面。",
        }
