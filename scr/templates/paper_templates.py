"""数学建模竞赛论文模板
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "PaperTemplate",
    "SectionSpec",
    "get_template",
    "get_template_by_problem_text",
    "ALL_TEMPLATES",
]


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionSpec:
    """章节规格。

    Attributes:
        section_id: 章节编号（如 "1", "4.1"）。
        title: 章节标题模板。
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
    """论文模板。

    Attributes:
        problem_type: 题型标识（A/B/C/D/E/F）。
        problem_type_name: 题型中文名称。
        category: 题型类别（如"机理建模/仿真类"）。
        sections: 推荐章节列表。
        abstract_guide: 摘要写作指导。
        keyword_suggestions: 关键词建议列表。
        method_preferences: 方法偏好（该题型常用的数学方法）。
        writing_tips: 整体写作建议列表。
        example_title: 示例题目（来源论文的题目）。
    """

    problem_type: str
    problem_type_name: str
    category: str
    sections: list[SectionSpec]
    abstract_guide: str
    keyword_suggestions: list[str]
    method_preferences: list[str]
    writing_tips: list[str]
    example_title: str


# ---------------------------------------------------------------------------
# A 题：机理建模/仿真类
# ---------------------------------------------------------------------------

TEMPLATE_A = PaperTemplate(
    problem_type="A",
    problem_type_name="A题",
    category="机理建模/仿真类",
    example_title="WLAN网络信道接入机制建模",
    sections=[
        SectionSpec(
            section_id="1",
            title="问题重述",
            writing_guide=(
                "1.1 问题背景：阐述问题的现实背景和技术背景，引出研究目标。\n"
                "1.2 问题描述：逐条列出题目要求的各个子问题，明确每个问题的假设条件和求解目标。"
            ),
            min_words=400,
        ),
        SectionSpec(
            section_id="2",
            title="模型假设与符号说明",
            writing_guide=(
                "2.1 模型假设：列出建模所需的所有假设条件，每条假设需说明合理性。\n"
                "2.2 符号说明：用三线表列出所有数学符号及其含义，按类别分组（参数/变量/下标/常量）。"
            ),
            min_words=200,
        ),
        SectionSpec(
            section_id="3",
            title="问题分析与求解思路",
            writing_guide=(
                "3.1 问题分析：逐一分析每个子问题的难点和求解方向。\n"
                "3.2 求解思路：给出总体技术路线，说明各问题之间的逻辑关系和递进关系。\n"
                "建议绘制技术路线图（流程图），展示从基本模型到复杂场景的推广路径。"
            ),
            min_words=300,
        ),
        SectionSpec(
            section_id="4",
            title="基本模型",
            writing_guide=(
                "建立问题所需的基础数学模型，为后续各问提供公共理论基础。\n"
                "典型内容：核心数学公式推导、模型参数定义、理论分析（如概率计算、稳态分析）。\n"
                "此章节是全文的理论核心，需严谨推导每个公式，标注公式编号。"
            ),
            min_words=500,
        ),
        SectionSpec(
            section_id="5",
            title="问题一的分析与求解",
            writing_guide=(
                "5.1 问题分析：针对问题一的具体场景进行分析。\n"
                "5.2 模型建立：将基本模型应用于问题一，给出具体参数和公式。\n"
                "5.3 模型理论求解：通过数学推导得到理论结果（解析解或数值解）。\n"
                "5.4 模型仿真验证：编写仿真器进行验证，对比理论值与仿真值的误差。\n"
                "关键：理论值与仿真值的对比表格，误差分析。"
            ),
            min_words=600,
        ),
        SectionSpec(
            section_id="6",
            title="问题二的分析与求解",
            writing_guide=(
                "在问题一基础上推广模型，处理更复杂的场景。\n"
                "结构同问题一：问题分析 → 模型建立 → 理论求解 → 仿真验证。\n"
                "重点说明与问题一的区别和推广方向。"
            ),
            min_words=500,
        ),
        SectionSpec(
            section_id="7",
            title="问题三的分析与求解",
            writing_guide=(
                "继续推广模型，处理更复杂的场景（如引入新约束、新参数）。\n"
                "结构同前，如有多种子场景需分小节讨论。\n"
                "重点分析新引入的因素对模型结果的影响。"
            ),
            min_words=500,
        ),
        SectionSpec(
            section_id="8",
            title="问题四的分析与求解",
            writing_guide=(
                "处理最复杂的场景（如扩展到更大规模系统）。\n"
                "结构同前，如有多种情况需分类讨论。\n"
                "给出系统级的性能分析和评价。"
            ),
            min_words=500,
        ),
        SectionSpec(
            section_id="9",
            title="模型评价",
            writing_guide=(
                "9.1 模型的优点：理论贡献和实用价值。\n"
                "9.2 模型的缺点：局限性和未考虑的因素。\n"
                "9.3 未来的展望：改进方向和扩展可能。"
            ),
            min_words=200,
        ),
        SectionSpec(
            section_id="ref",
            title="参考文献",
            writing_guide="按引用顺序列出参考文献，格式规范统一。",
            min_words=50,
        ),
        SectionSpec(
            section_id="app",
            title="附录",
            writing_guide=(
                "附录A：仿真器程序与运行说明。\n"
                "附录B：关键求解代码。\n"
                "附录C：补充图表和数据。"
            ),
            min_words=100,
            required=False,
        ),
    ],
    abstract_guide=(
        "摘要结构（约500-800字）：\n"
        "1. 一句话概括研究背景和目标。\n"
        "2. 针对问题一：简述方法、关键公式/模型、理论结果和仿真验证结果（含具体数值和误差）。\n"
        "3. 针对问题二~四：同上，每问2-3句话。\n"
        "4. 总结模型特点和创新点。\n"
        "5. 关键词：3-5个，用分号分隔。\n"
        "要点：摘要中必须包含具体的数值结果，体现理论值与仿真值的对比。"
    ),
    keyword_suggestions=[
        "马尔科夫链", "概率模型", "仿真验证", "吞吐量分析",
        "理论推导", "离散事件仿真", "性能分析", "冲突概率",
    ],
    method_preferences=[
        "马尔科夫链模型", "概率论与随机过程", "离散事件仿真",
        "数值分析", "蒙特卡洛模拟", "排队论",
    ],
    writing_tips=[
        "理论推导必须严谨，每个公式都要有编号并在正文中引用",
        "仿真验证是关键：理论值与仿真值的对比表格必不可少",
        "模型推广要有逻辑递进：从简单场景到复杂场景逐步推广",
        "统一模型思路：尝试建立适用于所有场景的统一公式",
        "仿真器需说明可扩展性和可复用性",
        "误差分析要具体：给出误差百分比和原因分析",
    ],
)


