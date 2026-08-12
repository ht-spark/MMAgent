"""运行注册表（SQLite）与后台执行管理。

本地单机单人：用 asyncio.to_thread 在后台线程跑同步的 run_graph，
进度事件通过 progress_callback 写回注册表，供前端轮询。
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 确保项目根目录在 sys.path，便于 import scr.math_modeling_agent
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(PROJECT_ROOT))

from scr.math_modeling_agent.graph import run_graph  # noqa: E402
from scr.math_modeling_agent.llm import create_llm  # noqa: E402
from scr.runtime.budget import BudgetType  # noqa: E402

_DB_PATH = PROJECT_ROOT / "server" / "runs.db"
_MAX_PROGRESS_EVENTS = 500

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

# 取消意图标志：run_id -> True。仅存在于进程内存；
# 服务重启后后台任务本就不会存活，无需持久化。
_cancel_flags: dict[str, bool] = {}

# ---------------------------------------------------------------------------
# 预算确认（人工介入）：run 跑到 configure_question_budget 节点时暂停，
# 等待前端弹窗确认该问预算覆盖后再继续。仅进程内存。
# ---------------------------------------------------------------------------
_budget_lock = threading.Lock()
# run_id -> {"event": Event, "question_id": str, "proposed": dict}
_pending_budget: dict[str, dict] = {}
# run_id -> 用户决定（dict[BudgetType值, int] 或 None=用默认）
_budget_decisions: dict[str, dict | None] = {}


def request_budget_confirmation(
    run_id: str, question_id: str, proposed: dict
) -> threading.Event:
    """注册一个待确认的预算请求，返回用于阻塞等待的 Event。"""
    ev = threading.Event()
    with _budget_lock:
        _pending_budget[run_id] = {
            "event": ev,
            "question_id": question_id,
            "proposed": proposed,
        }
        _budget_decisions.pop(run_id, None)
    return ev


def get_pending_budget(run_id: str) -> dict | None:
    """查询某个 run 当前是否有待确认的预算请求（供前端轮询/判断）。"""
    with _budget_lock:
        p = _pending_budget.get(run_id)
        return dict(p) if p else None


def submit_budget_decision(run_id: str, decision: dict | None) -> bool:
    """前端提交预算决定；写入并唤醒阻塞中的回调。无 pending 返回 False。"""
    with _budget_lock:
        p = _pending_budget.get(run_id)
        if not p:
            return False
        _budget_decisions[run_id] = decision
        p["event"].set()
    return True


def take_budget_decision(run_id: str) -> dict | None:
    """回调取出决定（并移除）。"""
    with _budget_lock:
        return _budget_decisions.pop(run_id, None)


def clear_budget_pending(run_id: str) -> None:
    with _budget_lock:
        _pending_budget.pop(run_id, None)
        _budget_decisions.pop(run_id, None)


# ---------------------------------------------------------------------------
# 人工介入（G0 硬失败澄清）：run 跑到 g0_clarification 节点时暂停，
# 等待前端弹窗选择"终止"或"上传补充材料继续"后再继续。仅进程内存。
# ---------------------------------------------------------------------------
_clarification_lock = threading.Lock()
# run_id -> {"event": Event, "failed_checks": list[str]}
_pending_clarification: dict[str, dict] = {}
# run_id -> {"action": "terminate"|"continue", "new_data_paths": list[str]}
_clarification_decisions: dict[str, dict] = {}


def request_clarification(
    run_id: str, failed_checks: list[str]
) -> threading.Event:
    """注册一个待确认的 G0 澄清请求，返回用于阻塞等待的 Event。"""
    ev = threading.Event()
    with _clarification_lock:
        _pending_clarification[run_id] = {
            "event": ev,
            "failed_checks": failed_checks,
        }
        _clarification_decisions.pop(run_id, None)
    return ev


def get_pending_clarification(run_id: str) -> dict | None:
    """查询某个 run 当前是否有待确认的 G0 澄清请求。"""
    with _clarification_lock:
        p = _pending_clarification.get(run_id)
        return dict(p) if p else None


def submit_clarification_decision(run_id: str, decision: dict) -> bool:
    """前端提交澄清决定；写入并唤醒阻塞中的回调。无 pending 返回 False。"""
    with _clarification_lock:
        p = _pending_clarification.get(run_id)
        if not p:
            return False
        _clarification_decisions[run_id] = decision
        p["event"].set()
    return True


def take_clarification_decision(run_id: str) -> dict | None:
    """回调取出决定（并移除）。"""
    with _clarification_lock:
        return _clarification_decisions.pop(run_id, None)


def clear_clarification_pending(run_id: str) -> None:
    with _clarification_lock:
        _pending_clarification.pop(run_id, None)
        _clarification_decisions.pop(run_id, None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                workflow_status TEXT,
                current_question_id TEXT,
                results_count INTEGER,
                paper_title TEXT,
                review_status TEXT,
                error TEXT,
                problem_preview TEXT,
                model_config TEXT,
                progress_json TEXT,
                artifacts_json TEXT,
                task_name TEXT
            )
            """
        )
        # 兼容已有数据库：若 task_name 列不存在则添加
        cols = {r[1] for r in _conn.execute("PRAGMA table_info(runs)").fetchall()}
        if "task_name" not in cols:
            _conn.execute("ALTER TABLE runs ADD COLUMN task_name TEXT")
        _conn.commit()
    return _conn


