# AGENTS.md

本文件定义 MMAgent 项目中智能体的职责边界、协作流程、工具规范和代码约束。后续新增节点、工具或模型调用时，优先遵守本文件。

## 项目目标

MMAgent 是一个用于数学建模的智能体工具，主体基于 LangGraph 实现。系统目标不是让多个智能体自由对话，而是把数学建模过程拆成可追踪、可验证、可回滚的状态流。

核心能力：

- 解析数学建模题目，识别目标、变量、约束、数据需求和输出要求。
- 选择合适的建模路线，例如优化、预测、评价、仿真、统计分析、图论、微分方程或组合模型。
- 生成可执行 Python 代码，并保存中间产物。
- 执行、校验和修正模型结果。
- 输出图表、结论和建模报告。

## 技术约束

- 工作流编排使用 `langgraph`。
- LLM 调用封装在独立模块中，节点不要直接散落调用模型 API。
- 节点之间通过结构化 `State` 传递信息，不依赖纯自然语言上下文。
- 数据处理优先使用 `pandas`、`numpy`、`scipy`、`sympy`、`scikit-learn`、`statsmodels`。
- 优化建模可使用 `scipy.optimize`、`pulp`、`ortools`。
- 图表生成优先使用 `matplotlib` 或 `seaborn`。
- 文件读写、代码执行、图表生成等能力必须封装为 tools，不直接写在 agent prompt 中。

## 推荐目录

当前项目代码目录为 `scr/`。如后续重构，可统一迁移到 `src/mmagent/`。

```text
scr/
  graph/
    state.py          # 全局状态定义
    builder.py        # LangGraph 构图入口
    router.py         # 条件分支和循环控制

  nodes/
    problem_parser.py
    modeling_planner.py
    data_analyzer.py
    model_builder.py
    code_generator.py
    code_executor.py
    result_validator.py
    visualizer.py
    report_writer.py

  tools/
    file_io.py
    python_exec.py
    math_tools.py
    optimization.py
    plotting.py

  final_outputs/
    # 每次任务输出的报告、图表、代码和日志
```

## 全局状态规范

LangGraph 的 State 应该尽量稳定。新增字段前先确认是否可以复用已有字段。

建议字段：

```python
class ModelingState(TypedDict):
    problem_text: str
    problem_type: str | None
    objectives: list[str]
    variables: list[dict]
    constraints: list[str]
    assumptions: list[str]
    data_files: list[str]
    data_summary: dict | None
    model_plan: dict | None
    mathematical_model: dict | None
    generated_code: str | None
    execution_result: dict | None
    validation_result: dict | None
    figures: list[str]
    report_path: str | None
    errors: list[str]
    messages: list
```

状态设计原则：

- 节点只写入自己负责的字段。
- 不在 State 中保存大体积原始数据，保存文件路径和摘要。
- `errors` 用于记录可恢复错误，不直接吞掉异常。
- 所有产物路径必须可追踪到一次具体运行。

## 智能体节点职责

### problem_parser

职责：

- 解析原始题目。
- 抽取目标、变量、约束、已知条件、待求结果。
- 判断是否需要外部数据或用户上传数据。

不得：

- 直接选择最终模型。
- 编写求解代码。

### modeling_planner

职责：

- 根据题目类型选择建模路线。
- 给出候选模型和优先级。
- 判断是否需要数据分析、仿真、优化或机器学习。

输出要求：

- 模型路线必须包含理由。
- 对不确定性给出备选方案。

### data_analyzer

职责：

- 读取、清洗和摘要数据。
- 检查缺失值、异常值、字段类型、量纲和样本规模。
- 输出数据分析结论，不直接决定最终建模结果。

### model_builder

职责：

- 明确变量、参数、目标函数、约束条件。
- 将建模方案转成数学表达。
- 给出模型假设和适用范围。

### code_generator

职责：

- 生成可执行 Python 代码。
- 代码应包含必要输入、计算过程、结果保存和图表保存。
- 优先生成简单、可调试、依赖明确的代码。

不得：

- 生成需要人工交互的代码。
- 把 API key 或本地绝对隐私路径写入代码。

### code_executor

职责：

- 在受控环境中执行生成代码。
- 捕获 stdout、stderr、异常、输出文件路径。
- 不修改模型逻辑，只反馈执行结果。

### result_validator

职责：

- 检查代码是否成功运行。
- 检查结果是否满足约束、量纲和常识。
- 决定是否回退到 `model_builder` 或 `code_generator`。

### visualizer

职责：

- 生成图表。
- 图表必须有标题、坐标轴说明、图例或必要注释。
- 保存图表路径到 State。

### report_writer

职责：

- 输出数学建模报告。
- 报告应包含问题重述、假设、符号说明、模型建立、求解、结果分析、优缺点评价。
- 引用图表和代码产物路径。

## LangGraph 流程

推荐主流程：

```text
START
  -> problem_parser
  -> modeling_planner
  -> data_analyzer 或 model_builder
  -> model_builder
  -> code_generator
  -> code_executor
  -> result_validator
  -> visualizer
  -> report_writer
  -> END
```

推荐循环：

- 执行失败：`code_executor -> code_generator`
- 结果不合理：`result_validator -> model_builder`
- 数据不足：`data_analyzer -> problem_parser` 或请求补充输入

循环必须设置最大次数，避免无限重试。

## Prompt 规范

Prompt 应放在独立文件中，不要大段硬编码在节点逻辑里。

Prompt 输出优先使用结构化 JSON，字段必须和 State 对齐。

每个 Prompt 至少说明：

- 当前节点角色。
- 输入字段。
- 输出字段。
- 不允许做的事情。
- 失败时如何反馈。

## Tool 规范

工具函数必须满足：

- 输入输出清晰，尽量使用类型标注。
- 不直接依赖全局变量。
- 对文件路径做存在性检查。
- 对异常返回可诊断信息。
- 不在工具中调用 LLM。

代码执行工具必须额外满足：

- 设置运行超时。
- 捕获 stdout 和 stderr。
- 限制输出目录。
- 返回生成文件列表。

## 产物管理

每次运行建议创建独立目录：

```text
scr/final_outputs/<run_id>/
  input/
  data/
  code/
  figures/
  reports/
  logs/
```

命名建议：

- `solution.py`：最终求解代码。
- `execution.json`：执行结果。
- `validation.json`：校验结果。
- `report.md`：建模报告。
- `figures/`：图表文件。

## 质量要求

新增或修改功能时，应优先验证：

- 图能否成功构建。
- State 字段是否完整。
- 每个节点是否能单独运行。
- 失败路径是否能返回可读错误。
- 至少用一个简单数学建模题跑通端到端流程。

建议测试样例：

- 线性规划：生产计划、运输问题。
- 预测模型：时间序列或回归预测。
- 评价模型：TOPSIS、熵权法、层次分析法。
- 仿真模型：排队、蒙特卡洛。

## 开发原则

- 先做可运行的最小闭环，再扩展复杂能力。
- 节点职责保持单一。
- 复杂逻辑放到普通 Python 函数中，节点只负责读写 State。
- 工具和节点分离，避免 prompt 里承载业务逻辑。
- 可验证结果优先于漂亮表述。
- 对数学假设、模型适用范围和结果局限必须显式说明。

## 禁止事项

- 不要让 LLM 直接执行任意用户代码。
- 不要在仓库中提交真实 API key、账号、数据隐私文件。
- 不要让多个 agent 修改同一个 State 字段而没有明确合并规则。
- 不要把一次性实验代码混入核心节点。
- 不要为了增加智能体数量而拆分职责不清的节点。

## 当前优先级

1. 建立 LangGraph 最小闭环。
2. 完成题目解析、建模规划、代码生成、执行和报告输出。
3. 增加结果校验和失败回退。
4. 增加数据文件读取与图表生成。
5. 增加 Web UI 或 API 服务。