# ---------------------------------------------------------------------------
# B 题：优化/排样类
# ---------------------------------------------------------------------------

TEMPLATE_B = PaperTemplate(
    problem_type="B",
    problem_type_name="B题",
    category="优化/排样类",
    example_title="方形件排布优化与组批问题",
    sections=[
        SectionSpec(
            section_id="1",
            title="问题重述",
            writing_guide=(
                "阐述问题的工业背景（如智能制造、材料切割），\n"
                "明确优化目标（如最小化耗材、最大化利用率），\n"
                "逐条列出各子问题的约束条件和求解要求。"
            ),
            min_words=300,
        ),
        SectionSpec(
            section_id="2",
            title="问题分析",
            writing_guide=(
                "2.1 问题一分析：分析优化目标和约束条件，说明建模思路。\n"
                "2.2 问题二分析：在问题一基础上新增的约束和求解策略。\n"
                "重点：逆推思维（将切割问题转化为组合问题）、分阶段求解策略。"
            ),
            min_words=300,
        ),
        SectionSpec(
            section_id="3",
            title="模型假设",
            writing_guide=(
                "列出所有简化假设，每条假设需与题目条件对应。\n"
                "典型假设：材料均匀、切割方式限定、产品独立性等。"
            ),
            min_words=150,
        ),
        SectionSpec(
            section_id="4",
            title="符号说明",
            writing_guide=(
                "用三线表列出所有符号，按类别分组：\n"
                "下标（编号类）→ 变量（尺寸/距离类）→ 虚拟变量（0-1决策变量）→ 常量。\n"
                "每个符号需标注单位和含义。"
            ),
            min_words=100,
        ),
        SectionSpec(
            section_id="5",
            title="模型的建立与求解",
            writing_guide=(
                "5.1 问题一：混合整数规划模型的排样优化\n"
                "  5.1.1 模型建立：目标函数 + 约束条件（含公式编号）\n"
                "  5.1.2 求解算法：迭代法/启发式算法的设计\n"
                "  5.1.3 结果分析：板材利用率、最优切割方案\n"
                "5.2 问题二：组批优化模型\n"
                "  5.2.1 模型建立：聚类+排样的两阶段模型\n"
                "  5.2.2 求解算法：K-Means聚类+迭代法\n"
                "  5.2.3 结果分析：批次划分结果和利用率\n"
                "关键：目标函数公式、约束条件公式、算法流程图。"
            ),
            min_words=800,
        ),
        SectionSpec(
            section_id="6",
            title="模型评价与改进",
            writing_guide=(
                "6.1 模型优点：算法特点（如自行封装、运算速度快）。\n"
                "6.2 模型缺点：局限性分析。\n"
                "6.3 推广应用：对其他领域（PCB、家具、家电）的参考价值。"
            ),
            min_words=200,
        ),
        SectionSpec(
            section_id="ref",
            title="参考文献",
            writing_guide="按引用顺序列出，格式规范。",
            min_words=50,
        ),
        SectionSpec(
            section_id="app",
            title="附录",
            writing_guide="关键算法代码和运行说明。",
            min_words=100,
            required=False,
        ),
    ],
    abstract_guide=(
        "摘要结构（约400-600字）：\n"
        "1. 一句话概括方法和目标。\n"
        "2. 问题一：建模方法、目标函数、求解算法、关键结果（如利用率百分比）。\n"
        "3. 问题二：新增约束、聚类方法、求解策略、关键结果。\n"
        "4. 代码特点和实用价值。\n"
        "5. 关键词：3-5个。"
    ),
    keyword_suggestions=[
        "混合整数规划", "迭代法", "K-Means聚类", "排样优化",
        "组批问题", "板材利用率", "启发式算法", "下料问题",
    ],
    method_preferences=[
        "混合整数规划", "迭代法", "K-Means聚类", "启发式算法",
        "动态规划", "贪心算法", "列生成算法",
    ],
    writing_tips=[
        "目标函数和约束条件必须用公式编号明确标注",
        "虚拟变量（0-1变量）的定义和使用要清晰",
        "算法流程图是必备的，展示求解步骤",
        "结果需用表格展示板材利用率和切割方案",
        "自行编写的算法需强调运算速度和可修改性",
        "推广价值要联系实际工业应用场景",
    ],
)


