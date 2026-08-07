"""LLM 生成的建模代码执行沙箱。

"任务驱动建模"计算层的执行端：在独立子进程中运行 LLM 生成的求解代码，
提供超时终止、结果解析与基本环境隔离。

设计约定（与模型生成 Prompt 对应）：
  - 生成代码必须是完整可运行的 Python 脚本
  - 数据 CSV 路径通过环境变量 ``MODEL_DATA_PATH`` 传入
  - 代码用 ``print("__MODEL_RESULT__" + json.dumps(result))`` 输出结果，
    其余 stdout 内容视为调试输出
  - 只允许数学计算：标准库 + numpy/pandas/scipy/sklearn/pulp

安全模型：
  - 独立子进程 + timeout 强制终止（防死循环/失控计算）
  - 清除常见 API 密钥环境变量（防泄漏）
  - 不提供网络/文件写入能力的显式授权（代码自带的库能力不在本层治理范围）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

#: 结果输出标记：``__MODEL_RESULT__<json>``
RESULT_MARKER = "__MODEL_RESULT__"

#: 常见敏感环境变量名（执行时从子进程环境中清除）
_SENSITIVE_ENV_KEYS = (
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
    "TAVILY_API_KEY", "SERPAPI_API_KEY", "GOOGLE_API_KEY",
    "AZURE_OPENAI_API_KEY", "GITHUB_TOKEN", "API_KEY", "SECRET",
)


class CodeExecutionError(Exception):
    """代码执行失败（语法错误、运行异常、超时或结果解析失败）。"""


def execute_model_code(
    code: str,
    data_csv_path: str | Path | None = None,
    timeout: int = 30,
) -> dict:
    """在子进程中执行生成的建模代码。

    Args:
        code: 完整可运行的 Python 脚本。
        data_csv_path: 数据 CSV 路径（经 ``MODEL_DATA_PATH`` 传入代码）。
        timeout: 执行超时秒数。

    Returns:
        从代码输出中解析出的结果字典（``__MODEL_RESULT__`` 标记后的 JSON）。

    Raises:
        CodeExecutionError: 语法错误、运行异常、超时、未输出结果标记或
                            JSON 无法解析。
    """
    code = _validate_code(code)

    # 写入临时脚本（避免命令行长度限制）
    tmp_script = None
    try:
        fd, tmp_script = tempfile.mkstemp(suffix=".py", prefix="mma_model_", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)

        env = _build_child_env(data_csv_path)

        try:
            proc = subprocess.run(
                [sys.executable, tmp_script],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise CodeExecutionError(
                f"代码执行超时（>{timeout}s），已强制终止。请减小计算规模或简化算法。"
            )

        if proc.returncode != 0:
            raise CodeExecutionError(_format_run_error(proc))

        return _parse_result(proc.stdout)
    finally:
        if tmp_script and os.path.exists(tmp_script):
            try:
                os.unlink(tmp_script)
            except OSError:
                pass


def _validate_code(code: str) -> str:
    """代码基本校验：非空、含结果输出标记。"""
    if not code or not code.strip():
        raise CodeExecutionError("生成的代码为空")
    if RESULT_MARKER not in code:
        raise CodeExecutionError(
            f"生成的代码未包含结果输出标记 {RESULT_MARKER}，"
            "请以 print('__MODEL_RESULT__' + json.dumps(result)) 结束"
        )
    return textwrap.dedent(code)


def _build_child_env(data_csv_path: str | Path | None) -> dict:
    """构建子进程环境：清除敏感变量，注入数据路径，固定 UTF-8 输出。"""
    env = {
        k: v
        for k, v in os.environ.items()
        if not any(s in k.upper() for s in _SENSITIVE_ENV_KEYS)
    }
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONNOUSERSITE"] = "1"
    if data_csv_path is not None:
        env["MODEL_DATA_PATH"] = str(data_csv_path)
    return env


def _format_run_error(proc: subprocess.CompletedProcess) -> str:
    """格式化运行错误（含最后一段 traceback 和 stdout 线索）。"""
    stderr = (proc.stderr or "").strip()
    stdout = (proc.stdout or "").strip()
    lines = stderr.splitlines()
    # 取最后 15 行 traceback
    tail = "\n".join(lines[-15:]) if lines else stderr
    msg = f"代码运行失败（exit={proc.returncode}）:\n{tail}"
    if stdout:
        msg += f"\n--- 执行输出 ---\n{stdout[-800:]}"
    return msg


def _parse_result(stdout: str) -> dict:
    """从 stdout 中解析 ``__MODEL_RESULT__<json>`` 结果。"""
    marker_idx = stdout.rfind(RESULT_MARKER)
    if marker_idx == -1:
        raise CodeExecutionError(
            "执行完成但未输出结果标记 __MODEL_RESULT__；"
            "请确认代码末尾调用 print('__MODEL_RESULT__' + json.dumps(result))"
        )
    payload = stdout[marker_idx + len(RESULT_MARKER):].strip()
    if not payload:
        raise CodeExecutionError("结果标记后无 JSON 内容")

    try:
        result = json.loads(payload)
    except json.JSONDecodeError as e:
        raise CodeExecutionError(
            f"结果 JSON 解析失败: {e}；输出片段: {payload[:200]}"
        )

    if not isinstance(result, dict):
        raise CodeExecutionError("结果必须是 JSON 对象（dict）")

    # 校验数值有限性：NaN/Infinity 会破坏后续指标计算
    _check_finite_values(result)
    return result


def _check_finite_values(result: dict) -> None:
    """递归检查结果中的数值均为有限值（float/int），否则报错。"""
    bad: list[str] = []

    def _walk(obj: object, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                _walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                _walk(v, f"{path}[{i}]")
        elif isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
            bad.append(path or "<root>")

    _walk(result)
    if bad:
        raise CodeExecutionError(
            "结果包含非有限数值（NaN/Inf）: " + ", ".join(bad[:10])
        )
