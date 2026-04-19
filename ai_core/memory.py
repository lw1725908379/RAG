# -*- coding: utf-8 -*-
"""
AI核心层 - 记忆管理模块 (增强版)
支持:
- 短期记忆 (上下文检查)
- 长期记忆 (FAISS向量存储 + TTL)
- Memory_Tool (检索/存储/重要性打分)
- Agent集成
"""
import logging
import time
import json
import os
from typing import Dict, Any, List, Optional
from collections import deque
from datetime import datetime, timedelta
from enum import Enum

import numpy as np
import faiss

logger = logging.getLogger(__name__)

# 配置
MEMORY_FAISS_PATH = "faiss_db/memory_index.faiss"
MEMORY_DOCS_PATH = "faiss_db/memory_docs.json"
DEFAULT_TTL_DAYS = 30  # 默认TTL 30天
IMPORTANCE_THRESHOLD = 7  # 重要性阈值
MEMORY_EMBEDDING_DIM = 1024  # 与主向量库一致


class MemoryImportance(Enum):
    """记忆重要性等级"""
    CRITICAL = 9  # 关键信息 (如账号、密码)
    HIGH = 8     # 高重要性 (偏好、重要决策)
    MEDIUM = 7   # 中等 (一般信息)
    LOW = 6      # 低价值 (闲聊)
    TRIVIAL = 5  # 无价值 (客套话)


class ShortTermMemory:
    """短期记忆 - 存储近N轮对话摘要"""

    def __init__(self, max_turns: int = 5):
        self.max_turns = max_turns
        self.buffer = deque(maxlen=max_turns)

    def add(self, query: str, answer: str, metadata: Dict = None):
        """添加一轮对话"""
        summary = self._summarize(query, answer)
        self.buffer.append({
            "query": query[:100],
            "answer": answer[:200] if answer else "",
            "summary": summary,
            "timestamp": time.time(),
            "metadata": metadata or {}
        })
        logger.debug(f"[短期记忆] 添加轮次，当前{len(self.buffer)}/{self.max_turns}")

    def _summarize(self, query: str, answer: str) -> str:
        """生成对话摘要"""
        query_keywords = query[:30]
        answer_preview = answer[:50] if answer else "无"
        return f"Q:{query_keywords}... A:{answer_preview}..."

    def get_context(self) -> str:
        """获取格式化的上下文"""
        if not self.buffer:
            return ""
        lines = []
        for i, turn in enumerate(self.buffer):
            lines.append(f"轮次{i+1}: {turn['summary']}")
        return "\n".join(lines)

    def get_recent_queries(self) -> List[str]:
        """获取最近的查询"""
        return [turn["query"] for turn in self.buffer]

    def clear(self):
        """清空短期记忆"""
        self.buffer.clear()
        logger.info("[短期记忆] 已清空")


class EntityMemory:
    """长期记忆 - 存储用户偏好和实体信息"""

    def __init__(self):
        self.entities: Dict[str, Dict] = {}
        self.preferences: Dict[str, Any] = {}
        self.tags: Dict[str, List[str]] = {}

    def add_entity(self, entity_type: str, entity_value: str, confidence: float = 1.0):
        if entity_type not in self.entities:
            self.entities[entity_type] = {}
        current = self.entities[entity_type].get(entity_value, 0)
        if confidence > current:
            self.entities[entity_type][entity_value] = confidence
            logger.debug(f"[长期记忆] 添加实体: {entity_type}={entity_value}")

    def add_preference(self, key: str, value: Any):
        self.preferences[key] = {"value": value, "timestamp": time.time()}

    def get_context(self) -> str:
        parts = []
        for entity_type, entities in self.entities.items():
            if entities:
                top_entity = max(entities.items(), key=lambda x: x[1])[0]
                parts.append(f"{entity_type}: {top_entity}")
        for key, pref in self.preferences.items():
            parts.append(f"偏好_{key}: {pref['value']}")
        return "; ".join(parts) if parts else ""

    def clear(self):
        self.entities.clear()
        self.preferences.clear()
        self.tags.clear()


# ===== 增强：长期记忆向量存储 =====