# ---------------------------------------------------------------------------
# C 题：评价/规划类
# ---------------------------------------------------------------------------

TEMPLATE_C = PaperTemplate(
    problem_type="C",
    problem_type_name="C题",
    category="评价/规划类",
    example_title="大规模创新类竞赛评审方案研究",
    sections=[
        SectionSpec(
            section_id="1",
            title="问题重述",
            writing_guide=(
                "1.1 问题背景：阐述评审问题的现实背景和挑战。\n"
                "1.2 问题提出：逐条列出各子问题。"
            ),
            min_words=300,
        ),
        SectionSpec(
            section_id="2",
            title="总体技术路线图",
            writing_guide=(
                "绘制全文的技术路线图，展示各问题之间的逻辑关系。\n"
                "说明总体研究框架和各问题采用的方法。"
            ),
            min_words=100,
        ),
        SectionSpec(
            section_id="3",
            title="符号说明",
            writing_guide="用三线表列出所有符号及其含义。",
            min_words=100,
        ),
        SectionSpec(
            section_id="4",
            title="问题一：交叉分发方案研究",
            writing_guide=(
                "4.1 问题描述与分析：明确优化目标和约束。\n"
                "4.2 模型建立：数学规划模型（0-1变量、目标函数、约束条件）。\n"
                "4.3 模型评价指标：定义评价方案质量的指标（如均衡性、交叉值）。\n"
                "4.4 模型求解：算法设计（如NSGA-II）、算法步骤和流程图。\n"
                "4.5 求解结果与分析：结果表格、可视化分析。"
            ),
            min_words=600,
        ),
        SectionSpec(
            section_id="5",
            title="问题二：评审方案设计与标准分改进",
            writing_guide=(
                "5.1 问题描述与分析。\n"
                "5.2 数据预处理：数据转换、分布特征分析、评价指标确立。\n"
                "5.3 标准分计算模型：线性回归建模、模型评估、模型改进。\n"
                "5.4 调整后成绩分析：分布特征、获奖等级对比。\n"
                "关键：回归模型公式、评价指标体系、调整前后对比。"
            ),
            min_words=600,
        ),
        SectionSpec(
            section_id="6",
            title="问题三：基于机器学习的极差模型",
            writing_guide=(
                "6.1 问题描述与分析。\n"
                "6.2 数据预处理与探索分析。\n"
                "6.3 评价指标确立。\n"
                "6.4 模型建立：多算法对比（线性回归/决策树/随机森林/XGBoost），选择最优。\n"
                "6.5 模型训练与评估。\n"
                "6.6 极差调整与相关性分析。"
            ),
            min_words=500,
        ),
        SectionSpec(
            section_id="7",
            title="问题四：评审模型建立与求解",
            writing_guide=(
                "7.1 问题描述与分析。\n"
                "7.2 两阶段模型建立：第一阶段筛选+第二阶段优化。\n"
                "7.3 模型求解：算法设计、算法步骤。\n"
                "7.4 求解结果与分析：实验设计、结果展示。"
            ),
            min_words=500,
        ),
        SectionSpec(
            section_id="8",
            title="模型评价与改进",
            writing_guide=(
                "8.1 模型和算法的优点。\n"
                "8.2 模型改进和展望。"
            ),
            min_words=200,
        ),
        SectionSpec(
            section_id="ref",
            title="参考文献",
            writing_guide="按引用顺序列出。",
            min_words=50,
        ),
    ],
    abstract_guide=(
        "摘要结构（约500-800字）：\n"
        "1. 背景和目标（1-2句）。\n"
        "2. 问题一：模型类型、算法、关键结果数值。\n"
        "3. 问题二：分析方法、关键公式/模型、改进效果。\n"
        "4. 问题三：算法对比、选择结果、相关性发现。\n"
        "5. 问题四：两阶段模型、算法、关键结果。\n"
        "6. 关键词：3-5个。"
    ),
    keyword_suggestions=[
        "NSGA-II", "线性回归", "随机森林", "XGBoost",
        "多目标优化", "评价指标体系", "标准分模型", "两阶段评审",
    ],
    method_preferences=[
        "NSGA-II", "线性回归", "决策树", "随机森林", "XGBoost",
        "层次分析法", "TOPSIS", "熵权法", "数学规划",
    ],
    writing_tips=[
        "总体技术路线图是必备的，展示研究全貌",
        "评价指标体系需要完整，每个指标需说明定义和计算方法",
        "多算法对比时需用表格展示各算法的性能指标",
        "数据预处理和特征分析要详细，体现数据驱动的特点",
        "模型公式需有编号，回归方程要写具体",
        "两阶段模型需清晰说明各阶段的目标和约束",
    ],
)


