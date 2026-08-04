"""Tavily 联网搜索工具。

用于方法探索阶段，通过联网搜索获取方法候选。
方法探索完全由联网搜索+LLM思考驱动，不依赖预设方法目录。

功能：
  - TavilySearchTool.search: 通用搜索接口
  - TavilySearchTool.search_methods: 方法探索专用搜索（根据任务类型构造查询）
  - extract_method_candidates: 从搜索结果中启发式提取方法候选（无需 LLM）
  - WebMethodCandidate: 从网络搜索结果中提取的结构化方法候选

设计要点：
  - API key 从环境变量读取（Tavily_API_KEY / TAVILY_API_KEY）
  - 无 API key 或网络错误时优雅降级（返回空列表，不中断流程）
  - 搜索结果可被 MethodExplorer 用于生成候选方法
  - 支持中英文双语查询，提高搜索覆盖面

对应 architecture.md §5.3 方法探索与决策：
  方法候选完全由联网搜索+LLM思考生成，不预设方法目录。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "TavilySearchTool",
    "WebMethodCandidate",
    "WebMethodCandidateList",
    "create_search_tool",
]


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


class WebMethodCandidate(BaseModel):
    """从网络搜索结果+LLM推理生成的方法候选。

    完全由联网搜索和大模型思考生成，不依赖预设方法目录。

    Attributes:
        name: 方法名称。
        family: 方法家族（如 "机器学习"、"启发式算法"）。
        description: 方法描述。
        pros: 优点列表。
        cons: 缺点列表。
        assumptions: 核心假设列表。
        required_data: 所需数据类型列表。
        implementation_difficulty: 实现难度（low/medium/high）。
        validation_method: 推荐的验证方法。
        required_outputs: 该方法应产出的结果类型列表（如 ["decision_solution", "objective_value"]）。
        validation_requirements: 验证该方法的检查项列表（如 ["constraint_feasibility", "sensitivity_analysis"]）。
        source_url: 来源 URL（用于追溯）。
        source_title: 来源标题。
        relevance_score: 搜索相关性分数（0-1，来自 Tavily）。
    """

    name: str
    family: str = ""
    description: str = ""
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    required_data: list[str] = Field(default_factory=list)
    implementation_difficulty: str = "medium"
    validation_method: str = ""
    required_outputs: list[str] = Field(default_factory=list)
    validation_requirements: list[str] = Field(default_factory=list)
    source_url: str = ""
    source_title: str = ""
    relevance_score: float = Field(default=0.5, ge=0.0, le=1.0)


class WebMethodCandidateList(BaseModel):
    """方法候选列表包装（供 LLM 结构化输出使用）。"""

    candidates: list[WebMethodCandidate] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 查询模板：按数学任务类型构造搜索查询
# ---------------------------------------------------------------------------


_TASK_QUERY_TEMPLATES: dict[str, dict[str, str]] = {
    "evaluation": {
        "zh": "数学建模 评价方法 排序 综合评价 {keywords} 推荐 适用",
        "en": "mathematical modeling evaluation ranking method {keywords} multi-criteria",
    },
    "prediction": {
        "zh": "数学建模 预测方法 模型 {keywords} 趋势预测 推荐",
        "en": "prediction model forecasting method {keywords} mathematical modeling",
    },
    "optimization": {
        "zh": "数学建模 优化方法 求解 {keywords} 最优策略 规划",
        "en": "optimization method mathematical modeling {keywords} solve optimal strategy",
    },
    "stochastic_optimization": {
        "zh": "数学建模 不确定性 随机优化 鲁棒优化 {keywords} 方法",
        "en": "stochastic optimization robust optimization uncertainty {keywords} method",
    },
    "classification": {
        "zh": "数学建模 分类方法 聚类 {keywords} 模型 推荐",
        "en": "classification clustering method {keywords} mathematical modeling",
    },
    "simulation": {
        "zh": "数学建模 仿真 模拟 蒙特卡洛 {keywords} 方法",
        "en": "simulation Monte Carlo method {keywords} mathematical modeling",
    },
    "mechanism": {
        "zh": "数学建模 机理模型 微分方程 {keywords} 建立",
        "en": "mechanism model differential equation {keywords} mathematical modeling",
    },
    "composite": {
        "zh": "数学建模 方法 {keywords} 综合 求解 推荐",
        "en": "mathematical modeling method {keywords} comprehensive solve",
    },
}


# ---------------------------------------------------------------------------
# 搜索工具
# ---------------------------------------------------------------------------


@dataclass
class TavilySearchTool:
    """Tavily 联网搜索工具。

    用于方法探索阶段，从互联网搜索补充方法候选。

    Attributes:
        api_key: Tavily API 密钥。若为 None 则搜索功能不可用。
        client: TavilyClient 实例（惰性初始化）。
        max_results: 每次搜索返回的最大结果数。
        search_depth: 搜索深度（"basic" 或 "advanced"）。
        timeout: 请求超时秒数。
    """

    api_key: str | None = None
    max_results: int = 5
    search_depth: str = "advanced"
    timeout: int = 30
    _client: Any = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # 工厂方法
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls, **kwargs: Any) -> "TavilySearchTool":
        """从环境变量创建搜索工具。

        读取以下环境变量（按优先级）：
          1. TAVILY_API_KEY
          2. Tavily_API_KEY
          3. tavily_api_key

        若均不存在，返回 api_key=None 的实例（搜索功能降级为空）。
        """
        api_key = (
            os.getenv("TAVILY_API_KEY")
            or os.getenv("Tavily_API_KEY")
            or os.getenv("tavily_api_key")
        )
        return cls(api_key=api_key, **kwargs)

    # ------------------------------------------------------------------
    # 客户端管理
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """搜索工具是否可用（有 API key）。"""
        return self.api_key is not None and len(self.api_key) > 0

    def _get_client(self) -> Any:
        """惰性初始化 TavilyClient。"""
        if self._client is not None:
            return self._client
        if not self.available:
            return None
        try:
            from tavily import TavilyClient

            self._client = TavilyClient(api_key=self.api_key)
            return self._client
        except ImportError:
            print("[tavily] 警告：tavily-python 未安装，联网搜索不可用")
            return None
        except Exception as e:
            print(f"[tavily] 警告：TavilyClient 初始化失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 通用搜索
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        max_results: int | None = None,
        search_depth: str | None = None,
        include_answer: bool = True,
        include_raw_content: bool = False,
    ) -> dict[str, Any]:
        """执行 Tavily 搜索。

        Args:
            query: 搜索查询字符串。
            max_results: 最大结果数，默认使用实例配置。
            search_depth: 搜索深度，默认使用实例配置。
            include_answer: 是否包含 AI 生成的摘要。
            include_raw_content: 是否包含原始页面内容。

        Returns:
            Tavily API 返回的字典，包含：
              - query: 查询字符串
              - answer: AI 摘要（若 include_answer=True）
              - results: 结果列表，每项含 title/url/content/score
              - response_time: 响应时间

            若搜索不可用或出错，返回 {"results": [], "answer": "", "error": "..."}。
        """
        if not self.available:
            return {"results": [], "answer": "", "error": "API key not configured"}

        client = self._get_client()
        if client is None:
            return {"results": [], "answer": "", "error": "client init failed"}

        try:
            result = client.search(
                query=query,
                max_results=max_results or self.max_results,
                search_depth=search_depth or self.search_depth,
                include_answer=include_answer,
                include_raw_content=include_raw_content,
            )
            return result
        except Exception as e:
            print(f"[tavily] 搜索失败: {e}")
            return {"results": [], "answer": "", "error": str(e)}

    # ------------------------------------------------------------------
    # 方法探索专用搜索
    # ------------------------------------------------------------------

    def search_methods(
        self,
        math_task: str,
        problem_description: str,
        max_results: int = 5,
    ) -> list[dict[str, Any]]:
        """方法探索专用搜索。

        根据数学任务类型和问题描述构造中英文双语查询，
        返回合并去重后的搜索结果。

        Args:
            math_task: 数学任务类型（evaluation/prediction/optimization 等）。
            problem_description: 问题描述文本（用于提取关键词）。
            max_results: 每次查询的最大结果数。

        Returns:
            搜索结果列表，每项含 title/url/content/score。
            合并去重后按 score 降序排列。
        """
        if not self.available:
            return []

        # 提取关键词
        keywords = _extract_keywords(problem_description)

        # 获取查询模板
        templates = _TASK_QUERY_TEMPLATES.get(
            math_task, _TASK_QUERY_TEMPLATES["composite"]
        )

        # 构造中英文查询
        zh_query = templates["zh"].format(keywords=keywords)
        en_query = templates["en"].format(keywords=keywords)

        print(f"[tavily] 方法搜索: task={math_task}")
        print(f"  → 中文查询: {zh_query[:80]}...")
        print(f"  → 英文查询: {en_query[:80]}...")

        # 执行搜索
        zh_result = self.search(zh_query, max_results=max_results)
        en_result = self.search(en_query, max_results=max_results)

        # 合并去重
        all_results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for r in zh_result.get("results", []):
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

        for r in en_result.get("results", []):
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

        # 按 score 降序
        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)

        print(f"[tavily] 搜索完成: 获得 {len(all_results)} 条去重结果")

        return all_results

    # ------------------------------------------------------------------
    # 启发式方法提取（无需 LLM）
    # ------------------------------------------------------------------

    def extract_method_candidates(
        self,
        search_results: list[dict[str, Any]],
        math_task: str,
        answer: str = "",
    ) -> list[WebMethodCandidate]:
        """从搜索结果中启发式提取方法候选。

        无需 LLM，通过正则和规则从标题和摘要中提取方法信息。

        Args:
            search_results: search_methods 返回的结果列表。
            math_task: 数学任务类型。
            answer: Tavily AI 摘要（可选，用于补充提取）。

        Returns:
            WebMethodCandidate 列表。
        """
        candidates: list[WebMethodCandidate] = []
        seen_names: set[str] = set()

        for result in search_results:
            title = result.get("title", "")
            content = result.get("content", "")
            url = result.get("url", "")
            score = result.get("score", 0)

            # 从标题和内容中提取方法名称
            method_names = _extract_method_names(title, content)

            if not method_names:
                # 如果没提取到明确的方法名，用标题作为方法名
                if title and len(title) < 50:
                    method_names = [title]

            for name in method_names:
                # 去重
                name_clean = name.strip()
                if not name_clean or name_clean in seen_names:
                    continue
                seen_names.add(name_clean)

                # 推断方法家族
                family = _infer_family(name_clean, content)

                # 提取描述（取内容的前 200 字符）
                description = content[:200].replace("\n", " ").strip()
                if len(content) > 200:
                    description += "..."

                candidate = WebMethodCandidate(
                    name=name_clean,
                    family=family,
                    description=description,
                    pros=_extract_pros(content),
                    cons=_extract_cons(content),
                    assumptions=[],
                    required_data=[],
                    implementation_difficulty=_infer_difficulty(name_clean, family),
                    validation_method="",
                    source_url=url,
                    source_title=title,
                    relevance_score=min(score, 1.0) if score else 0.5,
                )
                candidates.append(candidate)

        # 如果有 AI 摘要，尝试从中补充提取
        if answer and not candidates:
            method_names = _extract_method_names("", answer)
            for name in method_names:
                name_clean = name.strip()
                if name_clean and name_clean not in seen_names:
                    seen_names.add(name_clean)
                    family = _infer_family(name_clean, answer)
                    candidates.append(WebMethodCandidate(
                        name=name_clean,
                        family=family,
                        description=answer[:200],
                        source_url="",
                        source_title="Tavily AI Answer",
                        relevance_score=0.7,
                    ))

        print(f"[tavily] 启发式提取: {len(candidates)} 个方法候选")
        for c in candidates[:3]:
            print(f"  → {c.name} ({c.family}, relevance={c.relevance_score:.2f})")

        return candidates


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------


def create_search_tool(**kwargs: Any) -> TavilySearchTool:
    """从环境变量创建搜索工具的便捷函数。"""
    return TavilySearchTool.from_env(**kwargs)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


# 中文结构词：在搜索关键词提取时用于切分长中文片段，保持名词性短语完整
_ZH_SEPARATORS = re.compile(
    r"(?:的|和|与|及|或|在|对|于|请|并|且|使|将|以|为|等|但|而|从|到|按|"
    r"根据|要求|建立|给出|求解|分析|研究|考虑|其中|以及|进行|假定|假设|"
    r"相对|保持|增长|趋势|问题)"
)


def _extract_keywords(text: str, max_keywords: int = 5) -> str:
    """从问题描述中提取关键词。

    支持中文：在结构词/连词处切分长中文片段，保留名词性短语
    （如"各种农作物 预期销售量 种植成本 亩产量"），避免把整段
    中文当作一个"词"导致搜索查询失效。
    """
    if not text:
        return ""

    # 去除标点和特殊字符
    cleaned = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text)

    # 中文停用词
    stop_words = {
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都",
        "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你",
        "会", "着", "没有", "看", "好", "自己", "这", "那", "与", "及",
        "或", "为", "以", "及", "等", "但", "而", "从", "此", "使",
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "to", "of", "in", "on", "at", "by", "for", "with", "about",
        "as", "into", "through", "during", "before", "after",
    }

    # 中文片段在结构词处切分；英文按空格切分
    segments: list[str] = []
    for token in cleaned.split():
        if re.search(r"[\u4e00-\u9fff]", token):
            parts = [p.strip() for p in _ZH_SEPARATORS.split(token)]
            segments.extend(parts)
        else:
            segments.append(token)

    # 过滤停用词、短词与过长的句子片段
    keywords = [
        w for w in segments
        if w.lower() not in stop_words and 2 <= len(w) <= 12
    ]

    # 去重保序，取前 N 个
    seen: set[str] = set()
    unique: list[str] = []
    for w in keywords:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return " ".join(unique[:max_keywords])


def _extract_method_names(title: str, content: str) -> list[str]:
    """从标题和内容中提取方法名称。

    匹配模式：
      - 中文方法：XXX法、XXX模型、XXX算法、XXX分析、XXX规划
      - 英文方法：XXX method, XXX model, XXX algorithm, XXX analysis
      - 缩写方法：TOPSIS, AHP, PCA, SVM, ARIMA, GM(1,1) 等
    """
    names: list[str] = []
    combined = f"{title} {content}"

    # 中文方法模式
    zh_patterns = [
        r"([\u4e00-\u9fff]{2,8}(?:法|模型|算法|分析|规划|评价|决策|优化))",
        r"([\u4e00-\u9fff]{2,6}模糊[\u4e00-\u9fff]{0,4})",
        r"([\u4e00-\u9fff]{2,6}灰色[\u4e00-\u9fff]{0,4})",
    ]
    for pattern in zh_patterns:
        matches = re.findall(pattern, combined)
        names.extend(matches)

    # 英文方法模式
    en_patterns = [
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:method|model|algorithm|analysis|optimization))",
        r"([A-Z]{2,6}(?:\([0-9,]+\))?)",  # 缩写如 TOPSIS, AHP, GM(1,1)
    ]
    for pattern in en_patterns:
        matches = re.findall(pattern, combined)
        # 过滤过短或非方法的缩写
        for m in matches:
            m = m.strip()
            if len(m) >= 2 and m not in {"URL", "API", "PDF", "HTML", "JSON", "XML"}:
                names.append(m)

    # 去重并限制数量
    seen: set[str] = set()
    unique: list[str] = []
    for n in names:
        n = n.strip()
        if n and n not in seen:
            seen.add(n)
            unique.append(n)

    return unique[:8]  # 最多 8 个


def _infer_family(name: str, content: str) -> str:
    """根据方法名称和内容推断方法家族。"""
    name_lower = name.lower()
    content_lower = content.lower()

    family_map = [
        (["熵权", "entropy"], "客观赋权法"),
        (["topsis"], "多属性决策"),
        (["ahp", "层次分析"], "主观赋权法"),
        (["模糊", "fuzzy"], "模糊数学"),
        (["灰色", "grey", "gm("], "灰色系统理论"),
        (["回归", "regression"], "线性模型"),
        (["arima", "时间序列", "time series"], "时间序列模型"),
        (["神经网络", "neural", "bp", "深度学习"], "机器学习"),
        (["支持向量", "svm", "svr"], "机器学习"),
        (["随机森林", "random forest"], "机器学习"),
        (["决策树", "decision tree"], "树模型"),
        (["线性规划", "linear programming", "lp"], "数学规划"),
        (["整数规划", "integer programming"], "数学规划"),
        (["遗传算法", "genetic algorithm", "ga"], "启发式算法"),
        (["粒子群", "particle swarm", "pso"], "启发式算法"),
        (["模拟退火", "simulated annealing"], "启发式算法"),
        (["蚁群", "ant colony", "aco"], "启发式算法"),
        (["蒙特卡洛", "monte carlo"], "随机优化"),
        (["随机规划", "stochastic programming"], "随机优化"),
        (["鲁棒", "robust"], "鲁棒优化"),
        (["微分方程", "differential equation"], "机理模型"),
        (["元胞自动机", "cellular automata"], "仿真模型"),
        (["系统动力学", "system dynamics"], "仿真模型"),
        (["主成分", "pca", "降维"], "降维方法"),
        (["聚类", "cluster", "k-means"], "聚类分析"),
        (["博弈", "game"], "博弈论"),
        (["排队", "queue"], "排队论"),
        (["图论", "graph"], "图论方法"),
        (["马尔可夫", "markov"], "随机过程"),
    ]

    for keywords, family in family_map:
        if any(kw.lower() in name_lower or kw.lower() in content_lower for kw in keywords):
            return family

    return "其他方法"


def _infer_difficulty(name: str, family: str) -> str:
    """根据方法名称和家族推断实现难度。"""
    # 简单方法
    simple_families = {"客观赋权法", "主观赋权法", "多属性决策", "线性模型", "数学规划", "灰色系统理论"}
    if family in simple_families:
        return "low"

    # 复杂方法
    complex_families = {"机器学习", "随机优化", "鲁棒优化", "机理模型"}
    if family in complex_families:
        return "high"

    # 中等方法
    return "medium"


def _extract_pros(content: str) -> list[str]:
    """从内容中提取优点。"""
    pros: list[str] = []

    # 匹配 "优点：..." 或 "优势：..." 或 "pros: ..."
    patterns = [
        r"(?:优点|优势|优点包括|优点是)[:：\s]*(.*?)(?:缺点|劣势|cons|不足|$)",
        r"(?:advantages?|pros)[:：\s]*(.*?)(?:disadvantages?|cons|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if match:
            text = match.group(1).strip()
            # 按分号或换行分割
            items = re.split(r"[；;\n]", text)
            pros.extend([item.strip() for item in items if item.strip() and len(item.strip()) > 2])
            break

    return pros[:3]  # 最多 3 条


def _extract_cons(content: str) -> list[str]:
    """从内容中提取缺点。"""
    cons: list[str] = []

    patterns = [
        r"(?:缺点|劣势|缺点包括|缺点是|不足)[:：\s]*(.*?)(?:优点|优势|pros|适用|$)",
        r"(?:disadvantages?|cons|limitations?)[:：\s]*(.*?)(?:advantages?|pros|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if match:
            text = match.group(1).strip()
            items = re.split(r"[；;\n]", text)
            cons.extend([item.strip() for item in items if item.strip() and len(item.strip()) > 2])
            break

    return cons[:3]  # 最多 3 条
