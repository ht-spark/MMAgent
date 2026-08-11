"""Robust subproblem cleanup and fallback decomposition.

The fallback is intentionally generic for mathematical modeling contests: it
uses explicit problem questions when available, infers only light dependencies,
and fills task-appropriate deliverables without choosing a specific model.
"""
from __future__ import annotations

import re
from typing import Iterable

from ..schemas.problem import ProblemAnalysis, SubProblem

_CN_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def sanitize_subproblems(
    subproblems: Iterable[SubProblem | dict] | None,
    analysis: ProblemAnalysis,
) -> list[SubProblem]:
    """Normalize LLM subproblems and fall back when the list is unusable."""
    cleaned: list[SubProblem] = []
    used_ids: set[str] = set()

    for index, item in enumerate(subproblems or [], 1):
        try:
            sp = item if isinstance(item, SubProblem) else SubProblem.model_validate(item)
        except Exception:
            continue

        task = _compact(sp.task)
        if not task:
            continue

        subproblem_id = _normalize_id(sp.id, index, used_ids)
        used_ids.add(subproblem_id)
        expected_outputs = _clean_list(sp.expected_outputs) or _infer_expected_outputs(
            task, index, analysis
        )
        input_requirements = _clean_list(sp.input_requirements) or _infer_inputs(
            task, analysis
        )
        dependencies = _sanitize_dependencies(
            sp.dependencies,
            current_id=subproblem_id,
            known_ids=used_ids,
            task=task,
            index=index,
        )

        cleaned.append(
            SubProblem(
                id=subproblem_id,
                task=task,
                input_requirements=input_requirements,
                expected_outputs=expected_outputs,
                dependencies=dependencies,
                parallelizable=bool(sp.parallelizable and not dependencies),
            )
        )

    cleaned = cleaned or fallback_subproblems_from_analysis(analysis)

    # 一致性校验：当显式小问只有 1 个但 LLM 生成了多个子问题时，合并为 1 个
    explicit_count = len([q for q in analysis.explicit_questions if _compact(q)])
    if explicit_count == 1 and len(cleaned) > 1:
        print(
            f"[decompose] 单问任务但 LLM 生成了 {len(cleaned)} 个子问题，"
            f"自动合并为 1 个子问题",
            flush=True,
        )
        cleaned = _consolidate_to_single(cleaned, analysis)

    return cleaned


def _consolidate_to_single(
    subproblems: list[SubProblem], analysis: ProblemAnalysis
) -> list[SubProblem]:
    """Merge multiple subproblems into a single one when the task has only 1 question."""
    # 使用原始显式小问文本作为主任务描述
    question_text = _compact(analysis.explicit_questions[0]) if analysis.explicit_questions else ""

    # 合并所有子问题的输入和预期输出
    all_inputs: list[str] = []
    all_outputs: list[str] = []
    task_parts: list[str] = []
    for sp in subproblems:
        if sp.task:
            task_parts.append(sp.task)
        all_inputs.extend(sp.input_requirements or [])
        all_outputs.extend(sp.expected_outputs or [])

    # 如果原始小问文本存在，优先使用它作为 task；否则拼接子问题 task
    merged_task = question_text or "；".join(task_parts) if task_parts else "完成综合建模与求解"

    return [
        SubProblem(
            id="q1",
            task=merged_task,
            input_requirements=_dedupe(all_inputs)[:6],
            expected_outputs=_dedupe(all_outputs)[:6] or _infer_expected_outputs(merged_task, 1, analysis),
            dependencies=[],
            parallelizable=False,
        )
    ]


def fallback_subproblems_from_analysis(analysis: ProblemAnalysis) -> list[SubProblem]:
    """Create a conservative, non-model-specific decomposition from analysis."""
    questions = _fallback_questions(analysis)
    subproblems: list[SubProblem] = []

    for index, question in enumerate(questions, 1):
        task = _compact(question)
        dependencies = _infer_dependencies(task, index)
        subproblems.append(
            SubProblem(
                id=f"q{index}",
                task=task,
                input_requirements=_infer_inputs(task, analysis),
                expected_outputs=_infer_expected_outputs(task, index, analysis),
                dependencies=dependencies,
                parallelizable=not dependencies,
                is_fallback=True,
            )
        )

    return subproblems


def short_error(error: Exception, max_len: int = 160) -> str:
    """Return a single-line error summary suitable for workflow logs."""
    text = " ".join(str(error).split())
    return text[:max_len] + ("..." if len(text) > max_len else "")