class LongTermMemoryVector:
    """
    长期记忆向量存储
    支持:
    - FAISS向量存储
    - TTL过期管理
    - 重要性评分
    """

    def __init__(self, embedding_model=None):
        self.embedding_model = embedding_model
        self.index = None
        self.documents = []  # {"content": str, "importance": int, "expiry": datetime, "timestamp": datetime}
        self._load_index()

    def _load_index(self):
        """加载索引"""
        try:
            if os.path.exists(MEMORY_FAISS_PATH):
                self.index = faiss.read_index(MEMORY_FAISS_PATH)
                logger.info(f"[长期记忆] 加载向量索引: {self.index.ntotal} 条记录")
            else:
                self.index = faiss.IndexFlatIP(MEMORY_EMBEDDING_DIM)
                logger.info("[长期记忆] 创建新向量索引")

            # 加载文档
            if os.path.exists(MEMORY_DOCS_PATH):
                with open(MEMORY_DOCS_PATH, 'r', encoding='utf-8') as f:
                    self.documents = json.load(f)
                logger.info(f"[长期记忆] 加载文档: {len(self.documents)} 条")
        except Exception as e:
            logger.warning(f"[长期记忆] 初始化失败: {e}")
            self.index = None
            self.documents = []

    def _save_index(self):
        """保存索引"""
        if self.index is None:
            return
        try:
            os.makedirs(os.path.dirname(MEMORY_FAISS_PATH), exist_ok=True)
            faiss.write_index(self.index, MEMORY_FAISS_PATH)
            with open(MEMORY_DOCS_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.documents, f, ensure_ascii=False, indent=2, default=str)
            logger.debug("[长期记忆] 索引已保存")
        except Exception as e:
            logger.warning(f"[长期记忆] 保存失败: {e}")

    def add(
        self,
        content: str,
        importance: int = 7,
        ttl_days: int = DEFAULT_TTL_DAYS,
        metadata: Dict = None
    ) -> bool:
        """
        添加记忆

        Args:
            content: 记忆内容
            importance: 重要性 (1-10)
            ttl_days: 过期天数
            metadata: 额外元数据

        Returns:
            是否添加成功
        """
        if self.index is None or importance < IMPORTANCE_THRESHOLD:
            return False

        # 生成向量
        if self.embedding_model is None:
            from . import get_embedding_model
            self.embedding_model = get_embedding_model()

        try:
            vector = self.embedding_model.encode(content)
            if isinstance(vector, list):
                vector = np.array(vector)

            # 归一化 (FAISS使用IP需要归一化)
            norm = np.linalg.norm(vector)
            if norm > 0:
                vector = vector / norm

            # 添加到索引
            self.index.add(vector.reshape(1, -1))

            # 添加文档
            expiry = datetime.now() + timedelta(days=ttl_days)
            self.documents.append({
                "content": content,
                "importance": importance,
                "expiry": expiry.isoformat(),
                "timestamp": datetime.now().isoformat(),
                "metadata": metadata or {}
            })

            self._save_index()
            logger.info(f"[长期记忆] 添加: {content[:30]}... (重要性:{importance}, TTL:{ttl_days}天)")
            return True
        except Exception as e:
            logger.warning(f"[长期记忆] 添加失败: {e}")
            return False

    def search(self, query: str, top_k: int = 3) -> List[Dict]:
        """
        检索记忆

        Args:
            query: 查询内容
            top_k: 返回数量

        Returns:
            记忆列表 (已过滤过期)
        """
        if self.index is None or self.index.ntotal == 0:
            return []

        try:
            # 编码查询
            if self.embedding_model is None:
                from . import get_embedding_model
                self.embedding_model = get_embedding_model()

            vector = self.embedding_model.encode(query)
            if isinstance(vector, list):
                vector = np.array(vector)
            norm = np.linalg.norm(vector)
            if norm > 0:
                vector = vector / norm

            # 搜索
            scores, indices = self.index.search(vector.reshape(1, -1), min(top_k * 2, len(self.documents)))

            # 过滤过期并返回
            now = datetime.now()
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0 or idx >= len(self.documents):
                    continue
                doc = self.documents[idx]
                # 检查过期
                expiry = datetime.fromisoformat(doc['expiry'])
                if expiry < now:
                    continue  # 已过期
                results.append({
                    "content": doc["content"],
                    "importance": doc["importance"],
                    "score": float(score),
                    "timestamp": doc["timestamp"]
                })
                if len(results) >= top_k:
                    break

            logger.debug(f"[长期记忆] 检索 '{query[:20]}...' 返回 {len(results)} 条")
            return results
        except Exception as e:
            logger.warning(f"[长期记忆] 检索失败: {e}")
            return []

    def clean_expired(self) -> int:
        """清理过期记忆"""
        if not self.documents:
            return 0

        now = datetime.now()
        valid_docs = []
        for doc in self.documents:
            expiry = datetime.fromisoformat(doc['expiry'])
            if expiry >= now:
                valid_docs.append(doc)

        removed = len(self.documents) - len(valid_docs)
        if removed > 0:
            self.documents = valid_docs
            # 重建索引
            self._rebuild_index()
            logger.info(f"[长期记忆] 清理 {removed} 条过期记忆")

        return removed

    def _rebuild_index(self):
        """重建索引"""
        if not self.documents:
            self.index.reset()
            return

        try:
            vectors = []
            for doc in self.documents:
                vec = self.embedding_model.encode(doc["content"])
                if isinstance(vec, list):
                    vec = np.array(vec)
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
                vectors.append(vec)

            self.index.reset()
            self.index.add(np.array(vectors))
            self._save_index()
        except Exception as e:
            logger.warning(f"[长期记忆] 重建索引失败: {e}")


