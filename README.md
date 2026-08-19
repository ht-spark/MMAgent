# 终端一：后端（热重载）
uvicorn server.main:app --reload --port 8000

# 终端二：前端（Vite 热更新）
cd web && npm run dev
# 访问 Vite 提示的地址（默认 http://localhost:5173）