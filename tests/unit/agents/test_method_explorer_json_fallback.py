from scr.agents.method_explorer import MethodExplorer


class _DummyMessage:
    def __init__(self, content):
        self.content = content


class _DummyLLM:
    def invoke(self, prompt):
        return _DummyMessage(
            """```json
{
  "candidates": [
    {
      "name": "Robust Optimization",
      "family": "robust optimization",
      "description": "A method for optimization under uncertainty.",
      "pros": ["handles uncertainty"],
      "cons": ["requires scenario design"],
      "assumptions": ["uncertainty set is available"],
      "required_data": ["scenario data"],
      "implementation_difficulty": "medium",
      "validation_method": "sensitivity analysis",
      "source_url": "https://example.com",
      "source_title": "Robust Optimization",
      "relevance_score": 0.8
    }
  ]
}
```"""
        )


def test_llm_json_method_extraction_fallback_parses_code_fenced_json():
    explorer = MethodExplorer(llm=_DummyLLM())

    candidates = explorer._llm_extract_methods_as_json("prompt")

    assert len(candidates) == 1
    assert candidates[0].name == "Robust Optimization"
    assert candidates[0].relevance_score == 0.8
