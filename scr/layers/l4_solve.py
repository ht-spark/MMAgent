"""L4 求解与检验子图。

对应 architecture.md §4 L4 与 plan.md Phase 7：
  formulate → codegen → sandbox exec → analyze + G5

简化版（demo）：
  - 跳过确定性复跑 / analyze / validate（后续可加）
  - 用预定义模型代码模板（按 ModelCandidate.family 分发）
  - sandbox 用 subprocess + timeout 实现
  - 输出 ExecutionResult + G5 校验

按子问题 fan-out（plan.md Phase 7.12），但 demo 版按顺序处理。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from ..gates.g5_result import G5ResultGate
from ..schemas.common import GateResult
from ..schemas.model import ModelCandidate, ModelScore
from ..schemas.result import ExecutionResult, ResultAnalysis


# ---------------------------------------------------------------------------
# 预定义模型代码模板（demo 简化版）
# ---------------------------------------------------------------------------


_MODEL_TEMPLATES: dict[str, str] = {
    "客观赋权法": '''"""熵权法（demo 版）。"""
import json
import sys
import pandas as pd
import numpy as np

df = pd.read_csv(sys.argv[1])
# 选所有数值列
num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
if not num_cols:
    print(json.dumps({"success": False, "failure_reason": "data", "error": "无数值列"}))
    sys.exit(0)

# 标准化
X = df[num_cols].copy()
for c in num_cols:
    rng = X[c].max() - X[c].min()
    if rng == 0:
        X[c] = 0.5
    else:
        X[c] = (X[c] - X[c].min()) / rng

# 信息熵 + 权重
p = X / (X.sum(axis=0) + 1e-12)
k = 1 / np.log(max(1, len(X)))
e = -k * (p * np.log(p + 1e-12)).sum(axis=0)
d = 1 - e
w_arr = (d / (d.sum() + 1e-12)).values  # 转 numpy 数组，方便整数索引
score = (X * w_arr).sum(axis=1)

print(json.dumps({
    "success": True,
    "numeric_outputs": {
        "weights_sum": float(w_arr.sum()),
        "max_score": float(score.max()),
        "min_score": float(score.min()),
        "mean_score": float(score.mean()),
        "n_columns": float(len(num_cols)),
    },
    "weights": {c: float(w_arr[i]) for i, c in enumerate(num_cols)},
    "scores": [float(s) for s in score.tolist()],
}))
''',
    "线性模型": '''"""线性回归（demo 版）。"""
import json
import sys
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression

df = pd.read_csv(sys.argv[1])
num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
if len(num_cols) < 2:
    print(json.dumps({"success": False, "failure_reason": "data", "error": "需要 ≥ 2 数值列"}))
    sys.exit(0)

X = df[num_cols[:-1]].values
y = df[num_cols[-1]].values
model = LinearRegression().fit(X, y)
pred = model.predict(X)

print(json.dumps({
    "success": True,
    "numeric_outputs": {
        "r2_score": float(model.score(X, y)),
        "intercept": float(model.intercept_),
        "n_features": float(X.shape[1]),
        "mse": float(((y - pred) ** 2).mean()),
    },
}))
''',
    "逼近理想解法": '''"""TOPSIS（demo 版）。"""
import json
import sys
import pandas as pd
import numpy as np

df = pd.read_csv(sys.argv[1])
num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
if not num_cols:
    print(json.dumps({"success": False, "failure_reason": "data", "error": "无数值列"}))
    sys.exit(0)

X = df[num_cols].copy()
# 向量归一化
norm = np.sqrt((X ** 2).sum(axis=0)).replace(0, 1)
X_norm = X / norm

# 正负理想解（demo 假设全部为正向指标）
pos_ideal = X_norm.max(axis=0)
neg_ideal = X_norm.min(axis=0)

# 欧氏距离
d_pos = np.sqrt(((X_norm - pos_ideal) ** 2).sum(axis=1))
d_neg = np.sqrt(((X_norm - neg_ideal) ** 2).sum(axis=1))

# 贴近度 C_i = d_neg / (d_pos + d_neg)
closeness = d_neg / (d_pos + d_neg + 1e-12)

print(json.dumps({
    "success": True,
    "numeric_outputs": {
        "max_closeness": float(closeness.max()),
        "min_closeness": float(closeness.min()),
        "mean_closeness": float(closeness.mean()),
        "n_alternatives": float(len(df)),
    },
    "closeness": [float(c) for c in closeness.tolist()],
}))
''',
    "线性规划": '''"""线性规划（demo 版，使用 PuLP）。"""
import json
import sys
import pandas as pd
import numpy as np
try:
    import pulp
except ImportError:
    print(json.dumps({"success": False, "failure_reason": "code", "error": "需安装 pulp"}))
    sys.exit(0)

df = pd.read_csv(sys.argv[1])
num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
if not num_cols:
    print(json.dumps({"success": False, "failure_reason": "data", "error": "无数值列"}))
    sys.exit(0)

n = len(df)
x = [pulp.LpVariable(f"x{i}", lowBound=0, cat="Continuous") for i in range(n)]
prob = pulp.LpProblem("demo_lp", pulp.LpMaximize)

# 目标：最大化 sum(coef_i * x_i)，coef 取第一列
coef = df[num_cols[0]].tolist()
prob += pulp.lpSum([c * xi for c, xi in zip(coef, x)])

# 约束：sum(x) <= 100
prob += pulp.lpSum(x) <= 100

# 约束：每个 x_i <= 第二列对应值（如存在）
if len(num_cols) > 1:
    bound = df[num_cols[1]].tolist()
    for xi, b in zip(x, bound):
        prob += xi <= float(b)

status = prob.solve(pulp.PULP_CBC_CMD(msg=0))
optimal = pulp.LpStatus[status] == "Optimal"

print(json.dumps({
    "success": optimal,
    "numeric_outputs": {
        "objective_value": float(pulp.value(prob.objective) or 0.0),
        "n_variables": float(n),
        "is_optimal": 1.0 if optimal else 0.0,
    },
    "variables": [float(xi.value() or 0) for xi in x],
}))
''',
    "default": '''"""通用占位：返回简单统计。"""
import json
import sys
import pandas as pd
import numpy as np

df = pd.read_csv(sys.argv[1])
num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
print(json.dumps({
    "success": True,
    "numeric_outputs": {
        "n_rows": float(len(df)),
        "n_cols": float(len(num_cols)),
        "overall_mean": float(df[num_cols].mean().mean()) if num_cols else 0.0,
    },
}))
''',
}


def _get_template(family: str) -> str:
    """根据模型 family 获取代码模板。"""
    if family in _MODEL_TEMPLATES:
        return _MODEL_TEMPLATES[family]
    # 模糊匹配
    for key, tmpl in _MODEL_TEMPLATES.items():
        if key in family or family in key:
            return tmpl
    return _MODEL_TEMPLATES["default"]


# ---------------------------------------------------------------------------
# L4 子图
# ---------------------------------------------------------------------------


class L4SolveSubgraph:
    """L4 求解子图（demo 简化版）。

    Args:
        output_dir: 产物输出根目录。
        timeout_seconds: sandbox 执行超时。
        max_attempts: G5 失败重试次数。
    """

    def __init__(
        self,
        output_dir: str | Path | None = None,
        timeout_seconds: int = 30,
        max_attempts: int = 3,
    ) -> None:
        self.output_dir = Path(output_dir) if output_dir else Path("artifacts/default")
        self.timeout_seconds = timeout_seconds
        self.gate = G5ResultGate()
        self.max_attempts = max(1, max_attempts)

    def run(
        self,
        processed_data_path: str | Path,
        selected_models: list[tuple[ModelCandidate, ModelScore]],
    ) -> dict:
        """执行 L4 求解流程。

        Args:
            processed_data_path: L3 处理后的数据路径。
            selected_models: (candidate, score) 列表。

        Returns:
            State 部分更新 dict：
              - execution_result: ExecutionResult（最后一个或综合）
              - subproblem_executions: list[SubProblemExecution]
              - gate_result: GateResult
              - workflow_status: str
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        code_dir = self.output_dir / "code"
        code_dir.mkdir(exist_ok=True)

        subproblem_executions: list = []

        for candidate, _score in selected_models:
            # 1. formulate（这里用 family 选择代码模板）
            # 2. codegen
            template = _get_template(candidate.family)
            code_file = code_dir / f"{candidate.id}.py"
            code_file.write_text(template, encoding="utf-8")

            # 3. sandbox exec（带 G5 重试）
            result = self._exec_with_retry(code_file, processed_data_path)

            from ..schemas.result import SubProblemExecution
            subproblem_executions.append(
                SubProblemExecution(
                    subproblem_id=candidate.id.split("_c")[0],  # 从 "q1_c1" 提取 "q1"
                    candidate_id=candidate.id,
                    result=result,
                    repair_count=0,
                )
            )

        # 综合结果（demo：取最后一个）
        last_result = subproblem_executions[-1].result if subproblem_executions else ExecutionResult(
            success=False, failure_reason="code", error_message="no candidates"
        )

        # G5 校验
        state = {
            "execution_result": last_result.model_dump(),
            "_g5_budget_used": 0,
        }
        gate_result = self.gate.evaluate(state)

        if gate_result.passed:
            status = "l4_completed"
        elif gate_result.action == "human":
            status = "l4_human_review"
        else:
            status = "l4_failed"

        return {
            "execution_result": last_result,
            "subproblem_executions": subproblem_executions,
            "gate_result": gate_result,
            "workflow_status": status,
            "code_files": [str(sf.result.output_files) for sf in subproblem_executions],
        }

    # ------------------------------------------------------------------
    # 内部：沙箱执行
    # ------------------------------------------------------------------

    def _exec_with_retry(
        self,
        code_file: Path,
        data_path: str | Path,
    ) -> ExecutionResult:
        """沙箱执行代码（subprocess + timeout），带 G5 重试。"""
        last_result: ExecutionResult | None = None

        for attempt in range(1, self.max_attempts + 1):
            start = time.time()
            try:
                proc = subprocess.run(
                    [sys.executable, str(code_file), str(data_path)],
                    capture_output=True,
                    timeout=self.timeout_seconds,
                    text=True,
                    encoding="utf-8",
                )
                runtime = time.time() - start

                if proc.returncode != 0:
                    last_result = ExecutionResult(
                        success=False,
                        error_message=proc.stderr[:500],
                        failure_reason="code",
                        runtime_seconds=runtime,
                    )
                else:
                    try:
                        payload = json.loads(proc.stdout.strip())
                    except json.JSONDecodeError as e:
                        last_result = ExecutionResult(
                            success=False,
                            error_message=f"输出解析失败: {e}",
                            failure_reason="code",
                            runtime_seconds=runtime,
                        )
                    else:
                        success = payload.get("success", False)
                        last_result = ExecutionResult(
                            success=success,
                            numeric_outputs=payload.get("numeric_outputs", {}),
                            error_message=payload.get("error", ""),
                            failure_reason=payload.get("failure_reason", "") if not success else "",
                            runtime_seconds=runtime,
                            output_files=[str(code_file)],
                        )

                # G5 判定
                state = {
                    "execution_result": last_result.model_dump(),
                    "_g5_budget_used": attempt - 1,
                }
                gate_result = self.gate.evaluate(state)
                if gate_result.passed or gate_result.action in ("escalate", "human"):
                    break

            except subprocess.TimeoutExpired:
                last_result = ExecutionResult(
                    success=False,
                    error_message=f"执行超时（>{self.timeout_seconds}s）",
                    failure_reason="code",
                    runtime_seconds=self.timeout_seconds,
                )
                break

        return last_result or ExecutionResult(
            success=False, error_message="no result", failure_reason="code",
        )