# 数学建模智能体 Workflow 设计稿

> 目标：把“数学建模比赛流程”转化为可编排的智能体工作流，使智能体能够从题目理解开始，逐步完成任务拆解、数据处理、建模求解、结果分析、论文写作、论文审查与最终提交准备。

---

## 1. Workflow 总览

数学建模智能体的主流程建议设计为：

```text
题目输入
  ↓
题目理解节点
  ↓
任务拆解节点
  ↓
题型识别节点
  ↓
数据与资料规划节点
  ↓
模型方案生成节点
  ↓
模型选择与确认节点
  ↓
分问题建模求解节点
  ↓
结果分析节点
  ↓
模型检验节点
  ↓
论文生成节点
  ↓
论文审查节点
  ↓
修改迭代节点
  ↓
最终交付节点
```

核心思想：

> 先理解题目，再拆解任务；先确定数据和模型路线，再求解；先验证结果，再写论文；最后通过审查节点形成闭环。

---

## 2. 推荐智能体角色

建议采用“主控智能体 + 多个专业子智能体”的结构。

| 智能体 | 职责 | 主要输出 |
|---|---|---|
| 主控智能体 Orchestrator | 控制整体流程、维护状态、决定路由 | workflow 状态、下一步任务 |
| 题目理解智能体 Problem Understanding Agent | 解析题目背景、目标和约束 | 问题摘要、关键词、目标清单 |
| 任务拆解智能体 Task Decomposition Agent | 将题目拆成多个子问题 | 子任务列表、输入输出关系 |
| 数据规划智能体 Data Planning Agent | 判断需要哪些数据、是否需要预处理 | 数据需求表、预处理方案 |
| 建模方案智能体 Modeling Strategy Agent | 根据题型推荐模型方案 | 候选模型、模型理由 |
| 模型求解智能体 Solver Agent | 写代码、运行模型、输出结果 | 代码、图表、数值结果 |
| 结果分析智能体 Result Analysis Agent | 解释结果含义 | 结果解释、结论草稿 |
| 模型检验智能体 Validation Agent | 做误差、敏感性、稳健性分析 | 检验报告、问题反馈 |
| 论文写作智能体 Paper Writing Agent | 生成论文各章节 | 论文初稿 |
| 论文审查智能体 Review Agent | 检查完整性、一致性和格式 | 审查清单、修改建议 |
| 交付智能体 Final Packaging Agent | 整理最终文件和附录 | 最终论文、代码、图表清单 |

---

## 3. 全局状态 State 设计

建议让主控智能体维护一个统一状态对象。

```python
class MathModelingState:
    problem_text: str
    competition_rules: dict

    problem_summary: str
    keywords: list[str]
    problem_goals: list[str]
    constraints: list[str]

    subproblems: list[dict]
    problem_types: list[str]

    data_requirements: list[dict]
    available_data: list[dict]
    preprocessing_plan: list[str]
    processed_data_paths: list[str]

    assumptions: list[str]
    symbols: dict

    model_candidates: list[dict]
    selected_models: list[dict]
    model_formulas: list[str]

    code_files: list[str]
    result_tables: list[str]
    figures: list[str]
    numerical_results: list[dict]

    result_analysis: list[str]
    validation_report: dict

    paper_outline: list[str]
    paper_draft: str
    review_report: dict
    revision_tasks: list[dict]

    final_files: list[str]
    workflow_status: str
```

核心原则：

```text
每个节点只负责更新一部分 State；
每个节点的输出必须能被下一个节点直接使用；
审查节点发现问题后，要能路由回对应节点修改。
```

---

## 4. 节点级 Workflow 设计

### Node 1：题目理解节点

#### 输入

```text
problem_text
competition_rules
```

#### 处理任务

- 提取题目背景；
- 提取研究对象；
- 提取所有小问；
- 提取显式约束；
- 判断最终需要输出的结果；
- 标记关键词。

#### 输出

```json
{
  "problem_summary": "题目简要说明",
  "keywords": ["评价", "预测", "优化"],
  "problem_goals": ["目标1", "目标2"],
  "constraints": ["约束1", "约束2"],
  "expected_outputs": ["排名", "预测值", "优化方案"]
}
```

#### 推荐提示词

```text
你是数学建模比赛题目理解智能体。请阅读题目，提取研究对象、背景、所有小问、约束条件、关键词和最终输出要求。不要建模，只做题目理解。
```

---

### Node 2：任务拆解节点

#### 输入

```text
problem_summary
problem_goals
expected_outputs
```

#### 处理任务

- 将题目拆成若干子问题；
- 为每个子问题明确输入、处理方法和输出；
- 判断各子问题之间的依赖关系；
- 形成论文主线。

#### 输出

```json
{
  "subproblems": [
    {
      "id": "Q1",
      "task": "建立评价指标体系",
      "input": ["指标数据"],
      "output": ["综合得分", "排名"],
      "depends_on": []
    }
  ]
}
```

#### 推荐提示词

```text
你是任务拆解智能体。请将数学建模题目拆解为可执行子任务。每个子任务必须包含任务目标、输入数据、处理步骤、输出结果和依赖关系。
```

---

### Node 3：题型识别节点

#### 输入

```text
subproblems
keywords
```

#### 处理任务

判断每个子问题属于哪类建模问题：

- 评价类；
- 预测类；
- 优化类；
- 分类类；
- 仿真类；
- 机理分析类；
- 综合类。

#### 输出

```json
{
  "problem_types": [
    {
      "subproblem_id": "Q1",
      "type": "评价类",
      "reason": "需要建立指标体系并进行综合评分"
    }
  ]
}
```

#### 推荐提示词

```text
你是题型识别智能体。请根据每个子问题的目标、关键词和输出结果，判断其数学建模类型，并说明判断依据。
```

---

### Node 4：数据与资料规划节点

#### 输入

```text
subproblems
problem_types
available_data
```

#### 处理任务

- 判断每个子问题需要哪些数据；
- 判断题目数据是否足够；
- 设计数据预处理流程；
- 给出指标构造方案；
- 标记可能缺失的数据。

#### 输出

```json
{
  "data_requirements": [
    {
      "subproblem_id": "Q1",
      "required_data": ["指标A", "指标B"],
      "source": "题目附件或外部资料",
      "preprocessing": ["缺失值处理", "标准化", "正向化"]
    }
  ]
}
```

#### 推荐提示词

```text
你是数据规划智能体。请根据子问题和题型，列出所需数据、数据来源、预处理方法、指标构造方法和潜在数据风险。
```

---

### Node 5：模型方案生成节点

#### 输入

```text
subproblems
problem_types
data_requirements
```

#### 处理任务

为每个子问题生成 2 到 3 个候选模型。

示例：

| 题型 | 候选模型 |
|---|---|
| 评价类 | 熵权法、TOPSIS、AHP、PCA |
| 预测类 | 回归分析、ARIMA、灰色预测、机器学习 |
| 优化类 | 线性规划、整数规划、遗传算法、粒子群算法 |
| 分类类 | Logistic 回归、SVM、随机森林 |
| 仿真类 | 蒙特卡洛模拟、微分方程、元胞自动机 |

#### 输出

```json
{
  "model_candidates": [
    {
      "subproblem_id": "Q1",
      "candidate_models": [
        {
          "name": "熵权 TOPSIS",
          "reason": "适合多指标综合评价，主观性较低",
          "difficulty": "中",
          "interpretability": "强"
        }
      ]
    }
  ]
}
```

#### 推荐提示词

```text
你是建模方案智能体。请为每个子问题提出候选模型，说明适用原因、输入数据、输出结果、优点、缺点和实现难度。
```

---

### Node 6：模型选择与确认节点

#### 输入

```text
model_candidates
competition_time_limit
team_capability
```

#### 处理任务

- 对候选模型进行比较；
- 选择主模型；
- 必要时选择对比模型；
- 输出完整技术路线。

#### 输出

```json
{
  "selected_models": [
    {
      "subproblem_id": "Q1",
      "main_model": "熵权 TOPSIS",
      "comparison_model": "AHP TOPSIS",
      "reason": "兼顾客观权重和综合评价"
    }
  ],
  "technical_route": "数据预处理 → 熵权法求权重 → TOPSIS 评分 → 排名分析 → 灵敏度检验"
}
```

#### 推荐提示词

```text
你是模型选择智能体。请从候选模型中选择最适合比赛场景的模型。优先考虑模型合理性、可解释性、实现难度、论文表达和时间成本。
```

---

### Node 7：分问题建模求解节点

#### 输入

```text
selected_models
processed_data_paths
assumptions
symbols
```

#### 处理任务

- 写出模型公式；
- 定义变量和参数；
- 生成求解代码；
- 运行模型；
- 输出结果表和图表；
- 记录核心代码。

#### 输出

```json
{
  "model_formulas": ["公式1", "公式2"],
  "code_files": ["q1_model.py"],
  "result_tables": ["q1_result.csv"],
  "figures": ["q1_ranking.png"],
  "numerical_results": [
    {
      "subproblem_id": "Q1",
      "key_result": "A 城市得分最高"
    }
  ]
}
```

#### 推荐提示词

```text
你是模型求解智能体。请根据选定模型建立数学表达，生成可运行代码，输出计算结果、图表和关键结论。代码结果必须能对应论文中的数据。
```

---

### Node 8：结果分析节点

#### 输入

```text
numerical_results
result_tables
figures
```

#### 处理任务

- 解释主要结果；
- 分析排名、趋势或优化方案；
- 找出影响因素；
- 给出实际意义；
- 形成论文中的结果分析段落。

#### 输出

```json
{
  "result_analysis": [
    {
      "subproblem_id": "Q1",
      "analysis": "A 城市综合得分最高，主要原因是……"
    }
  ]
}
```

#### 推荐提示词

```text
你是结果分析智能体。请基于模型输出结果，解释数字和图表的实际含义，说明主要发现、影响因素和现实意义。不要只复述数值。
```

---

### Node 9：模型检验节点

#### 输入

```text
selected_models
numerical_results
result_tables
figures
```

#### 处理任务

根据模型类型选择检验方法。

| 模型类型 | 检验方法 |
|---|---|
| 评价模型 | 灵敏度分析、权重扰动、排序稳定性 |
| 预测模型 | MAE、RMSE、MAPE、残差分析 |
| 优化模型 | 约束检查、参数扰动、方案对比 |
| 分类模型 | 准确率、召回率、F1、混淆矩阵 |
| 仿真模型 | 多次仿真、参数敏感性、结果稳定性 |

#### 输出

```json
{
  "validation_report": {
    "passed": true,
    "checks": [
      "结果稳定",
      "误差可接受",
      "参数扰动后结论不变"
    ],
    "problems": []
  }
}
```

#### 推荐提示词

```text
你是模型检验智能体。请根据模型类型选择合适的检验方式，判断结果是否可靠。如果发现问题，请指出问题原因并建议回到哪个节点修改。
```

---

### Node 10：论文生成节点

#### 输入

```text
problem_summary
subproblems
assumptions
symbols
model_formulas
numerical_results
result_analysis
validation_report
figures
```

#### 处理任务

生成完整论文初稿。

建议结构：

```text
1. 摘要
2. 问题重述
3. 问题分析
4. 模型假设
5. 符号说明
6. 数据预处理
7. 模型建立与求解
8. 结果分析
9. 模型检验
10. 模型评价与推广
11. 参考文献
12. 附录
```

#### 输出

```json
{
  "paper_outline": ["摘要", "问题重述", "问题分析", "..."],
  "paper_draft": "完整论文初稿"
}
```

#### 推荐提示词

```text
你是数学建模论文写作智能体。请根据已有建模过程、结果、图表和检验报告，生成结构完整、逻辑清晰、语言规范的数学建模论文初稿。
```

---

### Node 11：论文审查节点

#### 输入

```text
paper_draft
model_formulas
numerical_results
figures
competition_rules
```

#### 处理任务

对论文做最终审查。

审查维度：

| 审查类型 | 检查内容 |
|---|---|
| 完整性审查 | 是否回答所有问题 |
| 逻辑审查 | 问题分析、模型、结果是否连贯 |
| 数据审查 | 数据、表格、代码输出是否一致 |
| 公式审查 | 变量、公式、符号是否统一 |
| 图表审查 | 标题、编号、单位、清晰度 |
| 语言审查 | 是否有错别字、口语化和重复 |
| 格式审查 | 是否符合比赛论文格式 |
| 提交审查 | 文件命名、附件、代码和最终版本 |

#### 输出