# ---------------------------------------------------------------------------
# 注册表写操作
# ---------------------------------------------------------------------------


def create_run(run_id: str, problem_preview: str, model_config: dict, task_name: str | None = None) -> None:
    """登记一次新运行（状态 queued）。"""
    safe_cfg = {
        k: v for k, v in (model_config or {}).items() if k != "api_key"
    }
    with _lock:
        _get_conn().execute(
            """
            INSERT INTO runs
                (run_id, status, created_at, updated_at, problem_preview, model_config, progress_json, artifacts_json, task_name)
            VALUES (?, 'queued', ?, ?, ?, ?, '[]', '[]', ?)
            """,
            (
                run_id,
                _now(),
                _now(),
                problem_preview,
                json.dumps(safe_cfg, ensure_ascii=False),
                task_name,
            ),
        )
        _get_conn().commit()


def rename_run(run_id: str, task_name: str) -> bool:
    """更新任务名称。返回是否成功（run_id 存在即成功）。"""
    with _lock:
        cur = _get_conn().execute(
            "UPDATE runs SET task_name=?, updated_at=? WHERE run_id=?",
            (task_name, _now(), run_id),
        )
        _get_conn().commit()
        return cur.rowcount > 0


def mark_running(run_id: str) -> None:
    _update(run_id, status="running")


def mark_failed(run_id: str, error: str) -> None:
    _update(run_id, status="failed", error=error)


def mark_cancelled(run_id: str) -> None:
    _update(run_id, status="cancelled", error="用户已中断任务")


def set_result(run_id: str, summary: dict, artifacts: list[str]) -> None:
    fields = {
        "status": "succeeded",
        "workflow_status": summary.get("workflow_status"),
        "paper_title": summary.get("paper_title"),
        "review_status": summary.get("review_status"),
        "results_count": summary.get("results_count"),
        "artifacts_json": json.dumps(artifacts, ensure_ascii=False),
    }
    _update(run_id, **fields)


def append_progress(run_id: str, event: dict) -> None:
    """记录一个进度事件，并同步更新当前状态快照。"""
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT progress_json, workflow_status, current_question_id, results_count FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        events = json.loads(row["progress_json"]) if row else []
        events.append(event)
        if len(events) > _MAX_PROGRESS_EVENTS:
            events = events[-_MAX_PROGRESS_EVENTS:]
        # 用事件里的状态快照更新行
        wf = event.get("workflow_status") or (row["workflow_status"] if row else None)
        cq = event.get("current_question_id") or (row["current_question_id"] if row else None)
        rc = event.get("results_count")
        if rc is None:
            rc = row["results_count"] if row else None
        conn.execute(
            """
            UPDATE runs SET progress_json=?, workflow_status=?, current_question_id=?,
                results_count=?, updated_at=? WHERE run_id=?
            """,
            (json.dumps(events, ensure_ascii=False), wf, cq, rc, _now(), run_id),
        )
        conn.commit()


def _update(run_id: str, **fields: Any) -> None:
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [run_id]
    with _lock:
        _get_conn().execute(f"UPDATE runs SET {cols} WHERE run_id=?", vals)
        _get_conn().commit()


# ---------------------------------------------------------------------------
# 注册表读操作
# ---------------------------------------------------------------------------


def get_run(run_id: str) -> dict | None:
    with _lock:
        row = _get_conn().execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def list_runs(limit: int = 50) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def cleanup_stale_runs(max_age_seconds: int = 300) -> int:
    """把处于 queued/running 但已超过 max_age_seconds 没更新的运行标记为 failed。

    用于服务重启时自动清理：旧的后台线程已随旧进程死亡，但 DB 里的状态
    不会自动更新。重启时扫一遍，僵尸任务会转成 failed，历史页不再误显示
    正在运行，也允许用户在历史页删除这些记录。

    Returns:
        清理的任务数。
    """
    now = datetime.now(timezone.utc)
    cleaned = 0
    with _lock:
        rows = _get_conn().execute(
            "SELECT run_id, status, updated_at FROM runs WHERE status IN ('queued', 'running')"
        ).fetchall()
        for row in rows:
            try:
                ts = datetime.fromisoformat(row["updated_at"])
            except (ValueError, TypeError):
                ts = now
            age = (now - ts).total_seconds()
            if age >= max_age_seconds:
                _get_conn().execute(
                    "UPDATE runs SET status=?, error=?, updated_at=? WHERE run_id=?",
                    (
                        "failed",
                        f"服务重启后未完成（已停止 {int(age)}s）",
                        _now(),
                        row["run_id"],
                    ),
                )
                cleaned += 1
        if cleaned:
            _get_conn().commit()
    return cleaned


