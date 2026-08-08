"""定义证据目录、任务产物、决策记录和运行账本的数据结构。"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field

from .research import EvidenceItem


class EvidenceCatalog(BaseModel):
    """证据目录（architecture.md §3.4）。
    
    联网检索或本地资料形成的来源、关键观点、适用条件、局限和引用信息。
    """
    items: list[EvidenceItem] = Field(default_factory=list)
    
    @property
    def total_count(self) -> int:
        return len(self.items)
    
    def add(self, item: EvidenceItem) -> None:
        """添加证据项。"""
        self.items.append(item)
    
    def get_by_source(self, source_id: str) -> list[EvidenceItem]:
        """按来源 ID 查询证据。"""
        return [e for e in self.items if e.source_id == source_id]


class ArtifactRecord(BaseModel):
    """产物记录（ArtifactRegistry 列表项）。"""
    name: str  # 逻辑名称
    path: str  # 文件路径
    artifact_type: Literal[
        "code", "data", "figure", "table", "report", "paper", "config", "other",
    ]
    created_at: str = ""
    metadata: dict = Field(default_factory=dict)


class ArtifactRegistry(BaseModel):
    """产物注册表（architecture.md §3.4）。"""
    records: list[ArtifactRecord] = Field(default_factory=list)
    
    def register(self, name: str, path: str, artifact_type: str, **metadata) -> ArtifactRecord:
        """注册一个产物。"""
        from datetime import datetime
        record = ArtifactRecord(
            name=name, path=path, artifact_type=artifact_type,
            created_at=datetime.now().isoformat(), metadata=metadata,
        )
        self.records.append(record)
        return record
    
    def get_by_name(self, name: str) -> ArtifactRecord | None:
        """按逻辑名称查询产物。"""
        for r in self.records:
            if r.name == name:
                return r
        return None
    
    def get_by_type(self, artifact_type: str) -> list[ArtifactRecord]:
        """按类型查询产物。"""
        return [r for r in self.records if r.artifact_type == artifact_type]


class DecisionLogEntry(BaseModel):
    """决策日志条目。"""
    timestamp: str
    decision_type: Literal[
        "model_selection", "assumption", "rollback", "human_intervention", "budget_exceeded",
    ]
    question_id: str = ""  # 关联的小问（全局决策为空）
    description: str
    reasoning: str = ""


class DecisionLog(BaseModel):
    """决策日志（architecture.md §3.4）。"""
    entries: list[DecisionLogEntry] = Field(default_factory=list)
    
    def log(self, decision_type: str, description: str, question_id: str = "", reasoning: str = "") -> None:
        from datetime import datetime
        self.entries.append(DecisionLogEntry(
            timestamp=datetime.now().isoformat(),
            decision_type=decision_type,
            question_id=question_id,
            description=description,
            reasoning=reasoning,
        ))


class RunLedgerEntry(BaseModel):
    """运行账本条目。"""
    step: str
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    duration_seconds: float = Field(ge=0.0, default=0.0)
    tool_calls: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    retry_count: int = Field(ge=0, default=0)
    checkpoint_path: str | None = None


class RunLedger(BaseModel):
    """运行账本（architecture.md §3.4）。"""
    entries: list[RunLedgerEntry] = Field(default_factory=list)
    
    def log(self, step: str, status: str, duration: float = 0.0, 
            errors: list[str] | None = None, retry_count: int = 0,
            checkpoint_path: str | None = None) -> None:
        self.entries.append(RunLedgerEntry(
            step=step, status=status, duration_seconds=duration,
            errors=errors or [], retry_count=retry_count,
            checkpoint_path=checkpoint_path,
        ))
