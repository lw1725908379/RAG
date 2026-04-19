# -*- coding: utf-8 -*-
"""
第2层：应用逻辑层 - 业务逻辑模块
- 日志记录
- 性能监控
- 缓存管理
"""

from .logger import (
    PerformanceMonitor,
    performance_monitor,
    RequestLogger,
    BusinessLogger,
    log_request,
    performance_monitor as pm
)

from .cache import (
    Cache,
    RedisCache,
    MemoryCache,
    QuestionCache,
    get_question_cache,
    CacheConfig
)

__all__ = [
    # Logger
    'PerformanceMonitor',
    'performance_monitor',
    'pm',
    'RequestLogger',
    'BusinessLogger',
    'log_request',
    # Cache
    'Cache',
    'RedisCache',
    'MemoryCache',
    'QuestionCache',
    'get_question_cache',
    'CacheConfig',
]
