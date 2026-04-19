# -*- coding: utf-8 -*-
"""
增强日志工具 - 支持 Trace-ID、JSON格式化、性能指标
"""
import os
import json
import uuid
import logging
import time
import functools
from datetime import datetime
from typing import Any, Dict, Optional
from contextvars import ContextVar

# ContextVar 用于跨协程传递 trace_id
_trace_id_var: ContextVar[Optional[str]] = ContextVar('trace_id', default=None)


def generate_trace_id() -> str:
    """生成唯一的 Trace-ID"""
    return f"REQ-{uuid.uuid4().hex[:8]}"


def get_trace_id() -> Optional[str]:
    """获取当前 Trace-ID"""
    return _trace_id_var.get()


def set_trace_id(trace_id: str):
    """设置当前 Trace-ID"""
    _trace_id_var.set(trace_id)


class TraceContext:
    """Trace-ID 上下文管理器"""

    def __init__(self, trace_id: str = None):
        self.trace_id = trace_id or generate_trace_id()
        self.token = None

    def __enter__(self):
        self.token = _trace_id_var.set(self.trace_id)
        return self.trace_id

    def __exit__(self, exc_type, exc_val, exc_tb):
        _trace_id_var.reset(self.token)
        return False


class StructuredLogFormatter(logging.Formatter):
    """结构化 JSON 日志格式化器"""

    def __init__(self, json_mode: bool = False):
        super().__init__()
        self.json_mode = json_mode

    def format(self, record: logging.LogRecord) -> str:
        # 构建基础日志数据
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 添加 Trace-ID
        trace_id = get_trace_id()
        if trace_id:
            log_data["trace_id"] = trace_id

        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # 添加自定义字段（通过 extra 传入）
        if hasattr(record, 'extra_data'):
            log_data.update(record.extra_data)

        # 添加性能指标
        if hasattr(record, 'perf_metrics'):
            log_data["perf_metrics"] = record.perf_metrics

        if self.json_mode:
            return json.dumps(log_data, ensure_ascii=False)
        else:
            # 人类可读格式
            trace_str = f"[{trace_id}] " if trace_id else ""
            level_str = f"{record.levelname:8s}"
            module_str = f"[{record.name}:{record.lineno}]"
            return f"{record.asctime} - {level_str} - {module_str} {trace_str}{record.getMessage()}"


class PerformanceLogger:
    """性能指标日志记录器"""

    @staticmethod
    def log_performance(
        logger: logging.Logger,
        operation: str,
        duration: float,
        extra: Dict[str, Any] = None
    ):
        """记录性能指标"""
        metrics = {
            "operation": operation,
            "duration_sec": round(duration, 3),
        }
        if extra:
            metrics.update(extra)

        # 使用 extra 传递性能数据
        extra_data = {"perf_metrics": metrics}
        logger.info(f"性能指标: {operation} 耗时 {duration:.3f}s", extra={"extra_data": extra_data})

    @staticmethod
    def log_retrieval_summary(
        logger: logging.Logger,
        query: str,
        results: list,
        scores: list = None
    ):
        """记录检索效果概览"""
        if not results:
            logger.info(f"检索总结: Query='{query}', 结果数=0")
            return

        # 提取文档 ID
        doc_ids = [r.get('id', r.get('doc_id', f'doc_{i}')) for i, r in enumerate(results)]
        top1_score = scores[0] if scores else results[0].get('score', 0)
        mean_score = sum(scores) / len(scores) if scores else 0

        summary = {
            "query": query[:50],
            "result_count": len(results),
            "top1_score": round(top1_score, 4),
            "mean_score": round(mean_score, 4),
            "doc_ids": doc_ids[:5]  # 只显示前5个
        }

        logger.info(
            f"检索总结: Query='{query[:30]}...', Top1={top1_score:.4f}, Mean={mean_score:.4f}, "
            f"结果数={len(results)}, IDs={doc_ids[:3]}",
            extra={"extra_data": {"retrieval_summary": summary}}
        )


def log_performance_decorator(operation_name: str = None):
    """性能日志装饰器"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            operation = operation_name or func.__name__
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                # 获取 logger
                logger = logging.getLogger(func.__module__)
                PerformanceLogger.log_performance(logger, operation, duration)
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger = logging.getLogger(func.__module__)
                logger.error(f"{operation} 失败: {e}, 耗时 {duration:.3f}s", exc_info=True)
                raise
        return wrapper
    return decorator


class StructuredLogger:
    """结构化日志记录器 - 简化接口"""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.name = name

    def info(self, message: str, **kwargs):
        """记录信息日志"""
        extra = {"extra_data": kwargs} if kwargs else None
        self.logger.info(message, extra=extra)

    def debug(self, message: str, **kwargs):
        extra = {"extra_data": kwargs} if kwargs else None
        self.logger.debug(message, extra=extra)

    def warning(self, message: str, **kwargs):
        extra = {"extra_data": kwargs} if kwargs else None
        self.logger.warning(message, extra=extra)

    def error(self, message: str, exc_info: bool = True, **kwargs):
        """记录错误日志（默认包含堆栈）"""
        extra = {"extra_data": kwargs} if kwargs else None
        self.logger.error(message, exc_info=exc_info, extra=extra)

    def perf(self, operation: str, duration: float, **kwargs):
        """记录性能指标"""
        PerformanceLogger.log_performance(self.logger, operation, duration, kwargs)

    def retrieval(self, query: str, results: list, scores: list = None):
        """记录检索概览"""
        PerformanceLogger.log_retrieval_summary(self.logger, query, results, scores)