# ---------------------------------------------------------------------------
# D 题：预测/规划类
# ---------------------------------------------------------------------------

TEMPLATE_D = PaperTemplate(
    problem_type="D",
    problem_type_name="D题",
    category="预测/规划类",
    example_title="基于碳排放时序分析的区域双碳目标与路径规划",
    sections=[
        SectionSpec(
            section_id="1",
            title="问题重述",
            writing_guide=(
                "1.1 问题背景：宏观政策背景（如双碳目标）、现实意义。\n"
                "1.2 问题提出：逐条列出各子问题。"
            ),
            min_words=400,
        ),
        SectionSpec(
            section_id="2",
            title="总体技术路线图",
            writing_guide="绘制技术路线图，展示从现状分析到预测再到规划的逻辑链条。",
            min_words=100,
        ),
        SectionSpec(
            section_id="3",
            title="基本假设与符号说明",
            writing_guide=(
                "3.1 基本假设：建模假设条件。\n"
                "3.2 符号说明：三线表列出所有符号。"
            ),
            min_words=150,
        ),
        SectionSpec(
            section_id="4",
            title="问题一：现状分析",
            writing_guide=(
                "4.1 问题分析。\n"
                "4.2 数据预处理：缺失值处理、数据清洗。\n"
                "4.3 指标体系建立：构建原则→构建方法→初始指标→指标筛选→最终指标。\n"
                "4.4 基于指标的区域现状分析：趋势分析、相关性分析。\n"
                "4.5 关联模型建立与分析：影响因素分析、主要挑战。\n"
                "关键：指标体系表格、相关性矩阵、趋势图。"
            ),
            min_words=700,
        ),
        SectionSpec(
            section_id="5",
            title="问题二：预测模型",
            writing_guide=(
                "5.1 问题分析与数据观察。\n"
                "5.2 人口/经济预测模型：Logistic回归/时序分析。\n"
                "5.3 能源消费预测模型：分部门预测。\n"
                "5.4 碳排放预测模型：碳排放因子×能源消费量。\n"
                "5.5 预测结果分析：关键年份的预测值。\n"
                "关键：预测模型公式、预测值表格、预测趋势图。"
            ),
            min_words=700,
        ),
        SectionSpec(
            section_id="6",
            title="问题三：目标与路径规划",
            writing_guide=(
                "6.1 问题分析。\n"
                "6.2 情景设计：自然情景/基准情景/雄心情景。\n"
                "6.3 多情景模型建立：各情景的参数设定。\n"
                "6.4 模型求解：各情景下的预测结果。\n"
                "6.5 措施分析：能效提升、产业升级、能源脱碳等。\n"
                "关键：情景参数表、各情景对比图、路径规划表。"
            ),
            min_words=600,
        ),
        SectionSpec(
            section_id="7",
            title="模型评价与改进",
            writing_guide="7.1 模型评价。7.2 模型改进。",
            min_words=200,
        ),
        SectionSpec(
            section_id="ref",
            title="参考文献",
            writing_guide="按引用顺序列出。",
            min_words=50,
        ),
        SectionSpec(
            section_id="app",
            title="附录",
            writing_guide="补充数据表、图表和代码。",
            min_words=100,
            required=False,
        ),
    ],
    abstract_guide=(
        "摘要结构（约600-1000字）：\n"
        "1. 政策背景和研究目标（2-3句）。\n"
        "2. 问题一：指标体系方法、相关性分析结果、主要影响因素。\n"
        "3. 问题二：预测模型方法、关键年份预测值（含具体数值）。\n"
        "4. 问题三：情景设计、各情景目标值、路径规划措施。\n"
        "5. 关键词：3-5个。"
    ),
    keyword_suggestions=[
        "时间序列分析", "Logistic回归", "指标体系", "情景分析",
        "碳排放预测", "路径规划", "相关性分析", "随机森林",
    ],
    method_preferences=[
        "时间序列ARIMA", "Logistic回归", "随机森林", "灰色预测GM(1,1)",
        "指标体系构建", "皮尔森相关系数", "情景分析", "多元回归",
    ],
    writing_tips=[
        "指标体系构建是核心，需说明构建原则和筛选过程",
        "数据预处理要详细：缺失值处理方法、异常值检测",
        "预测模型需给出具体预测值，不能只有趋势描述",
        "情景设计需有明确依据，各情景参数需用表格对比",
        "趋势图和相关性热力图是必备可视化",
        "关键年份的数值需在摘要和正文中都出现",
    ],
)


