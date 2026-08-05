"""FastAPI 服务端：把已有的 MMAgent 智能体包装为 Web 服务。

W1 范围：
  - 接收题目文本/文件 + 多个数据附件 + 每请求模型配置
  - 后台线程跑 run_graph（asyncio.to_thread）
  - SQLite 记录运行状态，GET 轮询进度（W2 再接 WebSocket）
  - 提供论文 / DOCX / 图表 / 审查报告的安全下载

本地单机单人使用，无需任务队列。
"""
