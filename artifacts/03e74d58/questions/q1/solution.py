import numpy as np
from scipy.optimize import minimize_scalar
import json
import os

# 定义参数（示例数值，根据实际需求调整）
V_smoke = 10.0  # 烟幕弹运动速度（m/s）
V_m1 = 20.0     # M1运动速度（m/s）
R_smoke = 50.0  # 烟雾有效覆盖半径（m）
D_initial = 1000.0  # 初始拦截距离（m）
T_max = 60.0    # 烟幕有效持续时间（s）

t_upper = min(T_max, D_initial / V_smoke)

def objective(t):
    numerator_low = D_initial + V_smoke * t - R_smoke
    numerator_high = D_initial + V_smoke * t + R_smoke
    denominator = V_m1 + V_smoke
    if denominator == 0:
        return 0.0
    tau_low = numerator_low / denominator
    tau_high = numerator_high / denominator

    start = max(tau_low, t)
    end = min(tau_high, t + T_max)
    T = max(0.0, end - start)
    return -T  # 最小化负的T以达到最大化

# 进行优化
result_opt = minimize_scalar(objective, bounds=(0, t_upper), method='bounded')

optimal_t = result_opt.x
max_T = -result_opt.fun

# 检查约束
constraint_check = {
    "V_smoke * t <= D_initial": V_smoke * optimal_t <= D_initial + 1e-9,
    "0 <= t <= T_max": 0 <= optimal_t <= T_max + 1e-9
}

# 构建结果
result = {
    "optimization": {
        "solution": float(optimal_t),
        "objective": float(max_T),
        "constraint_check": constraint_check
    },
    "simulation": float(max_T),
    "confidence_interval": [0.0, 0.0],
    "metrics": {
        "optimization_success": result_opt.success,
        "optimization_message": result_opt.message
    }
}

print("__MODEL_RESULT__" + json.dumps(result, ensure_ascii=False, default=str))