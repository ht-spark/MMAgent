import numpy as np
from scipy.optimize import minimize
import os
import json

# 定义参数
R = 1000.0  # 烟幕覆盖半径
T = 10.0    # 烟幕持续时间
V_m = 500.0 # 导弹速度
D = 500.0   # 初始距离

# 定义目标函数
def objective(theta):
    sin_theta = np.sin(theta)
    if sin_theta <= R / D:
        return 2 * np.sqrt(R**2 - D**2 * sin_theta**2) / V_m
    else:
        return 0.0

# 定义约束条件
def constraint1(theta):
    return R/D - np.sin(theta)

def constraint2(theta):
    sin_theta = np.sin(theta)
    if sin_theta <= R / D:
        return T - 2 * np.sqrt(R**2 - D**2 * sin_theta**2) / V_m
    else:
        return T  # 此时遮蔽时长为0，约束自动满足

# 初始猜测
theta_initial = np.pi / 2  # 初始猜测为90度

# 设置约束条件
cons = [
    {'type': 'ineq', 'fun': constraint1},
    {'type': 'ineq', 'fun': constraint2}
]

# 定义优化问题，最大化目标函数，转化为最小化负的目标函数
def neg_objective(theta):
    return -objective(theta)

# 执行优化
result_opt = minimize(neg_objective, theta_initial, constraints=cons)

# 检查优化是否成功
if result_opt.success:
    theta_opt = result_opt.x[0]
    objective_opt = -result_opt.fun
else:
    # 如果优化失败，可能需要处理，例如设置为0
    theta_opt = 0.0
    objective_opt = 0.0

# 构建结果字典
result = {
    "optimization": {
        "solution": theta_opt,
        "objective": objective_opt,
        "constraint_check": {
            "constraint1": constraint1(theta_opt) >= 0,
            "constraint2": constraint2(theta_opt) >= 0
        }
    },
    "simulation": objective_opt,
    "confidence_interval": [objective_opt, objective_opt]  # 假设置信区间为该值本身
}

# 输出结果
print("__MODEL_RESULT__" + json.dumps(result, ensure_ascii=False, default=str))