# ===== 技巧1: LLM重要性评估 =====

class ImportanceEvaluator:
    """
    LLM重要性评估器
    """

    def __init__(self, llm=None):
        self.llm = llm

    def evaluate(self, query: str, answer: str) -> Dict[str, Any]:
        """
        评估对话的重要性

        Returns:
            {
                "importance": int,  # 1-10
                "reason": str,      # 判断理由
                "should_store": bool  # 是否应该存储
            }
        """
        if self.llm is None:
            from . import get_llm
            self.llm = get_llm()

        # 构造prompt
        prompt = f"""请评估以下对话信息的重要性（1-10分）:

用户问题: {query}
系统回答: {answer[:200] if answer else '无'}

评分标准:
- 9-10分: 关键信息（账号、密码、重要决策、特殊偏好）
- 7-8分: 重要信息（一般偏好、重要操作）
- 5-6分: 一般信息（闲聊、日常操作）
- 1-4分: 无价值信息（客套话、感谢）

请只输出JSON:
{{"importance": 分数, "reason": "一句话理由", "should_store": true/false}}
"""

        try:
            response = self.llm.generate(prompt)
            # 解析JSON
            import re
            match = re.search(r'\{[\s\S]*\}', response)
            if match:
                result = json.loads(match.group())
                return {
                    "importance": result.get("importance", 5),
                    "reason": result.get("reason", ""),
                    "should_store": result.get("should_store", result.get("importance", 5) >= IMPORTANCE_THRESHOLD)
                }
        except Exception as e:
            logger.warning(f"[重要性评估] 失败: {e}")

        # 默认返回值
        return {
            "importance": 5,
            "reason": "默认评估",
            "should_store": False
        }


# ===== Memory_Tool: Agent专用工具 =====

