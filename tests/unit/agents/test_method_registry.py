from scr.agents.method_registry import annotate_candidate, canonicalize_method


def test_web_fragment_optimization_method_is_canonicalized():
    candidate = {
        "name": "进行农作物种植的优化",
        "family": "其他方法",
    }

    annotate_candidate(candidate, "optimization")

    assert candidate["canonical_method"] == "linear_programming"
    assert candidate["name"] != candidate["raw_name"]
    assert candidate["raw_name"] == "进行农作物种植的优化"
    assert candidate["is_actionable"] is True


def test_stochastic_keywords_map_to_standard_method():
    spec = canonicalize_method("Robust Optimization under uncertainty", "", "stochastic_optimization")

    assert spec is not None
    assert spec.key == "robust_optimization"