# ---------------------------------------------------------------------------
# E 题：机理/预测/优化综合类
# ---------------------------------------------------------------------------

TEMPLATE_E = PaperTemplate(
    problem_type="E",
    problem_type_name="E题",
    category="机理/预测/优化综合类",
    example_title="草原放牧策略研究",
    sections=[
        SectionSpec(
            section_id="1",
            title="问题简介",
            writing_guide=(
                "1.1 问题背景：阐述问题的生态/环境背景，说明研究意义。\n"
                "1.2 问题重述：逐条列出各子问题（通常5-6个）。"
            ),
            min_words=400,
        ),
        SectionSpec(
            section_id="2",
            title="问题分析",
            writing_guide=(
                "对每个子问题逐一分析，说明求解思路和方法选择依据。\n"
                "2.1~2.6 分别对应问题一~六的分析。\n"
                "重点：方法选择需有依据（如数据特点→方法选择）。"
            ),
            min_words=300,
        ),
        SectionSpec(
            section_id="3",
            title="模型假设与符号说明",
            writing_guide=(
                "3.1 模型假设：所有假设条件。\n"
                "3.2 符号说明：三线表列出符号。"
            ),
            min_words=150,
        ),
        SectionSpec(
            section_id="4",
            title="问题一模型建立与求解",
            writing_guide=(
                "4.1 数据处理：数据清洗、标准化。\n"
                "4.2 模型建立：如微分方程模型。\n"
                "4.3 结果与分析：分因素讨论，含图表。\n"
                "典型方法：微分方程描述动态变化。"
            ),
            min_words=400,
        ),
        SectionSpec(
            section_id="5",
            title="问题二模型建立与求解",
            writing_guide=(
                "5.1 数据处理。\n"
                "5.2 预测模型：如LSTM时间序列模型。\n"
                "  模型介绍 → 模型构建 → 预测结果。\n"
                "5.3 结果与分析：预测值表格、预测趋势图。"
            ),
            min_words=400,
        ),
        SectionSpec(
            section_id="6",
            title="问题三模型建立与求解",
            writing_guide=(
                "6.1 数据处理。\n"
                "6.2 模型建立：如ARIMA时间序列模型，可结合回归模型。\n"
                "6.3 结果与讨论：多维度分析（如不同放牧强度对比的箱线图）。"
            ),
            min_words=400,
        ),
        SectionSpec(
            section_id="7",
            title="问题四模型建立与求解",
            writing_guide=(
                "7.1 数据处理。\n"
                "7.2 模型建立：如主成分分析+综合评价模型。\n"
                "7.3 结果与讨论：模型参数、预测结果。"
            ),
            min_words=400,
        ),
        SectionSpec(
            section_id="8",
            title="问题五模型建立与求解",
            writing_guide=(
                "8.1 数据处理。\n"
                "8.2 模型建立：如目标规划模型，求解最优策略。\n"
                "8.3 结果与讨论：最优解、阈值分析。"
            ),
            min_words=300,
        ),
        SectionSpec(
            section_id="9",
            title="问题六模型建立与求解",
            writing_guide=(
                "9.1 数据处理。\n"
                "9.2 模型建立：如时间序列预测+可视化。\n"
                "9.3 结果与讨论：预测结果图示、变化趋势分析。"
            ),
            min_words=300,
        ),
        SectionSpec(
            section_id="10",
            title="总结与评价",
            writing_guide="10.1 模型优点。10.2 模型缺点及改进方向。",
            min_words=200,
        ),
        SectionSpec(
            section_id="ref",
            title="参考文献",
            writing_guide="按引用顺序列出。",
            min_words=50,
        ),
    ],
    abstract_guide=(
        "摘要结构（约500-800字）：\n"
        "1. 背景和意义（1-2句）。\n"
        "2. 问题一：建模方法、关键发现。\n"
        "3. 问题二：预测方法、预测结果。\n"
        "4. 问题三：建模方法、预测结果。\n"
        "5. 问题四：建模方法、关键结论。\n"
        "6. 问题五：优化方法、最优解。\n"
        "7. 问题六：预测方法、趋势结论。\n"
        "8. 关键词：4-6个。"
    ),
    keyword_suggestions=[
        "微分方程", "LSTM", "ARIMA", "主成分分析",
        "熵值法", "目标规划", "时间序列预测", "综合评价",
    ],
    method_preferences=[
        "微分方程模型", "LSTM", "ARIMA", "主成分分析",
        "熵权法", "目标规划", "回归分析", "时间序列预测",
    ],
    writing_tips=[
        "E题通常子问题多（5-6个），每个问题的方法可能不同",
        "方法选择需有依据：说明为什么选这个方法而非其他",
        "数据处理要详细：标准化方法、缺失值处理",
        "不同问题之间可能有递进关系，需说明关联",
        "多种方法综合使用时，需说明各方法的协同关系",
        "箱线图、折线图、热力图等可视化要丰富",
    ],
)


