# -*- coding: utf-8 -*-
"""
搜索引擎抽象基类
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """搜索结果"""
    title: str
    url: str
    snippet: str
    relevance: float = 0.0  # 相关性评分 0-1

    def to_dict(self):
        return {
            'title': self.title,
            'url': self.url,
            'snippet': self.snippet,
            'relevance': self.relevance
        }


class SearchEngine(ABC):
    """
    搜索引擎抽象基类
    """

    def __init__(
        self,
        max_results: int = 10,
        timeout: int = 30,
        language: str = "zh-CN"
    ):
        """
        初始化搜索引擎

        Args:
            max_results: 最大返回结果数
            timeout: 超时时间(秒)
            language: 搜索语言
        """
        self.max_results = max_results
        self.timeout = timeout
        self.language = language

    @abstractmethod
    def search(self, query: str, **kwargs) -> List[SearchResult]:
        """
        执行搜索

        Args:
            query: 搜索关键词
            **kwargs: 其他参数

        Returns:
            搜索结果列表
        """
        pass

    def search_with_fallback(
        self,
        queries: List[str],
        **kwargs
    ) -> List[SearchResult]:
        """
        使用多个查询词搜索，结果合并去重

        Args:
            queries: 查询词列表
            **kwargs: 其他参数

        Returns:
            合并去重后的结果
        """
        all_results = []
        seen_urls = set()

        for query in queries:
            try:
                results = self.search(query, **kwargs)
                for r in results:
                    if r.url not in seen_urls:
                        all_results.append(r)
                        seen_urls.add(r.url)
            except Exception as e:
                logger.warning(f"搜索 '{query}' 失败: {e}")
                continue

        # 按相关性排序
        all_results.sort(key=lambda x: x.relevance, reverse=True)
        return all_results[:self.max_results]
