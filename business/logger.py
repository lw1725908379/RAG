# -*- coding: utf-8 -*-
"""
第2层：应用逻辑层 - 业务逻辑模块
- 日志记录
- 性能监控
- 缓存管理
"""
import os
import time
import logging
import functools
from datetime import datetime
from typing import Callable, Any

logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """性能监控器"""

    def __init__(self):
        self.metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "avg_response_time": 0,
            "total_response_time": 0,
            "slow_requests": 0,  # >10秒
        }
        self.request_times = []

    def record_request(self, duration: float, success: bool = True):
        """记录请求"""
        self.metrics["total_requests"] += 1
        if success:
            self.metrics["successful_requests"] += 1
        else:
            self.metrics["failed_requests"] += 1

        self.request_times.append(duration)
        self.metrics["total_response_time"] += duration

        # 保持最近1000条记录
        if len(self.request_times) > 1000:
            self.request_times = self.request_times[-1000:]

        # 计算平均响应时间
        if self.request_times:
            self.metrics["avg_response_time"] = sum(self.request_times) / len(self.request_times)

        # 记录慢请求
        if duration > 10:
            self.metrics["slow_requests"] += 1
            logger.warning(f"慢请求: {duration:.2f}秒")

    def get_metrics(self) -> dict:
        """获取指标"""
        return {
            **self.metrics,
            "avg_response_time": round(self.metrics["avg_response_time"], 3),
            "success_rate": round(
                self.metrics["successful_requests"] / max(self.metrics["total_requests"], 1) * 100, 2
            )
        }

    def reset(self):
        """重置指标"""
        self.metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "avg_response_time": 0,
            "total_response_time": 0,
            "slow_requests": 0,
        }
        self.request_times = []


# 性能监控装饰器
def performance_monitor(func: Callable) -> Callable:
    """性能监控装饰器"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            performance_monitor.record_request(duration, success=True)
            logger.info(f"{func.__name__} 执行时间: {duration:.3f}秒")
            return result
        except Exception as e:
            duration = time.time() - start_time
            performance_monitor.record_request(duration, success=False)
            logger.error(f"{func.__name__} 执行失败: {e}")
            raise

    return wrapper


# 全局性能监控器
performance_monitor = PerformanceMonitor()


class RequestLogger:
    """请求日志记录器"""

    @staticmethod
    def log_request(query: str, method: str = "chat"):
        """记录请求"""
        logger.info(f"[请求] 方法: {method}, 查询: {query[:50]}")

    @staticmethod
    def log_response(query: str, duration: float, case_count: int = 0):
        """记录响应"""
        logger.info(f"[响应] 查询: {query[:30]}, 耗时: {duration:.3f}秒, 用例数: {case_count}")

    @staticmethod
    def log_error(query: str, error: str):
        """记录错误"""
        logger.error(f"[错误] 查询: {query[:30]}, 错误: {error}")

    @staticmethod
    def log_score(query: str, rating: int):
        """记录打分"""
        logger.info(f"[打分] 查询: {query[:30]}, 评分: {rating}分")


class BusinessLogger:
    """业务日志"""

    @staticmethod
    def log_user_action(action: str, details: dict = None):
        """记录用户行为"""
        details = details or {}
        logger.info(f"[用户行为] {action}, 详情: {details}")

    @staticmethod
    def log_system_event(event: str, details: dict = None):
        """记录系统事件"""
        details = details or {}
        logger.info(f"[系统事件] {event}, 详情: {details}")


# 请求日志装饰器
def log_request(func: Callable) -> Callable:
    """请求日志装饰器"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        query = kwargs.get('query', args[0] if args else '')

        RequestLogger.log_request(query, func.__name__)

        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            case_count = len(result.get('cases', [])) if isinstance(result, dict) else 0
            RequestLogger.log_response(query, duration, case_count)
            return result
        except Exception as e:
            RequestLogger.log_error(query, str(e))
            raise

    return wrapper