# ---------------------------------------------------------------------------
# F 题：综合/优化类
# ---------------------------------------------------------------------------

TEMPLATE_F = PaperTemplate(
    problem_type="F",
    problem_type_name="F题",
    category="综合/优化类",
    example_title="COVID-19疫情期间生活物资的科学管理问题建模与优化",
    sections=[
        SectionSpec(
            section_id="1",
            title="问题重述",
            writing_guide=(
                "1.1 问题背景：阐述问题的社会背景和现实挑战。\n"
                "1.2 问题提出：逐条列出各子问题及其子问题。"
            ),
            min_words=400,
        ),
        SectionSpec(
            section_id="2",
            title="模型假设",
            writing_guide="列出所有假设条件，与题目条件对应。",
            min_words=150,
        ),
        SectionSpec(
            section_id="3",
            title="符号说明",
            writing_guide="三线表列出所有符号。",
            min_words=100,
        ),
        SectionSpec(
            section_id="4",
            title="问题一分析与求解",
            writing_guide=(
                "4.1 问题分析：明确分析目标。\n"
                "4.2 多角度分析：\n"
                "  4.2.1 可视化分析：数据趋势图。\n"
                "  4.2.2 统计分析：统计特征指标。\n"
                "  4.2.3 预测对比分析：如SEIR传染病模型。\n"
                "4.3 结果分析：综合结论。\n"
                "关键：多方法交叉验证，结论需有数据支撑。"
            ),
            min_words=500,
        ),
        SectionSpec(
            section_id="5",
            title="问题二分析与求解",
            writing_guide=(
                "5.1 问题分析：子问题分解。\n"
                "5.2 子问题1：评价方法（如Person相关+层次分析法）。\n"
                "5.3 子问题2：规划方法（如平均法+数据挖掘）。\n"
                "5.4 子问题3：选址优化（如K-means聚类+遗传算法）。\n"
                "  5.4.1 选址模型 → 5.4.2 优化算法 → 5.4.3 计算结果。\n"
                "关键：子问题分解清晰，各子问题方法独立。"
            ),
            min_words=600,
        ),
        SectionSpec(
            section_id="6",
            title="问题三分析与求解",
            writing_guide=(
                "6.1 问题分析。\n"
                "6.2 子问题1：规律分析（数据挖掘+统计分析）。\n"
                "  供应规律 → 需求规律 → 供需规律。\n"
                "6.3 子问题2：评价与优化（如TOPSIS综合评价）。\n"
                "  评价指标体系 → 评价结果 → 结果分析。\n"
                "关键：供需规律的多层次分析，评价体系完整。"
            ),
            min_words=500,
        ),
        SectionSpec(
            section_id="7",
            title="问题四分析与求解",
            writing_guide=(
                "7.1 问题分析：多级网络优化。\n"
                "7.2 上游选址：如射线法+枚举法。\n"
                "7.3 中游分配：如轴辐射网络模型。\n"
                "7.4 下游路径优化：如考虑约束的路径优化模型+混合启发式算法。\n"
                "  7.4.1 传播模型 → 7.4.2 路径优化模型 → 7.4.3 混合算法。\n"
                "7.5 结果分析：多级物流网络方案。\n"
                "7.6 有序网络结果可视化。\n"
                "关键：多级网络图、路径规划图、算法流程图。"
            ),
            min_words=700,
        ),
        SectionSpec(
            section_id="8",
            title="模型的改进与推广",
            writing_guide=(
                "8.1 模型的优点。\n"
                "8.2 模型的缺点。\n"
                "8.3 模型的改进与推广。"
            ),
            min_words=200,
        ),
        SectionSpec(
            section_id="ref",
            title="参考文献",
            writing_guide="按引用顺序列出。",
            min_words=50,
        ),
        SectionSpec(
            section_id="app",
            title="附录",
            writing_guide="各问题算法程序代码。",
            min_words=100,
            required=False,
        ),
    ],
    abstract_guide=(
        "摘要结构（约600-1000字）：\n"
        "1. 背景和挑战（2-3句）。\n"
        "2. 问题一：分析方法（多种）、关键发现（含具体结论）。\n"
        "3. 问题二：子问题分解、各子问题方法、关键结果（含表格引用）。\n"
        "4. 问题三：分析方法、评价体系、优化效果。\n"
        "5. 问题四：多级网络方法、算法、关键结果、可视化。\n"
        "6. 关键词：5-8个。"
    ),
    keyword_suggestions=[
        "数据挖掘", "SEIR模型", "K-means聚类", "遗传算法",
        "TOPSIS综合评价", "层次分析法", "路径优化", "混合启发式算法",
        "选址优化", "多级物流网络",
    ],
    method_preferences=[
        "数据挖掘", "SEIR传染病模型", "K-means聚类", "遗传算法",
        "TOPSIS", "层次分析法", "模拟退火", "大规模邻域搜索",
        "路径优化", "复杂网络",
    ],
    writing_tips=[
        "F题通常涉及多子问题，需清晰分解",
        "数据挖掘和数据分析是核心，需多角度分析",
        "多方法协同：不同子问题可用不同方法，需说明选择依据",
        "可视化非常重要：网络图、路径图、趋势图、热力图",
        "NP-hard问题需说明为什么用启发式算法",
        "混合算法需说明各组件的作用和协同方式",
        "结果表格需有明确的编号和标题",
    ],
)


