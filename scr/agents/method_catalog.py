"""数学建模方法目录（内置知识库）。

对应 architecture.md §5.3 方法探索与决策。

按数学任务类型（math_task）组织候选方法，每个方法包含：
  - 基本信息：名称、家族、描述
  - 数据要求：所需数据类型、最小样本量、是否需要时间列
  - 假设条件：核心假设列表
  - 优缺点：pros / cons
  - 淘汰条件：不适用的情况
  - 实现难度：low / medium / high
  - 验证方法：推荐的结果验证方式

此目录作为确定性知识库，供 MethodExplorer 做硬过滤和候选生成。
LLM 可在此基础上扩展和精调，但不依赖 LLM 即可提供合理候选。
"""
from __future__ import annotations

from typing import Literal


MethodDifficulty = Literal["low", "medium", "high"]


# ---------------------------------------------------------------------------
# 方法目录：按 math_task 类型组织
# ---------------------------------------------------------------------------

METHOD_CATALOG: dict[str, list[dict]] = {
    "evaluation": [
        {
            "name": "熵权法",
            "family": "客观赋权法",
            "description": "基于信息熵计算指标权重，数据离散度越大权重越高",
            "required_data": ["多指标数值数据"],
            "assumptions": ["指标间无完全共线性", "数据可标准化处理"],
            "pros": ["完全客观，无主观偏差", "计算简单快速", "可复现性强"],
            "cons": ["对极端值敏感", "无法处理定性指标", "权重可能不符合实际意义"],
            "elimination_conditions": ["指标数 < 2", "某指标为常数列"],
            "implementation_difficulty": "low",
            "data_requirements": {"min_samples": 3, "min_features": 2, "needs_time": False},
            "validation_method": "权重敏感性分析",
        },
        {
            "name": "TOPSIS",
            "family": "多属性决策",
            "description": "逼近理想解排序法，计算各方案与正负理想解的距离",
            "required_data": ["多指标数值数据", "指标方向（效益型/成本型）"],
            "assumptions": ["指标可标准化", "各指标相互独立"],
            "pros": ["概念清晰", "可处理多量纲数据", "结果直观"],
            "cons": ["权重需外部确定", "对权重敏感", "无法处理模糊信息"],
            "elimination_conditions": ["指标数 < 2", "样本量 < 2"],
            "implementation_difficulty": "low",
            "data_requirements": {"min_samples": 2, "min_features": 2, "needs_time": False},
            "validation_method": "权重扰动稳定性检验",
        },
        {
            "name": "层次分析法(AHP)",
            "family": "主观赋权法",
            "description": "通过专家判断构建判断矩阵，计算各指标权重",
            "required_data": ["指标体系", "专家判断矩阵"],
            "assumptions": ["判断矩阵满足一致性", "专家判断可靠"],
            "pros": ["可结合定性指标", "层级结构清晰", "适用于无数据场景"],
            "cons": ["主观性强", "一致性检验可能不通过", "指标多时判断困难"],
            "elimination_conditions": ["一致性比率 CR > 0.1 且无法调整"],
            "implementation_difficulty": "low",
            "data_requirements": {"min_samples": 0, "min_features": 2, "needs_time": False},
            "validation_method": "一致性比率检验",
        },
        {
            "name": "模糊综合评价",
            "family": "模糊数学",
            "description": "用模糊集合和隶属度函数对多因素问题综合评价",
            "required_data": ["评价指标", "评价等级标准"],
            "assumptions": ["隶属度函数选择合理", "评价等级划分恰当"],
            "pros": ["可处理模糊性", "适合定性定量混合", "结果丰富"],
            "cons": ["隶属度函数主观", "计算较复杂", "等级划分影响结果"],
            "elimination_conditions": ["无法确定隶属度函数"],
            "implementation_difficulty": "medium",
            "data_requirements": {"min_samples": 1, "min_features": 2, "needs_time": False},
            "validation_method": "不同隶属度函数对比",
        },
        {
            "name": "灰色关联分析",
            "family": "灰色系统理论",
            "description": "计算各方案与参考序列的灰色关联度，进行排序",
            "required_data": ["参考序列", "比较序列"],
            "assumptions": ["数据序列具有可比性", "分辨系数选择合理"],
            "pros": ["小样本也可用", "计算简单", "无需分布假设"],
            "cons": ["参考序列选择主观", "分辨系数影响结果", "信息利用率低"],
            "elimination_conditions": ["序列长度 < 3"],
            "implementation_difficulty": "low",
            "data_requirements": {"min_samples": 3, "min_features": 1, "needs_time": False},
            "validation_method": "分辨系数敏感性分析",
        },
    ],

    "prediction": [
        {
            "name": "线性回归",
            "family": "线性模型",
            "description": "建立因变量与自变量之间的线性关系",
            "required_data": ["因变量数值数据", "自变量数值数据"],
            "assumptions": ["线性关系", "误差独立同分布", "无多重共线性", "同方差性"],
            "pros": ["简单直观", "可解释性强", "计算快速"],
            "cons": ["仅适用线性关系", "对异常值敏感", "需满足统计假设"],
            "elimination_conditions": ["关系明显非线性", "样本量 < 自变量数+2"],
            "implementation_difficulty": "low",
            "data_requirements": {"min_samples": 10, "min_features": 1, "needs_time": False},
            "validation_method": "R²、调整R²、F检验、残差分析",
        },
        {
            "name": "时间序列ARIMA",
            "family": "时间序列模型",
            "description": "自回归积分滑动平均模型，用于时间序列预测",
            "required_data": ["时间序列数据"],
            "assumptions": ["序列平稳（差分后）", "自相关结构稳定"],
            "pros": ["捕捉时间依赖", "理论成熟", "可解释"],
            "cons": ["需要平稳性", "参数选择复杂", "长期预测精度低"],
            "elimination_conditions": ["无时间列", "序列长度 < 10", "非平稳且差分无效"],
            "implementation_difficulty": "medium",
            "data_requirements": {"min_samples": 20, "min_features": 1, "needs_time": True},
            "validation_method": "AIC/BIC、Ljung-Box检验、残差白噪声",
        },
        {
            "name": "灰色预测GM(1,1)",
            "family": "灰色系统理论",
            "description": "对少数据、不完全信息进行趋势预测",
            "required_data": ["时间序列或渐进序列"],
            "assumptions": ["数据呈指数增长趋势", "级比检验通过"],
            "pros": ["小样本可用（4+）", "无需分布假设", "短期预测精度高"],
            "cons": ["仅适合指数趋势", "长期预测不准", "波动数据效果差"],
            "elimination_conditions": ["级比检验不通过", "数据波动剧烈"],
            "implementation_difficulty": "low",
            "data_requirements": {"min_samples": 4, "min_features": 1, "needs_time": True},
            "validation_method": "后验差比、小误差概率",
        },
        {
            "name": "神经网络(BP)",
            "family": "机器学习",
            "description": "多层前馈神经网络，通过反向传播训练",
            "required_data": ["输入特征数据", "目标变量数据"],
            "assumptions": ["数据量充足", "特征与目标存在非线性映射"],
            "pros": ["拟合非线性", "通用近似", "可处理多输入多输出"],
            "cons": ["需要大量数据", "易过拟合", "可解释性差", "调参复杂"],
            "elimination_conditions": ["样本量 < 50", "特征数过多且无降维"],
            "implementation_difficulty": "high",
            "data_requirements": {"min_samples": 50, "min_features": 1, "needs_time": False},
            "validation_method": "交叉验证、早停、测试集误差",
        },
        {
            "name": "支持向量回归(SVR)",
            "family": "机器学习",
            "description": "基于统计学习理论的回归方法，适用于小样本",
            "required_data": ["输入特征数据", "目标变量数据"],
            "assumptions": ["核函数选择合理", "参数可调优"],
            "pros": ["小样本表现好", "泛化能力强", "可处理非线性"],
            "cons": ["参数选择敏感", "大规模数据计算慢", "核函数选择困难"],
            "elimination_conditions": ["样本量 < 10"],
            "implementation_difficulty": "medium",
            "data_requirements": {"min_samples": 10, "min_features": 1, "needs_time": False},
            "validation_method": "交叉验证、不同核函数对比",
        },
    ],

    "optimization": [
        {
            "name": "线性规划",
            "family": "数学规划",
            "description": "在线性约束下优化线性目标函数",
            "required_data": ["决策变量", "目标函数系数", "约束条件"],
            "assumptions": ["目标函数和约束均为线性", "变量连续"],
            "pros": ["理论成熟", "求解快速", "全局最优", "可解释"],
            "cons": ["仅适用线性问题", "无法处理整数约束", "对规模有上限"],
            "elimination_conditions": ["目标或约束非线性", "变量需为整数"],
            "implementation_difficulty": "low",
            "data_requirements": {"min_samples": 0, "min_features": 1, "needs_time": False},
            "validation_method": "对偶问题验证、灵敏度分析",
        },
        {
            "name": "整数规划",
            "family": "数学规划",
            "description": "决策变量取整数值的优化问题",
            "required_data": ["决策变量", "目标函数系数", "约束条件"],
            "assumptions": ["线性目标函数", "线性约束", "变量为整数"],
            "pros": ["可处理离散决策", "全局最优", "理论成熟"],
            "cons": ["NP-hard，大规模求解慢", "松弛可能不准", "建模复杂"],
            "elimination_conditions": ["变量连续", "约束非线性"],
            "implementation_difficulty": "medium",
            "data_requirements": {"min_samples": 0, "min_features": 1, "needs_time": False},
            "validation_method": "松弛界对比、分支定界验证",
        },
        {
            "name": "遗传算法",
            "family": "启发式算法",
            "description": "模拟自然选择和遗传机制的全局优化算法",
            "required_data": ["目标函数", "变量范围"],
            "assumptions": ["适应度函数设计合理", "参数（种群、代数）设置恰当"],
            "pros": ["全局搜索", "可处理非线性", "可处理离散和连续", "并行化"],
            "cons": ["收敛慢", "参数敏感", "不保证最优", "早熟收敛风险"],
            "elimination_conditions": ["问题规模极小可用精确方法", "实时性要求高"],
            "implementation_difficulty": "medium",
            "data_requirements": {"min_samples": 0, "min_features": 1, "needs_time": False},
            "validation_method": "多次运行一致性、与精确解对比",
        },
        {
            "name": "粒子群算法",
            "family": "启发式算法",
            "description": "模拟鸟群觅食行为的群体智能优化算法",
            "required_data": ["目标函数", "变量范围"],
            "assumptions": ["速度更新公式合理", "惯性权重衰减恰当"],
            "pros": ["收敛快", "实现简单", "适合连续优化", "并行化"],
            "cons": ["易陷入局部最优", "参数敏感", "离散问题需改编"],
            "elimination_conditions": ["问题有精确解法", "变量为纯整数"],
            "implementation_difficulty": "medium",
            "data_requirements": {"min_samples": 0, "min_features": 1, "needs_time": False},
            "validation_method": "多次运行一致性、收敛曲线分析",
        },
        {
            "name": "模拟退火",
            "family": "启发式算法",
            "description": "基于金属退火原理的概率性全局优化算法",
            "required_data": ["目标函数", "变量范围"],
            "assumptions": ["温度下降策略合理", "接受概率公式恰当"],
            "pros": ["可跳出局部最优", "通用性强", "可处理复杂约束"],
            "cons": ["收敛慢", "参数调优困难", "结果随机性"],
            "elimination_conditions": ["实时性要求高", "问题规模小"],
            "implementation_difficulty": "medium",
            "data_requirements": {"min_samples": 0, "min_features": 1, "needs_time": False},
            "validation_method": "多次运行一致性、冷却曲线分析",
        },
    ],

    "stochastic_optimization": [
        {
            "name": "随机规划(两阶段)",
            "family": "随机优化",
            "description": "两阶段随机规划：第一阶段做确定性决策，第二阶段根据场景做补偿决策",
            "required_data": ["决策变量", "随机参数分布", "场景数据"],
            "assumptions": ["随机参数分布已知或可估计", "场景数足够覆盖不确定性"],
            "pros": ["理论成熟", "可处理不确定性", "期望最优", "适用面广"],
            "cons": ["场景数多时计算量大", "分布假设影响结果", "求解复杂"],
            "elimination_conditions": ["无不确定性", "分布完全未知"],
            "implementation_difficulty": "high",
            "data_requirements": {"min_samples": 0, "min_features": 1, "needs_time": False},
            "validation_method": "样本量敏感性分析、场景覆盖率检验",
        },
        {
            "name": "鲁棒优化",
            "family": "鲁棒优化",
            "description": "在最坏情况不确定性下优化决策，保证解的鲁棒性",
            "required_data": ["决策变量", "不确定性集合", "目标函数"],
            "assumptions": ["不确定性集合合理", "最坏情况可定义"],
            "pros": ["保证最坏情况性能", "无需分布假设", "解的鲁棒性强"],
            "cons": ["可能过于保守", "不确定性集合设计困难", "计算复杂"],
            "elimination_conditions": ["无不确定性", "需要期望最优而非最坏最优"],
            "implementation_difficulty": "high",
            "data_requirements": {"min_samples": 0, "min_features": 1, "needs_time": False},
            "validation_method": "不同不确定性集合对比、保守度分析",
        },
        {
            "name": "蒙特卡洛+优化",
            "family": "随机优化",
            "description": "通过蒙特卡洛模拟生成场景，在每个场景下求解优化问题，统计最优解分布",
            "required_data": ["决策变量", "随机参数分布", "目标函数"],
            "assumptions": ["分布假设合理", "模拟次数足够", "场景独立"],
            "pros": ["实现相对简单", "可量化决策风险", "适用面广", "结果直观"],
            "cons": ["计算量大", "精度依赖模拟次数", "需分布假设"],
            "elimination_conditions": ["无不确定性", "实时性要求高"],
            "implementation_difficulty": "medium",
            "data_requirements": {"min_samples": 0, "min_features": 1, "needs_time": False},
            "validation_method": "收敛性检验、不同样本量对比、敏感性分析",
        },
        {
            "name": "机会约束规划",
            "family": "随机优化",
            "description": "约束以一定概率满足的优化问题，允许小概率违约",
            "required_data": ["决策变量", "随机参数分布", "置信水平"],
            "assumptions": ["分布已知", "置信水平合理", "约束可转化为确定性等价"],
            "pros": ["灵活平衡风险与收益", "适用于风险管理", "理论成熟"],
            "cons": ["转化困难", "分布假设影响结果", "计算复杂"],
            "elimination_conditions": ["无随机约束", "分布完全未知"],
            "implementation_difficulty": "high",
            "data_requirements": {"min_samples": 0, "min_features": 1, "needs_time": False},
            "validation_method": "不同置信水平对比、违约概率检验",
        },
        {
            "name": "线性规划(确定性基础)",
            "family": "数学规划",
            "description": "作为随机规划的确定性基础模型，先用线性规划建立基线方案",
            "required_data": ["决策变量", "目标函数系数", "约束条件"],
            "assumptions": ["目标函数和约束均为线性", "变量连续", "参数确定性"],
            "pros": ["求解快速", "可作为基线对比", "理论成熟", "可解释"],
            "cons": ["未考虑不确定性", "解可能不鲁棒", "实际应用受限"],
            "elimination_conditions": ["目标或约束非线性"],
            "implementation_difficulty": "low",
            "data_requirements": {"min_samples": 0, "min_features": 1, "needs_time": False},
            "validation_method": "与随机规划结果对比、灵敏度分析",
        },
    ],

    "classification": [
        {
            "name": "逻辑回归",
            "family": "线性模型",
            "description": "通过logit变换进行二分类或多分类",
            "required_data": ["特征数据", "类别标签"],
            "assumptions": ["logit线性", "样本独立", "无严重多重共线性"],
            "pros": ["简单快速", "可解释", "概率输出", "不易过拟合"],
            "cons": ["仅线性边界", "需特征工程", "多分类需扩展"],
            "elimination_conditions": ["边界高度非线性", "样本量 < 特征数"],
            "implementation_difficulty": "low",
            "data_requirements": {"min_samples": 20, "min_features": 1, "needs_time": False},
            "validation_method": "交叉验证、AUC、混淆矩阵",
        },
        {
            "name": "决策树",
            "family": "树模型",
            "description": "基于特征阈值递归划分的树形分类器",
            "required_data": ["特征数据", "类别标签"],
            "assumptions": ["特征有区分度", "无大量噪声"],
            "pros": ["可解释性极强", "无需标准化", "可处理混合类型", "特征选择"],
            "cons": ["易过拟合", "不稳定", "偏向多数类"],
            "elimination_conditions": ["样本量 < 10", "特征无区分度"],
            "implementation_difficulty": "low",
            "data_requirements": {"min_samples": 10, "min_features": 1, "needs_time": False},
            "validation_method": "交叉验证、剪枝对比、特征重要性",
        },
        {
            "name": "支持向量机(SVM)",
            "family": "机器学习",
            "description": "基于最大间隔的分类器，通过核函数处理非线性",
            "required_data": ["特征数据", "类别标签"],
            "assumptions": ["核函数选择合理", "惩罚参数可调优"],
            "pros": ["小样本好", "泛化强", "核技巧灵活", "高维适用"],
            "cons": ["参数敏感", "大规模数据慢", "核选择困难", "可解释性差"],
            "elimination_conditions": ["样本量 > 10000（计算慢）", "特征无信息"],
            "implementation_difficulty": "medium",
            "data_requirements": {"min_samples": 10, "min_features": 1, "needs_time": False},
            "validation_method": "交叉验证、不同核函数对比",
        },
        {
            "name": "K近邻(KNN)",
            "family": "惰性学习",
            "description": "基于最近邻投票的分类方法",
            "required_data": ["特征数据", "类别标签"],
            "assumptions": ["距离度量合理", "K值选择恰当"],
            "pros": ["简单直观", "无需训练", "可处理多分类", "天然非线性"],
            "cons": ["预测慢", "维度灾难", "需标准化", "K值敏感"],
            "elimination_conditions": ["特征维度极高", "样本量极大"],
            "implementation_difficulty": "low",
            "data_requirements": {"min_samples": 10, "min_features": 1, "needs_time": False},
            "validation_method": "交叉验证、不同K值对比",
        },
    ],

    "clustering": [
        {
            "name": "K-Means",
            "family": "划分聚类",
            "description": "基于距离的迭代聚类算法",
            "required_data": ["数值特征数据"],
            "assumptions": ["簇为球形", "K值已知", "各簇大小相近"],
            "pros": ["简单快速", "可扩展", "结果直观"],
            "cons": ["需指定K", "对初始值敏感", "仅球形簇", "对异常值敏感"],
            "elimination_conditions": ["簇形状非球形", "无法确定K值"],
            "implementation_difficulty": "low",
            "data_requirements": {"min_samples": 10, "min_features": 1, "needs_time": False},
            "validation_method": "轮廓系数、肘部法则、稳定性检验",
        },
        {
            "name": "层次聚类",
            "family": "层次聚类",
            "description": "通过合并或分裂构建聚类层次树",
            "required_data": ["数值特征数据"],
            "assumptions": ["距离度量合理", "链接方法恰当"],
            "pros": ["无需指定K", "可视化树状图", "可灵活切分"],
            "cons": ["计算复杂度高", "不可逆合并", "大规模不适用"],
            "elimination_conditions": ["样本量 > 1000", "维度极高"],
            "implementation_difficulty": "low",
            "data_requirements": {"min_samples": 5, "min_features": 1, "needs_time": False},
            "validation_method": "树状图分析、轮廓系数、不同链接方法对比",
        },
        {
            "name": "DBSCAN",
            "family": "密度聚类",
            "description": "基于密度可达的聚类算法，可识别噪声点",
            "required_data": ["数值特征数据"],
            "assumptions": ["密度参数选择合理", "簇密度均匀"],
            "pros": ["无需指定K", "可发现任意形状", "可识别噪声", "鲁棒性强"],
            "cons": ["参数敏感", "密度不均效果差", "高维困难"],
            "elimination_conditions": ["密度差异大", "维度极高"],
            "implementation_difficulty": "medium",
            "data_requirements": {"min_samples": 10, "min_features": 1, "needs_time": False},
            "validation_method": "轮廓系数、噪声比例、不同参数对比",
        },
    ],

    "simulation": [
        {
            "name": "蒙特卡洛模拟",
            "family": "统计模拟",
            "description": "通过随机抽样和统计实验近似求解问题",
            "required_data": ["概率分布参数", "模拟场景定义"],
            "assumptions": ["分布假设合理", "样本量足够大", "随机数质量好"],
            "pros": ["通用性强", "可处理复杂系统", "直观", "可量化不确定性"],
            "cons": ["收敛慢", "精度依赖样本量", "需分布假设", "计算量大"],
            "elimination_conditions": ["无概率分布信息", "实时性要求高"],
            "implementation_difficulty": "medium",
            "data_requirements": {"min_samples": 0, "min_features": 1, "needs_time": False},
            "validation_method": "收敛性检验、不同样本量对比、敏感性分析",
        },
        {
            "name": "系统动力学",
            "family": "动力学模型",
            "description": "通过因果反馈环和存量流量图模拟系统行为",
            "required_data": ["因果回路图", "存量流量参数"],
            "assumptions": ["因果关系正确", "反馈结构完整", "参数可估计"],
            "pros": ["可模拟复杂系统", "揭示反馈机制", "政策分析能力强"],
            "cons": ["建模复杂", "参数标定难", "结构假设主观", "计算量大"],
            "elimination_conditions": ["系统无反馈结构", "无法确定因果链"],
            "implementation_difficulty": "high",
            "data_requirements": {"min_samples": 0, "min_features": 1, "needs_time": True},
            "validation_method": "历史数据对比、敏感性分析、结构验证",
        },
        {
            "name": "离散事件仿真",
            "family": "仿真模型",
            "description": "模拟系统中离散事件按时间序列发生的动态过程",
            "required_data": ["事件定义", "时间参数", "资源约束"],
            "assumptions": ["事件逻辑正确", "分布假设合理", "资源建模准确"],
            "pros": ["可模拟排队系统", "资源优化", "可视化过程", "灵活建模"],
            "cons": ["建模复杂", "需大量参数", "验证困难", "计算量大"],
            "elimination_conditions": ["系统连续非离散", "无法确定事件逻辑"],
            "implementation_difficulty": "high",
            "data_requirements": {"min_samples": 0, "min_features": 1, "needs_time": True},
            "validation_method": "多次运行统计、与理论值对比、敏感性分析",
        },
    ],

    "mechanism": [
        {
            "name": "常微分方程(ODE)",
            "family": "微分方程模型",
            "description": "用常微分方程描述系统状态随时间的演化",
            "required_data": ["状态变量", "参数估计", "初始条件"],
            "assumptions": ["连续变化", "参数恒定或可变", "初始条件准确"],
            "pros": ["物理意义明确", "可外推", "可解释因果", "理论成熟"],
            "cons": ["参数标定难", "解析解少", "数值求解有误差", "假设理想化"],
            "elimination_conditions": ["系统离散", "无动力学机制", "参数不可辨识"],
            "implementation_difficulty": "high",
            "data_requirements": {"min_samples": 5, "min_features": 1, "needs_time": True},
            "validation_method": "与实测数据对比、参数敏感性分析、残差检验",
        },
        {
            "name": "差分方程",
            "family": "离散动力学模型",
            "description": "用差分方程描述离散时间步的系统演化",
            "required_data": ["状态变量", "离散时间序列", "参数"],
            "assumptions": ["离散时间步合理", "递推关系正确", "参数恒定"],
            "pros": ["适合离散数据", "计算简单", "可解释", "数值稳定"],
            "cons": ["时间步选择影响结果", "参数标定难", "长期预测偏差大"],
            "elimination_conditions": ["系统连续", "无递推关系", "参数不可辨识"],
            "implementation_difficulty": "medium",
            "data_requirements": {"min_samples": 5, "min_features": 1, "needs_time": True},
            "validation_method": "与历史数据对比、稳定性分析、参数敏感性",
        },
        {
            "name": "偏微分方程(PDE)",
            "family": "微分方程模型",
            "description": "用偏微分方程描述空间和时间上的连续变化",
            "required_data": ["空间网格", "边界条件", "初始条件", "物理参数"],
            "assumptions": ["连续介质假设", "边界条件准确", "数值格式稳定"],
            "pros": ["可模拟空间分布", "物理意义强", "精确度高"],
            "cons": ["建模极复杂", "数值求解难", "计算量大", "参数标定难"],
            "elimination_conditions": ["无空间维度", "边界条件未知", "计算资源不足"],
            "implementation_difficulty": "high",
            "data_requirements": {"min_samples": 10, "min_features": 2, "needs_time": True},
            "validation_method": "数值稳定性检验、与解析解对比、网格无关性验证",
        },
    ],

    "composite": [
        {
            "name": "综合评价+优化",
            "family": "组合模型",
            "description": "先评价后优化的两阶段方法",
            "required_data": ["评价指标数据", "优化约束条件"],
            "assumptions": ["评价结果可靠", "优化模型合理"],
            "pros": ["逻辑完整", "评价指导优化", "竞赛常见组合"],
            "cons": ["两阶段误差累积", "建模复杂", "计算量大"],
            "elimination_conditions": ["无评价需求", "无优化需求"],
            "implementation_difficulty": "medium",
            "data_requirements": {"min_samples": 3, "min_features": 2, "needs_time": False},
            "validation_method": "分阶段验证、整体一致性检验",
        },
        {
            "name": "预测+优化",
            "family": "组合模型",
            "description": "先预测参数再优化决策的两阶段方法",
            "required_data": ["历史时间序列", "优化模型参数"],
            "assumptions": ["预测结果可靠", "优化模型合理", "预测-优化耦合正确"],
            "pros": ["数据驱动决策", "竞赛常见组合", "逻辑清晰"],
            "cons": ["预测误差传递", "两阶段耦合复杂", "不确定性处理难"],
            "elimination_conditions": ["无时间序列数据", "无优化需求"],
            "implementation_difficulty": "high",
            "data_requirements": {"min_samples": 10, "min_features": 1, "needs_time": True},
            "validation_method": "预测精度检验、优化结果敏感性分析",
        },
        {
            "name": "多模型集成",
            "family": "集成方法",
            "description": "综合多个模型的预测/评价结果",
            "required_data": ["多模型输出", "权重或投票机制"],
            "assumptions": ["模型间有差异性", "集成方式合理"],
            "pros": ["降低单一模型风险", "鲁棒性强", "精度可能提升"],
            "cons": ["计算量大", "解释困难", "模型选择主观"],
            "elimination_conditions": ["模型高度同质", "计算资源不足"],
            "implementation_difficulty": "medium",
            "data_requirements": {"min_samples": 5, "min_features": 1, "needs_time": False},
            "validation_method": "与单模型对比、交叉验证、多样性度量",
        },
    ],
}


def get_candidates_for_task(math_task: str) -> list[dict]:
    """获取指定数学任务类型的候选方法列表。

    Args:
        math_task: 数学任务类型（evaluation/prediction/optimization/...）。

    Returns:
        候选方法列表（深拷贝），如果 math_task 不在目录中则返回 composite 的候选。
    """
    import copy
    candidates = METHOD_CATALOG.get(math_task, METHOD_CATALOG["composite"])
    return copy.deepcopy(candidates)


def get_all_task_types() -> list[str]:
    """获取所有支持的数学任务类型。"""
    return list(METHOD_CATALOG.keys())


def get_method_by_name(name: str) -> dict | None:
    """按名称查找方法定义。

    在所有任务类型中搜索，返回第一个匹配的方法（深拷贝）。
    """
    import copy
    for task_type, methods in METHOD_CATALOG.items():
        for m in methods:
            if m["name"] == name:
                return copy.deepcopy(m)
    return None
