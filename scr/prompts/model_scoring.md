你是一位资深的数学建模竞赛评审。请为以下候选模型按 7 个维度打分（0–1）。

## 候选模型列表

{candidates}

## 题目分析

{problem_analysis}

## 子问题

{subproblems}

## 数据画像

{data_inventory}

## 评分维度

为每个候选输出 7 个单项分（0–1，含 2 位小数）+ reasoning：

| 维度 | 权重 | 说明 |
|------|------|------|
| problem_fit | 0.25 | 与题目的匹配程度（题型吻合） |
| data_fit | 0.20 | 与数据的匹配程度（字段可获得） |
| assumption_validity | 0.15 | 核心假设是否成立 |
| validation_feasibility | 0.15 | 验证方法是否可行 |
| interpretability | 0.10 | 可解释性 |
| implementation_feasibility | 0.10 | 实现难度（代码可用、库支持） |
| innovation | 0.05 | 创新性 |

**注意：不要计算总分。总分由代码按上述权重加权计算。**

## 评分依据

- 高分（>0.7）：强支持（数据齐备 / 假设合理 / 文献充分）
- 中分（0.4-0.7）：可行但有局限
- 低分（<0.4）：不推荐

## 输出

每个候选一个 ModelScore 对象，包含：
- candidate_id
- 7 个单项分
- reasoning（整体理由）