# ---------------------------------------------------------------------------
# 模板注册表
# ---------------------------------------------------------------------------


ALL_TEMPLATES: dict[str, PaperTemplate] = {
    "A": TEMPLATE_A,
    "B": TEMPLATE_B,
    "C": TEMPLATE_C,
    "D": TEMPLATE_D,
    "E": TEMPLATE_E,
    "F": TEMPLATE_F,
}


def get_template(problem_type: str) -> PaperTemplate:
    """获取指定题型的论文模板。

    Args:
        problem_type: 题型标识（A/B/C/D/E/F），大小写不敏感。

    Returns:
        对应的 PaperTemplate。若题型不存在，返回通用模板（基于C题）。
    """
    key = problem_type.upper().strip()
    return ALL_TEMPLATES.get(key, TEMPLATE_C)


def get_template_by_problem_text(problem_text: str) -> PaperTemplate:
    """根据题目文本推断题型并返回对应模板。

    通过关键词匹配推断题目类型：
      - 机理/仿真/马尔科夫/仿真器/概率模型 → A题
      - 优化/排样/切割/排布/整数规划 → B题
      - 评价/评审/排序/指标体系/多目标 → C题
      - 预测/时序/碳排放/趋势/情景 → D题
      - 生态/环境/微分方程/放牧/草原 → E题
      - 物资/疫情/物流/选址/路径优化 → F题

    Args:
        problem_text: 题目文本。

    Returns:
        最匹配的 PaperTemplate。无法匹配时返回C题模板。
    """
    text_lower = problem_text.lower()

    # 关键词匹配规则
    rules = [
        ("A", ["仿真", "马尔科夫", "仿真器", "信道", "网络接入", "simulation", "markov"]),
        ("B", ["排样", "切割", "排布", "下料", "组批", "整数规划", "cutting", "packing"]),
        ("C", ["评价", "评审", "排序", "指标体系", "多目标", "evaluate", "review"]),
        ("D", ["预测", "时序", "碳排放", "趋势", "情景", "双碳", "forecast", "carbon"]),
        ("E", ["生态", "环境", "微分方程", "放牧", "草原", "土壤", "生态", "ecology"]),
        ("F", ["物资", "疫情", "物流", "选址", "路径优化", "配送", "logistics", "pandemic"]),
    ]

    scores: dict[str, int] = {k: 0 for k in "ABCDEF"}
    for problem_type, keywords in rules:
        for kw in keywords:
            if kw.lower() in text_lower:
                scores[problem_type] += 1

    best_type = max(scores, key=lambda k: scores[k])
    if scores[best_type] == 0:
        return TEMPLATE_C  # 默认返回C题模板

    return ALL_TEMPLATES[best_type]


def get_all_section_titles(problem_type: str) -> list[str]:
    """获取指定题型的所有章节标题列表。

    Args:
        problem_type: 题型标识。

    Returns:
        章节标题列表。
    """
    template = get_template(problem_type)
    return [s.title for s in template.sections]


def get_writing_guide_summary(problem_type: str) -> str:
    """获取指定题型的写作指导摘要。

    Args:
        problem_type: 题型标识。

    Returns:
        写作指导摘要文本。
    """
    template = get_template(problem_type)
    lines = [
        f"=== {template.problem_type_name}({template.category})论文模板 ===",
        f"示例题目: {template.example_title}",
        "",
        "【章节结构】",
    ]
    for s in template.sections:
        required_mark = "*" if s.required else "（可选）"
        lines.append(f"  {s.section_id}. {s.title} {required_mark}")

    lines.append("")
    lines.append("【写作要点】")
    for tip in template.writing_tips:
        lines.append(f"  - {tip}")

    lines.append("")
    lines.append("【常用方法】")
    lines.append(f"  {', '.join(template.method_preferences)}")

    lines.append("")
    lines.append("【摘要指导】")
    lines.append(f"  {template.abstract_guide[:200]}...")

    return "\n".join(lines)
