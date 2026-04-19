# -*- coding: utf-8 -*-
"""
AI核心层 - RAG智能路由器
支持多种路由策略：Logical(LLM意图分类) / Semantic(embedding相似度)
"""
import os
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RoutingDecision:
    """路由决策结果"""
    strategy: str  # "logical" | "semantic" | "cross"
    selected_kbs: List[str]
    reasoning: str
    confidence: float = 1.0


class LogicalRouter:
    """
    逻辑路由器 - 基于LLM意图分析
    使用LLM分析用户查询意图，自动选择相关知识库
    """

    # 知识库领域定义 - 只保留用例库
    KB_DOMAINS = {
        "use_cases": "测试用例、禅道用例、功能测试、测试场景"
    }

    # 意图关键词映射 - 只保留用例相关
    INTENT_KEYWORDS = {
        "use_cases": ["测试用例", "用例", "测试场景", "测试点", "功能测试", "测试步骤", "预期结果"]
    }

    def __init__(self, llm=None):
        self.llm = llm

    def route(self, query: str, available_kbs: List[str]) -> RoutingDecision:
        """
        基于LLM进行路由决策

        Args:
            query: 用户查询
            available_kbs: 可用的知识库ID列表

        Returns:
            路由决策结果
        """
        # 先用关键词快速判断
        keyword_result = self._keyword_route(query, available_kbs)

        # 如果LLM可用，使用LLM进行更精确的判断
        if self.llm:
            try:
                llm_result = self._llm_route(query, available_kbs)
                # 合并结果
                if llm_result.selected_kbs:
                    return llm_result
            except Exception as e:
                logger.warning(f"LLM路由失败，使用关键词路由: {e}")

        return keyword_result

    def _keyword_route(self, query: str, available_kbs: List[str]) -> RoutingDecision:
        """基于关键词的快速路由"""
        query_lower = query.lower()
        scores = {}

        for kb_id in available_kbs:
            keywords = self.INTENT_KEYWORDS.get(kb_id, [])
            score = sum(1 for kw in keywords if kw in query_lower)
            scores[kb_id] = score

        # 选择得分最高的KB
        if scores and max(scores.values()) > 0:
            selected = [kb for kb, score in scores.items() if score == max(scores.values())]
            # 如果多个KB得分相同，返回全部
            confidence = max(scores.values()) / max(len(keywords) for keywords in self.INTENT_KEYWORDS.values())
            return RoutingDecision(
                strategy="logical",
                selected_kbs=selected,
                reasoning=f"关键词匹配: {query}",
                confidence=min(confidence + 0.3, 1.0)
            )

        # 没有匹配，返回全部KB
        return RoutingDecision(
            strategy="logical",
            selected_kbs=available_kbs,
            reasoning=f"无明确意图，查询全部知识库: {query}",
            confidence=0.5
        )

    def _llm_route(self, query: str, available_kbs: List[str]) -> RoutingDecision:
        """基于LLM的路由"""
        if not self.llm:
            return self._keyword_route(query, available_kbs)

        # 构建提示
        kb_info = "\n".join([
            f"- {kb_id}: {self.KB_DOMAINS.get(kb_id, '')}"
            for kb_id in available_kbs
        ])

        prompt = f"""你是一个智能路由器，负责根据用户查询选择最相关的知识库。

可用知识库:
{kb_info}

用户查询: {query}

请分析用户查询的意图，选择最相关的知识库。

输出格式（JSON）:
{{
    "selected_kbs": ["kb_id1", "kb_id2"],
    "reasoning": "简短的原因说明",
    "confidence": 0.0-1.0
}}

注意：如果查询涉及多个领域，可以选择多个知识库。
"""

        try:
            response = self.llm.generate(prompt)
            import json

            # 解析JSON响应
            # 尝试提取JSON部分
            if "{" in response and "}" in response:
                json_str = response[response.find("{"):response.rfind("}")+1]
                result = json.loads(json_str)

                selected = result.get("selected_kbs", [])
                # 验证KB有效性
                selected = [kb for kb in selected if kb in available_kbs]

                if selected:
                    return RoutingDecision(
                        strategy="logical",
                        selected_kbs=selected,
                        reasoning=result.get("reasoning", ""),
                        confidence=result.get("confidence", 0.8)
                    )
        except Exception as e:
            logger.warning(f"LLM路由解析失败: {e}")

        # 回退到关键词路由
        return self._keyword_route(query, available_kbs)


