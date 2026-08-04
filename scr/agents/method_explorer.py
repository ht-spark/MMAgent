"""方法探索与决策 Agent。

对应 architecture.md §5.3-5.4 方法探索与方法决策。

职责：
  1. explore — 基于问题澄清和数据画像，通过联网搜索+LLM思考生成候选方法
  2. decide — 对候选方法评分和排序，选择最佳方法
  3. generate_assumptions — 为选中方法生成假设列表

设计要点：
  - 纯联网+LLM驱动：不依赖预设方法目录，方法候选完全由搜索+LLM生成
  - 确定性硬过滤：根据数据要求淘汰不满足条件的方法
  - 启发式评分：用规则评分（数据匹配度、实现难度、适用性、文本匹配）
  - 降级处理：无网络或LLM不可用时提供通用候选
  - 决策可追溯：记录选择理由、备选方案和淘汰原因
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..schemas.context import DataProfile
from ..schemas.question import CurrentQuestionContext, ProblemInterpretation
from ..tools.tavily_search import (
    TavilySearchTool,
    WebMethodCandidate,
    WebMethodCandidateList,
)


class _MethodDecision(BaseModel):
    """LLM 方法决策输出（P1-B2：方法决策 LLM 化）。"""
    selected_method: str = ""
    canonical_method: str = ""
    canonical_family: str = ""
    reason: str = ""
    validation_method: str = ""
    assumptions: list[str] = Field(default_factory=list)
    required_outputs: list[str] = Field(default_factory=list)
    validation_requirements: list[str] = Field(default_factory=list)


class MethodExplorer:
    """方法探索与决策 Agent。

    Args:
        llm: 可选的 LLM 客户端。无则使用启发式规则。
        search_tool: 可选的联网搜索工具。无则从环境变量自动创建。
                     若无 Tavily_API_KEY 则搜索功能降级为空。
    """

    def __init__(
        self,
        llm: Any | None = None,
        search_tool: TavilySearchTool | None = None,
    ) -> None:
        self._llm = llm
        self._search_tool = search_tool or TavilySearchTool.from_env()
        self._prompt_dir = Path(__file__).resolve().parent.parent / "prompts"
        # 缓存标志：一旦发现 LLM 不支持 json_schema response_format，
        # 后续直接使用 json_mode，避免每次都尝试失败并打印错误日志。
        self._json_schema_unsupported: bool = False

    # ------------------------------------------------------------------
    # explore — 候选生成
    # ------------------------------------------------------------------

    def explore(
        self,
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
        data_profile: DataProfile | None = None,
    ) -> list[dict]:
        """基于问题澄清生成候选方法。

        完全由联网搜索+LLM思考驱动，不依赖预设方法目录。

        步骤：
          1. 联网搜索获取方法候选（LLM提取或启发式提取）
          2. 硬过滤：淘汰不满足数据要求的方法
          3. 为每个候选添加评分信息

        Args:
            context: 当前小问上下文。
            interpretation: 问题澄清结果。
            data_profile: 数据画像（用于硬过滤）。

        Returns:
            候选方法列表，每个方法包含字段 + score + eliminated + reason。
        """
        # 联网搜索+LLM生成候选方法
        candidates = self._search_external_methods(context, interpretation)

        if not candidates:
            # 降级：当无网络或LLM不可用时，提供一个通用候选
            candidates = [_fallback_candidate(interpretation)]

        # 硬过滤
        data_info = _extract_data_info(data_profile, context)
        filtered = []
        eliminated = []

        for c in candidates:
            reason = _check_eligibility(c, data_info, interpretation)
            if reason:
                c["eliminated"] = True
                c["elimination_reason"] = reason
                eliminated.append(c)
            else:
                c["eliminated"] = False
                c["elimination_reason"] = ""
                # 启发式评分
                c["heuristic_score"] = _heuristic_score(c, data_info, interpretation)
                filtered.append(c)

        # 如果全部被淘汰，保留得分最高的淘汰候选（降级处理）
        if not filtered and eliminated:
            best_eliminated = max(eliminated, key=lambda x: x.get("heuristic_score", 0))
            best_eliminated["eliminated"] = False
            best_eliminated["elimination_reason"] = ""
            best_eliminated["degraded"] = True
            filtered.append(best_eliminated)

        # 按启发式分数排序
        filtered.sort(key=lambda x: x.get("heuristic_score", 0), reverse=True)

        # 合并结果（保留被淘汰的记录用于决策追溯）
        all_candidates = filtered + [c for c in eliminated if c not in filtered]

        print(f"[explorer] 小问 {context.question_id}: "
              f"候选 {len(candidates)} → 通过 {len(filtered)} → 淘汰 {len(eliminated)}")
        if filtered:
            print(f"  → 推荐: {filtered[0]['name']} (score={filtered[0].get('heuristic_score', 0):.3f})")

        return all_candidates

    # ------------------------------------------------------------------
    # decide — 方法决策
    # ------------------------------------------------------------------

    def decide(
        self,
        candidates: list[dict],
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
    ) -> dict:
        """从候选方法中选择最佳方法，生成决策记录。

        Args:
            candidates: explore 产出的候选列表。
            context: 当前小问上下文。
            interpretation: 问题澄清结果。

        Returns:
            决策记录字典，包含：
              - selected_method: 选中方法名称
              - selected_family: 方法家族
              - selected_reason: 选择理由
              - alternatives: 备选方法列表
              - eliminated: 被淘汰方法及原因
              - assumptions: 选中方法的核心假设
              - validation_method: 推荐的验证方法
        """
        # 获取未淘汰的候选
        viable = [c for c in candidates if not c.get("eliminated", False)]

        if not viable:
            # 降级：选择第一个候选
            viable = candidates[:1] if candidates else []
            if viable:
                viable[0]["degraded"] = True

        if not viable:
            return {
                "selected_method": "无可用方法",
                "selected_family": "",
                "selected_reason": "所有候选方法均被淘汰且无降级候选",
                "alternatives": [],
                "eliminated": [],
                "assumptions": [],
                "validation_method": "",
            }

        # LLM 综合决策（失败时回退启发式评分取最高分）
        llm_pick = self._decide_with_llm(viable, context, interpretation)
        if llm_pick is not None:
            selected = llm_pick["selected"]
            selected_reason = llm_pick["selected_reason"]
            assumptions = llm_pick["assumptions"]
            decision_source = "llm"
        else:
            # 启发式回退：选择得分最高的
            selected = viable[0]
            selected_reason = _build_selection_reason(selected, interpretation, context)
            assumptions = _format_assumptions(selected, context, interpretation)
            decision_source = "heuristic"

        alternatives = viable[1:4]  # 最多 3 个备选
        eliminated = [c for c in candidates if c.get("eliminated", False)]

        # 构建决策记录
        decision = {
            "selected_method": selected["name"],
            "selected_family": selected.get("family", ""),
            "canonical_method": selected.get("canonical_method", ""),
            "canonical_family": selected.get("canonical_family", selected.get("family", "")),
            "required_outputs": selected.get("required_outputs", []),
            "validation_requirements": selected.get("validation_requirements", []),
            "selected_reason": selected_reason,
            "alternatives": [
                {
                    "name": a["name"],
                    "family": a.get("family", ""),
                    "score": a.get("heuristic_score", 0),
                    "reason": f"备选方案，得分 {a.get('heuristic_score', 0):.3f}",
                }
                for a in alternatives
            ],
            "eliminated": [
                {
                    "name": e["name"],
                    "reason": e.get("elimination_reason", ""),
                }
                for e in eliminated
            ],
            "assumptions": assumptions,
            "validation_method": selected.get("validation_method", ""),
            "implementation_difficulty": selected.get("implementation_difficulty", "medium"),
            "selected_details": selected,
            "decision_source": decision_source,
        }

        print(f"[explorer] 决策: {selected['name']} "
              f"(备选 {len(alternatives)}, 淘汰 {len(eliminated)}, source={decision_source})")

        return decision

    def _decide_with_llm(
        self,
        viable: list[dict],
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
    ) -> dict | None:
        """用 LLM 综合权衡候选方法并生成决策（P1-B2）。

        让 LLM 按题意匹配/数据匹配/可实现性/可验证性选择方法，
        并把选中方法映射到内置可执行计算（canonical_method），
        避免"选中了方法名却无法落地计算"的问题。

        Returns:
            含 selected/selected_reason/assumptions 的字典；
            无 LLM 或调用失败时返回 None（调用方回退启发式）。
        """
        if self._llm is None or not viable:
            return None
        try:
            candidates_summary = json.dumps(
                [
                    {
                        "name": c.get("name", ""),
                        "family": c.get("family", ""),
                        "description": (c.get("description", "") or "")[:200],
                        "pros": (c.get("pros") or [])[:3],
                        "cons": (c.get("cons") or [])[:3],
                        "implementation_difficulty": c.get("implementation_difficulty", ""),
                        "canonical_method": c.get("canonical_method", ""),
                        "heuristic_score": c.get("heuristic_score", 0),
                    }
                    for c in viable
                ],
                ensure_ascii=False,
            )
            template = self._load_prompt("method_decision")
            prompt = self._render_prompt(
                template,
                question_text=context.question_text,
                math_task=interpretation.math_task,
                math_task_description=interpretation.math_task_description,
                decision_variables=interpretation.decision_variables,
                objective_function=interpretation.objective_function,
                constraints=interpretation.constraints,
                available_data=interpretation.available_data,
                data_quality_summary=context.data_quality_summary,
                candidates=candidates_summary,
            )
            decision_data = self._call_structured_generic(_MethodDecision, prompt)
        except Exception as e:
            print(f"[explorer] LLM 方法决策失败，回退启发式: {e}")
            return None

        if not decision_data.selected_method:
            return None  # LLM 认为无合适候选，回退启发式

        # 找到 LLM 选中的候选
        selected = next(
            (c for c in viable if c.get("name") == decision_data.selected_method),
            None,
        )
        if selected is None:
            print(
                f"[explorer] LLM 选择了不在候选列表中的方法 "
                f"'{decision_data.selected_method}'，回退启发式"
            )
            return None

        # 用 LLM 决策覆盖 canonical 映射、验证与产出要求
        selected = {**selected}
        selected["canonical_method"] = decision_data.canonical_method
        selected["canonical_family"] = decision_data.canonical_family
        selected["validation_method"] = decision_data.validation_method
        selected["required_outputs"] = decision_data.required_outputs
        selected["validation_requirements"] = decision_data.validation_requirements

        print(
            f"[explorer] LLM 决策: {selected['name']} "
            f"(canonical={decision_data.canonical_method or '未映射'})"
        )

        return {
            "selected": selected,
            "selected_reason": decision_data.reason,
            "assumptions": decision_data.assumptions,
        }

    def _call_structured_generic(self, schema: type[BaseModel], prompt: str) -> BaseModel:
        """调用 LLM 并返回 schema 实例（三级回退：json_schema → json_mode → JSON 文本）。"""
        # 方案 1：structured output（json_schema）
        if not self._json_schema_unsupported:
            try:
                structured_llm = self._llm.with_structured_output(schema)
                return structured_llm.invoke(prompt)
            except Exception as e:
                err_msg = str(e)
                if "response_format" in err_msg or "BadRequestError" in str(type(e).__name__):
                    self._json_schema_unsupported = True
                else:
                    raise

        # 方案 2：json_mode
        try:
            structured_llm = self._llm.with_structured_output(schema, method="json_mode")
            return structured_llm.invoke(prompt)
        except Exception:
            pass

        # 方案 3：JSON 文本 + 手动解析
        schema_json = schema.model_json_schema()
        example = _schema_to_example_str(schema_json)
        json_prompt = (
            f"{prompt}\n\n"
            "---\n**重要**：你必须用纯 JSON 格式回答，不要用 Markdown 代码块，不要加解释。\n"
            f"JSON 格式和字段说明：\n```json\n{example}\n```\n"
            "直接返回 JSON，不要 ```json 包裹。"
        )
        response = self._llm.invoke(json_prompt)
        content = getattr(response, "content", response)
        data = _extract_json_object(str(content))
        if data is None:
            raise ValueError("LLM 未返回有效 JSON")
        return schema.model_validate(data)

    # ------------------------------------------------------------------
    # explore_and_decide — 串联两步
    # ------------------------------------------------------------------

    def explore_and_decide(
        self,
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
        data_profile: DataProfile | None = None,
    ) -> tuple[list[dict], dict]:
        """串联 explore → decide。

        Returns:
            (candidates, decision) 二元组。
        """
        candidates = self.explore(context, interpretation, data_profile)
        decision = self.decide(candidates, context, interpretation)
        return candidates, decision

    # ------------------------------------------------------------------
    # 联网搜索集成
    # ------------------------------------------------------------------

    def _search_external_methods(
        self,
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
    ) -> list[dict]:
        """联网搜索+LLM生成方法候选。

        流程：
          1. 检查搜索工具是否可用
          2. 构造搜索查询并执行搜索
          3. 从搜索结果中提取方法候选（LLM 优先，启发式回退）
          4. 转换为候选方法字典格式

        Returns:
            方法候选列表。
        """
        if not self._search_tool or not self._search_tool.available:
            return []

        math_task = interpretation.math_task
        problem_desc = (
            interpretation.math_task_description
            or context.objective
            or context.question_text
        )

        # 执行搜索
        search_results = self._search_tool.search_methods(
            math_task=math_task,
            problem_description=problem_desc,
        )

        if not search_results:
            return []

        # 提取方法候选
        if self._llm is not None:
            # LLM 提取（更精确）
            web_candidates = self._llm_extract_methods(
                search_results, math_task, problem_desc
            )
        else:
            # 启发式提取（无需 LLM）
            web_candidates = self._search_tool.extract_method_candidates(
                search_results, math_task
            )

        if not web_candidates:
            return []

        # 转换为候选方法字典格式
        method_candidates = self._convert_web_candidates(web_candidates)

        print(f"[explorer] 联网搜索生成: {len(method_candidates)} 个方法候选")

        return method_candidates

    def _llm_extract_methods(
        self,
        search_results: list[dict],
        math_task: str,
        problem_description: str,
    ) -> list[WebMethodCandidate]:
        """使用 LLM 从搜索结果中提取结构化方法候选。

        Args:
            search_results: Tavily 搜索结果列表。
            math_task: 数学任务类型。
            problem_description: 问题描述。

        Returns:
            WebMethodCandidate 列表。LLM 失败时回退到启发式提取。
        """
        # 格式化搜索结果
        formatted_results = self._format_search_results(search_results)

        # 加载并渲染 prompt
        try:
            template = self._load_prompt("method_search")
            prompt = self._render_prompt(
                template,
                math_task=math_task,
                problem_description=problem_description[:500],
                search_results=formatted_results,
            )
        except FileNotFoundError:
            # prompt 模板不存在，回退到启发式
            return self._search_tool.extract_method_candidates(
                search_results, math_task
            )

        # 调用 LLM — 方案 1：尝试 structured output（默认方式，使用 json_schema）
        # 若已缓存"不支持 json_schema"标志，则跳过
        if not self._json_schema_unsupported:
            try:
                structured_llm = self._llm.with_structured_output(WebMethodCandidateList)
                result = structured_llm.invoke(prompt)
                candidates = result.candidates
                print(f"[explorer] LLM 提取: {len(candidates)} 个方法候选")
                return candidates
            except Exception as e:
                err_msg = str(e)
                if "response_format" in err_msg or "BadRequestError" in str(type(e).__name__):
                    # 记住此 LLM 不支持 json_schema，后续直接走 json_mode
                    self._json_schema_unsupported = True
                    print(f"[explorer] LLM 不支持 json_schema，切换到 json_mode: {e}")
                else:
                    raise  # 非结构化输出相关错误，直接抛出

        # 方案 2：尝试 json_mode（兼容 DeepSeek 等仅支持 json_object 的模型）
        try:
            structured_llm = self._llm.with_structured_output(
                WebMethodCandidateList, method="json_mode"
            )
            result = structured_llm.invoke(prompt)
            candidates = result.candidates
            print(f"[explorer] LLM json_mode 提取: {len(candidates)} 个方法候选")
            return candidates
        except Exception as e:
            print(f"[explorer] LLM json_mode 提取失败，尝试 JSON 文本提取: {e}")

        # 方案 3：JSON 文本提取（最终回退）
        candidates = self._llm_extract_methods_as_json(prompt)
        if candidates:
            print(f"[explorer] LLM JSON 提取: {len(candidates)} 个方法候选")
            return candidates

        print("[explorer] LLM 全部提取方式失败，回退到启发式")
        return self._search_tool.extract_method_candidates(
            search_results, math_task
        )

    def _llm_extract_methods_as_json(self, prompt: str) -> list[WebMethodCandidate]:
        """Retry method extraction without provider-native response_format.

        通过在 prompt 中嵌入 JSON Schema 示例，引导 LLM 返回符合结构的纯 JSON 文本，
        然后手动解析并校验。兼容所有支持文本生成的 LLM 模型。
        """
        # 生成 schema 示例，帮助 LLM 理解期望的输出结构
        schema_json = WebMethodCandidateList.model_json_schema()
        example = _schema_to_example_str(schema_json)

        json_prompt = (
            f"{prompt}\n\n"
            "---\n**重要**：你必须用纯 JSON 格式回答，不要用 Markdown 代码块，不要加解释。\n"
            f"JSON 格式和字段说明：\n```json\n{example}\n```\n"
            "直接返回 JSON，不要 ```json 包裹。"
        )
        try:
            response = self._llm.invoke(json_prompt)
            content = getattr(response, "content", response)
            data = _extract_json_object(str(content))
            if data is None:
                print("[explorer] JSON 文本提取：未找到有效 JSON 对象")
                return []
            try:
                parsed = WebMethodCandidateList.model_validate(data)
            except Exception:
                # 尝试逐条解析 candidates，跳过不合规的条目
                raw_candidates = data.get("candidates", []) if isinstance(data, dict) else []
                valid: list[WebMethodCandidate] = []
                for item in raw_candidates:
                    if isinstance(item, dict):
                        try:
                            valid.append(WebMethodCandidate.model_validate(item))
                        except Exception:
                            continue
                if valid:
                    return valid
                print(f"[explorer] JSON 文本提取：数据校验失败，原始数据: {str(data)[:200]}")
                return []
            return parsed.candidates
        except Exception as e:
            print(f"[explorer] LLM JSON 提取失败: {e}")
            return []

    @staticmethod
    def _format_search_results(results: list[dict]) -> str:
        """格式化搜索结果供 LLM 阅读。"""
        lines: list[str] = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            url = r.get("url", "")
            content = r.get("content", "")
            # 截取内容，避免 prompt 过长
            content = content[:500] + "..." if len(content) > 500 else content
            lines.append(
                f"### 结果 {i}\n- 标题: {title}\n- URL: {url}\n- 内容: {content}\n"
            )
        return "\n".join(lines)

    @staticmethod
    def _convert_web_candidates(
        web_candidates: list[WebMethodCandidate],
    ) -> list[dict]:
        """将 WebMethodCandidate 转换为候选方法字典格式。

        外部方法候选的 data_requirements 设为宽松（不设硬性要求），
        以避免被硬过滤淘汰。通过 source 字段标记来源。
        """
        method_candidates: list[dict] = []
        for wc in web_candidates:
            candidate = {
                "name": wc.name,
                "family": wc.family,
                "description": wc.description,
                "required_data": wc.required_data if wc.required_data else ["待确认"],
                "assumptions": wc.assumptions,
                "pros": wc.pros,
                "cons": wc.cons,
                "elimination_conditions": [],
                "implementation_difficulty": wc.implementation_difficulty,
                "data_requirements": {
                    "min_samples": 0,
                    "min_features": 0,
                    "needs_time": False,
                },
                "validation_method": wc.validation_method or "交叉验证、敏感性分析",
                "required_outputs": wc.required_outputs,
                "validation_requirements": wc.validation_requirements,
                "canonical_method": "",
                "canonical_family": wc.family,
                "source": "web_search",
                "source_url": wc.source_url,
                "source_title": wc.source_title,
                "relevance_score": wc.relevance_score,
            }
            method_candidates.append(candidate)
        return method_candidates

    def _load_prompt(self, name: str) -> str:
        """加载 prompt 模板文件。"""
        path = self._prompt_dir / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _render_prompt(template: str, **kwargs: Any) -> str:
        """渲染 prompt 模板（替换 {var} 占位符）。"""
        result = template
        for key, value in kwargs.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result


def _extract_json_object(text: str) -> dict | None:
    """Extract the first JSON object from an LLM text response.

    Handles markdown code fences (```...``` or ```json...```) appearing
    anywhere in the text, as well as raw JSON embedded in prose.
    """
    cleaned = text.strip()
    # Strip markdown code fences — handle both leading and embedded code blocks
    if "```" in cleaned:
        lines = cleaned.splitlines()
        start_idx = None
        end_idx = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("```"):
                if start_idx is None:
                    start_idx = i
                else:
                    end_idx = i
                    break
        if start_idx is not None:
            if end_idx is not None:
                cleaned = "\n".join(lines[start_idx + 1:end_idx]).strip()
            else:
                cleaned = "\n".join(lines[start_idx + 1:]).strip()

    decoder = json.JSONDecoder()
    for start in [i for i, ch in enumerate(cleaned) if ch == "{"]:
        try:
            obj, _ = decoder.raw_decode(cleaned[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _schema_to_example_str(schema_json: dict) -> str:
    """从 JSON Schema 生成简化的示例 JSON 字符串，供 LLM prompt 使用。

    支持 ``$ref`` 引用解析（如 ``#/$defs/SomeModel``）。
    """
    defs = schema_json.get("$defs", {})
    example = _props_to_example(schema_json.get("properties", {}), defs)
    return json.dumps(example, ensure_ascii=False, indent=2)


def _props_to_example(props: dict, defs: dict) -> dict:
    """递归地将 JSON Schema properties 转为示例字典。"""
    example: dict = {}
    for key, prop in props.items():
        example[key] = _prop_to_example(prop, defs)
    return example


def _prop_to_example(prop: dict, defs: dict) -> Any:
    """将单个 JSON Schema property 转为示例值。"""
    # 解析 $ref
    if "$ref" in prop:
        ref_path = prop["$ref"]
        ref_name = ref_path.split("/")[-1]
        ref_schema = defs.get(ref_name, {})
        return _props_to_example(ref_schema.get("properties", {}), defs)

    ptype = prop.get("type", "string")

    if ptype == "array":
        items = prop.get("items", {})
        item_val = _prop_to_example(items, defs)
        return [item_val]
    elif ptype == "object":
        return _props_to_example(prop.get("properties", {}), defs)
    elif ptype in ("integer", "number"):
        return 0
    elif ptype == "boolean":
        return False
    else:
        enum = prop.get("enum")
        return enum[0] if enum else "示例文本"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _fallback_candidate(interpretation: ProblemInterpretation) -> dict:
    """当联网搜索和LLM均不可用时，根据任务类型提供一个通用候选。

    这是一个最小化的降级方案，确保工作流不会因无候选而中断。
    """
    math_task = interpretation.math_task
    task_defaults: dict[str, dict] = {
        "evaluation": {
            "name": "综合评价方法",
            "family": "多属性决策",
            "description": "基于多指标的综合评价方法，可根据数据特点选择熵权法或TOPSIS",
            "required_outputs": ["indicator_weights", "scores_or_ranking"],
            "validation_requirements": ["weight_sensitivity", "ranking_stability"],
            "assumptions": ["指标间相互独立或相关性可接受", "数据标准化后具有可比性"],
        },
        "prediction": {
            "name": "回归预测模型",
            "family": "线性模型",
            "description": "基于历史数据的回归预测方法",
            "required_outputs": ["predictions", "error_metrics"],
            "validation_requirements": ["residual_analysis", "error_metrics"],
            "assumptions": ["历史数据能反映未来趋势", "变量间存在线性或可线性化的关系"],
        },
        "optimization": {
            "name": "数学规划",
            "family": "数学规划",
            "description": "基于目标和约束的数学优化方法",
            "required_outputs": ["decision_solution", "objective_value", "constraint_check"],
            "validation_requirements": ["objective_recompute", "constraint_feasibility"],
            "assumptions": ["目标函数和约束条件可线性化", "决策变量为连续或整数"],
        },
        "stochastic_optimization": {
            "name": "随机优化",
            "family": "随机优化",
            "description": "考虑不确定性的优化方法",
            "required_outputs": ["scenario_solutions", "expected_objective", "risk_metrics"],
            "validation_requirements": ["scenario_sensitivity", "baseline_comparison"],
            "assumptions": ["不确定参数的分布已知或可估计", "场景集合具有代表性"],
        },
        "simulation": {
            "name": "蒙特卡洛模拟",
            "family": "仿真模型",
            "description": "基于随机采样的仿真模拟方法",
            "required_outputs": ["simulation_summary", "confidence_interval"],
            "validation_requirements": ["seed_reproducibility", "sample_size_sensitivity"],
            "assumptions": ["随机变量的分布已知或可拟合", "采样次数足够保证收敛"],
        },
    }
    defaults = task_defaults.get(
        math_task,
        task_defaults["optimization"],  # 通用回退
    )
    # canonical_method：与 model_builder._execute 的分发条件对齐，
    # 确保兜底方法也能命中对应的确定性计算实现（而非 generic_stats）。
    _CANONICAL_BY_TASK = {
        "evaluation": "topsis",
        "prediction": "linear_regression",
        "optimization": "linear_programming",
        "stochastic_optimization": "stochastic_programming",
        "simulation": "monte_carlo_simulation",
    }
    return {
        "name": defaults["name"],
        "family": defaults["family"],
        "description": defaults["description"],
        "required_data": ["待确认"],
        "assumptions": defaults.get("assumptions", []),
        "pros": [],
        "cons": [],
        "elimination_conditions": [],
        "implementation_difficulty": "medium",
        "data_requirements": {
            "min_samples": 0,
            "min_features": 0,
            "needs_time": False,
        },
        "validation_method": "交叉验证、敏感性分析",
        "required_outputs": defaults["required_outputs"],
        "validation_requirements": defaults["validation_requirements"],
        "canonical_method": _CANONICAL_BY_TASK.get(math_task, ""),
        "canonical_family": defaults["family"],
        "source": "fallback",
        "source_url": "",
        "source_title": "",
        "relevance_score": 0.3,
    }


def _extract_data_info(
    data_profile: DataProfile | None,
    context: CurrentQuestionContext,
) -> dict:
    """从数据画像和上下文中提取用于硬过滤的数据信息。

    Returns:
        包含 sample_size, feature_count, has_time_column 的字典。
    """
    info = {
        "sample_size": 0,
        "feature_count": 0,
        "has_time_column": False,
        "data_quality_summary": context.data_quality_summary or "",
    }

    if data_profile is not None:
        info["sample_size"] = data_profile.max_sample_size
        info["feature_count"] = len(data_profile.fields)
        info["has_time_column"] = data_profile.has_time_column

    return info


def _check_eligibility(
    method: dict,
    data_info: dict,
    interpretation: ProblemInterpretation,
) -> str:
    """检查方法是否满足数据要求（硬过滤）。

    Returns:
        空字符串表示通过，非空字符串为淘汰原因。
    """
    req = method.get("data_requirements", {})

    # 检查最小样本量
    min_samples = req.get("min_samples", 0)
    if min_samples > 0 and data_info["sample_size"] < min_samples:
        return f"样本量不足: 需要≥{min_samples}, 实际={data_info['sample_size']}"

    # 检查最小特征数
    min_features = req.get("min_features", 0)
    if min_features > 0 and data_info["feature_count"] < min_features:
        return f"特征数不足: 需要≥{min_features}, 实际={data_info['feature_count']}"

    # 检查时间列要求
    needs_time = req.get("needs_time", False)
    if needs_time and not data_info["has_time_column"]:
        return "需要时间列但数据中无时间维度"

    return ""


def _heuristic_score(
    method: dict,
    data_info: dict,
    interpretation: ProblemInterpretation,
) -> float:
    """启发式评分（0-1）。

    评分维度：
      - data_fit (0.25): 数据是否满足方法要求（满足程度）
      - implementation (0.20): 实现难度（越简单越高）
      - interpretability (0.15): 可解释性（简单方法更高）
      - robustness (0.10): 鲁棒性（有无淘汰条件）
      - suitability (0.10): 与任务类型的匹配度
      - text_match (0.20): 题目文本与方法的匹配度

    Returns:
      0-1 之间的分数。
    """
    score = 0.0

    # data_fit: 数据满足程度
    req = method.get("data_requirements", {})
    min_samples = req.get("min_samples", 0)
    if min_samples == 0:
        score += 0.25 * 1.0  # 无数据要求，满分
    elif data_info["sample_size"] >= min_samples * 3:
        score += 0.25 * 1.0  # 充足
    elif data_info["sample_size"] >= min_samples:
        score += 0.25 * 0.7  # 刚好满足
    else:
        score += 0.25 * 0.3  # 不足但未淘汰

    # implementation: 实现难度
    difficulty = method.get("implementation_difficulty", "medium")
    diff_score = {"low": 1.0, "medium": 0.6, "high": 0.3}.get(difficulty, 0.5)
    score += 0.20 * diff_score

    # interpretability: 可解释性（简单方法更高）
    family = method.get("family", "")
    interpretable_families = [
        "客观赋权法", "主观赋权法", "多属性决策", "线性模型",
        "数学规划", "灰色系统理论", "树模型",
    ]
    if family in interpretable_families:
        score += 0.15 * 0.9
    elif family in ["机器学习", "启发式算法"]:
        score += 0.15 * 0.5
    else:
        score += 0.15 * 0.6

    # robustness: 淘汰条件越少越鲁棒
    elimination_count = len(method.get("elimination_conditions", []))
    rob_score = max(0.3, 1.0 - 0.2 * elimination_count)
    score += 0.10 * rob_score

    # suitability: 与任务类型匹配（已在目录中按类型组织，所以匹配度高）
    score += 0.10 * 0.9

    # text_match: 题目文本与方法的匹配度
    score += 0.20 * _text_match_score(method, interpretation)

    # 外部方法（网络搜索）的微调：根据搜索相关性调整
    # 相关性高的外部方法可以接近内置方法，相关性低的则适当降分
    if method.get("source") == "web_search":
        relevance = method.get("relevance_score", 0.5)
        score *= (0.75 + 0.25 * relevance)  # 0.75-1.0 的系数

    return round(score, 4)


def _text_match_score(
    method: dict,
    interpretation: ProblemInterpretation,
) -> float:
    """计算题目文本与方法的匹配度（0-1）。

    根据题目文本中的关键词与方法描述的匹配程度评分。
    匹配度高的方法获得更高分数，从而实现方法推荐的差异化。
    """
    # 从 math_task_description 中提取文本
    text = (interpretation.math_task_description or "").lower()
    method_name = method.get("name", "").lower()
    method_desc = method.get("description", "").lower()
    method_family = method.get("family", "").lower()

    score = 0.5  # 基础分

    # 不确定性相关 → 随机/鲁棒优化方法加分
    uncertainty_keywords = ["不确定性", "随机", "鲁棒", "概率", "波动", "风险", "不确定"]
    has_uncertainty = any(kw in text for kw in uncertainty_keywords)
    if has_uncertainty:
        if any(kw in method_name for kw in ["随机", "鲁棒", "蒙特卡洛", "机会约束"]):
            score = 1.0
        elif any(kw in method_family for kw in ["随机", "鲁棒"]):
            score = 0.9
        elif "确定性" in method_name:
            score = 0.3  # 确定性方法在不确定性场景下降分
        else:
            score = 0.4

    # 整数/离散相关 → 整数规划加分
    integer_keywords = ["整数", "离散", "0-1", "二元", "integer", "discrete"]
    has_integer = any(kw in text for kw in integer_keywords)
    if has_integer:
        if "整数" in method_name:
            score = max(score, 0.9)
        elif "遗传" in method_name or "粒子群" in method_name:
            score = max(score, 0.7)
        elif "线性规划" in method_name and "整数" not in method_name:
            score = min(score, 0.4)  # 纯连续LP在整数场景下降分

    # 非线性相关 → 启发式算法加分
    nonlinear_keywords = ["非线性", "nonlinear", "复杂约束"]
    has_nonlinear = any(kw in text for kw in nonlinear_keywords)
    if has_nonlinear:
        if method.get("family") == "启发式算法":
            score = max(score, 0.85)
        elif "线性规划" in method_name:
            score = min(score, 0.3)

    # 时间序列/趋势相关 → 时间序列方法加分
    time_keywords = ["时间序列", "趋势", "forecast", "预测"]
    has_time = any(kw in text for kw in time_keywords)
    if has_time:
        if "arima" in method_name or "时间序列" in method_name:
            score = max(score, 0.9)
        elif "灰色" in method_name or "gm" in method_name:
            score = max(score, 0.8)
        elif "线性回归" in method_name:
            score = max(score, 0.6)

    # 多指标评价相关 → 评价方法加分
    eval_keywords = ["评价", "排序", "评估", "rank", "evaluate"]
    has_eval = any(kw in text for kw in eval_keywords)
    if has_eval:
        if any(kw in method_name for kw in ["熵权", "topsis", "ahp", "层次"]):
            score = max(score, 0.9)
        elif "灰色关联" in method_name:
            score = max(score, 0.75)

    return score


def _format_assumptions(
    method: dict,
    context: CurrentQuestionContext,
    interpretation: ProblemInterpretation,
) -> list[dict]:
    """格式化选中方法的假设列表。

    Returns:
        假设列表，每个假设包含 description, type, verifiable 字段。
    """
    assumptions: list[dict] = []

    # 方法自带假设
    for a in method.get("assumptions", []):
        assumptions.append({
            "description": a,
            "type": "method_inherent",
            "verifiable": True,
        })

    # 基于数据质量的假设
    if context.data_quality_summary:
        if "小样本" in context.data_quality_summary or "样本量" in context.data_quality_summary:
            assumptions.append({
                "description": "样本量有限，结果可能存在统计偏差",
                "type": "data_limitation",
                "verifiable": True,
            })
        if "无时间" in context.data_quality_summary:
            assumptions.append({
                "description": "无时间维度数据，不可使用时间序列方法",
                "type": "data_limitation",
                "verifiable": True,
            })

    # 基于前问继承的假设
    if context.inherited_summaries:
        for s in context.inherited_summaries:
            if s.get("status") == "validated":
                prev_limitations = s.get("limitations", [])
                for lim in prev_limitations[:1]:  # 只取第一条
                    assumptions.append({
                        "description": f"继承前问假设: {lim}",
                        "type": "inherited",
                        "verifiable": False,
                    })

    return assumptions


def _build_selection_reason(
    selected: dict,
    interpretation: ProblemInterpretation,
    context: CurrentQuestionContext,
) -> str:
    """构建方法选择理由。"""
    reasons: list[str] = []

    # 任务匹配
    reasons.append(
        f"任务类型 {interpretation.math_task} 与方法 {selected['name']} "
        f"({selected.get('family', '')}) 匹配"
    )

    # 数据匹配
    req = selected.get("data_requirements", {})
    if req.get("min_samples", 0) == 0:
        reasons.append("无特殊数据要求")
    else:
        reasons.append(f"满足数据要求（最小样本量 {req.get('min_samples', 0)}）")

    # 实现难度
    difficulty = selected.get("implementation_difficulty", "medium")
    if difficulty == "low":
        reasons.append("实现难度低，竞赛中可快速落地")
    elif difficulty == "medium":
        reasons.append("实现难度适中")
    else:
        reasons.append("实现难度较高，需要更多工程投入")

    # 继承关系
    if context.inherited_summaries:
        dep_ids = [s.get("question_id", "?") for s in context.inherited_summaries]
        reasons.append(f"可利用前问 {', '.join(dep_ids)} 的结论作为输入")

    # 降级标记
    if selected.get("degraded"):
        reasons.append("⚠ 降级选择：数据不完全满足要求，结果需谨慎解读")

    return "; ".join(reasons)