class MemoryTool:
    """
    记忆工具 - 供Agent调用
    功能:
    - 检索: 向量搜索 + 过期过滤
    - 存储: LLM评估 + 重要性打分 + TTL
    """

    def __init__(self):
        self.long_term = LongTermMemoryVector()
        self.evaluator = ImportanceEvaluator()
        self.importance_threshold = IMPORTANCE_THRESHOLD

    def retrieve(self, query: str, top_k: int = 3) -> Dict[str, Any]:
        """
        检索记忆

        Args:
            query: 查询内容
            top_k: 返回数量

        Returns:
            {
                "success": bool,
                "memories": [...],
                "count": int
            }
        """
        memories = self.long_term.search(query, top_k)
        return {
            "success": True,
            "memories": memories,
            "count": len(memories)
        }

    def store(self, query: str, answer: str) -> Dict[str, Any]:
        """
        存储记忆

        流程:
        1. LLM评估重要性
        2. 达标则添加TTL并存储

        Args:
            query: 用户问题
            answer: 系统回答

        Returns:
            {
                "success": bool,
                "importance": int,
                "stored": bool,
                "reason": str
            }
        """
        # LLM评估
        eval_result = self.evaluator.evaluate(query, answer)
        importance = eval_result["importance"]
        should_store = eval_result["should_store"]

        if not should_store:
            return {
                "success": True,
                "importance": importance,
                "stored": False,
                "reason": f"重要性{importance}低于阈值{self.importance_threshold}"
            }

        # 确定TTL
        ttl_days = 30
        if importance >= 9:
            ttl_days = 90  # 关键信息保留90天
        elif importance >= 8:
            ttl_days = 60  # 重要信息保留60天

        # 提取关键内容存储
        content = f"Q: {query[:100]}\nA: {answer[:200]}"

        stored = self.long_term.add(
            content=content,
            importance=importance,
            ttl_days=ttl_days,
            metadata={"query": query, "answer": answer[:100]}
        )

        return {
            "success": True,
            "importance": importance,
            "stored": stored,
            "reason": f"重要性{importance}，存储{ttl_days}天"
        }

    def clean(self) -> Dict[str, Any]:
        """清理过期记忆"""
        removed = self.long_term.clean_expired()
        return {
            "success": True,
            "removed": removed
        }

    def get_schema(self) -> Dict:
        """获取工具Schema"""
        return {
            "name": "memory",
            "description": "记忆管理工具 - 检索或存储长期记忆",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["retrieve", "store", "clean"],
                        "description": "操作类型"
                    },
                    "query": {
                        "type": "string",
                        "description": "检索时的查询内容"
                    },
                    "answer": {
                        "type": "string",
                        "description": "存储时的回答内容（仅store操作需要）"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "检索返回数量"
                    }
                },
                "required": ["action"]
            }
        }


# ===== 统一会话记忆 =====

class ConversationMemory:
    """
    统一记忆管理器
    整合短期记忆 + 长期记忆 + Memory_Tool
    """

    def __init__(
        self,
        session_id: str = "default",
        max_short_term_turns: int = 5
    ):
        self.session_id = session_id
        self.short_term = ShortTermMemory(max_turns=max_short_term_turns)
        self.long_term = EntityMemory()
        self.long_term_vector = LongTermMemoryVector()
        self.memory_tool = MemoryTool()

        self.history: List[Dict] = []
        logger.info(f"[记忆管理] 会话 {session_id} 初始化完成")

    def add_turn(
        self,
        query: str,
        answer: str,
        metadata: Dict = None,
        auto_store: bool = True
    ):
        """添加一轮对话"""
        # 添加到历史
        self.history.append({
            "query": query,
            "answer": answer,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        })

        # 添加到短期记忆
        self.short_term.add(query, answer, metadata)

        # 提取实体
        self._extract_entities(query, answer)

        # 技巧1: 自动存储重要记忆
        if auto_store:
            self._auto_store_memory(query, answer)

    def _auto_store_memory(self, query: str, answer: str):
        """自动评估并存储重要记忆"""
        result = self.memory_tool.store(query, answer)
        if result["stored"]:
            logger.info(f"[记忆] 自动存储: {result['reason']}")

    def _extract_entities(self, query: str, answer: str):
        """从对话中提取实体"""
        user_type_keywords = {
            "用户类型": ["月租", "月卡", "临时车", "VIP", "储值卡"],
            "角色": ["车主", "管理员", "运维", "客服"],
            "系统": ["jielink", "捷顺", "云停车"]
        }

        text = query + " " + answer
        for entity_type, keywords in user_type_keywords.items():
            for keyword in keywords:
                if keyword in text:
                    self.long_term.add_entity(entity_type, keyword, confidence=0.8)

    def get_augmented_query(self, query: str) -> str:
        """获取增强后的查询（带记忆上下文）"""
        # 1. 短期记忆
        short_context = self.short_term.get_context()
        # 2. 长期记忆向量检索
        relevant_memories = self.long_term_vector.search(query, top_k=2)
        long_context = "\n".join([m["content"] for m in relevant_memories]) if relevant_memories else ""

        if not short_context and not long_context:
            return query

        context_parts = []
        if long_context:
            context_parts.append(f"[长期记忆: {long_context[:100]}...]")
        if short_context:
            recent = self.short_term.get_recent_queries()
            if recent:
                context_parts.append(f"[最近: {recent[-1][:30]}...]")

        if context_parts:
            return " ".join(context_parts) + " " + query
        return query

    def retrieve_memory(self, query: str, top_k: int = 3) -> List[Dict]:
        """检索长期记忆"""
        return self.long_term_vector.search(query, top_k)

    def get_system_prompt(self) -> str:
        """获取带记忆的系统提示"""
        parts = []

        # 长期记忆
        long_context = self.long_term.get_context()
        if long_context:
            parts.append(f"用户背景: {long_context}")

        # 短期记忆
        short_context = self.short_term.get_context()
        if short_context:
            parts.append(f"对话历史:\n{short_context}")

        if parts:
            return "\n".join(parts) + "\n"
        return ""

    def get_history_summary(self, last_n: int = 3) -> str:
        if not self.history:
            return "无历史对话"
        recent = self.history[-last_n:]
        lines = []
        for i, turn in enumerate(recent):
            lines.append(f"{i+1}. Q: {turn['query'][:50]}...")
            if turn.get('answer'):
                lines.append(f"   A: {turn['answer'][:50]}...")
        return "\n".join(lines)

    def is_continuation(self, query: str) -> bool:
        """判断是否为追问"""
        # 1. 检查明确指示词
        indicators = ["它", "这个", "那个", "这", "那", "再", "还有", "补充", "更多", "继续", "?", "还有吗"]
        if any(ind in query for ind in indicators):
            logger.debug(f"[is_continuation] 指示词匹配: {query}")
            return True

        # 2. 检查与最近查询的关键词重叠
        recent = self.short_term.get_recent_queries()
        if recent:
            last_query = recent[-1].lower()
            query_lower = query.lower()

            # 提取关键词（2字以上）
            def extract_keywords(text):
                # 简单分词：提取连续的中文字符
                import re
                return set(re.findall(r'[\u4e00-\u9fa5]{2,}', text))

            last_keywords = extract_keywords(last_query)
            query_keywords = extract_keywords(query_lower)

            # 计算重叠
            common = last_keywords & query_keywords

            # 如果有2个以上关键词重叠，认为是追问
            if len(common) >= 2:
                logger.debug(f"[is_continuation] 关键词重叠: {common}, 上轮: {last_query[:20]}...")
                return True

            # 如果查询本身很短（<10字）且有重叠，也认为是追问
            if len(query) < 10 and common:
                logger.debug(f"[is_continuation] 短查询关键词重叠: {common}")
                return True

        return False

    def clear(self):
        """清空所有记忆"""
        self.short_term.clear()
        self.long_term.clear()
        self.history.clear()
        logger.info(f"[记忆管理] 会话 {self.session_id} 记忆已清空")


