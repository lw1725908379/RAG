# -*- coding: utf-8 -*-
"""
配置模块 - 统一配置入口
"""
import os
import logging
from pathlib import Path

# ===== 调试模式 =====
DEBUG_MODE = True  # 直接修改此处开启/关闭 DEBUG

# 同步设置环境变量
os.environ["DEBUG_MODE"] = "true" if DEBUG_MODE else "false"
LOG_LEVEL = logging.DEBUG if DEBUG_MODE else logging.INFO

# ===== 项目路径 =====
BASE_DIR = Path(__file__).resolve().parent.parent
BASE_DIR_STR = str(BASE_DIR)

# ===== 目录配置 =====
LOG_DIR = BASE_DIR / "logs"
LOG_DIR_STR = str(LOG_DIR)

DATA_DIR = BASE_DIR / "data"
DATA_DIR_STR = str(DATA_DIR)

FAISS_DIR = BASE_DIR / "faiss_db"
FAISS_DIR_STR = str(FAISS_DIR)

MODELS_DIR = BASE_DIR / "models"
MODELS_DIR_STR = str(MODELS_DIR)

# ===== 文件路径 =====
SCORES_PATH = DATA_DIR / "human_scores.json"
SCORES_PATH_STR = str(SCORES_PATH)

# ===== 测试方案目录配置 =====
TEST_REQUIREMENTS_DIR = "test_requirements"  # 测试需求输入
TEST_STRATEGIES_DIR = "test_strategies"      # 测试策略输出

# 兼容旧路径（软链接或迁移后删除）
TEST_REQUIREMENTS_PATH = DATA_DIR / TEST_REQUIREMENTS_DIR
TEST_STRATEGIES_PATH = DATA_DIR / TEST_STRATEGIES_DIR

# ===== Flask 配置 =====
FLASK_CONFIG = {
    "DEBUG": DEBUG_MODE,
    "PORT": 5000,
    "THREADED": True,
}

# ===== 知识库配置 =====
DEFAULT_KB = "kb_use_cases"  # 单一知识库

KB_CONFIG = {
    "default_top_k": 5,
    "default_routing": "none",
    "default_kb": DEFAULT_KB,
}

# ===== 检索配置 =====
RETRIEVAL_CONFIG = {
    "top_k": 5,
    "retrieve_top_k": 8,          # 减少候选数量提升速度
    "bm25_weight": 0.4,
    "dense_weight": 0.6,
    "hyde_threshold": 20,
}

# ===== 启用/禁用功能开关 =====
FEATURE_FLAGS = {
    "enable_fusion": True,       # 保留混合检索
    "enable_hyde": True,         # 保留 HyDE（对复杂查询有效）
    "enable_crag": False,        # 关闭 CRAG 提升速度
    "enable_query_rewrite": True,
    "enable_rerank": True,
    "enable_onnx": False,        # ONNX 加速（实验性，有稳定性问题）
    "enable_cache": True,        # 启用缓存提升速度
    "rewrite_mode": "fast",      # fast 模式
    "rewrite_simple_only": True, # 只对复杂问题改写，简单问题跳过
    "simple_query_length": 20,   # 缩短阈值，更多查询走快速路径
    "default_top_k": 5,         # 减少检索数量提升速度
    "quality_threshold": 0.7,    # 质量评估阈值
}

# ===== 日志格式 =====
LOG_FORMAT = '%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] %(message)s'

# ===== API 配置 =====
# DeepSeek API Key（集中统一配置在此）
DEEPSEEK_API_KEY = "sk-99203ec9158e490db4f53ff4432bde19"  # 从 .env 迁移
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# 同步设置环境变量，供其他模块使用
os.environ["DEEPSEEK_API_KEY"] = DEEPSEEK_API_KEY
os.environ["DEEPSEEK_URL"] = DEEPSEEK_URL
os.environ["DEEPSEEK_MODEL"] = DEEPSEEK_MODEL

# ===== 确保目录存在 =====
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(FAISS_DIR, exist_ok=True)
