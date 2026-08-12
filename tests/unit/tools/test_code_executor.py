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

    def test_relative_files_are_cleaned_with_the_execution_directory(
        self, tmp_path: Path, monkeypatch
    ):
        output_name = "temporary_result.txt"
        code = (
            "import json\n"
            f'open("{output_name}", "w", encoding="utf-8").write("ok")\n'
            'print("__MODEL_RESULT__" + json.dumps({"ok": True}))\n'
        )

        monkeypatch.chdir(tmp_path)
        assert execute_model_code(code) == {"ok": True}
        assert not (tmp_path / output_name).exists()

    def test_collects_model_generated_figures(self, tmp_path: Path):
        code = (
            "import json, os\n"
            "import matplotlib.pyplot as plt\n"
            "figure_path = os.path.join(os.environ['MODEL_FIGURE_DIR'], 'fit.png')\n"
            "plt.plot([0, 1], [0, 1])\n"
            "plt.savefig(figure_path)\n"
            "plt.close()\n"
            "print('__MODEL_RESULT__' + json.dumps({'objective': 1.0}))\n"
        )

        result = execute_model_code(
            code,
            figure_output_dir=tmp_path / "figures",
            figure_prefix="q1",
            require_figures=True,
        )

        assert len(result["figures"]) == 1
        assert Path(result["figures"][0]).is_file()

    def test_injects_chinese_matplotlib_font_config(self, tmp_path: Path):
        code = (
            "import json, os\n"
            "import matplotlib.pyplot as plt\n"
            "from matplotlib import rcParams\n"
            "rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']\n"
            "fig, ax = plt.subplots()\n"
            "ax.set_title('中文标题')\n"
            "ax.set_xlabel('时间')\n"
            "ax.set_ylabel('目标值')\n"
            "figure_path = os.path.join(os.environ['MODEL_FIGURE_DIR'], 'zh.png')\n"
            "fig.savefig(figure_path)\n"
            "plt.close(fig)\n"
            "result = {'fonts': list(rcParams['font.sans-serif'])[:4]}\n"
            "print('__MODEL_RESULT__' + json.dumps(result, ensure_ascii=False))\n"
        )

        result = execute_model_code(
            code,
            figure_output_dir=tmp_path / "figures",
            figure_prefix="q1",
            require_figures=True,
        )

        assert result["fonts"][0] == "Microsoft YaHei"
        assert "SimHei" in result["fonts"]
        assert len(result["figures"]) == 1
        assert Path(result["figures"][0]).is_file()

    def test_empty_code(self):
        with pytest.raises(CodeExecutionError, match="为空"):
            execute_model_code("   \n  ")
