# Repository Guidelines

### 项目目标和功能

    目标：这是一个数学建模智能体，目标是实现面向具体任务的自动化数学建模

    功能：通过用户提交的问题和附件资料，全流程自动化完成建模、执行和生成最终交付报告。

### 项目核心设定

    1、该智能体一定是面向通用数学建模任务，所有提出的优化或者修改错误均需要基于通用性考虑，不能为了一个具体的问题做局限性的修改；

    2、智能体的核心是建模，建模的核心是建立准确合理的模型，本智能体项目的所有建模工作流均基于LLM-only策略，不做方法预设，不对问题进行分类，然后基于类别用僵化的方法，本智能体的策略是LLM驱动建模，是聚焦于问题本身的建模，需要具体问题具体分析。

## Coding Style & Naming Conventions

Use Python 3.11+, four-space indentation, `snake_case` for modules/functions/variables, `PascalCase` for classes, and `UPPER_CASE` for constants. Add type annotations and Google-style docstrings to public Python functions. Keep imports ordered: standard library, third-party, then project modules. Prefer `logging` over `print`, catch specific exceptions, and keep prompts under `scr/prompts/` rather than embedding large prompt strings in code.

Use TypeScript/React components in `PascalCase`; keep page-specific styles in `web/src/forms.css` and avoid unrelated CSS rewrites. Follow existing formatting; this repository does not currently enforce Black, isort, or ESLint through scripts.

## Testing Guidelines

Write `pytest` tests named `test_<behavior>.py` or `test_<behavior>` and cover malformed LLM/tool output at schema boundaries. Add a regression test for every bug fix. Mock LLM and network calls; tests must not require API keys. Run the focused test first, then the relevant suite, and run `npm run build` after frontend changes.

## Configuration & Safety

Store local provider settings in `.env` and frontend-only API settings in browser storage. Validate file paths before writing under `artifacts/`, and preserve the existing allowed-artifact checks in `server/runs.py`.
