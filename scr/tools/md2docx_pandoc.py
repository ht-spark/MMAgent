"""Markdown + Pandoc → DOCX 转换器（优先方案）。

将论文写作生成的带 LaTeX 公式的 Markdown 用 pandoc 转为 DOCX：
  - 公式：``$...$`` / ``$$...$$`` 自动转为 Word 原生公式（OMML），
    打开 Word 可直接编辑（区别于自研 python-docx 的 LaTeX→OMML 近似解析）
  - 图片：相对路径通过 ``--resource-path`` 解析
  - 标题 / 表格 / 列表：pandoc 原生支持

依赖：pandoc 可执行文件（查找顺序：PATH → 项目 ``tools/pandoc/`` → 常见安装位置）。
找不到 pandoc 或转换失败时，``convert_paper_md_to_docx`` 回退到
自研 ``md2docx.py``（python-docx 实现）。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

__all__ = [
    "find_pandoc",
    "pandoc_available",
    "pandoc_to_docx",
    "convert_paper_md_to_docx",
]


def _project_tools_dir() -> Path:
    """项目根目录下的 tools/ 目录（scr/ 的上一级）。"""
    return Path(__file__).resolve().parent.parent.parent / "tools"


def find_pandoc() -> str | None:
    """查找 pandoc 可执行文件。

    查找顺序：
      1. 系统 PATH
      2. 项目 tools/pandoc/（portable 安装）
      3. Windows 常见安装位置（AppData/Local/Pandoc）
    """
    exe_name = "pandoc.exe" if sys.platform == "win32" else "pandoc"

    found = shutil.which(exe_name)
    if found:
        return found

    candidates = [
        _project_tools_dir() / "pandoc" / exe_name,
        _project_tools_dir() / exe_name,
    ]
    for c in candidates:
        if c.exists():
            return str(c)

    if sys.platform == "win32":
        local = Path.home() / "AppData" / "Local" / "Pandoc" / exe_name
        if local.exists():
            return str(local)

    return None


def pandoc_available() -> bool:
    """pandoc 是否可用。"""
    return find_pandoc() is not None


def pandoc_to_docx(
    md_path: str | Path,
    output_path: str | Path,
    resource_path: str | Path | None = None,
    reference_doc: str | Path | None = None,
    extra_args: list[str] | None = None,
) -> str:
    """调用 pandoc 将 Markdown 文件转换为 DOCX。

    Args:
        md_path: 输入 Markdown 文件路径。
        output_path: 输出 DOCX 文件路径。
        resource_path: 图片资源基准目录（解析相对图片路径），
                       默认取 md 文件所在目录。
        reference_doc: 可选的 reference.docx（样式模板）。
        extra_args: 附加 pandoc 参数。

    Returns:
        输出 DOCX 文件路径。

    Raises:
        FileNotFoundError: pandoc 不可用。
        subprocess.CalledProcessError: pandoc 转换失败。
    """
    pandoc = find_pandoc()
    if pandoc is None:
        raise FileNotFoundError(
            "pandoc 未找到。请安装 pandoc（winget install JohnMacFarlane.Pandoc）"
            "或下载 portable 版到 tools/pandoc/ 目录。"
        )

    md_path = Path(md_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if resource_path is None:
        resource_path = md_path.parent

    # 启用 $...$ / $$...$$ 公式（tex_math_dollars）与 raw TeX 透传
    cmd = [
        pandoc,
        str(md_path),
        "-o", str(output_path),
        "--from", "markdown+tex_math_dollars+raw_tex",
        "--resource-path", str(resource_path),
    ]
    if reference_doc is not None:
        cmd += ["--reference-doc", str(reference_doc)]
    if extra_args:
        cmd += extra_args

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, cmd,
            output=proc.stdout,
            stderr=proc.stderr[-2000:],
        )

    return str(output_path)


def convert_paper_md_to_docx(
    md_file_path: str | Path,
    output_dir: str | Path | None = None,
) -> str:
    """将论文 Markdown 文件转换为 DOCX（pandoc 优先，python-docx 回退）。

    Args:
        md_file_path: Markdown 文件路径。
        output_dir: 输出目录（默认与 md 文件同目录）。

    Returns:
        输出 DOCX 文件路径。
    """
    md_path = Path(md_file_path)
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown 文件不存在: {md_file_path}")

    if output_dir is None:
        output_dir = md_path.parent
    output_path = Path(output_dir) / f"{md_path.stem}.docx"

    # 优先 pandoc：公式转 Word 原生 OMML，可编辑
    if pandoc_available():
        try:
            result = pandoc_to_docx(
                md_path, output_path, resource_path=md_path.parent
            )
            print(f"[md2docx] 已用 pandoc 转换: {result}")
            return result
        except Exception as e:
            print(f"[md2docx] pandoc 转换失败，回退 python-docx: {e}")

    # 回退：自研 python-docx 实现（可能因缺少 python-docx 而失败）
    try:
        from ..tools.md2docx import convert_paper_md_to_docx as _legacy
        return _legacy(md_file_path, str(output_dir))
    except ImportError as e:
        raise ImportError(
            f"DOCX 转换不可用：pandoc 未安装且 python-docx 缺失（{e}）。\n"
            "请安装 pandoc：winget install JohnMacFarlane.Pandoc"
        ) from e
