# -*- coding: utf-8 -*-
"""
AI核心层 - 嵌入模型模块
第3层：AI核心层
"""
import os
import logging
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# 配置
MODEL_NAME = "BAAI/bge-large-zh-v1.5"
EMBEDDING_DIM = 1024  # 向量维度 (从768升级到1024)


class EmbeddingModel:
    """嵌入模型封装"""

    def __init__(self, model_path=None):
        self.model = None
        self.model_path = model_path

    def load(self, local_path=None):
        """加载模型"""
        if local_path and os.path.exists(local_path):
            logger.info(f"加载本地嵌入模型: {local_path}")
            self.model = SentenceTransformer(local_path)
        else:
            logger.info(f"加载嵌入模型: {MODEL_NAME}")
            self.model = SentenceTransformer(MODEL_NAME)

        logger.info(f"嵌入模型加载完成，向量维度: {EMBEDDING_DIM}")
        return self

    def encode(self, texts, normalize=True):
        """编码文本为向量"""
        if self.model is None:
            raise ValueError("模型未加载，请先调用 load()")

        if isinstance(texts, str):
            texts = [texts]

        embeddings = self.model.encode(
            texts,
            normalize_embeddings=normalize,
            convert_to_numpy=True
        )

        return embeddings if len(embeddings) > 1 else embeddings[0].tolist()

    def encode_query(self, query):
        """编码查询"""
        return self.encode(query)


# 全局单例（延迟加载）
_embedding_model = None
_embedding_model_path = None


def get_embedding_model():
    """获取嵌入模型单例（延迟加载，首次调用时加载模型）"""
    global _embedding_model, _embedding_model_path
    if _embedding_model is None:
        _embedding_model = EmbeddingModel()
        # 延迟加载：首次获取时才加载模型
        _embedding_model.load(_embedding_model_path)
    return _embedding_model


def init_embedding_model(local_path=None):
    """初始化嵌入模型（可选，如果调用则会预加载模型）"""
    global _embedding_model, _embedding_model_path
    _embedding_model_path = local_path  # 保存路径但不立即加载
    # 立即加载模型（可选）
    _embedding_model = EmbeddingModel()
    _embedding_model.load(local_path)
    return _embedding_model