# ===== 全局会话管理 =====

class MemoryManager:
    """全局记忆管理器"""

    def __init__(self):
        self.sessions: Dict[str, ConversationMemory] = {}
        self.default_session = "default"
        self.memory_tool = MemoryTool()  # 全局Memory_Tool

    def get_session(self, session_id: str = None) -> ConversationMemory:
        session_id = session_id or self.default_session
        if session_id not in self.sessions:
            self.sessions[session_id] = ConversationMemory(session_id)
            logger.info(f"[记忆管理] 创建新会话: {session_id}")
        return self.sessions[session_id]

    def add_turn(
        self,
        query: str,
        answer: str,
        session_id: str = None,
        metadata: Dict = None
    ):
        session = self.get_session(session_id)
        session.add_turn(query, answer, metadata)

    def get_augmented_query(self, query: str, session_id: str = None) -> str:
        session = self.get_session(session_id)
        return session.get_augmented_query(query)

    def retrieve_memory(self, query: str, session_id: str = None, top_k: int = 3) -> List[Dict]:
        """检索记忆 (供Agent调用)"""
        session = self.get_session(session_id)
        return session.retrieve_memory(query, top_k)

    def is_continuation(self, query: str, session_id: str = None) -> bool:
        session = self.get_session(session_id)
        return session.is_continuation(query)

    def clear_session(self, session_id: str = None):
        session_id = session_id or self.default_session
        if session_id in self.sessions:
            self.sessions[session_id].clear()
            del self.sessions[session_id]

    def clean_expired(self) -> int:
        """清理过期记忆"""
        return self.memory_tool.clean()["removed"]


# 全局实例
_memory_manager = None


def get_memory_manager() -> MemoryManager:
    """获取全局记忆管理器"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
