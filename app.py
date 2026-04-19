# -*- coding: utf-8 -*-
"""
Test Strategy Generator (MCP)
聚焦于原子化需求 -> 测试用例生成
"""
import os

# 禁用SSL验证
os.environ['HF_HUB_DISABLE_SSL_VERIFY'] = '1'

from flask import Flask, jsonify

# ===== 配置模块 =====
from config import (
    DEBUG_MODE,
    LOG_LEVEL,
    LOG_FORMAT,
    BASE_DIR,
    BASE_DIR_STR,
    FLASK_CONFIG,
    DEFAULT_KB,
)
from config.logging_config import setup_logging
from config.models_config import get_model_config

# 配置日志
logger = setup_logging(
    log_dir=os.path.join(BASE_DIR_STR, "logs"),
    log_level=LOG_LEVEL,
    log_format=LOG_FORMAT
).getChild(__name__)

# ===== Flask 应用 =====
app = Flask(__name__)

# 全局变量
qa_chain = None


def init(lazy=False):
    """初始化系统

    Args:
        lazy: 是否延迟加载模型（True=首次请求时加载，False=启动时加载）
    """
    global qa_chain

    logger.info("=" * 50)
    logger.info("Test Strategy Generator 启动中...")
    logger.info("=" * 50)

    # 获取模型配置
    model_config = get_model_config(BASE_DIR_STR)

    # 导入AI核心层
    from ai_core import init_qa_chain
    from ai_core.chains import get_qa_chain

    logger.info("初始化 AI Engine...")

    if lazy:
        # 延迟加载模式：服务快速启动，模型在首次请求时加载
        # 只预加载 FAISS 向量库（内存占用较小）
        from ai_core.retriever import get_faiss_retriever
        faiss_kb_path = model_config.get_faiss_path(DEFAULT_KB)
        retriever = get_faiss_retriever(faiss_kb_path)
        logger.info("FAISS 向量库已加载（延迟加载模式）")
        # 不在这里初始化 qa_chain，让它在首次请求时加载
    else:
        # 立即加载模式
        faiss_kb_path = model_config.get_faiss_path(DEFAULT_KB)
        qa_chain = init_qa_chain(
            model_path=model_config.get_embedding_path(),
            chroma_path=faiss_kb_path,
            reranker_model_path=model_config.get_reranker_path()
        )
        logger.info("QA Chain 已初始化（立即加载模式）")

    # 导入业务层
    from business import get_question_cache, performance_monitor as pm
    cache = get_question_cache()

    logger.info(f"缓存初始化完成 (类型: {type(cache.cache).__name__})")

    # 注册路由
    from api.routes.register import register_routes
    register_routes(
        app=app,
        qa_chain=qa_chain,
        cache=cache,
        pm=pm,
        kb_manager=None,
        base_dir=BASE_DIR_STR,
        model_path=model_config.get_embedding_path()
    )

    logger.info("系统就绪!")
    print(f"服务启动: http://localhost:5000")


# ===== 根路径 =====
@app.route('/')
def index():
    """API 信息"""
    return jsonify({
        "name": "Test Strategy Generator",
        "version": "1.0",
        "description": "原子化需求 -> 测试用例生成",
        "endpoints": {
            "health": "/api/mcp/health",
            "generate": "/api/mcp/generate-test-strategy",
            "generate_async": "/api/mcp/generate-test-strategy-async",
            "task_status": "/api/mcp/task/<task_id>",
            "token_stats": "/api/mcp/token-stats"
        }
    })


# 全局错误处理
@app.errorhandler(500)
def handle_500(e):
    import traceback
    logger.error(f"500错误: {e}")
    logger.error(traceback.format_exc())
    return f"服务器错误: {e}", 500


# ===== 启动 =====
if __name__ == '__main__':
    # 进程管理：清理残留进程
    import subprocess
    import time
    try:
        # 尝试清理可能残留的 python 进程
        subprocess.run(['taskkill', '/F', '/IM', 'python.exe'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        time.sleep(1)
    except:
        pass

    # 使用延迟加载模式（首次请求时加载模型）
    # 如需预加载模型，可调用 init()
    init()
    app.run(debug=False, port=FLASK_CONFIG["PORT"], threaded=FLASK_CONFIG["THREADED"])