```json
{
  "review_report": {
    "passed": false,
    "critical_issues": [
      {
        "issue": "问题二结果缺少误差检验",
        "route_to": "模型检验节点",
        "priority": "high"
      }
    ],
    "minor_issues": [
      {
        "issue": "图 3 缺少单位",
        "route_to": "论文生成节点",
        "priority": "low"
      }
    ]
  }
}
```

#### 推荐提示词

```text
你是论文审查智能体。请从完整性、逻辑、数据、公式、图表、语言、格式和提交要求八个方面审查论文。发现问题时，必须指出问题位置、严重程度和应返回修改的节点。
```

---

### Node 12：修改迭代节点

#### 输入

```text
review_report
workflow_state
```

#### 处理任务

根据审查结果决定返回哪个节点。

#### 路由规则

```text
题目理解错误 → 返回题目理解节点
任务遗漏 → 返回任务拆解节点
数据问题 → 返回数据与资料规划节点
模型不合适 → 返回模型方案生成节点
结果异常 → 返回分问题建模求解节点
缺少检验 → 返回模型检验节点
论文表达问题 → 返回论文生成节点
格式问题 → 返回论文审查节点局部修正
全部通过 → 进入最终交付节点
```

#### 输出

```json
{
  "revision_tasks": [
    {
      "target_node": "模型检验节点",
      "task": "补充问题二预测误差检验",
      "priority": "high"
    }
  ]
}
```

---

### Node 13：最终交付节点

#### 输入

```text
paper_draft
code_files
figures
result_tables
review_report
```

#### 处理任务

- 生成最终论文；
- 整理代码文件；
- 整理图表和结果表；
- 检查文件命名；
- 保存最终版本；
- 生成提交清单。

#### 输出

```json
{
  "final_files": [
    "paper_final.docx",
    "appendix_code.zip",
    "result_tables.zip"
  ],
  "submit_checklist": [
    "论文可正常打开",
    "编号信息正确",
    "图表完整",
    "代码已保存",
    "格式符合要求"
  ],
  "workflow_status": "ready_to_submit"
}
```

---

## 5. LangGraph 风格 Workflow 编排示例

如果使用 LangGraph，可以将节点抽象为以下结构。

```python
workflow.add_node("understand_problem", understand_problem)
workflow.add_node("decompose_tasks", decompose_tasks)
workflow.add_node("classify_problem_type", classify_problem_type)
workflow.add_node("plan_data", plan_data)
workflow.add_node("generate_model_candidates", generate_model_candidates)
workflow.add_node("select_model", select_model)
workflow.add_node("solve_model", solve_model)
workflow.add_node("analyze_results", analyze_results)
workflow.add_node("validate_model", validate_model)
workflow.add_node("write_paper", write_paper)
workflow.add_node("review_paper", review_paper)
workflow.add_node("revise", revise)
workflow.add_node("final_package", final_package)
```

基础边：

```python
workflow.add_edge("understand_problem", "decompose_tasks")
workflow.add_edge("decompose_tasks", "classify_problem_type")
workflow.add_edge("classify_problem_type", "plan_data")
workflow.add_edge("plan_data", "generate_model_candidates")
workflow.add_edge("generate_model_candidates", "select_model")
workflow.add_edge("select_model", "solve_model")
workflow.add_edge("solve_model", "analyze_results")
workflow.add_edge("analyze_results", "validate_model")
workflow.add_edge("validate_model", "write_paper")
workflow.add_edge("write_paper", "review_paper")
```

条件边：

```python
def route_after_review(state):
    report = state["review_report"]

    if report["passed"]:
        return "final_package"

    issue = report["critical_issues"][0]

    route_map = {
        "problem_understanding": "understand_problem",
        "task_decomposition": "decompose_tasks",
        "data": "plan_data",
        "model": "generate_model_candidates",
        "solver": "solve_model",
        "validation": "validate_model",
        "writing": "write_paper",
        "format": "write_paper"
    }

    return route_map.get(issue["route_type"], "write_paper")
```

```python
workflow.add_conditional_edges(
    "review_paper",
    route_after_review,
    {
        "understand_problem": "understand_problem",
        "decompose_tasks": "decompose_tasks",
        "plan_data": "plan_data",
        "generate_model_candidates": "generate_model_candidates",
        "solve_model": "solve_model",
        "validate_model": "validate_model",
        "write_paper": "write_paper",
        "final_package": "final_package"
    }
)
```

