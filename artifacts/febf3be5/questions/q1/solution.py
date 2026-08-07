import numpy as np
import scipy.stats as stats
import json
import os

# 定义关键参数
v_m = 10  # 目标速度
t_s = 30  # 烟幕持续时间

# 生成随机样本
np.random.seed(42)
num_samples = 10000
r_samples = np.random.uniform(0, 10, num_samples)  # 烟幕弹散布半径范围
d_samples = np.random.uniform(0, 20, num_samples)  # 目标初始距离范围

# 计算遮蔽时间
def calculate_T(r, d, v_m, t_s):
    term1 = (d + r) / v_m
    term2 = (d - r) / v_m
    lower = max(term2, 0)
    upper = min(term1, t_s)
    return upper - lower

T_values = np.array([calculate_T(r, d, v_m, t_s) for r, d in zip(r_samples, d_samples)])

# 计算期望和置信区间
expected_T = np.mean(T_values)
confidence_interval = stats.norm.interval(0.95, loc=expected_T, scale=stats.sem(T_values))

# 构建结果字典
result = {
    "simulation": T_values.tolist(),
    "confidence_interval": [float(confidence_interval[0]), float(confidence_interval[1])],
    "metrics": {
        "mean": float(expected_T),
        "std": float(np.std(T_values)),
        "min": float(np.min(T_values)),
        "max": float(np.max(T_values))
    }
}

# 输出结果
print("__MODEL_RESULT__" + json.dumps(result, ensure_ascii=False, default=str))