def _fallback_questions(analysis: ProblemAnalysis) -> list[str]:
    questions = [_compact(q) for q in analysis.explicit_questions if _compact(q)]
    if questions:
        return questions

    source = _compact(analysis.background) or _compact(analysis.research_subject)
    if source:
        chunks = re.split(r"(?:^|\n)\s*(?=问题\s*[一二三四五六七八九十\d]+)", source)
        questions = [_compact(chunk) for chunk in chunks if _compact(chunk).startswith("问题")]
        if questions:
            return questions

    subject = _compact(analysis.research_subject) or "任务对象"
    return [f"围绕{subject}完成综合建模、求解与结果解释"]


def _infer_inputs(task: str, analysis: ProblemAnalysis) -> list[str]:
    inputs: list[str] = []
    if analysis.keywords:
        inputs.extend(analysis.keywords[:3])
    if re.search(r"数据|附件|指标|样本|观测|变量|字段", task):
        inputs.append("任务附件数据与字段说明")
    if not inputs:
        inputs.append("任务条件与附件数据")
    return _dedupe(inputs)[:4]


def _infer_expected_outputs(
    task: str,
    index: int,
    analysis: ProblemAnalysis,
) -> list[str]:
    if analysis.expected_outputs:
        if len(analysis.expected_outputs) == len(analysis.explicit_questions):
            output = _compact(analysis.expected_outputs[index - 1])
            if output:
                return [output]
        outputs = [_compact(x) for x in analysis.expected_outputs[:3] if _compact(x)]
        if outputs:
            return outputs

    if re.search(r"评价|评估|排序|排名|得分|综合", task):
        return ["指标体系与权重说明", "综合得分与排序结果", "结果解释与稳健性分析"]
    if re.search(r"预测|预报|趋势|未来|估计", task):
        return ["预测结果", "误差评价指标", "趋势解释与不确定性说明"]
    if re.search(r"优化|最优|方案|调度|路径|选址|配置|成本|收益", task):
        return ["最优方案", "目标函数值", "约束满足性与敏感性分析"]
    if re.search(r"分类|识别|判别|聚类", task):
        return ["分类或分组结果", "模型性能指标", "关键特征解释"]
    if re.search(r"仿真|模拟|随机|情景|风险", task):
        return ["模拟结果", "情景或风险指标", "敏感性分析"]
    return [f"问题{index}的计算结果", "建模过程与结论分析"]


def _infer_dependencies(task: str, index: int) -> list[str]:
    if index <= 1:
        return []

    refs = []
    for token in re.findall(r"问题\s*(\d+|[一二三四五六七八九十]+)", task):
        number = _parse_question_number(token)
        if number is not None and number < index:
            refs.append(f"q{number}")

    if refs:
        return _dedupe(refs)

    if re.search(r"在.*基础|基于|根据|利用.*结果|结合.*结果|进一步|前述|上一问|前一问", task):
        return [f"q{index - 1}"]
    return []


def _sanitize_dependencies(
    dependencies: Iterable[str],
    current_id: str,
    known_ids: set[str],
    task: str,
    index: int,
) -> list[str]:
    cleaned = [
        dep
        for dep in _clean_list(dependencies)
        if dep in known_ids and dep != current_id
    ]
    return cleaned or _infer_dependencies(task, index)


def _normalize_id(raw_id: str, index: int, used_ids: set[str]) -> str:
    candidate = _compact(raw_id).lower()
    if not re.fullmatch(r"q[\w-]+", candidate) or candidate in used_ids:
        candidate = f"q{index}"
    while candidate in used_ids:
        candidate = f"q{index}_{len(used_ids) + 1}"
    return candidate


def _parse_question_number(token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        return int(token)
    if token in _CN_NUMBERS:
        return _CN_NUMBERS[token]
    if token.startswith("十") and len(token) == 2:
        return 10 + _CN_NUMBERS.get(token[1], 0)
    if token.endswith("十") and len(token) == 2:
        return _CN_NUMBERS.get(token[0], 0) * 10
    if "十" in token and len(token) == 3:
        left, right = token.split("十", 1)
        return _CN_NUMBERS.get(left, 0) * 10 + _CN_NUMBERS.get(right, 0)
    return None


def _clean_list(values: Iterable[object]) -> list[str]:
    return _dedupe(_compact(value) for value in values if _compact(value))


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _compact(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
