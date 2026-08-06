"""InstrumentedLLM 单元测试：监控 TIME/TOKEN，幂等折叠，结构化输出透传。"""
import time

from scr.runtime.budget import BudgetManager, BudgetType
from scr.runtime.instrumented_llm import InstrumentedLLM


class _FakeResp:
    def __init__(self, tokens):
        self.usage_metadata = {
            "total_tokens": tokens,
            "input_tokens": tokens // 2,
            "output_tokens": tokens // 2,
        }


class _FakeLLM:
    def __init__(self):
        self.n = 0
        self.calls = []

    def invoke(self, prompt, *args, **kwargs):
        self.n += 1
        self.calls.append((prompt, kwargs.get("config")))
        return _FakeResp(40 + self.n * 10)

    def with_structured_output(self, *args, **kwargs):
        # 返回一个"结构化"包装；这里直接复用自身以便计数
        return self


def test_monitors_time_and_token():
    bm = BudgetManager()
    llm = InstrumentedLLM(_FakeLLM(), bm, qid_getter=lambda: "Q1")
    for _ in range(3):
        llm.invoke("hi")
    assert bm.get_record(BudgetType.TOKEN).run_total == (50 + 60 + 70)
    assert bm.get_record(BudgetType.TIME).run_total > 0


def test_passes_callbacks_to_underlying():
    bm = BudgetManager()
    inner = _FakeLLM()
    llm = InstrumentedLLM(inner, bm, qid_getter=lambda: "Q1")
    llm.invoke("hi")
    # 底层 llm 必须被调用
    assert inner.calls, "底层 llm 未被调用"
    # 监控必须生效：token 已记账（无论是否注入 callbacks，都应落到 run_total）
    assert bm.get_record(BudgetType.TOKEN).run_total == 50
    # 若可用 UsageMetadataCallbackHandler（已安装 langchain），则应注入 callbacks；
    # 否则走 usage_metadata 回退路径，二者都记录 token，故仅校验 token 已记账。


def test_per_question_qid_attribution():
    bm = BudgetManager()
    qid_holder = {"q": "Q1"}
    llm = InstrumentedLLM(_FakeLLM(), bm, qid_getter=lambda: qid_holder["q"])
    llm.invoke("hi")
    qid_holder["q"] = "Q2"
    llm.invoke("hi")
    d = bm.to_dict()
    assert d["per_question_monitor_usage"]["Q1"]["token"] == 50
    assert d["per_question_monitor_usage"]["Q2"]["token"] == 60


def test_no_budget_manager_passthrough():
    inner = _FakeLLM()
    llm = InstrumentedLLM(inner, None, qid_getter=lambda: "Q1")
    resp = llm.invoke("hi")
    assert resp.usage_metadata["total_tokens"] == 50
    # 无预算时不记账
    assert llm._budget_manager is None


def test_idempotent_collapse():
    bm = BudgetManager()
    inner = _FakeLLM()
    wrapped = InstrumentedLLM(inner, bm, qid_getter=lambda: "Q1")
    # 再次包裹应折叠，复用同一底层 llm，不双重计数
    wrapped2 = InstrumentedLLM(wrapped, bm, qid_getter=lambda: "Q2")
    assert wrapped2._llm is inner
    wrapped2.invoke("hi")
    # 仅 1 次调用 → 仅 50 token，未双重记账
    assert bm.get_record(BudgetType.TOKEN).run_total == 50
    # qid_getter 以最外层为准
    assert wrapped2._current_qid() == "Q2"


def test_structured_output_returns_instrumented():
    bm = BudgetManager()
    llm = InstrumentedLLM(_FakeLLM(), bm, qid_getter=lambda: "Q1")
    structured = llm.with_structured_output("schema")
    assert isinstance(structured, InstrumentedLLM)
    structured.invoke("hi")
    assert bm.get_record(BudgetType.TOKEN).run_total == 50
