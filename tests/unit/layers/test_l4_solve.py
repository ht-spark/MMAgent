"""L4 求解子图单元测试（demo 简化版）。"""
from __future__ import annotations

import pandas as pd
import pytest

from scr.layers.l4_solve import L4SolveSubgraph
from scr.schemas.model import ModelCandidate, ModelScore
from scr.schemas.result import ExecutionResult


@pytest.fixture
def sample_csv(tmp_path) -> str:
    df = pd.DataFrame({
        "GDP": [40269, 43215, 28232, 30664, 27670],
        "人口": [2189, 2487, 1881, 1768, 321],
        "增长率": [5.2, 3.1, 4.5, 4.8, 2.9],
    })
    path = tmp_path / "city.csv"
    df.to_csv(path, index=False, encoding="utf-8")
    return str(path)


@pytest.fixture
def entropy_candidate() -> ModelCandidate:
    return ModelCandidate(
        id="q1_c1", name="熵权法", family="客观赋权法",
        required_data=["GDP", "人口"],
        assumptions=["指标独立"],
        output_description="权重 + 得分",
        validation_method="权重扰动",
    )


def test_entropy_weight_pipeline(sample_csv, entropy_candidate, tmp_path):
    """熵权法：执行成功 + G5 通过。"""
    score = ModelScore(
        candidate_id="q1_c1", problem_fit=0.9, data_fit=0.9,
        assumption_validity=0.7, validation_feasibility=0.8,
        interpretability=0.9, implementation_feasibility=0.9,
        innovation=0.5, total_score=0.85, reasoning="",
    )
    subgraph = L4SolveSubgraph(output_dir=tmp_path / "artifacts")
    result = subgraph.run(sample_csv, [(entropy_candidate, score)])

    assert result["workflow_status"] == "l4_completed"
    assert result["execution_result"].success is True
    assert "weights_sum" in result["execution_result"].numeric_outputs
    # 熵权法权重和应接近 1.0
    assert abs(result["execution_result"].numeric_outputs["weights_sum"] - 1.0) < 0.01
    # 代码文件已写入
    assert (tmp_path / "artifacts" / "code" / "q1_c1.py").exists()


def test_g5_routes_code_failure(tmp_path):
    """模拟 code 失败 → G5 action=retry。"""
    from scr.gates.g5_result import G5ResultGate

    gate = G5ResultGate()
    state = {
        "execution_result": ExecutionResult(
            success=False, failure_reason="code",
            error_message="syntax error",
        ).model_dump(),
    }
    result = gate.evaluate(state)
    assert result.passed is False
    assert result.action == "retry"