# -*- coding: utf-8 -*-
"""
AI核心层 - 智能检索模块
第3层：AI核心层
使用 FAISS 作为向量数据库
支持 Re-ranking 提升精度
"""
import os
import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# 尝试导入 FAISS
try:
    import faiss
    import numpy as np
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    logger.warning("FAISS 未安装，请运行: pip install faiss-cpu")


class FAISSRetriever:
    """FAISS 向量检索器"""

    def __init__(
        self,
        dimension: int = 1024,
        index_path: str = None,
        enable_rerank: bool = True,
        rerank_top_k: int = 10,
        final_top_k: int = 3
    ):
        """
        初始化 FAISS 检索器

        Args:
            dimension: 向量维度
            index_path: 索引文件路径
            enable_rerank: 是否启用Re-ranking
            rerank_top_k: Re-ranking前检索的数量
            final_top_k: 最终返回数量
        """
        self.dimension = dimension
        self.index_path = index_path
        self.index = None
        self.documents = []
        self.metadatas = []
        self.ids = []

        # Re-ranking 配置
        self.enable_rerank = enable_rerank
        self.rerank_top_k = rerank_top_k
        self.final_top_k = final_top_k
        self.reranker = None

        if FAISS_AVAILABLE:
            # 创建索引 (使用 HNSW 高速索引)
            self.index = faiss.IndexHNSWFlat(dimension, 32)
            logger.info(f"FAISS 索引创建完成: HNSW, dimension={dimension}")

    def _init_reranker(self):
        """初始化Re-ranker（已简化，不再使用独立模块）"""
        # Re-ranking功能已移除，简化系统复杂度
        self.enable_rerank = False
        self.reranker = None

    def load(self, index_path: str):
        """加载索引"""
        if not FAISS_AVAILABLE:
            raise RuntimeError("FAISS 未安装")

        self.index_path = index_path

        # 加载 FAISS 索引
        index_file = f"{index_path}/index.faiss"
        if os.path.exists(index_file):
            self.index = faiss.read_index(index_file)
            logger.info(f"FAISS 索引已加载: {index_file}")

        # 加载文档
        docs_file = f"{index_path}/documents.json"
        if os.path.exists(docs_file):
            with open(docs_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.documents = data.get('documents', [])
                self.metadatas = data.get('metadatas', [])
                self.ids = data.get('ids', [])

        count = self.count()
        logger.info(f"向量库加载完成，共 {count} 条记录")
        return self

    def save(self, index_path: str):
        """保存索引"""
        if self.index is None:
            logger.warning("没有索引可保存")
            return

        os.makedirs(index_path, exist_ok=True)

        # 保存 FAISS 索引
        faiss.write_index(self.index, f"{index_path}/index.faiss")

        # 保存文档
        with open(f"{index_path}/documents.json", 'w', encoding='utf-8') as f:
            json.dump({
                'documents': self.documents,
                'metadatas': self.metadatas,
                'ids': self.ids,
                'dimension': self.dimension
            }, f, ensure_ascii=False)

        logger.info(f"索引已保存: {index_path}")

    def add_vectors(self, vectors: List[List[float]], documents: List[str], metadatas: List[Dict] = None, ids: List[str] = None):
        """添加向量"""
        if not FAISS_AVAILABLE:
            raise RuntimeError("FAISS 未安装")

        vectors_array = np.array(vectors).astype('float32')
        self.index.add(vectors_array)

        self.documents.extend(documents)
        if metadatas:
            self.metadatas.extend(metadatas)
        if ids:
            self.ids.extend(ids)

        logger.info(f"已添加 {len(vectors)} 个向量，总计 {self.index.ntotal}")

    def search(
        self,
        query_vector: List[float],
        top_k: int = None,
        use_rerank: bool = None
    ) -> List[Dict]:
        """
        向量相似度搜索

        Args:
            query_vector: 查询向量
            top_k: 返回数量（可选）
            use_rerank: 是否使用Re-ranking（可选，默认使用实例配置）

        Returns:
            检索结果列表
        """
        if self.index is None:
            raise ValueError("索引未加载")

        # 确定使用的top_k
        if top_k is None:
            top_k = self.rerank_top_k if (use_rerank or self.enable_rerank) else self.final_top_k

        use_rerank = use_rerank if use_rerank is not None else self.enable_rerank

        # 初始化reranker（延迟加载）
        if use_rerank and self.reranker is None:
            self._init_reranker()

        query_array = np.array([query_vector]).astype('float32')
        distances, indices = self.index.search(query_array, top_k)

        results = []
        for i, idx in enumerate(indices[0]):
            if idx >= 0 and idx < len(self.documents):
                results.append({
                    "document": self.documents[idx],
                    "metadata": self.metadatas[idx] if idx < len(self.metadatas) else {},
                    "distance": float(distances[0][i]),
                    "score": 1 / (1 + float(distances[0][i])),  # 转换为相似度
                    "index": int(idx)
                })

        # Re-ranking
        if use_rerank and self.reranker and results:
            # 需要query来进行rerank，这里暂时跳过
            # 在chains中会调用rerank方法
            logger.debug(f"检索完成: {len(results)} 条，将进行Re-ranking")

        return results

    def count(self) -> int:
        """获取向量数量"""
        return self.index.ntotal if self.index else 0


class KeywordRetriever:
    """关键词检索器（备选）"""

    def __init__(self):
        self.documents = []
        self.ids = []

    def load_documents(self, documents: List[str], ids: List[str] = None):
        """加载文档"""
        self.documents = documents
        self.ids = ids or [str(i) for i in range(len(documents))]

    def search(self, query: str, top_k: int = 3) -> List[Dict]:
        """关键词搜索"""
        query_words = set(query.lower().split())

        scored = []
        for i, doc in enumerate(self.documents):
            doc_lower = doc.lower()
            score = sum(1 for word in query_words if word in doc_lower)

            # 标题匹配加权
            if '##' in doc:
                title_match = doc.split('##')[1].split('(')[0] if '(' in doc else doc.split('##')[1]
                if any(word in title_match.lower() for word in query_words):
                    score += 5

            if score > 0:
                scored.append((score, i, doc))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, idx, doc in scored[:top_k]:
            results.append({
                "document": doc,
                "metadata": {"id": self.ids[idx]},
                "score": score
            })

        return results


# 全局单例
_faiss_retriever = None


def get_faiss_retriever(chroma_path: str = None, dimension: int = 1024) -> FAISSRetriever:
    """获取 FAISS 检索器"""
    global _faiss_retriever

    if _faiss_retriever is None:
        _faiss_retriever = FAISSRetriever(dimension=dimension)

        # 尝试加载索引
        index_path = chroma_path or os.path.join(os.path.dirname(os.path.dirname(__file__)), "faiss_db")
        if os.path.exists(f"{index_path}/documents.json"):
            _faiss_retriever.load(index_path)
        else:
            logger.info(f"FAISS 索引不存在，将在新构建时创建: {index_path}")

    return _faiss_retriever
