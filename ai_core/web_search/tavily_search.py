# -*- coding: utf-8 -*-
"""
Tavily 搜索引擎实现 (可选)
需安装: pip install tavily-python
"""
import logging
from typing import List
from .search_engine import SearchEngine, SearchResult

logger = logging.getLogger(__name__)

TAVILY_AVAILABLE = False
try:
    from tavily import TavilyClient
    TAVILY_AVAILABLE = True
except ImportError:
    logger.warning("tavily-python 未安装，使用 pip install tavily-python 安装")


class TavilySearch(SearchEngine):
    """
    Tavily 搜索引擎
    专为 RAG 设计，结果质量高
    需要 API Key: https://app.tavily.com/
    """

    def __init__(
        self,
        api_key: str = None,
        max_results: int = 10,
        timeout: int = 30,
        include_answer: bool = True,
        include_raw_content: bool = False
    ):
        """
        初始化 Tavily 搜索

        Args:
            api_key: Tavily API Key
            max_results: 最大返回结果数
            timeout: 超时时间
            include_answer: 是否包含AI生成的答案
            include_raw_content: 是否包含原始内容
        """
        super().__init__(max_results, timeout)
        self.api_key = api_key
        self.include_answer = include_answer
        self.include_raw_content = include_raw_content

        if not TAVILY_AVAILABLE:
            logger.error("tavily-python 未安装")
            raise ImportError("tavily-python 未安装，请运行: pip install tavily-python")

        if not api_key:
            logger.warning("未提供 Tavily API Key，将从环境变量 TAVILY_API_KEY 获取")
            import os
            api_key = os.getenv('TAVILY_API_KEY')

        if not api_key:
            raise ValueError("需要提供 Tavily API Key")

        self.client = TavilyClient(api_key=api_key)

    def search(self, query: str, **kwargs) -> List[SearchResult]:
        """
        执行 Tavily 搜索

        Args:
            query: 搜索关键词
            **kwargs: 其他参数

        Returns:
            搜索结果列表
        """
        if not query:
            return []

        logger.info(f"Tavily 搜索: {query}")

        try:
            response = self.client.search(
                query=query,
                max_results=self.max_results,
                include_answer=self.include_answer,
                include_raw_content=self.include_raw_content
            )

            results = []
            for item in response.get('results', []):
                results.append(SearchResult(
                    title=item.get('title', ''),
                    url=item.get('url', ''),
                    snippet=item.get('content', ''),
                    relevance=item.get('score', 0.5)
                ))

            logger.info(f"Tavily 返回 {len(results)} 条结果")
            return results

        except Exception as e:
            logger.error(f"Tavily 搜索失败: {e}")
            return []
