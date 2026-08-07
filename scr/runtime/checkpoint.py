"""检查点与恢复。

对应 architecture.md §8.2：
  在 G0、每个 GQ、模型重选前、全任务审查前及交付前保存检查点。
  恢复时应跳过已验证的小问和已有的确定性产物，
  除非其上游数据或决策发生变化。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class CheckpointData(BaseModel):
    """检查点数据。"""
    checkpoint_id: str
    run_id: str
    timestamp: str
    phase: str  # "g0" / "gq_q1" / "model_reselect_q2" / "final_review" / "delivery"
    question_id: str = ""  # 关联的小问（全局检查点为空）
    state_snapshot: dict = Field(default_factory=dict)  # 状态快照
    description: str = ""


class CheckpointManager:
    """检查点管理器。
    
    在关键节点保存状态快照，支持恢复运行。
    
    Args:
        checkpoint_dir: 检查点存储目录。
        run_id: 运行 ID。
    """
    
    def __init__(self, checkpoint_dir: str | Path, run_id: str) -> None:
        self.checkpoint_dir = Path(checkpoint_dir)
        self.run_id = run_id
        self.dir = self.checkpoint_dir / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0
    
    def save(
        self,
        phase: str,
        state: dict,
        question_id: str = "",
        description: str = "",
    ) -> CheckpointData:
        """保存检查点。
        
        Args:
            phase: 检查点阶段标识。
            state: 状态快照（可序列化为 JSON 的字典）。
            question_id: 关联的小问 ID。
            description: 检查点描述。
        
        Returns:
            检查点数据对象。
        """
        self._counter += 1
        checkpoint_id = f"cp_{self._counter:03d}_{phase}"
        
        # 序列化 state 中的 Pydantic 对象
        serializable_state = self._serialize_state(state)
        
        data = CheckpointData(
            checkpoint_id=checkpoint_id,
            run_id=self.run_id,
            timestamp=datetime.now().isoformat(),
            phase=phase,
            question_id=question_id,
            state_snapshot=serializable_state,
            description=description,
        )
        
        path = self.dir / f"{checkpoint_id}.json"
        path.write_text(data.model_dump_json(indent=2), encoding="utf-8")
        
        return data
    
    def load(self, checkpoint_id: str) -> CheckpointData | None:
        """加载检查点。"""
        path = self.dir / f"{checkpoint_id}.json"
        if not path.exists():
            return None
        return CheckpointData.model_validate_json(path.read_text(encoding="utf-8"))
    
    def load_latest(self) -> CheckpointData | None:
        """加载最新的检查点。"""
        checkpoints = self.list_checkpoints()
        if not checkpoints:
            return None
        return self.load(checkpoints[-1])
    
    def list_checkpoints(self) -> list[str]:
        """列出所有检查点 ID（按顺序）。"""
        files = sorted(self.dir.glob("cp_*.json"))
        return [f.stem for f in files]
    
    def list_by_phase(self, phase: str) -> list[str]:
        """按阶段列出检查点。"""
        files = sorted(self.dir.glob(f"cp_*_{phase}.json"))
        return [f.stem for f in files]
    
    def get_latest_question_checkpoint(self, question_id: str) -> CheckpointData | None:
        """获取指定小问的最新检查点。"""
        all_cps = []
        for cp_id in self.list_checkpoints():
            cp = self.load(cp_id)
            if cp and cp.question_id == question_id:
                all_cps.append(cp)
        if not all_cps:
            return None
        return all_cps[-1]
    
    def is_question_validated(self, question_id: str) -> bool:
        """检查小问是否已通过验证（存在 phase 包含 'gq' 的检查点）。"""
        for cp_id in self.list_checkpoints():
            cp = self.load(cp_id)
            if cp and cp.question_id == question_id and cp.phase.startswith("gq"):
                return True
        return False
    
    def _serialize_state(self, state: dict) -> dict:
        """序列化状态字典中的 Pydantic 对象。"""
        result: dict[str, Any] = {}
        for key, value in state.items():
            if hasattr(value, "model_dump"):
                result[key] = value.model_dump()
            elif isinstance(value, dict):
                result[key] = self._serialize_state(value)
            elif isinstance(value, list):
                result[key] = [
                    v.model_dump() if hasattr(v, "model_dump") else v
                    for v in value
                ]
            else:
                # 尝试 JSON 序列化，失败则转字符串
                try:
                    json.dumps(value)
                    result[key] = value
                except (TypeError, ValueError):
                    result[key] = str(value)
        return result