class SemanticRouter:
    """
    语义路由器 - 基于Embedding相似度
    为每个知识库生成描述向量，计算与查询的相似度
    """

    def __init__(self, embedding_model=None):
        self.embedding_model = embedding_model
        self.kb_embeddings: Dict[str, List[float]] = {}

    def set_kb_domains(self, kb_configs: Dict[str, Dict]):
        """设置知识库领域描述"""
        if not self.embedding_model:
            logger.warning("Embedding模型未初始化，使用默认领域匹配")
            return

        for kb_id, config in kb_configs.items():
            domain_desc = config.get("description", "")
            name = config.get("name", kb_id)
            full_desc = f"{name} {domain_desc}"

            try:
                embedding = self.embedding_model.encode(full_desc)
                self.kb_embeddings[kb_id] = embedding.tolist()
                logger.info(f"已生成KB嵌入: {kb_id}")
            except Exception as e:
                logger.warning(f"生成KB嵌入失败 {kb_id}: {e}")

    def route(self, query: str, available_kbs: List[str]) -> RoutingDecision:
        """
        基于语义相似度进行路由

        Args:
            query: 用户查询
            available_kbs: 可用的知识库ID列表

        Returns:
            路由决策结果
        """
        if not self.embedding_model or not self.kb_embeddings:
            # 无embedding模型，返回全部
            return RoutingDecision(
                strategy="semantic",
                selected_kbs=available_kbs,
                reasoning="无embedding模型，查询全部知识库",
                confidence=0.5
            )

        try:
            # 计算query embedding
            query_embedding = self.embedding_model.encode(query)

            # 计算与每个KB的相似度
            scores = {}
            for kb_id in available_kbs:
                kb_embedding = self.kb_embeddings.get(kb_id)
                if kb_embedding is not None:
                    similarity = self._cosine_similarity(
                        query_embedding,
                        kb_embedding
                    )
                    scores[kb_id] = similarity

            if not scores:
                return RoutingDecision(
                    strategy="semantic",
                    selected_kbs=available_kbs,
                    reasoning="无KB嵌入，查询全部知识库",
                    confidence=0.5
                )

            # 选择相似度最高的KB
            max_score = max(scores.values())
            threshold = 0.3  # 相似度阈值

            if max_score < threshold:
                # 相似度太低，查询全部
                selected = available_kbs
                reasoning = f"最高相似度 {max_score:.2f} 低于阈值"
                confidence = 0.5
            else:
                # 选择相似度高于阈值的KB
                selected = [kb for kb, score in scores.items() if score >= threshold]
                if not selected:
                    # 没有满足阈值的，选择最高的
                    selected = [max(scores, key=scores.get)]
                    confidence = max_score
                else:
                    confidence = sum(scores[kb] for kb in selected) / len(selected)

            return RoutingDecision(
                strategy="semantic",
                selected_kbs=selected,
                reasoning=f"语义相似度: {query}",
                confidence=confidence
            )

        except Exception as e:
            logger.error(f"语义路由失败: {e}")
            return RoutingDecision(
                strategy="semantic",
                selected_kbs=available_kbs,
                reasoning=f"语义路由异常: {str(e)}",
                confidence=0.5
            )

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """计算余弦相似度"""
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)


class RAGRouter:
    """
    RAG智能路由器
    整合Logical和Semantic路由策略
    """

    def __init__(self, kb_router, embedding_model=None, llm=None):
        """
        初始化RAG路由器

        Args:
            kb_router: 知识库路由器实例
            embedding_model: embedding模型
            llm: 大语言模型
        """
        self.kb_router = kb_router
        self.embedding_model = embedding_model
        self.llm = llm

        # 初始化路由策略
        self.logical_router = LogicalRouter(llm=llm)
        self.semantic_router = SemanticRouter(embedding_model=embedding_model)

        # 设置KB领域描述
        self.semantic_router.set_kb_domains(kb_router.kb_configs)

    def route(self, query: str, mode: str = "auto") -> Dict[str, Any]:
        """
        执行路由查询

        Args:
            query: 用户查询
            mode: 路由模式
                - "auto": 自动选择最佳策略
                - "logical": 仅使用LLM逻辑路由
                - "semantic": 仅使用语义路由
                - "cross": 跨库查询（查询全部）

        Returns:
            包含路由决策和查询结果的字典
        """
        available_kbs = list(self.kb_router.kbs.keys())

        if not available_kbs:
            return {
                "error": "没有可用的知识库",
                "query": query
            }

        # 根据模式选择路由策略
        if mode == "cross":
            # 跨库查询
            decision = RoutingDecision(
                strategy="cross",
                selected_kbs=available_kbs,
                reasoning="跨库查询模式",
                confidence=1.0
            )
        elif mode == "logical":
            # 逻辑路由
            decision = self.logical_router.route(query, available_kbs)
        elif mode == "semantic":
            # 语义路由
            decision = self.semantic_router.route(query, available_kbs)
        else:
            # auto模式：优先语义，备选逻辑
            decision = self.semantic_router.route(query, available_kbs)
            if not decision.selected_kbs or len(decision.selected_kbs) == len(available_kbs):
                # 语义路由返回全部，回退到逻辑
                decision = self.logical_router.route(query, available_kbs)

        # 执行查询
        results = self.kb_router.query(
            query=query,
            kbs=decision.selected_kbs,
            mode="single" if len(decision.selected_kbs) == 1 else "cross"
        )

        # 添加路由信息
        results["routing"] = {
            "strategy": decision.strategy,
            "selected_kbs": decision.selected_kbs,
            "reasoning": decision.reasoning,
            "confidence": decision.confidence
        }

        return results


def get_rag_router(kb_router=None, embedding_model=None, llm=None):
    """
    获取RAG路由器实例

    Args:
        kb_router: 知识库路由器
        embedding_model: embedding模型
        llm: 大语言模型

    Returns:
        RAGRouter实例
    """
    if kb_router is None:
        from .kb_router import get_router
        kb_router = get_router()

    return RAGRouter(
        kb_router=kb_router,
        embedding_model=embedding_model,
        llm=llm
    )
