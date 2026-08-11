你是一位数学建模方法专家。你的任务是从网络搜索结果中，结合你的专业知识，提取并生成适用于当前数学建模问题的方法候选。

## 当前问题信息

- **数学任务类型**: {math_task}
- **问题描述**: {problem_description}

## 搜索结果

以下是针对该问题进行联网搜索后的结果（包含标题、内容和来源 URL）：

{search_results}

## 提取要求

请从搜索结果中结合你的专业知识，提取 **3-5 个** 适用于该数学建模问题的方法候选。提取时注意：

1. **方法名称规范**：使用学术界通用名称（如"熵权法"、"TOPSIS"、"ARIMA"、"线性规划"等）
2. **方法家族**：归类到标准家族（客观赋权法/主观赋权法/多属性决策/线性模型/时间序列模型/机器学习/树模型/数学规划/启发式算法/随机优化/鲁棒优化/灰色系统理论/模糊数学/机理模型/仿真模型/降维方法/聚类分析/博弈论/排队论/图论方法/随机过程/其他方法）
3. **优缺点**：从搜索内容和你的知识中提取
4. **实现难度**：low/medium/high
5. **相关性分数**：根据搜索结果的相关性打分（0-1）
6. **来源 URL**：记录方法信息来源的 URL，便于追溯
7. **required_outputs**（重要）：该方法应产出的结果类型列表，例如：

   - 评价类：["indicator_weights", "scores_or_ranking"]
   - 预测类：["predictions", "error_metrics", "confidence_interval"]
   - 优化类：["decision_solution", "objective_value", "constraint_check"]
   - 仿真类：["simulation_summary", "confidence_interval", "distribution_assumptions"]
   - 随机优化类：["scenario_solutions", "expected_objective", "risk_metrics"]
8. **validation_requirements**（重要）：验证该方法结果的检查项列表，例如：

   - 评价类：["weight_sensitivity", "ranking_stability"]
   - 预测类：["residual_analysis", "error_metrics"]
   - 优化类：["objective_recompute", "constraint_feasibility", "sensitivity_analysis"]
   - 仿真类：["seed_reproducibility", "sample_size_sensitivity"]
9. **假设条件**：列出该方法的核心假设
10. **所需数据**：列出该方法需要的数据类型

## 输出格式

返回 JSON，格式如下：

```json
{{
  "candidates": [
    {{
      "name": "方法名称",
      "family": "方法家族",
      "description": "方法描述（100-200字，包含核心原理和适用场景）",
      "pros": ["优点1", "优点2"],
      "cons": ["缺点1"],
      "assumptions": ["假设1"],
      "required_data": ["所需数据1"],
      "implementation_difficulty": "medium",
      "validation_method": "验证方法描述",
      "required_outputs": ["output1", "output2"],
      "validation_requirements": ["check1", "check2"],
      "source_url": "https://...",
      "source_title": "来源标题",
      "relevance_score": 0.85
    }}
  ]
}}
```
