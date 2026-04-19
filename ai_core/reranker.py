# -*- coding: utf-8 -*-
"""
AI核心层 - 重排模块
使用 BGE Cross-Encoder 进行语义重排
四阶段检索流程：
1. 向量检索 (Top-100)
2. BM25检索 (Top-50)
3. RRF融合 (Top-30)
4. Cross-Encoder重排 (Top-10)
"""
import logging
import os
import time
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# 禁用SSL验证
os.environ['HF_HUB_DISABLE_SSL_VERIFY'] = '1'


class CrossEncoderReranker:
    """
    Cross-Encoder 重排器
    使用 BGE-reranker-base 对候选文档进行精确排序
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-base",
        model_path: str = None,
        top_k: int = 10,
        device: str = "cpu",
        use_fp16: bool = False
    ):
        """
        初始化 Cross-Encoder 重排器
        """
        self.model_name = model_name
        self.model_path = model_path
        self.top_k = top_k
        self.device = device
        self.use_fp16 = use_fp16 and device == "cuda"
        self.model = None
        self._load_model()

    def _load_model(self):
        """加载模型"""
        try:
            from sentence_transformers import CrossEncoder

            # 优先使用本地模型
            if self.model_path and os.path.exists(self.model_path):
                logger.info(f"加载本地 Cross-Encoder 模型: {self.model_path}")
                self.model = CrossEncoder(
                    self.model_path,
                    max_length=512,
                    device=self.device
                )
                logger.info(f"Cross-Encoder 模型加载成功: {self.model_path}")
            else:
                self.model = CrossEncoder(
                    self.model_name,
                    max_length=512,
                    device=self.device
                )
                logger.info(f"Cross-Encoder 模型加载成功: {self.model_name}")
        except Exception as e:
            logger.warning(f"Cross-Encoder 模型加载失败: {e}")
            self.model = None

    def rerank(
        self,
        query: str,
        candidates: List[Dict],
        top_k: int = None
    ) -> List[Dict]:
        """
        对候选文档进行重排
        """
        if not candidates or not self.model:
            return candidates

        top_k = top_k or self.top_k
        start_time = time.time()

        # 提取文档内容
        documents = [doc.get('document', '') for doc in candidates]

        # 构建查询-文档对
        pairs = [[query, doc] for doc in documents]

        # 批量预测分数
        try:
            scores = self.model.predict(pairs)
        except Exception as e:
            logger.warning(f"重排预测失败: {e}")
            return candidates

        # 为每个文档添加重排分数
        for i, doc in enumerate(candidates):
            doc['rerank_score'] = float(scores[i])

        # 按重排分数排序
        ranked = sorted(candidates, key=lambda x: x.get('rerank_score', 0), reverse=True)

        duration = time.time() - start_time
        logger.info(
            f"重排完成: 耗时 {duration:.2f}s, 输入 {len(candidates)} 条, 输出 {top_k} 条, "
            f"Top1分数={ranked[0].get('rerank_score', 0):.4f}" if ranked else f"重排完成: 耗时 {duration:.2f}s"
        )

        return ranked[:top_k]

    def rerank_with_context(
        self,
        query: str,
        candidates: List[str],
        top_k: int = None
    ) -> List[Dict]:
        """
        简化版重排（文档直接传入）
        """
        if not candidates or not self.model:
            return [{"document": doc, "rerank_score": 0} for doc in candidates]

        top_k = top_k or self.top_k
        pairs = [[query, doc] for doc in candidates]

        try:
            scores = self.model.predict(pairs)
        except Exception as e:
            logger.warning(f"重排预测失败: {e}")
            return [{"document": doc, "rerank_score": 0} for doc in candidates]

        results = []
        for i, doc in enumerate(candidates):
            results.append({
                "document": doc,
                "rerank_score": float(scores[i])
            })

        results.sort(key=lambda x: x["rerank_score"], reverse=True)
        return results[:top_k]


class LightweightReranker:
    """
    轻量级重排器
    基于关键词匹配和位置的特征进行快速排序
    """

    def __init__(self, top_k: int = 10):
        self.top_k = top_k

    def rerank(self, query: str, candidates: List[Dict], top_k: int = None) -> List[Dict]:
        """
        轻量级重排
        """
        top_k = top_k or self.top_k
        import re

        query_terms = set(query.lower().split())

        for doc in candidates:
            document = doc.get('document', '')
            doc_lower = document.lower()

            # 初始化分数
            rerank_score = doc.get('score', 0)

            # 1. 标题匹配加分
            title_match = re.search(r'##\s*(.+?)\s*\(ID:', document)
            if title_match:
                title = title_match.group(1).lower()
                for term in query_terms:
                    if term in title:
                        rerank_score += 0.3

            # 2. 查询词精确匹配加分
            for term in query_terms:
                if term in doc_lower:
                    rerank_score += 0.1

            # 3. 查询词在文档开头出现加分
            if doc_lower.startswith(query_terms.pop() if query_terms else ''):
                rerank_score += 0.1

            doc['rerank_score'] = rerank_score

        ranked = sorted(candidates, key=lambda x: x.get('rerank_score', 0), reverse=True)
        return ranked[:top_k]


# 全局单例
_reranker = None


def get_reranker(
    model_name: str = "BAAI/bge-reranker-base",
    model_path: str = None,
    top_k: int = 10,
    use_lightweight: bool = False,
    use_onnx: bool = False
) -> Any:
    """
    获取重排器

    Args:
        model_name: Cross-Encoder模型名称
        model_path: 本地模型路径
        top_k: 返回Top-K
        use_lightweight: 是否使用轻量级重排

    Returns:
        重排器实例
    """
    global _reranker

    if _reranker is None:
        if use_lightweight:
            _reranker = LightweightReranker(top_k=top_k)
            logger.info("使用轻量级重排器")
        else:
            _reranker = CrossEncoderReranker(
                model_name=model_name,
                model_path=model_path,
                top_k=top_k
            )
            # 记录实际使用的模型路径
            if model_path and os.path.exists(model_path):
                logger.info(f"使用本地 Cross-Encoder 模型: {model_path}")
            else:
                logger.info(f"使用远程 Cross-Encoder 模型: {model_name}")

    return _reranker


def init_reranker(
    model_name: str = "BAAI/bge-reranker-base",
    top_k: int = 10,
    force_reload: bool = False
) -> Any:
    """
    初始化重排器
    """
    return get_reranker(model_name, top_k=top_k)
