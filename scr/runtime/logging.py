"""结构化日志。

提供 JSON 格式的结构化日志，记录每个步骤的状态、耗时和错误，
同时支持实时控制台输出与 run.log 文件（实时查看运行状态）。
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# 全局运行日志器名称（graph / workflow / agents 统一使用）
RUN_LOGGER_NAME = "mmagent"


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
        for key in ("run_id", "step", "question_id", "duration", "error", "detail"):
            value = getattr(record, key, None)
            if value is not None:
                log_entry[key] = value
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


class HumanFormatter(logging.Formatter):
    """人类可读的控制台日志格式化器（用于实时查看状态）。"""

    def format(self, record: logging.LogRecord) -> str:
        prefix = f"{datetime.fromtimestamp(record.created):%H:%M:%S} [{record.levelname}]"
        message = record.getMessage()
        # 附加 step/question 上下文
        step = getattr(record, "step", None)
        question_id = getattr(record, "question_id", None)
        duration = getattr(record, "duration", None)
        context: list[str] = []
        if step:
            context.append(step)
        if question_id:
            context.append(f"Q={question_id}")
        if duration is not None:
            context.append(f"{duration:.1f}s")
        if context:
            message = f"{message}  ({', '.join(context)})"
        return f"{prefix} {message}"


def _reset_handlers(logger: logging.Logger) -> None:
    """清空日志器的所有 handler（保证按最新参数重建，幂等）。"""
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


def _configure_logger(
    name: str,
    level: int,
    log_file: str | Path | None = None,
    console: bool = True,
    console_level: int = logging.WARNING,
) -> tuple[logging.Logger, Path | None]:
    """配置一个日志器：可选 JSON 文件 + 人类可读控制台。

    Args:
        name: 日志器名称。
        level: 日志器与文件 handler 的最低级别。
        log_file: 可选日志文件路径（JSON 结构化）。
        console: 是否添加控制台 handler（人类可读）。
        console_level: 控制台 handler 的最低级别。

    Returns:
        (logger, log_path)。log_path 为 None 表示未写文件。
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    _reset_handlers(logger)

    log_path: Path | None = None
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8", mode="a")
        file_handler.setLevel(level)
        file_handler.setFormatter(StructuredFormatter())
        logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(HumanFormatter())
        logger.addHandler(console_handler)

    return logger, log_path


def get_logger(
    name: str = "mmagent",
    run_id: str | None = None,
    log_file: str | Path | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """获取结构化日志器（幂等，按最新参数重建 handler）。

    Args:
        name: 日志器名称。
        run_id: 运行 ID（附加到每条日志）。
        log_file: 可选的日志文件路径。不指定时只输出到 stderr。
        level: 日志级别。

    Returns:
        配置好的 Logger 实例（带 run_id 时返回 LoggerAdapter）。
    """
    logger, _ = _configure_logger(
        name=name,
        level=level,
        log_file=log_file,
        console=True,
        console_level=logging.WARNING,
    )

    # 使用 LoggerAdapter 附加 run_id
    if run_id:
        logger = logging.LoggerAdapter(logger, {"run_id": run_id})

    return logger


def setup_run_logger(
    run_id: str,
    log_dir: str | Path | None = None,
    level: int = logging.INFO,
    console: bool = True,
    console_level: int = logging.WARNING,
) -> tuple[logging.Logger, Path | None]:
    """配置整个运行共享的结构化日志器。

    写 JSON 结构化日志到 <log_dir>/run.log（实时追加，可用
    `Get-Content -Wait <log_dir>/run.log` 实时查看），
    并可选输出人类可读控制台日志。

    Args:
        run_id: 运行 ID。
        log_dir: 日志目录（run.log 写入该目录）。None 则只输出控制台。
        level: 文件日志级别（默认 INFO，记全量）。
        console: 是否输出控制台日志。
        console_level: 控制台日志级别（默认 WARNING，避免与 print 进度重复）。

    Returns:
        (logger, log_path)。log_path 为 None 表示未写文件。
    """
    log_file = Path(log_dir) / "run.log" if log_dir else None
    logger, log_path = _configure_logger(
        name=RUN_LOGGER_NAME,
        level=level,
        log_file=log_file,
        console=console,
        console_level=console_level,
    )
    logger = logging.LoggerAdapter(logger, {"run_id": run_id})
    return logger, log_path


def get_run_logger(level: int = logging.INFO) -> logging.Logger:
    """获取全局运行日志器。

    供 graph / workflow / agents 在任何位置直接使用；
    若尚未通过 setup_run_logger 配置，则创建最小 stderr 配置。
    """
    logger = logging.getLogger(RUN_LOGGER_NAME)
    if not logger.handlers:
        _configure_logger(
            name=RUN_LOGGER_NAME,
            level=level,
            console=True,
            console_level=logging.WARNING,
        )
    return logger


def log_step(
    logger: logging.Logger,
    step: str,
    status: str = "started",
    question_id: str | None = None,
    duration: float | None = None,
    error: str | None = None,
    detail: str | None = None,
    level: int | None = None,
) -> None:
    """记录步骤日志的便捷函数。

    Args:
        logger: 日志器（可为 LoggerAdapter）。
        step: 步骤标识（如 "node.intake"、"solve.explore"）。
        status: started / completed / failed / passed 等。
        question_id: 关联的小问 ID。
        duration: 耗时（秒）。
        error: 错误信息。
        detail: 附加详情（进度信息，如"已生成 5 个方法候选"）。
        level: 显式日志级别（默认按 status 推断）。
    """
    extra: dict[str, Any] = {"step": step}
    if question_id:
        extra["question_id"] = question_id
    if duration is not None:
        extra["duration"] = duration
    if error:
        extra["error"] = error
    if detail:
        extra["detail"] = detail

    message = f"[{step}] {status}"
    if question_id:
        message += f" (Q={question_id})"
    if duration is not None:
        message += f" ({duration:.1f}s)"
    if detail:
        message += f" - {detail}"
    if error:
        message += f" ERROR: {error}"

    if level is not None:
        logger.log(level, message, extra=extra)
    elif status in ("failed", "error"):
        logger.error(message, extra=extra)
    else:
        logger.info(message, extra=extra)