---

## 6. 推荐的 Workflow 闭环

数学建模智能体不应是单向流水线，而应有审查闭环。

```text
建模求解失败
  → 返回模型选择节点或数据规划节点

结果不合理
  → 返回模型求解节点或模型方案节点

缺少检验
  → 返回模型检验节点

论文逻辑断裂
  → 返回任务拆解节点或论文生成节点

格式不符合要求
  → 返回论文生成节点

全部通过
  → 最终交付
```

---

## 7. 最小可用版本 MVP Workflow

如果先做一个简单版本，建议保留 7 个节点：

```text
1. 题目理解
2. 任务拆解
3. 模型推荐
4. 模型求解
5. 结果分析
6. 论文生成
7. 论文审查
```

对应结构：

```text
ProblemInput
  → UnderstandProblem
  → DecomposeTasks
  → RecommendModels
  → SolveModels
  → AnalyzeResults
  → WritePaper
  → ReviewPaper
  → FinalOutput
```

---

## 8. 增强版 Workflow

如果要做更完整的数学建模智能体，建议使用增强版：

```text
题目理解
  → 任务拆解
  → 题型识别
  → 数据规划
  → 数据预处理
  → 模型候选生成
  → 模型选择
  → 公式生成
  → 代码生成
  → 代码运行
  → 结果分析
  → 模型检验
  → 摘要生成
  → 论文生成
  → 论文审查
  → 修改迭代
  → 最终交付
```

---

## 9. 人机协作检查点

建议在以下位置加入人工确认。

| 检查点 | 是否建议人工确认 | 原因 |
|---|---|---|
| 选题后 | 是 | 避免方向错误 |
| 模型选择后 | 是 | 避免模型过难或不适合 |
| 主要结果生成后 | 是 | 判断结果是否符合现实 |
| 论文初稿后 | 是 | 检查表达和比赛要求 |
| 最终提交前 | 必须 | 避免格式或文件错误 |

---

## 10. 每个节点的标准输出要求

为了让 workflow 稳定运行，每个节点输出应遵循统一规范。

```json
{
  "node_name": "节点名称",
  "status": "success | failed | need_human_review",
  "input_summary": "输入摘要",
  "output": {},
  "issues": [],
  "next_node": "下一节点"
}
```

如果节点失败，必须输出：

```json
{
  "status": "failed",
  "issues": [
    {
      "type": "data_missing | model_error | logic_error | code_error | writing_error",
      "description": "问题描述",
      "suggested_fix": "建议修正方式"
    }
  ],
  "next_node": "建议返回节点"
}
```

---

## 11. 数学建模智能体最终输出

最终输出不应只有论文，而应包括完整交付包。

```text
1. 最终论文
2. 模型说明
3. 数据处理说明
4. 代码文件
5. 结果表格
6. 图表文件
7. 审查报告
8. 提交清单
```

---

## 12. 推荐最终 Workflow

综合考虑可实现性和比赛需求，推荐使用以下 workflow：

```text
Start
  ↓
题目理解 Agent
  ↓
任务拆解 Agent
  ↓
题型识别 Agent
  ↓
数据规划 Agent
  ↓
模型方案 Agent
  ↓
模型选择 Agent
  ↓
建模求解 Agent
  ↓
结果分析 Agent
  ↓
模型检验 Agent
  ↓
论文写作 Agent
  ↓
论文审查 Agent
  ↓
是否通过审查？
      ├── 否：修改迭代 Agent → 返回对应节点
      └── 是：最终交付 Agent
  ↓
End
```

---

## 13. 设计原则

1. **题目理解先于建模。**
2. **任务拆解先于模型选择。**
3. **数据规划先于代码求解。**
4. **结果分析不能只输出数字。**
5. **模型检验必须进入 workflow。**
6. **论文审查必须能路由回前面节点。**
7. **最终输出必须包含论文、代码、图表和审查清单。**

---

## 14. 一句话总结

数学建模智能体的 workflow 应该设计成：

> **以题目理解为起点，以任务拆解为骨架，以模型求解为核心，以论文生成为交付，以论文审查为闭环。**
