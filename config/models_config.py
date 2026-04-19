# -*- coding: utf-8 -*-
"""
模型配置模块 - 统一管理模型路径和配置
"""
import os
from pathlib import Path
from typing import Optional


class ModelConfig:
    """模型配置类"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = Path(__file__).resolve().parent.parent
        self.base_dir = Path(base_dir)

        # 模型目录
        self.models_dir = self.base_dir / "models"
        self.models_dir_str = str(self.models_dir)

        # 嵌入模型
        self.embedding_model_path = self.models_dir / "bge-large-zh-v1.5"
        self.embedding_model_path_str = str(self.embedding_model_path)

        # 重排模型
        self.reranker_model_path = self.models_dir / "bge-reranker-base"
        self.reranker_model_path_str = str(self.reranker_model_path)

    def get_embedding_path(self) -> str:
        """获取嵌入模型路径（如果存在）"""
        if self.embedding_model_path.exists():
            return self.embedding_model_path_str
        return None

    def get_reranker_path(self) -> str:
        """获取重排模型路径（如果存在）"""
        if self.reranker_model_path.exists():
            return self.reranker_model_path_str
        return None

    def get_faiss_path(self, kb_name: str = "kb_use_cases") -> str:
        """获取 FAISS 索引路径"""
        return str(self.base_dir / "faiss_db" / kb_name)


# 全局配置实例
_model_config = None


def get_model_config(base_dir: str = None) -> ModelConfig:
    """获取模型配置单例"""
    global _model_config
    if _model_config is None:
        _model_config = ModelConfig(base_dir)
    return _model_config


# 预定义配置
EMBEDDING_CONFIG = {
    "model_name": "bge-large-zh-v1.5",
    "dimension": 1024,
    "device": "cpu",
}

RERANKER_CONFIG = {
    "model_name": "bge-reranker-base",
    "device": "cpu",
}

LLM_CONFIG = {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "temperature": 0.3,
    "max_tokens": 2000,
}
