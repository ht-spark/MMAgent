"""预算确认接口的回归测试。"""
from __future__ import annotations

import asyncio

from server import main
from server.schemas import BudgetConfirmBody


def test_initial_budget_confirmation_accepts_only_g0_field(monkeypatch):
    """确认 G0 预算时接口可用，并将校验后的决定交给运行线程。"""
    submitted: dict[str, object] = {}

    monkeypatch.setattr(main, "get_pending_budget", lambda run_id: {"question_id": ""})

    def _submit(run_id: str, decision: dict | None) -> bool:
        submitted["run_id"] = run_id
        submitted["decision"] = decision
        return True

    monkeypatch.setattr(main, "submit_budget_decision", _submit)

    result = asyncio.run(
        main.confirm_budget_endpoint(
            "run-g0",
            BudgetConfirmBody(
                use_defaults=False,
                limits={"intake_retry": 3, "unexpected": 99},
            ),
        )
    )

    assert result["ok"] is True
    assert submitted == {
        "run_id": "run-g0",
        "decision": {"intake_retry": 3},
    }
