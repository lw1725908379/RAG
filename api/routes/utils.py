# -*- coding: utf-8 -*-
"""
工具 API 路由（精简版）
保留：打分、指标、日志、RAG工具
"""
from flask import Blueprint, jsonify
import json
from datetime import datetime
import logging
import os

# 创建蓝图
utils_bp = Blueprint('utils', __name__, url_prefix='/api')
logger = logging.getLogger(__name__)

# 配置
SCORES_PATH = None
LOG_DIR = None


def init_utils_routes(scores_path, log_dir):
    """初始化工具路由的全局变量"""
    global SCORES_PATH, LOG_DIR
    SCORES_PATH = scores_path
    LOG_DIR = log_dir


@utils_bp.route('/score', methods=['POST'])
def save_score():
    """保存打分"""
    from flask import request

    data = request.json
    key = f"{hash(data.get('query', ''))}_{data.get('case_id', '')}"

    scores = load_scores()
    scores[key] = {
        "query": data.get('query'),
        "case_id": data.get('case_id'),
        "rating": int(data.get('rating', 3)),
        "timestamp": datetime.now().isoformat()
    }

    save_scores(scores)
    logger.info(f"保存打分: 查询={data.get('query')[:30]}, 评分={data.get('rating')}分")

    return jsonify({"success": True})


@utils_bp.route('/metrics')
def metrics():
    """获取性能指标"""
    from business import performance_monitor as pm

    scores = load_scores()

    return jsonify({
        "performance": pm.get_metrics(),
        "scores": {
            "total": len(scores),
            "avg": round(sum(s.get('rating', 0) for s in scores.values()) / max(len(scores), 1), 2)
        } if scores else {"total": 0, "avg": 0}
    })


@utils_bp.route('/logs')
def get_logs():
    """获取日志"""
    global LOG_DIR

    try:
        log_file = os.path.join(LOG_DIR, f'app_{datetime.now().strftime("%Y%m%d")}.log')
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                return jsonify({"logs": lines[-50:]})
        return jsonify({"logs": []})
    except Exception as e:
        return jsonify({"error": str(e)})


@utils_bp.route('/tool/rag', methods=['POST'])
def rag_tool_api():
    """RAG工具API - 供外部Agent调用"""
    from flask import request

    data = request.json
    query = data.get('query', '')
    session_id = data.get('session_id', 'default')
    top_k = data.get('top_k', 5)

    if not query:
        return jsonify({"success": False, "error": "查询不能为空"})

    try:
        from ai_core.tool import rag_tool
        result = rag_tool(
            query=query,
            session_id=session_id,
            top_k=top_k
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"RAG工具调用异常: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)})


@utils_bp.route('/tool/health')
def tool_health():
    """RAG工具健康检查"""
    try:
        from ai_core.tool import health_check
        return jsonify(health_check())
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)})


# ===== 数据操作 =====
def load_scores():
    """加载打分数据"""
    global SCORES_PATH

    import json
    if SCORES_PATH and os.path.exists(SCORES_PATH):
        with open(SCORES_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_scores(data):
    """保存打分数据"""
    global SCORES_PATH

    import json
    if SCORES_PATH:
        with open(SCORES_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
