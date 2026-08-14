# Repository Guidelines

### Project Objectives and Functions

    **Objective**: This is an intelligent agent for mathematical modeling, aiming to implement task-oriented automated mathematical modeling.

    **Functions**: Based on problems submitted by users and attached documents, it completes the full workflow automatically — including modeling, execution, and generation of final deliverable reports.

### Core Project Settings

1. The agent is designed for general mathematical modeling tasks. All proposed optimizations or error corrections must take generality into consideration; localized modifications tailored only to one specific problem are prohibited.
2. The core capability of this agent lies in modeling, and the essence of modeling is constructing accurate and reasonable models. The entire modeling workflow of this agent adopts an **LLM-only strategy**. No predefined methodologies are imposed, nor are problems rigidly categorized to apply fixed sets of methods. Driven by LLMs, the agent focuses on modeling centered on the problem itself and conducts targeted analysis for each individual case.

## Coding Style & Naming Conventions

Use Python 3.11+, four-space indentation, `snake_case` for modules/functions/variables, `PascalCase` for classes, and `UPPER_CASE` for constants. Add type annotations and Google-style docstrings to public Python functions. Keep imports ordered: standard library, third-party, then project modules. Prefer `logging` over `print`, catch specific exceptions, and keep prompts under `scr/prompts/` rather than embedding large prompt strings in code.

Use TypeScript/React components in `PascalCase`; keep page-specific styles in `web/src/forms.css` and avoid unrelated CSS rewrites. Follow existing formatting; this repository does not currently enforce Black, isort, or ESLint through scripts.

## Testing Guidelines

Write `pytest` tests named `test_<behavior>.py` or `test_<behavior>` and cover malformed LLM/tool output at schema boundaries. Add a regression test for every bug fix. Mock LLM and network calls; tests must not require API keys. Run the focused test first, then the relevant suite, and run `npm run build` after frontend changes.

## Configuration & Safety

Store local provider settings in `.env` and frontend-only API settings in browser storage. Validate file paths before writing under `artifacts/`, and preserve the existing allowed-artifact checks in `server/runs.py`.
