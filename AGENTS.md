# Repository Guidelines



### 项目目标和功能

    目标：这是一个数学建模智能体，目标是实现面向具体任务的自动化数学建模

    功能：通过用户提交的问题和附件资料，全流程自动化完成建模、执行和生成最终交付报告。

## Poject Structure & Module Organization

`scr/` contains the mathematical-modeling engine: `math_modeling_agent/` owns the LangGraph workflow, `agents/` implements reasoning stages, `workflow/` holds orchestration helpers, and `tools/` provides deterministic utilities. `server/` is the FastAPI service and SQLite run store. `web/` is the React + Vite interface (`src/pages/`, `src/components/`). Put Python tests in `tests/unit/`, mirroring the source area they cover. Runtime outputs belong in `artifacts/<run_id>/`; do not treat them as source assets.

## Build, Test, and Development Commands

- `uv run --no-sync python -m pytest -q` runs the Python suite using the locked environment.
- `uv run --no-sync python -m pytest tests/unit/tools/test_md2docx_math.py -q` runs a focused test file.
- `uvicorn server.main:app --reload --port 8000` starts the API with reload at `http://localhost:8000`.
- `cd web && npm run dev` starts the Vite development server.
- `cd web && npm run build` type-checks/builds the production frontend into `web/dist/`.

## Coding Style & Naming Conventions

Use Python 3.11+, four-space indentation, `snake_case` for modules/functions/variables, `PascalCase` for classes, and `UPPER_CASE` for constants. Add type annotations and Google-style docstrings to public Python functions. Keep imports ordered: standard library, third-party, then project modules. Prefer `logging` over `print`, catch specific exceptions, and keep prompts under `scr/prompts/` rather than embedding large prompt strings in code.

Use TypeScript/React components in `PascalCase`; keep page-specific styles in `web/src/forms.css` and avoid unrelated CSS rewrites. Follow existing formatting; this repository does not currently enforce Black, isort, or ESLint through scripts.

## Testing Guidelines

Write `pytest` tests named `test_<behavior>.py` or `test_<behavior>` and cover malformed LLM/tool output at schema boundaries. Add a regression test for every bug fix. Mock LLM and network calls; tests must not require API keys. Run the focused test first, then the relevant suite, and run `npm run build` after frontend changes.

## Configuration & Safety

Store local provider settings in `.env` and frontend-only API settings in browser storage. Validate file paths before writing under `artifacts/`, and preserve the existing allowed-artifact checks in `server/runs.py`.
