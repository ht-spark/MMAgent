"""数学建模报告统一模板。

设计原则：「公共骨架 + 可伸缩问题章节」结构，用于引导 LLM 撰写报告：

  - 公共骨架：摘要、问题重述、问题分析与技术路线、模型假设、
    符号说明、模型评价与推广、参考文献、附录。
  - 问题章节：按任务的子问题数量动态生成。章节的实际组织应由题目、
    已归档的模型、计算结果和图表决定，不预设题型、方法或公式位置。

对外接口：
    UNIFIED_TEMPLATE          统一模板（公共骨架部分）
    build_paper_outline(n)    生成含 n 个问题的完整章节大纲
    render_outline_prompt(n)  生成可直接注入 LLM 的写作引导提示词
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "SectionSpec",
    "PaperTemplate",
    "UNIFIED_TEMPLATE",
    "build_problem_section",
    "build_paper_outline",
    "render_outline_prompt",
    # 兼容旧接口（已废弃，统一返回同一套结构）
    "get_template",
    "get_all_section_titles",
    "get_writing_guide_summary",
]

_CN_NUM = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]


def _cn_num(n: int) -> str:
    """1 -> 一, 2 -> 二 ...（超出范围时退回阿拉伯数字）"""
    return _CN_NUM[n] if 0 < n < len(_CN_NUM) else str(n)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionSpec:
    """章节规格。

    Attributes:
        section_id: 章节编号（如 "1"、"4"、"ref"）。
        title: 章节标题。
        writing_guide: 写作指导（该章节应包含什么内容、如何组织）。
        min_words: 建议最少字数。
        required: 是否必需章节。
    """

    section_id: str
    title: str
    writing_guide: str
    min_words: int = 200
    required: bool = True


@dataclass(frozen=True)
class PaperTemplate:
    """报告模板（统一结构，公共骨架部分）。

    Attributes:
        name: 模板名称。
        fixed_sections: 公共骨架章节（问题章节之外的部分）。
        abstract_guide: 摘要写作指导。
        keyword_suggestions: 关键词建议。
        writing_tips: 整体写作建议。
    """

    name: str
    fixed_sections: list[SectionSpec]
    abstract_guide: str
    keyword_suggestions: list[str] = field(default_factory=list)
    writing_tips: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 公共骨架：问题重述 / 问题分析 / 假设 / 符号 / 评价 / 参考文献 / 附录
# ---------------------------------------------------------------------------

_SECTION_PROBLEM_RESTATEMENT = SectionSpec(
    section_id="1",
    title="问题重述",
    writing_guide=(
        "1.1 问题背景：阐述问题的现实背景（政策、行业、技术或学术背景），说明研究意义。\n"
        "1.2 问题提出：用自己的语言重述任务，逐条列出各子问题，明确每个问题的已知条件、约束与求解目标。\n"
        "注意：不要照抄任务原文，重述后的问题应能直接对应后文的章节安排。"
    ),
    min_words=400,
)

_SECTION_PROBLEM_ANALYSIS = SectionSpec(
    section_id="2",
    title="问题分析与总体思路",
    writing_guide=(
        "2.1 逐问分析：围绕题设对象、已知条件、关键约束和所需输出，说明问题之间的逻辑关系。\n"
        "2.2 总体思路：说明各子问题之间的逻辑关系（递进、并行还是前后衔接），以及前一问的结果如何被后一问使用。\n"
        "2.3 技术路线图：给出一张技术路线图（流程图），展示从问题出发到最终结论的完整研究路径。"
    ),
    min_words=300,
)

_SECTION_ASSUMPTIONS = SectionSpec(
    section_id="3",
    title="模型假设",
    writing_guide=(
        "列出建模所需的全部假设条件，要求：\n"
        "- 每条假设附一句合理性说明（依据任务条件、常识或文献）；\n"
        "- 假设要覆盖所有后文模型，不要出现模型用了却未声明的隐含假设；\n"
        "- 假设要适度：过度简化会削弱结果可信度，过少简化会让模型不可解。"
    ),
    min_words=150,
)

_SECTION_NOTATIONS = SectionSpec(
    section_id="4",
    title="符号说明",
    writing_guide=(
        "用三线表列出全文所有数学符号，建议按类别分组：下标/索引 → 集合与参数 → 决策变量 → 常量。\n"
        "每个符号标注含义和单位（无单位则注明『无量纲』）。只列贯穿全文的公共符号，"
        "仅在某一小节临时使用的符号可在该小节内说明。"
    ),
    min_words=100,
)

_SECTION_EVALUATION = SectionSpec(
    section_id="eval",
    title="模型评价与推广",
    writing_guide=(
        "模型优点：从建模思想、算法效率、结果可靠性等角度总结，结合本文具体结果谈，避免空话。\n"
        "模型缺点：如实说明局限性（假设的影响、未考虑的因素、计算代价等）。\n"
        "改进与推广：针对缺点给出可行的改进方向，并说明模型可推广到哪些同类实际问题。"
    ),
    min_words=200,
)

_SECTION_REFERENCES = SectionSpec(
    section_id="ref",
    title="参考文献",
    writing_guide=(
        "按正文引用顺序编号列出，格式统一（GB/T 7714）。"
        "正文中引用处用 [n] 标注，确保每条文献都被正文引用过。"
    ),
    min_words=50,
)

_SECTION_APPENDIX = SectionSpec(
    section_id="app",
    title="附录",
    writing_guide=(
        "附录A：核心求解代码（含必要注释）与运行环境说明。\n"
        "附录B：补充图表、中间结果数据。\n"
        "附录C：冗长推导的补充（正文只保留关键步骤）。"
    ),
    min_words=100,
    required=False,
)

# 公共骨架中位于问题章节之前 / 之后的部分
_PRE_PROBLEM_SECTIONS: list[SectionSpec] = [
    _SECTION_PROBLEM_RESTATEMENT,
    _SECTION_PROBLEM_ANALYSIS,
    _SECTION_ASSUMPTIONS,
    _SECTION_NOTATIONS,
]

_POST_PROBLEM_SECTIONS: list[SectionSpec] = [
    _SECTION_EVALUATION,
    _SECTION_REFERENCES,
    _SECTION_APPENDIX,
]


# ---------------------------------------------------------------------------
# 问题章节生成器：统一的五段式写法，与题型无关
# ---------------------------------------------------------------------------

_PROBLEM_SECTION_GUIDE = (
    "本问围绕实际建模证据组织：先交代本问目标及与题设的对应关系；"
    "再说明已建立的变量、关系、方程或约束；随后呈现实际求解得到的表格、图形和关键数值；"
    "最后说明已有验证证据及适用边界。\n"
    "仅在模型确有对应内容时展示公式、数据处理、算法步骤或检验；不得按预设题型补写，"
    "不得把内部探索过程或方法比选写入交付报告。"
)


def build_problem_section(problem_index: int, section_number: int | None = None) -> SectionSpec:
    """生成第 problem_index 个子问题的章节规格。

    Args:
        problem_index: 子问题序号（从 1 开始）。
        section_number: 章节编号；默认在公共骨架（4 章）之后顺排，
            即问题一为第 5 章。

    Returns:
        该问题的 SectionSpec，写作指导为统一五段式。
    """
    if problem_index < 1:
        raise ValueError("problem_index 从 1 开始")
    num = section_number if section_number is not None else len(_PRE_PROBLEM_SECTIONS) + problem_index
    return SectionSpec(
        section_id=str(num),
        title=f"问题{_cn_num(problem_index)}的建模与求解",
        writing_guide=_PROBLEM_SECTION_GUIDE.format(i=num),
        min_words=600,
    )


def build_paper_outline(num_problems: int) -> list[SectionSpec]:
    """生成含 num_problems 个子问题的完整报告大纲。

    Args:
        num_problems: 任务的子问题数量（通常为 3~6）。

    Returns:
        完整章节列表：公共骨架（前 4 章）+ 各问题章节 + 公共骨架（评价/文献/附录）。
    """
    if num_problems < 1:
        raise ValueError("num_problems 至少为 1")
    problems = [build_problem_section(i) for i in range(1, num_problems + 1)]
    return [*_PRE_PROBLEM_SECTIONS, *problems, *_POST_PROBLEM_SECTIONS]


# ---------------------------------------------------------------------------
# 统一模板
# ---------------------------------------------------------------------------

UNIFIED_TEMPLATE = PaperTemplate(
    name="数学建模竞赛报告统一模板",
    fixed_sections=[
        *_PRE_PROBLEM_SECTIONS,
        *_POST_PROBLEM_SECTIONS,
    ],
    abstract_guide=(
        "摘要结构（约 500~800 字，是全文最重要的部分，最后撰写）：\n"
        "1. 一句话概括问题背景与研究目标。\n"
        "2. 针对问题一：模型的关键关系、实际求解过程与具体数值结果（2~3 句）。\n"
        "3. 针对其余各问：同上，每问 2~3 句，必须含具体数值结论。\n"
        "4. 一至两句总结模型的特点、创新点与实用价值。\n"
        "5. 关键词：3~5 个，使用题设对象、核心变量或已建立的模型概念，用分号分隔。\n"
        "要点：摘要中禁止出现『见正文』『效果较好』等无信息量表述；"
        "每个数值结果必须与对应问题章节中的结果一致。"
    ),
    keyword_suggestions=[
        "使用题设对象和核心模型概念",
        "3~5 个，分号分隔",
    ],
    writing_tips=[
        "结构闭环：摘要中的每个结论都能在某个问题章节中找到出处，反之亦然",
        "公式规范：所有公式统一编号，正文引用公式编号，重要公式需解释符号含义与推导依据",
        "图表规范：每个图表都有编号和标题，正文中先引用后呈现，图表数据与文字结论一致",
        "证据优先：只写入已归档的模型关系、计算输出、图表与验证信息；未记录的内容不得补写",
        "结果量化：结论必须给出具体数值（误差百分比、利用率、预测值等），而非定性描述",
        "检验必备：每问结果都要有可信度支撑——敏感性分析、误差分析或仿真对比至少其一",
        "问题衔接：若后一问依赖前一问的结果，在章节开头明确说明承接关系",
        "篇幅分配：问题章节是主体（约占全文 60~70%），问题数量多时避免各问详略失衡",
    ],
)


# ---------------------------------------------------------------------------
# LLM 提示词渲染
# ---------------------------------------------------------------------------


def render_outline_prompt(num_problems: int) -> str:
    """生成可直接注入 LLM 的报告写作引导提示词。

    Args:
        num_problems: 任务的子问题数量。

    Returns:
        完整的写作引导文本（大纲 + 各章写作指导 + 摘要指导 + 方法库 + 写作要点）。
    """
    sections = build_paper_outline(num_problems)
    lines: list[str] = [
        "# 数学建模竞赛报告写作引导",
        "",
        f"本文共 {num_problems} 个子问题，请严格按以下章节结构撰写：",
        "",
        "## 章节结构与写作要求",
    ]
    for idx, s in enumerate(sections, start=1):
        # 章节编号：数字 section_id 直接用；收尾章节（eval/ref/app）按位置顺排，
        # 避免渲染出 "### eval. 模型评价与推广" 这类非编号标题。
        num = s.section_id if s.section_id.isdigit() else str(idx)
        required_mark = "（必需）" if s.required else "（可选）"
        lines.append(f"### {num}. {s.title} {required_mark} 建议不少于 {s.min_words} 字")
        lines.append(s.writing_guide)
        lines.append("")

    lines.append("## 摘要写作要求")
    lines.append(UNIFIED_TEMPLATE.abstract_guide)
    lines.append("")

    lines.append("## 全局写作要点")
    for tip in UNIFIED_TEMPLATE.writing_tips:
        lines.append(f"- {tip}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 兼容旧接口（已废弃）：无论传入什么题型都返回统一模板
# ---------------------------------------------------------------------------


def get_template(problem_type: str = "") -> PaperTemplate:
    """获取报告模板。统一模板不分题型，参数仅作兼容保留，将被忽略。"""
    return UNIFIED_TEMPLATE


def get_all_section_titles(problem_type: str = "") -> list[str]:
    """获取公共骨架的章节标题列表（不含动态问题章节）。"""
    return [s.title for s in UNIFIED_TEMPLATE.fixed_sections]


def get_writing_guide_summary(problem_type: str = "") -> str:
    """获取写作引导摘要（默认按 4 个子问题渲染）。"""
    return render_outline_prompt(num_problems=4)
