"""code_executor 沙箱单元测试。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scr.tools.code_executor import CodeExecutionError, execute_model_code


class TestExecuteModelCode:
    def test_normal_execution(self):
        code = (
            'import json\n'
            'result = {"solution": [1.0, 2.0], "objective": 3.0, '
            '"metrics": {"n": 2}}\n'
            'print("__MODEL_RESULT__" + json.dumps(result))\n'
        )
        result = execute_model_code(code)
        assert result["solution"] == [1.0, 2.0]
        assert result["objective"] == 3.0
        assert result["metrics"]["n"] == 2

    def test_syntax_error(self):
        with pytest.raises(CodeExecutionError, match="运行失败|未包含"):
            execute_model_code("def broken(:\n")

    def test_runtime_error(self):
        code = (
            "import json\n"
            'print("__MODEL_RESULT__" + json.dumps({"x": 1/0}))\n'
        )
        with pytest.raises(CodeExecutionError, match="运行失败"):
            execute_model_code(code)

    def test_missing_result_marker(self):
        with pytest.raises(CodeExecutionError, match="__MODEL_RESULT__"):
            execute_model_code('print("hello")\n')

    def test_nan_rejected(self):
        code = (
            "import json, math\n"
            'print("__MODEL_RESULT__" + json.dumps({"x": float("nan")}))\n'
        )
        with pytest.raises(CodeExecutionError, match="NaN"):
            execute_model_code(code)

    def test_reads_data_from_env(self, tmp_path: Path):
        csv_path = tmp_path / "data.csv"
        pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]}).to_csv(csv_path, index=False)
        code = (
            "import os, json, pandas as pd\n"
            'df = pd.read_csv(os.environ["MODEL_DATA_PATH"])\n'
            'print("__MODEL_RESULT__" + json.dumps('
            '{"rows": int(len(df)), "cols": int(df.shape[1])}))\n'
        )
        result = execute_model_code(code, data_csv_path=csv_path)
        assert result == {"rows": 3, "cols": 2}

    def test_timeout_killed(self):
        code = (
            "import json\n"
            "while True: pass\n"
            'print("__MODEL_RESULT__" + json.dumps({"x": 1}))\n'
        )
        with pytest.raises(CodeExecutionError, match="超时"):
            execute_model_code(code, timeout=3)

    def test_empty_code(self):
        with pytest.raises(CodeExecutionError, match="为空"):
            execute_model_code("   \n  ")
