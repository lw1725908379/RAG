# -*- coding: utf-8 -*-
"""
日志配置模块 - 统一管理日志配置
支持：
- Trace-ID 追踪
- 结构化 JSON 日志
- 性能指标记录
"""
import os
import logging
from pathlib import Path
from datetime import datetime


def get_log_level(debug_mode: bool = None) -> int:
    """获取日志级别"""
    if debug_mode is None:
        debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
    return logging.DEBUG if debug_mode else logging.INFO


def setup_logging(log_dir: str, log_level: int = None, log_format: str = None, json_mode: bool = False):
    """
    统一配置日志系统

    Args:
        log_dir: 日志目录
        log_level: 日志级别（默认从环境变量读取）
        log_format: 日志格式（json_mode=True 时忽略）
        json_mode: 是否输出 JSON 格式日志
    """
    if log_level is None:
        log_level = get_log_level()

    # 获取根日志
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 清理重复的 handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # 创建格式化器
    if json_mode:
        # JSON 格式（用于生产环境 ELK 分析）
        formatter = StructuredLogFormatter(json_mode=True)
    else:
        # 人类可读格式（支持 Trace-ID）
        formatter = StructuredLogFormatter(json_mode=False)

    # 文件 Handler
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f'app_{datetime.now().strftime("%Y%m%d")}.log')
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # 控制台 Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 设置子模块日志级别
    for name in ['ai_core', 'ai_core.chains', 'ai_core.query_rewriter',
                 'ai_core.hybrid_retriever', 'ai_core.llm', 'ai_core.reranker', 'business']:
        logger = logging.getLogger(name)
        logger.setLevel(log_level)
        logger.propagate = True

    # 导入并设置全局格式化器
    global _log_formatter
    _log_formatter = formatter

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的 logger"""
    return logging.getLogger(name)


# 延迟导入避免循环依赖
_log_formatter = None


class StructuredLogFormatter(logging.Formatter):
    """结构化日志格式化器（支持 Trace-ID）"""

    def __init__(self, json_mode: bool = False):
        super().__init__()
        self.json_mode = json_mode
        self._trace_id = None

    def format(self, record: logging.LogRecord) -> str:
        # 从 contextvars 获取 trace_id
        try:
            from .structured_logging import get_trace_id
            trace_id = get_trace_id()
        except Exception:
            trace_id = None

        # 构建基础日志数据
        if self.json_mode:
            import json
            log_data = {
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno,
            }
            if trace_id:
                log_data["trace_id"] = trace_id
            if record.exc_info:
                log_data["exception"] = self.formatException(record.exc_info)
            return json.dumps(log_data, ensure_ascii=False)
        else:
            # 人类可读格式
            trace_str = f"[{trace_id}] " if trace_id else ""
            return f"{self.formatTime(record)} - {record.levelname:8s} - [{record.name}:{record.lineno}] {trace_str}{record.getMessage()}"
