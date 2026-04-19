# -*- coding: utf-8 -*-
"""
路由注册模块 - MCP 测试策略生成系统
"""
from flask import Flask
import logging

logger = logging.getLogger(__name__)


def register_routes(app: Flask, qa_chain, cache, pm, kb_manager, base_dir, model_path):
    """
    注册路由蓝图

    Args:
        app: Flask 应用实例
        qa_chain: QAChain 实例
        cache: 缓存实例
        pm: 性能监控实例
        kb_manager: 知识库管理器实例
        base_dir: 基础目录
        model_path: 模型路径
    """
    # 初始化 utils 路由
    from .utils import utils_bp, init_utils_routes
    from config import SCORES_PATH, LOG_DIR
    init_utils_routes(SCORES_PATH, LOG_DIR)

    # 初始化 MCP 路由（测试策略生成）
    from .mcp import mcp_bp, init_mcp_routes
    init_mcp_routes(qa_chain)

    # 注册蓝图
    app.register_blueprint(mcp_bp)
    app.register_blueprint(utils_bp)

    logger.info("路由蓝图已注册 (mcp, utils)")
