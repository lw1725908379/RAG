# -*- coding: utf-8 -*-
"""
统一文档处理接口
根据文档类型自动选择合适的清洗策略
"""

import re
from typing import List, Dict, Callable


class DocumentCleaner:
    """文档清洗器统一接口"""

    _cleaners: Dict[str, Callable] = {}

    @classmethod
    def register(cls, doc_type: str, cleaner_func: Callable):
        cls._cleaners[doc_type] = cleaner_func

    @classmethod
    def clean(cls, text: str, doc_type: str = "generic") -> str:
        cleaner = cls._cleaners.get(doc_type)
        if cleaner:
            return cleaner(text)
        return cls._default_clean(text)

    @staticmethod
    def _default_clean(text: str) -> str:
        # 移除图片链接
        text = re.sub(r'!\[?\]\(https?://[^)]+\)', '', text)
        text = re.sub(r'<img[^>]*>', '', text)
        # 清理多余空白
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        return text.strip()


def _register_cleaners():
    """注册清洗器 - 只保留用例库"""

    # 通用清洗器
    def generic_cleaner(text: str) -> str:
        return DocumentCleaner._default_clean(text)

    # 测试用例清洗器
    def test_case_cleaner(text: str) -> str:
        # 移除图片链接
        text = re.sub(r'!\[?\]\(https?://[^)]+\)', '', text)
        # 清理多余空白
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        # 标准化测试用例格式
        text = re.sub(r'(?:ID|用例编号|编号)[:：]\s*(\w+)', r'ID: \1', text)
        return text.strip()

    DocumentCleaner.register("generic", generic_cleaner)
    DocumentCleaner.register("use_cases", test_case_cleaner)


_register_cleaners()


# ========== 核心函数 ==========

# 默认最小chunk长度
DEFAULT_MIN_LENGTH = 50


def clean_and_chunk(text: str, doc_type: str = "generic",
                    doc_id: str = "",
                    overlap_ratio: float = 0.2,
                    max_chunk_size: int = 2000,
                    min_length: int = DEFAULT_MIN_LENGTH,
                    deduplicate: bool = True) -> List[Dict]:
    """
    清洗并切分文档（统一入口）

    Args:
        text: 原始文本
        doc_type: 文档类型
        doc_id: 文档ID
        overlap_ratio: 重叠比例（保留，为未来扩展）
        max_chunk_size: 最大块大小（保留）
        min_length: 最小chunk长度，过滤太短的
        deduplicate: 是否去重

    Returns:
        [{"content": str, "metadata": dict}, ...]
    """
    # 1. 清洗
    cleaned_text = DocumentCleaner.clean(text, doc_type)

    # 2. 通用切分：按段落切分
    chunks = _generic_chunk(cleaned_text, doc_id, min_length)

    # 3. 过滤无效chunks
    chunks = [c for c in chunks if len(c['content'].strip()) >= min_length]

    # 4. 添加文档类型元数据
    for chunk in chunks:
        chunk["metadata"]["doc_type"] = doc_type

    return chunks


def _generic_chunk(text: str, doc_id: str, min_length: int = DEFAULT_MIN_LENGTH) -> List[Dict]:
    """通用切分：按段落"""
    paragraphs = text.split('\n\n')
    chunks = []
    for i, para in enumerate(paragraphs):
        para = para.strip()
        # 过滤太短的段落
        if len(para) >= min_length:
            chunks.append({
                "content": para,
                "metadata": {
                    "doc_id": doc_id,
                    "chunk_id": i
                }
            })
    # 如果没有有效chunks，返回整个文本
    if not chunks and text.strip():
        chunks.append({
            "content": text.strip()[:1000],  # 截断太长的
            "metadata": {"doc_id": doc_id, "chunk_id": 0}
        })
    return chunks


def process_import(documents: List[Dict], doc_type: str = "generic",
                  min_length: int = DEFAULT_MIN_LENGTH,
                  deduplicate: bool = True) -> List[Dict]:
    """
    处理导入的文档列表

    Args:
        documents: [{"id": str, "title": str, "content": str}, ...]
        doc_type: 文档类型
        min_length: 最小chunk长度
        deduplicate: 是否去重

    Returns:
        清洗并切分后的文档列表
    """
    results = []

    for doc in documents:
        doc_id = doc.get("id", "")
        title = doc.get("title", "")
        content = doc.get("content", "")

        # 组合完整文本
        full_text = f"{title}\n\n{content}" if title else content

        # 清洗并切分
        chunks = clean_and_chunk(full_text, doc_type, doc_id,
                                  min_length=min_length, deduplicate=deduplicate)

        for chunk in chunks:
            results.append({
                "content": chunk["content"],
                "metadata": {
                    **chunk["metadata"],
                    "original_id": doc_id,
                    "title": title
                }
            })

    return results
