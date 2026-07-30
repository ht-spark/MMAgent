# MMAgent

面向数学建模竞赛的智能体工作流。MMAgent 将题目文档与附件数据组织为一个可复现的解题过程：先理解问题和数据，再按小问递进完成方法选择、计算、验证与结果沉淀，最后生成论文草稿与交付材料。

它的目标不是机械地选择复杂模型，而是在竞赛约束下形成**题意匹配、数据可信、计算可复现、结论可解释**的建模方案。

## 工作流

```text
题目文档 + 附件数据
        |
        v
读取全部文件与 Sheet，生成数据画像
        |
        v
理解背景、拆分小问、建立依赖与题目-数据映射
        |
        v
按小问递进求解
  理解要求 -> 方法探索 -> 方法决策 -> 建模计算 -> 验证
        |
        v
每问生成结果包，供后续小问选择性复用
        |
        v
全题一致性审查 -> 论文写作 -> 格式审查 -> 交付
```

后续小问不会接收前题的全部推理记录，只接收经过验证且与当前问题有关的结论、数据、模型接口、限制和可改进方向。这使题目能够逐问推进，也避免错误或无关信息持续传播。

## 核心原则

- **先理解再建模**：明确题目目标、约束、输出和数据口径后才开始选法。
- **按小问闭环**：每问都完成“理解、选法、计算、验证、沉淀”，而不是全题一次性选模。
- **数据约束方法**：所有附件和 Excel Sheet 都要画像；字段、样本量、时间维度和质量决定方法是否可用。
- **数值由代码生成**：LLM 用于推理、方案和解释，最终数值、图表和表格必须来自可复跑的工具或代码。
- **验证是必经步骤**：根据题型进行误差、可行性、敏感性、稳定性或基线比较，不能只给出计算结果。
- **后题选择性继承前题**：可复用前问结论，也可以将前问模型作为基线或改进对象。
- **论文只使用已验证成果**：外部事实、计算数值、图表和方法选择都应可追溯。

## 当前状态

仓库中已有一个可运行的原型，包含题目与文件读取、数据画像、题目理解、方法研究和模型选择的基础模块，以及数据处理、求解、论文写作、审查和交付的演示流程。

当前代码仍保留旧的 L0-L6 演示编排；项目正按新的“逐问闭环”架构重构。新架构是后续实现的唯一目标，详见：

- [系统架构](architecture.md)
- [执行计划](plan.md)

## 支持的输入与产物

### 输入

- 题目文本或 UTF-8 文本文件
- CSV、Excel、JSON 等数据文件
- 多份附件；Excel 自动遍历全部 Sheet
- 可选的 OpenAI 兼容 LLM 配置，用于题目理解、方法探索和论文表达

### 产物

每次运行会在 `artifacts/<run_id>/` 下保存独立产物。目标结构如下：

```text
artifacts/<run_id>/
  input/                 # 题目与附件登记
  context/               # 题目理解、数据画像、依赖图
  questions/Q1/          # 本问代码、结果、图表、验证与结论
  questions/Q2/
  evidence/              # 检索来源与引用信息
  paper/                 # 论文草稿与参考文献
  review/                # 全题和格式审查报告
  final/                 # 最终论文、代码、图表、提交清单
```

## 快速开始

### 环境要求

- Python 3.11 或更高版本
- 推荐使用 [uv](https://docs.astral.sh/uv/) 管理依赖
- 可选：OpenAI 或兼容接口的 API Key

### 安装依赖

```bash
uv sync
```

也可以使用标准虚拟环境：

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
pip install -e .
```

### 配置 LLM（可选）

在项目根目录创建 `.env`：

```ini
OPENAI_API_KEY=your-api-key
MODEL_NAME=gpt-4o
OPENAI_BASE_URL=
```

也支持 DeepSeek 的 OpenAI 兼容接口：

```ini
DEEPSEEK_API_KEY=your-api-key
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

未配置 LLM 时可以添加 `--no-llm` 运行演示路径，但它会使用占位分析与模型，不能代表真实竞赛解题效果。

### 运行当前原型

当前源码位于 `scr/` 目录，使用以下命令运行：

```bash
uv run python -m scr.math_modeling_agent.main run \
  --problem examples/problem.md \
  --data examples/附件1.xlsx examples/附件2.xlsx
```

使用 LangGraph 演示编排：

```bash
uv run python -m scr.math_modeling_agent.main run-graph \
  --problem examples/problem.md \
  --data examples/附件1.xlsx examples/附件2.xlsx
```

不调用 LLM 的演示模式：

```bash
uv run python -m scr.math_modeling_agent.main run \
  --problem examples/problem.md \
  --data examples/附件1.xlsx \
  --no-llm
```

### 运行测试

```bash
uv run pytest
```

## 开发路线

开发遵循“先完成可信闭环，再扩展能力”的顺序：

1. **基础与输入理解**：Schema、运行产物、题目解析、多 Sheet 数据画像、小问依赖和题目-数据映射。
2. **逐问求解循环**：当前小问上下文、选择性继承、结果包、局部回退。
3. **方法探索与决策**：题型规则库、受控检索、候选比较、数据与假设过滤。
4. **确定性计算与验证**：评价、回归、规划等工具，配套可视化与题型验证。
5. **论文与交付**：全题一致性审查、论文生成、引用追溯、格式审查和提交清单。
6. **端到端加固**：真实样题、断点恢复、缓存复用、预算控制和能力扩展。

第一版优先覆盖多指标评价、回归预测和优化决策；复杂深度学习、自动多智能体协商和高级格式排版不阻塞主流程。

## 项目结构

```text
scr/
  math_modeling_agent/   # 命令行入口、图编排、配置与状态
  agents/                # 题目理解、研究、选模等结构化推理模块
  gates/                 # 输入、决策、数据、结果等质量检查
  layers/                # 当前原型的工作流节点
  schemas/               # Pydantic 数据契约
  tools/                 # 文件读取、数据画像等确定性工具
  prompts/               # 结构化输出提示词
tests/                   # 单元和流程测试
examples/                # 题目与附件样例
architecture.md          # 目标架构说明
plan.md                  # 实施计划与验收标准
```

> `scr` 是当前仓库已有的源码目录名称。后续是否迁移为标准 `src` 布局，应作为独立的结构调整处理，避免与工作流重构混在一起。

## 文档

- [architecture.md](architecture.md)：逐问闭环的目标架构、状态、质量门、模块职责与交付规范。
- [plan.md](plan.md)：MVP 范围、阶段任务、测试与验收标准。
- [LICENSE](LICENSE)：许可证信息。
