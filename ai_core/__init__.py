# -*- coding: utf-8 -*-
"""
AI核心层 (AI Engine)
四层架构：交互层 → 业务层 → AI核心层 → 数据层

模块:
- embedding: 嵌入模型 (BGE-large-zh-v1.5)
- retriever: 向量检索 (FAISS)
- summarizer: 多表示索引 (原始文档 + 摘要)
- hybrid_retriever: 混合检索 (BM25 + 向量 + HyDE)
- reranker: Cross-Encoder重排 (BGE-reranker-base)
- crag: 纠错检索增强生成 (CRAG)
- query_rewriter: Query改写 (意图识别、同义词、LLM改写)
- knowledge_base: 知识库管理 (导入/重建)
- kb_router: 知识库路由器 (多知识库支持)
- document_parser: 文档解析器 (支持JSON/TXT/MD/Word/PDF)
- data_cleaner: 数据清洗器 (OCR文档清洗)
- requirements_cleaner: 需求文档清洗（HTML表格、语义切分）
- doc_processor: 统一文档处理接口
- llm: 大语言模型 (DeepSeek)
- prompt: 提示工程
- chains: 工作流编排
- tool: RAG工具封装 (供外部Agent调用)
"""
import logging
import os

# ===== 先导入 config 确保环境变量已设置 =====
import config

# 从 config 获取 API Key 并设置到环境变量（供后续模块使用）
if config.DEEPSEEK_API_KEY:
    os.environ["DEEPSEEK_API_KEY"] = config.DEEPSEEK_API_KEY
    os.environ["DEEPSEEK_URL"] = config.DEEPSEEK_URL
    os.environ["DEEPSEEK_MODEL"] = config.DEEPSEEK_MODEL

# 从环境变量读取 DEBUG_MODE（由 config/settings.py 设置）
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
LOG_LEVEL = logging.DEBUG if DEBUG_MODE else logging.INFO

# 设置 ai_core 根日志级别
ai_core_logger = logging.getLogger('ai_core')
ai_core_logger.setLevel(LOG_LEVEL)
# 不设置 propagate，让 root logger 的 handler 处理输出

from .embedding import EmbeddingModel, get_embedding_model, init_embedding_model
from .retriever import FAISSRetriever, KeywordRetriever, get_faiss_retriever
from .summarizer import MultiGranularitySummarizer, get_summarizer
from .hybrid_retriever import (
    HybridRetriever,
    get_hyde_retriever,
    BM25Retriever,
    FusionRetriever,
    SparseDenseFusion
)
from .reranker import CrossEncoderReranker, LightweightReranker, get_reranker, init_reranker
from .crag import CRAGEvaluator, KnowledgeRefiner, CRAGRetriever, DocumentRelevance
from .query_rewriter import (
    IntentDetectorLLM,
    SynonymExpander,
    LLMRewriter,
    QueryRewriter,
    get_query_rewriter,
    init_query_rewriter
)
from .knowledge_base import KnowledgeBaseManager, get_kb_manager, init_kb_manager
from .kb_router import KnowledgeBaseRouter, get_router, reset_router
from .rag_router import RAGRouter, LogicalRouter, SemanticRouter, get_rag_router, RoutingDecision
from .document_parser import DocumentParser, parse_documents
from .data_cleaner import DataCleaner, CleanerConfig, clean_text, clean_documents
from .requirements_cleaner import RequirementsCleaner, chunk_document, clean_requirements_text
from .doc_processor import DocumentCleaner, clean_and_chunk, process_import
from .llm import LLM, get_llm
from .prompt import PromptTemplate, prompt_template
from .chains import QAChain, get_qa_chain, init_qa_chain
from .tool import rag_tool, rag_tool_simple, RAG_TOOL_SCHEMA, init_tool, health_check
from .agent import ReActAgent, AgentAction, get_react_agent, react_query
from .memory import (
    ShortTermMemory,
    EntityMemory,
    ConversationMemory,
    LongTermMemoryVector,
    ImportanceEvaluator,
    MemoryTool,
    MemoryManager,
    get_memory_manager
)

__all__ = [
    'EmbeddingModel', 'get_embedding_model', 'init_embedding_model',
    'FAISSRetriever', 'KeywordRetriever', 'get_faiss_retriever',
    'MultiGranularitySummarizer', 'get_summarizer',
    'HybridRetriever', 'get_hyde_retriever',
    'BM25Retriever', 'FusionRetriever', 'SparseDenseFusion',
    'CrossEncoderReranker', 'LightweightReranker', 'get_reranker', 'init_reranker',
    'CRAGEvaluator', 'KnowledgeRefiner', 'CRAGRetriever', 'DocumentRelevance',
    'IntentDetectorLLM', 'SynonymExpander', 'LLMRewriter', 'QueryRewriter',
    'get_query_rewriter', 'init_query_rewriter',
    'KnowledgeBaseManager', 'get_kb_manager', 'init_kb_manager',
    'KnowledgeBaseRouter', 'get_router', 'reset_router',
    'RAGRouter', 'LogicalRouter', 'SemanticRouter', 'get_rag_router', 'RoutingDecision',
    'DocumentParser', 'parse_documents',
    'DataCleaner', 'CleanerConfig', 'clean_text', 'clean_documents',
    'LLM', 'get_llm',
    'PromptTemplate', 'prompt_template',
    'QAChain', 'get_qa_chain', 'init_qa_chain',
    # tool模块
    'rag_tool', 'rag_tool_simple', 'RAG_TOOL_SCHEMA', 'init_tool', 'health_check',
    # agent模块
    'ReActAgent', 'AgentAction', 'get_react_agent', 'react_query',
    # memory模块
    'ShortTermMemory', 'EntityMemory', 'ConversationMemory',
    'LongTermMemoryVector', 'ImportanceEvaluator', 'MemoryTool',
    'MemoryManager', 'get_memory_manager',
]