def cancel_run(run_id: str) -> dict:
    """请求中断一个正在执行（queued/running）的任务。

    实现方式：设置内存标志 `_cancel_flags[run_id]=True`，后台线程在下一个
    节点边界检测到后抛出 RuntimeError 中断 stream。对于尚未开始的 queued
    任务，直接标 cancelled，后台线程根本不会启动该 run_graph。

    Returns:
        {"cancelled": bool, "blocked": bool, "reason": str}
    """
    with _lock:
        row = _get_conn().execute(
            "SELECT run_id, status FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            return {"cancelled": False, "blocked": False, "reason": "not_found"}
        status = row["status"]
        if status in ("succeeded", "failed", "cancelled"):
            return {
                "cancelled": False,
                "blocked": True,
                "reason": f"任务已结束（{status}），无需中断",
            }
        # 标记取消意图
        _cancel_flags[run_id] = True
        if status == "queued":
            # 还没开始跑，直接判定为已取消
            _get_conn().execute(
                "UPDATE runs SET status=?, error=?, updated_at=? WHERE run_id=?",
                ("cancelled", "用户已中断任务", _now(), run_id),
            )
            _get_conn().commit()
        return {"cancelled": True, "blocked": False, "reason": "ok"}


def delete_run(run_id: str) -> dict:
    """删除一条运行记录（DB 行 + 产物目录）。

    出于安全考虑：正在执行（queued/running）的任务不允许删除，
    避免后台线程读写被删目录引发异常。

    Returns:
        {"deleted": bool, "blocked": bool, "reason": str}
    """
    with _lock:
        row = _get_conn().execute(
            "SELECT run_id, status FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            return {"deleted": False, "blocked": False, "reason": "not_found"}
        status = row["status"]
        if status in ("queued", "running"):
            return {
                "deleted": False,
                "blocked": True,
                "reason": f"任务仍在执行（{status}），请等待完成后再删除",
            }
        _get_conn().execute("DELETE FROM runs WHERE run_id=?", (run_id,))
        _get_conn().commit()

    # 删除产物目录（best-effort，缺失也忽略）
    import shutil

    art_dir = PROJECT_ROOT / "artifacts" / run_id
    try:
        if art_dir.exists():
            shutil.rmtree(art_dir, ignore_errors=True)
    except Exception:
        pass
    return {"deleted": True, "blocked": False, "reason": "ok"}


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["progress"] = json.loads(d.pop("progress_json") or "[]")
    d["artifacts"] = json.loads(d.pop("artifacts_json") or "[]")
    return d


# ---------------------------------------------------------------------------
# 后台执行
# ---------------------------------------------------------------------------


def _summarize_final(state: dict) -> dict:
    paper = state.get("paper_draft")
    review = state.get("review_report")
    return {
        "workflow_status": state.get("workflow_status"),
        "paper_title": getattr(paper, "title", None) if paper else None,
        "review_status": getattr(review, "overall_status", None) if review else None,
        "results_count": len(state.get("question_results") or {}),
    }


def _collect_artifacts(output_dir: str) -> list[str]:
    """列出产物目录下相对路径（供前端下载与展示）。"""
    base = Path(output_dir)
    if not base.exists():
        return []
    allowed = {"paper.md", "paper.docx", "review_report.json"}
    out: list[str] = []
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(base).as_posix()
        top = rel.split("/")[0]
        if rel in allowed or top in ("figures", "questions", "context", "input"):
            out.append(rel)
    return out


async def execute_run(
    run_id: str,
    problem_text: str,
    data_paths: list[str],
    output_dir: str,
    model_config: dict,
) -> None:
    """后台执行一次完整解题流程。"""
    mark_running(run_id)
    llm = create_llm(
        provider=model_config.get("provider"),
        api_key=model_config.get("api_key"),
        base_url=model_config.get("base_url"),
        model=model_config.get("model"),
    )

    def _callback(event: dict) -> None:
        append_progress(run_id, event)

    def _cancel_check() -> bool:
        return _cancel_flags.get(run_id, False)

    def _budget_callback(state: dict) -> dict | None:
        """在每个子任务开始前请求搜索、验证和代码修复预算。

        返回 {BudgetType: int} 作为该问覆盖；返回 None 表示沿用默认。
        本函数在后台线程（asyncio.to_thread）中执行，可安全阻塞。
        """
        qid = state.get("current_question_id", "") or "current"
        bm = state.get("budget_manager")
        proposed: dict = {}
        if bm is not None:
            try:
                proposed = {
                    BudgetType.SEARCH.value: bm.get_record(BudgetType.SEARCH).limit,
                    BudgetType.VALIDATION_ITERATION.value:
                    bm.get_record(BudgetType.VALIDATION_ITERATION).limit,
                    BudgetType.CODE_REPAIR.value:
                    bm.get_record(BudgetType.CODE_REPAIR).limit,
                }
            except Exception:  # noqa: BLE001
                proposed = {}
        ev = request_budget_confirmation(run_id, qid, proposed)
        append_progress(
            run_id,
            {
                "type": "budget_request",
                "phase": "question",
                "node": "configure_question_budget",
                "question_id": qid,
                "proposed": proposed,
                "timestamp": time.time(),
            },
        )
        # 阻塞等待用户决定；每秒检查一次取消意图，便于中断时及时退出
        while not ev.wait(timeout=1.0):
            if _cancel_flags.get(run_id, False):
                clear_budget_pending(run_id)
                append_progress(
                    run_id,
                    {
                        "type": "budget_confirmed",
                        "phase": "question",
                        "question_id": qid,
                        "action": "cancelled",
                        "timestamp": time.time(),
                    },
                )
                return None
        decision = take_budget_decision(run_id)
        clear_budget_pending(run_id)
        if not decision:
            append_progress(
                run_id,
                {
                    "type": "budget_confirmed",
                    "phase": "question",
                    "question_id": qid,
                    "action": "default",
                    "timestamp": time.time(),
                },
            )
            return None
        append_progress(
            run_id,
            {
                "type": "budget_confirmed",
                "phase": "question",
                "question_id": qid,
                "action": "override",
                "limits": decision,
                "timestamp": time.time(),
            },
        )
        return {
            BudgetType(key): int(value)
            for key, value in decision.items()
            if key in {
                BudgetType.SEARCH.value,
                BudgetType.VALIDATION_ITERATION.value,
                BudgetType.CODE_REPAIR.value,
            }
        }

    def _request_initial_budget() -> dict | None:
        """任务启动前请求用户配置 G0 输入质量门重试预算。

        在后台线程中阻塞等待用户确认。返回 {BudgetType: int} 或 None（沿用默认）。
        """
        from scr.runtime.budget import DEFAULT_BUDGETS
        proposed = {
            BudgetType.INTAKE_RETRY.value:
            DEFAULT_BUDGETS[BudgetType.INTAKE_RETRY],
        }
        ev = request_budget_confirmation(run_id, "", proposed)
        append_progress(
            run_id,
            {
                "type": "budget_request",
                "phase": "initial",
                "node": "initial_budget",
                "question_id": "",
                "proposed": proposed,
                "timestamp": time.time(),
            },
        )
        while not ev.wait(timeout=1.0):
            if _cancel_flags.get(run_id, False):
                clear_budget_pending(run_id)
                append_progress(
                    run_id,
                    {
                        "type": "budget_confirmed",
                        "phase": "initial",
                        "action": "cancelled",
                        "timestamp": time.time(),
                    },
                )
                return None
        decision = take_budget_decision(run_id)
        clear_budget_pending(run_id)
        if not decision:
            append_progress(
                run_id,
                {
                    "type": "budget_confirmed",
                    "phase": "initial",
                    "action": "default",
                    "timestamp": time.time(),
                },
            )
            return None
        append_progress(
            run_id,
            {
                "type": "budget_confirmed",
                "phase": "initial",
                "action": "override",
                "limits": decision,
                "timestamp": time.time(),
            },
        )
        return {
            BudgetType(key): int(value)
            for key, value in decision.items()
            if key == BudgetType.INTAKE_RETRY.value
        }

    def _delivery_budget_callback(state: dict) -> dict | None:
        """所有子任务完成后请求用户配置 GF 交付修订预算。"""
        from scr.runtime.budget import DEFAULT_BUDGETS

        proposed = {
            BudgetType.PAPER_REVISION.value:
            DEFAULT_BUDGETS[BudgetType.PAPER_REVISION],
        }
        ev = request_budget_confirmation(run_id, "", proposed)
        append_progress(
            run_id,
            {
                "type": "budget_request",
                "phase": "delivery",
                "node": "configure_delivery_budget",
                "question_id": "",
                "proposed": proposed,
                "timestamp": time.time(),
            },
        )
        while not ev.wait(timeout=1.0):
            if _cancel_flags.get(run_id, False):
                clear_budget_pending(run_id)
                return None
        decision = take_budget_decision(run_id)
        clear_budget_pending(run_id)
        append_progress(
            run_id,
            {
                "type": "budget_confirmed",
                "phase": "delivery",
                "question_id": "",
                "action": "override" if decision else "default",
                "limits": decision or {},
                "timestamp": time.time(),
            },
        )
        return {
            BudgetType(key): int(value)
            for key, value in (decision or {}).items()
            if key == BudgetType.PAPER_REVISION.value
        }

    def _clarification_callback(state: dict) -> dict | None:
        """G0 硬失败时暂停等用户选择终止或补充材料继续。

        返回 {"action": "terminate"} 或 {"action": "continue", "new_data_paths": [...]}。
        本函数在后台线程（asyncio.to_thread）中执行，可安全阻塞。
        """
        failed_checks = state.get("_g0_failed_checks", [])
        run_id_val = state.get("run_id", "") or run_id
        ev = request_clarification(run_id_val, failed_checks)
        append_progress(
            run_id_val,
            {
                "type": "clarification_request",
                "failed_checks": failed_checks,
                "timestamp": time.time(),
            },
        )
        # 阻塞等待用户决定；每秒检查一次取消意图
        while not ev.wait(timeout=1.0):
            if _cancel_flags.get(run_id_val, False):
                clear_clarification_pending(run_id_val)
                append_progress(
                    run_id_val,
                    {
                        "type": "clarification_resolved",
                        "action": "cancelled",
                        "timestamp": time.time(),
                    },
                )
                return {"action": "terminate"}
        decision = take_clarification_decision(run_id_val)
        clear_clarification_pending(run_id_val)
        action = decision.get("action", "terminate") if decision else "terminate"
        append_progress(
            run_id_val,
            {
                "type": "clarification_resolved",
                "action": action,
                "timestamp": time.time(),
            },
        )
        return decision or {"action": "terminate"}

    try:
        # 任务启动前：请求用户配置 G0 输入质量门预算。
        from scr.runtime.budget import BudgetManager
        bm = BudgetManager()
        initial_limits = await asyncio.to_thread(_request_initial_budget)
        if initial_limits:
            bm.update_run_limits(initial_limits)

        final_state = await asyncio.to_thread(
            run_graph,
            problem_text=problem_text,
            data_paths=data_paths,
            output_dir=output_dir,
            llm=llm,
            run_id=run_id,
            progress_callback=_callback,
            console=False,
            cancel_check=_cancel_check,
            budget_manager=bm,
            budget_config_callback=_budget_callback,
            delivery_budget_config_callback=_delivery_budget_callback,
            clarification_callback=_clarification_callback,
        )
        # 任务完成后推送预算统计（time/token），前端在聊天中展示
        bm = final_state.get("budget_manager")
        if bm is not None:
            try:
                totals = bm.get_total_usage()
                append_progress(
                    run_id,
                    {
                        "type": "budget_summary",
                        "time_total": totals.get(BudgetType.TIME, 0),
                        "token_total": totals.get(BudgetType.TOKEN, 0),
                        "timestamp": time.time(),
                    },
                )
            except Exception:  # noqa: BLE001
                pass
        set_result(run_id, _summarize_final(final_state), _collect_artifacts(output_dir))
    except Exception as exc:  # noqa: BLE001
        # 记录完整堆栈，便于排查 NoneType.get 等深层 bug
        import traceback
        print(f"[run {run_id}] 执行失败: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        if _cancel_flags.get(run_id, False) or "cancelled" in str(exc).lower():
            mark_cancelled(run_id)
        else:
            mark_failed(run_id, f"{type(exc).__name__}: {exc}")
