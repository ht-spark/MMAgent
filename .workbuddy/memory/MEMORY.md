# MMAgent 项目长期记忆

## 项目概况
数学建模智能体，七层子图 + 门控闭环架构（见 architecture.md / plan.md）。
Python 3.13，依赖：langgraph, pandas, numpy, scipy, scikit-learn, pydantic, pulp 等。

## 目录结构注意事项
- 实际代码目录是 `scr/`（非 plan.md 中写的 `src/math_modeling_agent/`）
- `scr/` 下直接有 schemas/ tools/ layers/ math_modeling_agent/ 等同级包
- 导入用 `from scr.tools.xxx import ...` 或包内相对导入 `from ..schemas.xxx import ...`
- 旧文件 `scr/tools/file._tools.py` 含点号无法被 Python 导入，实际实现已迁移到 `file_tools.py`

## Python 环境
- Managed venv: `C:\Users\merit\.workbuddy\binaries\python\envs\default`
- 依赖需用清华镜像安装：`pip install xxx -i https://pypi.tuna.tsinghua.edu.cn/simple`
- 运行测试：`cd D:\MMAgent && python -m pytest tests/ -v`
- pyproject.toml 已配置 pythonpath=["."] 和 testpaths=["tests"]

## 确定性 Tool 构建流程（六步）
1. Schema 定义（schemas/xxx.py）— Pydantic 数据契约
2. 工具实现（tools/xxx_tools.py）— 纯函数，不依赖 LLM
3. 单元测试（tests/unit/tools/）— 已知答案 + 边界情况
4. 接入子图节点（layers/lN_xxx.py）— 节点调用工具，返回部分 State
5. Gate 校验（gates/gN_xxx.py）— 结果合法性 + 作用域回退
6. 产物落盘（artifacts/<run_id>/）— State 只存路径

## 已完成进度
- Phase 1 部分：schemas/{problem,common,research}.py（DataField, DataInventory, ProblemAnalysis, SubProblem, ProblemClassification, GateResult, KnowledgeGap, SearchRequest, EvidenceItem）
- Phase 3 部分：tools/file_tools.py（CSV/Excel/MD 读取 + data_inventory 画像）
- Phase 3 部分：agents/problem_analyst.py（understand/decompose/classify + BaseAgent 基类）
- Phase 3 部分：layers/l0_understanding.py（L0 子图 + G1 重试逻辑）
- Phase 3 部分：gates/g1_understanding.py（小问完整 + DAG 校验 + 主类型齐备）
- Phase 4 部分：agents/research_agent.py（identify_gaps / plan_queries / extract_evidence）
- Phase 3+4 部分：prompts/（problem_analysis.md, task_decomposition.md, problem_classification.md, knowledge_gap.md, query_planner.md, evidence_extraction.md）
- 101 个单元测试全部通过

## Gate 模式
- GateResult: gate_id / passed / failed_checks / action(pass|retry|escalate|human) / budget_used / budget_remaining
- 预算机制：max_budget=2，`budget_used <= max_budget → retry`，否则 human
- DAG 校验：DFS + 三色标记（WHITE/GRAY/BLACK），遇到 GRAY 节点判定有环

## Agent 构建模式
- BaseAgent 支持 LLM 注入：测试用 FakeLLM（实现 with_structured_output + invoke），生产从环境变量创建 ChatOpenAI
- prompt 模板用 {var} 占位符，_render_prompt 逐个替换（不影响 JSON 示例中的 {}）
- 返回 list 的方法用包装类（如 SubProblemList）适配 with_structured_output
- Prompt 与代码分离：模板存 prompts/*.md，Agent 加载后渲染
