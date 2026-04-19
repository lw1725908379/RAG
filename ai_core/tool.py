# -*- coding: utf-8 -*-
"""
AI核心层 - RAG工具封装
用于被外部Agent调用
"""
import logging
import time
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# 全局QAChain实例
_qa_chain = None


def get_qa_chain():
    """获取QAChain实例"""
    global _qa_chain
    if _qa_chain is None:
        from .chains import QAChain
        from .embedding import get_embedding_model
        from .retriever import get_faiss_retriever
        from .llm import get_llm

        embedding_model = get_embedding_model()
        retriever = get_faiss_retriever()
        llm = get_llm()

        _qa_chain = QAChain(
            embedding_model=embedding_model,
            retriever=retriever,
            llm=llm,
            top_k=5,
            retrieve_top_k=10
        )
        logger.info("RAG工具: QAChain初始化完成")
    return _qa_chain


def rag_tool(
    query: str,
    session_id: str = "default",
    top_k: int = 5,
    enable_cache: bool = True
) -> Dict[str, Any]:
    """
    RAG问答工具 - 主要入口函数

    Args:
        query: 用户问题（必须）
        session_id: 会话ID，用于上下文追踪（可选，默认"default"）
        top_k: 返回结果数量（可选，默认5）
        enable_cache: 是否启用缓存（可选，默认True）

    Returns:
        {
            "success": bool,           # 是否成功
            "answer": str,            # 最终答案
            "sources": List[str],     # 参考文档摘要(最多3条)
            "query_type": str,        # 意图类型
            "keywords": List[str],    # 提取的关键词
            "doc_count": int,         # 检索文档数
            "strategy": str,          # 使用的检索策略
            "duration": float,        # 耗时(秒)
            "error": str              # 错误信息(如有)
        }
    """
    start_time = time.time()
    result = {
        "success": False,
        "answer": "",
        "sources": [],
        "query_type": "一般查询",
        "keywords": [],
        "doc_count": 0,
        "strategy": "unknown",
        "duration": 0,
        "error": None
    }

    if not query or not query.strip():
        result["error"] = "查询不能为空"
        return result

    try:
        logger.info(f"[RAG工具] 开始处理: {query[:50]}...")

        # 获取QAChain
        qa_chain = get_qa_chain()

        # 临时修改top_k
        original_top_k = qa_chain.top_k
        qa_chain.top_k = top_k

        # 执行问答
        invoke_result = qa_chain.invoke(query, return_contexts=True)

        # 恢复top_k
        qa_chain.top_k = original_top_k

        # 提取关键信息
        result["success"] = True
        result["answer"] = invoke_result.get("answer", "")
        result["doc_count"] = invoke_result.get("doc_count", 0)
        result["strategy"] = invoke_result.get("strategy", "unknown")

        # 提取CRAG评估结果（用于Agent决策）
        crag_info = invoke_result.get("crag", {})
        result["crag"] = {
            "correct": crag_info.get("correct", 0),
            "ambiguous": crag_info.get("ambiguous", 0),
            "incorrect": crag_info.get("incorrect", 0)
        }

        # 提取意图信息
        rewrite_info = invoke_result.get("rewrite", {})
        intent_info = rewrite_info.get("intent", {})
        result["query_type"] = intent_info.get("primary_intent", "一般查询")
        result["keywords"] = intent_info.get("keywords", [])

        # 提取参考文档摘要(最多3条)
        docs = invoke_result.get("retrieved_docs", [])
        sources = []
        for doc in docs[:3]:
            content = doc.get("document", "")[:200]
            if content:
                sources.append(content.replace("\n", " "))
        result["sources"] = sources

        logger.info(f"[RAG工具] 完成: 策略={result['strategy']}, 文档数={result['doc_count']}")

    except Exception as e:
        logger.error(f"[RAG工具] 异常: {e}", exc_info=True)
        result["error"] = str(e)

    result["duration"] = round(time.time() - start_time, 3)
    return result


def rag_tool_simple(query: str) -> str:
    """
    简化版RAG问答工具 - 仅返回答案

    Args:
        query: 用户问题

    Returns:
        answer: str - 最终答案文本
    """
    result = rag_tool(query)
    if result["success"]:
        return result["answer"]
    else:
        return f"抱歉，处理您的问题时发生错误: {result.get('error', '未知错误')}"


# ===== JSON Schema 定义 (用于LLM Agent对接) =====

RAG_TOOL_SCHEMA = {
    "name": "rag_qa",
    "description": "基于停车场测试用例知识库的智能问答工具。可以回答关于测试方法、流程说明、异常处理、概念咨询等问题。适用于需要从知识库中检索相关测试用例或业务知识的场景。",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "用户的问题或查询内容。例如：'如何测试跟车功能？'、'通道引擎是什么？'、'月租卡如何续费？'"
            },
            "session_id": {
                "type": "string",
                "description": "会话ID，用于保持上下文连贯性。首次调用时可省略或设为'default'，后续追问使用相同ID。",
                "default": "default"
            },
            "top_k": {
                "type": "integer",
                "description": "返回的参考文档数量。默认5条，最多10条。",
                "default": 5,
                "minimum": 1,
                "maximum": 10
            }
        },
        "required": ["query"]
    },
    "responses": {
        "description": "返回问答结果，包含答案和参考来源",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "success": {
                            "type": "boolean",
                            "description": "请求是否成功"
                        },
                        "answer": {
                            "type": "string",
                            "description": "最终答案文本"
                        },
                        "sources": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "参考文档摘要(最多3条)"
                        },
                        "query_type": {
                            "type": "string",
                            "description": "识别的查询类型：测试方法/流程说明/对比分析/异常处理/边界条件/概念咨询/一般查询"
                        },
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "从查询中提取的关键词"
                        },
                        "doc_count": {
                            "type": "integer",
                            "description": "检索到的文档数量"
                        },
                        "strategy": {
                            "type": "string",
                            "description": "使用的检索策略：multi_query/fusion/direct"
                        },
                        "duration": {
                            "type": "number",
                            "description": "处理耗时(秒)"
                        },
                        "error": {
                            "type": "string",
                            "description": "错误信息(如有)"
                        }
                    }
                }
            }
        }
    }
}


# ===== 便捷函数 =====

def init_tool():
    """初始化工具（预热）"""
    get_qa_chain()
    logger.info("RAG工具初始化完成")


def health_check() -> Dict[str, Any]:
    """健康检查"""
    try:
        chain = get_qa_chain()
        embedding_dim = None
        if chain and chain.embedding_model:
            # 尝试从模型对象获取维度
            if hasattr(chain.embedding_model, 'model') and chain.embedding_model.model:
                embedding_dim = chain.embedding_model.model.get_sentence_embedding_dimension()
            # 如果没有，使用常量
            if not embedding_dim:
                from ai_core.embedding import EMBEDDING_DIM
                embedding_dim = EMBEDDING_DIM
        return {
            "status": "healthy",
            "model_loaded": chain is not None,
            "embedding_dim": embedding_dim,
            "doc_count": len(chain.retriever.documents) if chain and chain.retriever else 0
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }
