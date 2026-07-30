"""结构化日志。

提供 JSON 格式的结构化日志，记录每个步骤的状态、耗时和错误。
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


class StructuredFormatter(logging.Formatter):
    """JSON 结构化日志格式化器。"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # 附加自定义字段
        for key in ("run_id", "step", "question_id", "duration", "error"):
            value = getattr(record, key, None)
            if value is not None:
                log_entry[key] = value
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def get_logger(
    name: str = "mmagent",
    run_id: str | None = None,
    log_file: str | Path | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """获取结构化日志器。
    
    Args:
        name: 日志器名称。
        run_id: 运行 ID（附加到每条日志）。
        log_file: 可选的日志文件路径。不指定时只输出到 stderr。
        level: 日志级别。
    
    Returns:
        配置好的 Logger 实例。
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 避免重复添加 handler
    if logger.handlers:
        return logger
    
    formatter = StructuredFormatter()
    
    # stderr handler
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)
    
    # 文件 handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    # 使用 LoggerAdapter 附加 run_id
    if run_id:
        logger = logging.LoggerAdapter(logger, {"run_id": run_id})
    
    return logger


def log_step(
    logger: logging.Logger,
    step: str,
    status: str = "started",
    question_id: str | None = None,
    duration: float | None = None,
    error: str | None = None,
) -> None:
    """记录步骤日志的便捷函数。"""
    extra: dict[str, Any] = {"step": step}
    if question_id:
        extra["question_id"] = question_id
    if duration is not None:
        extra["duration"] = duration
    if error:
        extra["error"] = error
    
    message = f"[{step}] {status}"
    if question_id:
        message += f" (Q={question_id})"
    if duration is not None:
        message += f" ({duration:.1f}s)"
    if error:
        message += f" ERROR: {error}"
    
    if status in ("failed", "error"):
        logger.error(message, extra=extra)
    elif status in ("completed", "passed", "validated"):
        logger.info(message, extra=extra)
    else:
        logger.info(message, extra=extra)
