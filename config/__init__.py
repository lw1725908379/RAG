# -*- coding: utf-8 -*-
"""
配置模块 - 统一配置入口
"""
from .settings import (
    # 基础配置
    DEBUG_MODE,
    LOG_LEVEL,
    LOG_FORMAT,
    BASE_DIR,
    BASE_DIR_STR,
    # 目录配置
    LOG_DIR,
    LOG_DIR_STR,
    DATA_DIR,
    DATA_DIR_STR,
    FAISS_DIR,
    FAISS_DIR_STR,
    MODELS_DIR,
    MODELS_DIR_STR,
    # 测试方案目录
    TEST_REQUIREMENTS_DIR,
    TEST_STRATEGIES_DIR,
    # 文件路径
    SCORES_PATH,
    SCORES_PATH_STR,
    # Flask 配置
    FLASK_CONFIG,
    # 知识库配置
    KB_CONFIG,
    DEFAULT_KB,
    # 检索配置
    RETRIEVAL_CONFIG,
    # 功能开关
    FEATURE_FLAGS,
    # API 配置
    DEEPSEEK_API_KEY,
    DEEPSEEK_URL,
    DEEPSEEK_MODEL,
)
from .models_config import (
    ModelConfig,
    get_model_config,
    EMBEDDING_CONFIG,
    RERANKER_CONFIG,
    LLM_CONFIG,
)
from .logging_config import (
    setup_logging,
    get_logger,
)
from .structured_logging import (
    generate_trace_id,
    get_trace_id,
    set_trace_id,
    TraceContext,
    StructuredLogger,
    PerformanceLogger,
    log_performance_decorator,
)
from .prompts import (
    PROMPTS,
    QUERY_TYPES,
    classify_query,
    select_prompt,
)

__all__ = [
    # 基础配置
    "DEBUG_MODE",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "BASE_DIR",
    "BASE_DIR_STR",
    # 目录配置
    "LOG_DIR",
    "LOG_DIR_STR",
    "DATA_DIR",
    "DATA_DIR_STR",
    "FAISS_DIR",
    "FAISS_DIR_STR",
    "MODELS_DIR",
    "MODELS_DIR_STR",
    # 测试方案目录
    "TEST_REQUIREMENTS_DIR",
    "TEST_STRATEGIES_DIR",
    # 文件路径
    "SCORES_PATH",
    "SCORES_PATH_STR",
    # Flask 配置
    "FLASK_CONFIG",
    # 知识库配置
    "KB_CONFIG",
    "DEFAULT_KB",
    # 检索配置
    "RETRIEVAL_CONFIG",
    # 功能开关
    "FEATURE_FLAGS",
    # API 配置
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_URL",
    "DEEPSEEK_MODEL",
    # 模型配置
    "ModelConfig",
    "get_model_config",
    "EMBEDDING_CONFIG",
    "RERANKER_CONFIG",
    "LLM_CONFIG",
    # 日志配置
    "setup_logging",
    "get_logger",
    # Prompt
    "PROMPTS",
    "QUERY_TYPES",
    "classify_query",
    "select_prompt",
]
