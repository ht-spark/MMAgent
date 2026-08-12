"""为子任务寻找、筛选并确定可执行建模方法。

结合问题澄清、数据画像、联网资料和 LLM 推理生成候选方案；再以数据约束和可实现性筛选，
输出可追溯的方法决策、假设和备选理由。
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
    """LLM 建模参考决策输出。"""
    selected_method: str = ""
    canonical_method: str = ""
    canonical_family: str = ""
    reason: str = ""
    validation_method: str = ""
    assumptions: list[str] = Field(default_factory=list)
    required_outputs: list[str] = Field(default_factory=list)
    validation_requirements: list[str] = Field(default_factory=list)


class MethodExplorer:
    """方法探索与决策Agent。

    候选生成策略（双路径）：
      - 当 TavilySearch 可用时：搜索路径（LLM 从搜索结果提取）+ LLM 思考路径
        （LLM 直接根据问题信息生成）共同形成候选，每条路径生成 CANDIDATE 预算
        限额数量的方法，总计 2× 候选。
      - 当 TavilySearch 不可用时：仅 LLM 思考路径生成 CANDIDATE 预算限额数量的方法。

    Args:
        llm: 可选的 LLM 客户端。
        search_tool: 可选的联网搜索工具。无则从环境变量自动创建。
                     若无 Tavily_API_KEY 则搜索功能降级为空。
        budget_manager: 可选的预算管理器。提供时会：
            - 每次 Tavily 检索前消耗 SEARCH（超额则跳过该次查询）；
            - 候选生成后按实际数量消耗 CANDIDATE（双路径时允许 2× 超额）。
            为 None 时不消耗、不限制（保持旧行为）。
    """

    def __init__(
        self,
        llm: Any | None = None,
        search_tool: TavilySearchTool | None = None,
        budget_manager: Any | None = None,
    ) -> None:
        self._llm = llm
        self._search_tool = search_tool or TavilySearchTool.from_env()
        self._budget_manager = budget_manager
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
        """基于问题澄清生成候选方法（双路径：搜索 + LLM 思考）。

        候选生成策略：
          - TavilySearch 可用时：搜索路径 + LLM 思考路径各生成 candidate_limit
            个候选，合计 2× candidate_limit。
          - TavilySearch 不可用时：仅 LLM 思考路径生成 candidate_limit 个候选。

        步骤：
          1. 获取候选数量限额（CANDIDATE 预算）
          2. 双路径/单路径生成候选方法
          3. 消耗 CANDIDATE 预算（双路径允许 2× 超额）

        Args:
            context: 当前任务上下文。
            interpretation: 任务澄清结果。
            data_profile: 数据画像（保留签名兼容，候选筛选交由 LLM 决策）。

        Returns:
            候选方法列表。
        """
        qid = context.question_id
        candidate_limit = self._get_candidate_limit(qid)
        search_available = bool(
            self._llm is not None
            and self._search_tool
            and self._search_tool.available
        )

        # ------------------------------------------------------------------
        # 候选生成（双路径 / 单路径）
        # ------------------------------------------------------------------
        if search_available:
            # 双路径：搜索提取 + LLM 思考
            search_candidates = self._search_external_methods(
                context, interpretation, candidate_limit
            )
            think_candidates = self._llm_think_methods(
                context, interpretation, candidate_limit
            )
            candidates = search_candidates + think_candidates
            print(
                f"[explorer] 双路径生成: 搜索 {len(search_candidates)} "
                f"+ LLM思考 {len(think_candidates)} = {len(candidates)} 个候选"
            )
        else:
            # 单路径：仅 LLM 思考
            candidates = self._llm_think_methods(
                context, interpretation, candidate_limit
            )
            print(f"[explorer] LLM思考生成: {len(candidates)} 个候选")

        # 消耗 CANDIDATE 预算（双路径允许 2× 超额， consume 返回 False 时忽略）
        if self._budget_manager is not None and candidates:
            try:
                from ..runtime.budget import BudgetType
                consumed = 0
                for _ in candidates:
                    if self._budget_manager.consume(
                        BudgetType.CANDIDATE, amount=1, question_id=qid
                    ):
                        consumed += 1
                print(
                    f"[explorer] CANDIDATE 记账: {consumed}/{len(candidates)} 个 "
                    f"（双路径设计，允许 2× 超额）"
                )
            except Exception as e:
                print(f"[explorer] CANDIDATE 预算记账跳过: {e}")

        for candidate in candidates:
            candidate["eliminated"] = False
            candidate["elimination_reason"] = ""

        print(f"[explorer] 小问 {qid}: 候选 {len(candidates)} 个，等待 LLM 最终决策")

        return candidates

    def _get_candidate_limit(self, question_id: str) -> int:
        """获取当前小问的候选方法数量上限（每条路径的目标生成数量）。

        从 CANDIDATE 预算中读取有效限额（含用户覆盖）。
        无预算管理器时返回默认值 4。

        Returns:
            每条路径应生成的候选方法数量。
        """
        if self._budget_manager is None:
            return 4
        try:
            from ..runtime.budget import BudgetType
            remaining = self._budget_manager.remaining(
                BudgetType.CANDIDATE, question_id=question_id
            )
            if remaining > 0:
                return remaining
            # 预算已用完（理论上不应发生，explore 在小问开始时调用）
            record = self._budget_manager.get_record(BudgetType.CANDIDATE)
            return record.limit if record else 4
        except Exception:
            return 4

    # ------------------------------------------------------------------
    # decide — 方法决策
    # ------------------------------------------------------------------

    def decide(
        self,
        candidates: list[dict],
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
    ) -> dict:
        """整理候选参考，生成问题驱动建模决策记录。

        Args:
            candidates: explore 产出的候选列表。
            context: 当前小问上下文。
            interpretation: 问题澄清结果。

        Returns:
            决策记录字典，包含：
              - selected_method: 建模策略名称
              - selected_family: 建模策略家族
              - selected_reason: 建模参考说明
              - alternatives: 备选方法列表
              - eliminated: 被淘汰方法及原因
              - assumptions: 选中方法的核心假设
              - validation_method: 推荐的验证方法
        """
        if not candidates:
            return {
                "selected_method": "无可用方法",
                "selected_family": "",
                "selected_reason": "LLM 未生成候选方法",
                "alternatives": [],
                "eliminated": [],
                "assumptions": [],
                "validation_method": "",
                "decision_source": "none",
            }

        llm_pick = self._decide_with_llm(candidates, context, interpretation)
        if llm_pick is None:
            return {
                "selected_method": "无可用方法",
                "selected_family": "",
                "selected_reason": "LLM 方法决策不可用或失败，未启用非 LLM 回退策略",
                "alternatives": [
                    {
                        "name": c.get("name", ""),
                        "family": c.get("family", ""),
                        "reason": "候选方法，等待 LLM 决策",
                    }
                    for c in candidates[:3]
                ],
                "eliminated": [],
                "assumptions": [],
                "validation_method": "",
                "decision_source": "llm_unavailable",
            }

        selected = llm_pick["selected"]
        selected_reason = llm_pick["selected_reason"]
        assumptions = llm_pick["assumptions"]
        decision_source = "llm"

        references = [selected] + [
            c for c in candidates if c.get("name") != selected.get("name")
        ]
        alternatives = references[:3]

        # 构建决策记录
        decision = {
            "selected_method": "问题驱动建模",
            "selected_family": "LLM问题推理建模",
            "canonical_method": "",
            "canonical_family": "LLM问题推理建模",
            "required_outputs": selected.get("required_outputs", []),
            "validation_requirements": selected.get("validation_requirements", []),
            "selected_reason": selected_reason,
            "alternatives": [
                {
                    "name": a["name"],
                    "family": a.get("family", ""),
                    "reason": "参考资料，供 LLM 构造本题专属模型时吸收或舍弃",
                }
                for a in alternatives
            ],
            "eliminated": [],
            "assumptions": assumptions,
            "validation_method": selected.get("validation_method", ""),
            "implementation_difficulty": selected.get("implementation_difficulty", "medium"),
            "selected_details": selected,
            "reference_methods": references[:8],
            "decision_source": decision_source,
        }

        print(f"[explorer] 决策: 问题驱动建模 "
              f"(参考 {len(alternatives)} 个, source={decision_source})")

        return decision

    def _decide_with_llm(
        self,
        viable: list[dict],
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
    ) -> dict | None:
        """用 LLM 整理候选方法为建模参考。

        让 LLM 按题意匹配/数据匹配/可验证性选择最值得参考的候选，
        但后续建模不再把该候选方法名当成完整模型。

        Returns:
            含 selected/selected_reason/assumptions 的字典；
            无 LLM 或调用失败时返回 None。
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
                        "source": c.get("source", ""),
                        "source_title": c.get("source_title", ""),
                        "source_url": c.get("source_url", ""),
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
            print(f"[explorer] LLM 方法决策失败: {e}")
            return None

        if not decision_data.selected_method:
            return None

        # 找到 LLM 选中的候选
        selected = next(
            (c for c in viable if c.get("name") == decision_data.selected_method),
            None,
        )
        if selected is None:
            print(
                f"[explorer] LLM 选择了不在候选列表中的方法 "
                f"'{decision_data.selected_method}'"
            )
            return None

        # 用 LLM 决策覆盖验证与产出要求；canonical 不再驱动内置方法回退。
        selected = {**selected}
        selected["canonical_method"] = ""
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
                result = structured_llm.invoke(prompt)
                if result is None:
                    # 部分 langchain 包装器在底层错误时吞掉异常并返回 None，
                    # 统一抛出以便上层 try/except 走回退路径（启发式）。
                    raise RuntimeError("LLM structured call returned None")
                return result
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
        candidate_limit: int = 4,
    ) -> list[dict]:
        """联网搜索 + LLM 从搜索结果中提取方法候选（搜索路径）。

        流程：
          1. 检查搜索工具和 LLM 是否可用
          2. 消耗 SEARCH 预算并执行搜索
          3. 由 LLM 从搜索结果中整理候选方法
          4. 转换为候选方法字典格式

        注意：CANDIDATE 预算消耗由 ``explore()`` 统一管理，此方法不再记账。

        Args:
            context: 当前任务上下文。
            interpretation: 任务澄清结果。
            candidate_limit: 本路径目标生成数量（传入 LLM prompt）。

        Returns:
            方法候选列表。
        """
        if self._llm is None:
            return []

        if not self._search_tool or not self._search_tool.available:
            return []

        math_task = interpretation.math_task
        problem_desc = (
            interpretation.math_task_description
            or context.objective
            or context.question_text
        )
        qid = context.question_id

        # 预算：每次"方法搜索轮"消耗 1 次 SEARCH；超额则跳过本次联网搜索
        if self._budget_manager is not None:
            try:
                from ..runtime.budget import BudgetType
                if not self._budget_manager.consume(
                    BudgetType.SEARCH, amount=1, question_id=qid
                ):
                    print(f"[explorer] 预算：SEARCH 已超额，跳过联网搜索（{qid}）")
                    return []
            except Exception as e:
                print(f"[explorer] SEARCH 预算记账跳过: {e}")

        # 执行搜索
        search_results = self._search_tool.search_methods(
            math_task=math_task,
            problem_description=problem_desc,
        )

        if not search_results:
            return []

        web_candidates = self._llm_extract_methods(
            search_results, math_task, problem_desc, candidate_limit
        )

        if not web_candidates:
            return []

        # 转换为候选方法字典格式
        method_candidates = self._convert_web_candidates(
            web_candidates, source="web_search"
        )

        print(f"[explorer] 搜索路径生成: {len(method_candidates)} 个方法候选")

        return method_candidates

    def _llm_extract_methods(
        self,
        search_results: list[dict],
        math_task: str,
        problem_description: str,
        candidate_limit: int = 4,
    ) -> list[WebMethodCandidate]:
        """使用 LLM 从搜索结果中提取结构化方法候选。

        Args:
            search_results: Tavily 搜索结果列表。
            math_task: 数学任务类型。
            problem_description: 问题描述。
            candidate_limit: 目标生成数量（传入 prompt）。

        Returns:
            WebMethodCandidate 列表。LLM 失败时返回空列表。
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
                candidate_limit=str(candidate_limit),
            )
        except FileNotFoundError:
            print("[explorer] method_search.md 不存在，跳过搜索整理路径")
            return []

        # 调用 LLM 提取（三级回退）
        candidates = self._call_llm_for_candidates(prompt)
        if candidates:
            print(f"[explorer] LLM 提取: {len(candidates)} 个方法候选")
            return candidates

        print("[explorer] LLM 全部提取方式失败")
        return []

    def _llm_think_methods(
        self,
        context: CurrentQuestionContext,
        interpretation: ProblemInterpretation,
        candidate_limit: int = 4,
    ) -> list[dict]:
        """LLM 直接根据问题信息生成方法候选（思考路径，不依赖搜索结果）。

        与搜索路径互补：当 TavilySearch 可用时，两路径共同形成 2× 候选；
        当 TavilySearch 不可用时，此路径独立生成 candidate_limit 个候选。

        Args:
            context: 当前任务上下文。
            interpretation: 任务澄清结果。
            candidate_limit: 本路径目标生成数量（传入 LLM prompt）。

        Returns:
            方法候选列表（字典格式），LLM 不可用时返回空列表。
        """
        if self._llm is None:
            return []

        math_task = interpretation.math_task
        problem_desc = (
            interpretation.math_task_description
            or context.objective
            or context.question_text
        )
        data_quality_summary = context.data_quality_summary or "无数据质量信息"

        # 加载并渲染 prompt
        try:
            template = self._load_prompt("method_think")
            prompt = self._render_prompt(
                template,
                math_task=math_task,
                problem_description=problem_desc[:500],
                data_quality_summary=data_quality_summary,
                candidate_limit=str(candidate_limit),
            )
        except FileNotFoundError:
            print("[explorer] method_think.md 不存在，跳过 LLM 思考路径")
            return []

        # 调用 LLM 生成（三级回退）
        web_candidates = self._call_llm_for_candidates(prompt)
        if not web_candidates:
            print("[explorer] LLM 思考路径未生成候选")
            return []

        # 转换为候选方法字典格式
        method_candidates = self._convert_web_candidates(
            web_candidates, source="llm_think"
        )

        print(f"[explorer] LLM思考路径生成: {len(method_candidates)} 个方法候选")
        return method_candidates

    def _call_llm_for_candidates(self, prompt: str) -> list[WebMethodCandidate]:
        """调用 LLM 获取方法候选列表（三级回退：json_schema → json_mode → JSON 文本）。

        搜索路径和思考路径共享此方法，确保 LLM 调用行为一致。

        Args:
            prompt: 已渲染的完整 prompt。

        Returns:
            WebMethodCandidate 列表。全部失败时返回空列表。
        """
        # 方案 1：structured output（json_schema）
        if not self._json_schema_unsupported:
            try:
                structured_llm = self._llm.with_structured_output(WebMethodCandidateList)
                result = structured_llm.invoke(prompt)
                if result is None:
                    raise RuntimeError("LLM structured call returned None")
                return result.candidates
            except Exception as e:
                err_msg = str(e)
                if "response_format" in err_msg or "BadRequestError" in str(type(e).__name__):
                    self._json_schema_unsupported = True
                    print(f"[explorer] LLM 不支持 json_schema，切换到 json_mode: {e}")
                else:
                    raise

        # 方案 2：json_mode
        try:
            structured_llm = self._llm.with_structured_output(
                WebMethodCandidateList, method="json_mode"
            )
            result = structured_llm.invoke(prompt)
            if result is None:
                raise RuntimeError("LLM json_mode call returned None")
            return result.candidates
        except Exception as e:
            print(f"[explorer] LLM json_mode 提取失败，尝试 JSON 文本提取: {e}")

        # 方案 3：JSON 文本提取（最终回退）
        candidates = self._llm_extract_methods_as_json(prompt)
        if candidates:
            print(f"[explorer] LLM JSON 提取: {len(candidates)} 个方法候选")
            return candidates

        print("[explorer] LLM 全部提取方式失败")
        return []

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
        source: str = "web_search",
    ) -> list[dict]:
        """将 WebMethodCandidate 转换为候选方法字典格式。

        通过 source 字段标记来源，保留 LLM 决策需要的上下文。

        Args:
            web_candidates: LLM 生成的 WebMethodCandidate 列表。
            source: 候选来源标记（"web_search" / "llm_think"）。
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
                "source": source,
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

    Handles markdown code fences, prose-wrapped JSON, and DeepSeek-style
    ``<think>...</think>`` chains (via llm_response.strip_thinking).
    """
    from ..tools.llm_response import extract_json

    try:
        return extract_json(text)
    except ValueError:
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
