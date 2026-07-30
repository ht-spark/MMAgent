"""产物目录管理。

对应 architecture.md §6.3：
  artifacts/<run_id>/
    input/          # 原始题目与附件登记
    context/        # 题目理解、数据画像、依赖图
    questions/Q1/   # 每问的代码、数据、图表、结果包
    questions/Q2/
    evidence/       # 检索来源与引用库
    paper/          # 草稿、终稿、参考文献
    review/         # 全题与格式审查报告
    final/          # 最终论文、代码、图表、提交清单
"""
from __future__ import annotations

import shutil
from pathlib import Path


# 标准子目录定义
STANDARD_SUBDIRS = [
    "input",
    "context",
    "questions",
    "evidence",
    "paper",
    "review",
    "final",
]


class ArtifactManager:
    """产物目录管理器。
    
    负责创建和维护 artifacts/<run_id>/ 下的标准目录结构，
    并提供产物文件的路径管理和注册功能。
    
    Args:
        base_dir: 产物根目录（如 "artifacts"）。
        run_id: 运行 ID（如 "abc12345"）。
    """
    
    def __init__(self, base_dir: str | Path, run_id: str) -> None:
        self.base_dir = Path(base_dir)
        self.run_id = run_id
        self.run_dir = self.base_dir / run_id
        self._registry: dict[str, Path] = {}  # 逻辑名 → 路径
        self._ensure_dirs()
    
    def _ensure_dirs(self) -> None:
        """创建标准子目录。"""
        for subdir in STANDARD_SUBDIRS:
            (self.run_dir / subdir).mkdir(parents=True, exist_ok=True)
    
    @property
    def input_dir(self) -> Path:
        return self.run_dir / "input"
    
    @property
    def context_dir(self) -> Path:
        return self.run_dir / "context"
    
    @property
    def questions_dir(self) -> Path:
        return self.run_dir / "questions"
    
    @property
    def evidence_dir(self) -> Path:
        return self.run_dir / "evidence"
    
    @property
    def paper_dir(self) -> Path:
        return self.run_dir / "paper"
    
    @property
    def review_dir(self) -> Path:
        return self.run_dir / "review"
    
    @property
    def final_dir(self) -> Path:
        return self.run_dir / "final"
    
    def question_dir(self, question_id: str) -> Path:
        """获取指定小问的产物目录，自动创建。"""
        d = self.questions_dir / question_id
        d.mkdir(parents=True, exist_ok=True)
        return d
    
    def register(self, name: str, path: str | Path) -> None:
        """注册产物路径。"""
        self._registry[name] = Path(path)
    
    def get_path(self, name: str) -> Path | None:
        """查询已注册的产物路径。"""
        return self._registry.get(name)
    
    def save_text(self, subdir: str, filename: str, content: str, encoding: str = "utf-8") -> Path:
        """保存文本文件到指定子目录。"""
        d = self.run_dir / subdir
        d.mkdir(parents=True, exist_ok=True)
        path = d / filename
        path.write_text(content, encoding=encoding)
        return path
    
    def save_bytes(self, subdir: str, filename: str, data: bytes) -> Path:
        """保存二进制文件到指定子目录。"""
        d = self.run_dir / subdir
        d.mkdir(parents=True, exist_ok=True)
        path = d / filename
        path.write_bytes(data)
        return path
    
    def copy_input(self, src_path: str | Path) -> Path:
        """将原始输入文件复制到 input/ 目录。"""
        src = Path(src_path)
        if not src.exists():
            raise FileNotFoundError(f"Source file not found: {src}")
        dst = self.input_dir / src.name
        shutil.copy2(src, dst)
        return dst
    
    def exists(self) -> bool:
        """检查运行目录是否存在。"""
        return self.run_dir.exists()
    
    def list_artifacts(self, subdir: str | None = None) -> list[Path]:
        """列出产物文件。"""
        base = self.run_dir / subdir if subdir else self.run_dir
        if not base.exists():
            return []
        return [p for p in base.rglob("*") if p.is_file()]
