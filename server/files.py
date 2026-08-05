"""产物文件的安全解析与下载辅助。

所有下载都必须限制在 artifacts/<run_id>/ 之内，禁止目录穿越。
"""
from __future__ import annotations

from pathlib import Path
from typing import NoReturn

from server.runs import get_run

# 产物根目录：与 agent 写入位置一致（项目根 / artifacts）
ARTIFACTS_ROOT = Path(__file__).resolve().parents[1] / "artifacts"


def resolve_artifact(run_id: str, rel_path: str) -> Path:
    """将 run_id + 相对路径解析为绝对路径，校验合法性。

    Raises:
        FileNotFoundError: run 不存在或文件不存在
        ValueError: 路径非法（目录穿越）
    """
    if not get_run(run_id):
        raise FileNotFoundError(f"run 不存在: {run_id}")

    # 归一化并阻止穿越
    rel = Path(rel_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("非法路径（禁止绝对路径或 .. 穿越）")

    target = (ARTIFACTS_ROOT / run_id / rel).resolve()
    base = (ARTIFACTS_ROOT / run_id).resolve()
    if target != base and base not in target.parents:
        raise ValueError("路径超出 run 目录范围")

    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"文件不存在: {rel_path}")

    return target


def list_figures(run_id: str) -> list[str]:
    """列出该 run 的图表文件名（figures/ 下）。"""
    fig_dir = ARTIFACTS_ROOT / run_id / "figures"
    if not fig_dir.exists():
        return []
    return sorted(p.name for p in fig_dir.glob("*") if p.is_file())
