# -*- coding: utf-8 -*-
"""
Serper 搜索引擎实现 (可选)
需安装: pip install serper-python
"""
import logging
from typing import List
from .search_engine import SearchEngine, SearchResult

logger = logging.getLogger(__name__)

SERPER_AVAILABLE = False
try:
    import serper
    SERPER_AVAILABLE = True
except ImportError:
    logger.warning("serper-python 未安装，使用 pip install serper-python 安装")


class SerperSearch(SearchEngine):
    """
    Serper 搜索引擎
    Google 搜索结果，质量高
    需要 API Key: https://serper.dev/
    """

    def __init__(
        self,
        api_key: str = None,
        max_results: int = 10,
        timeout: int = 30
    ):
        """
        初始化 Serper 搜索

        Args:
            api_key: Serper API Key
            max_results: 最大返回结果数
            timeout: 超时时间
        """
        super().__init__(max_results, timeout)

        if not api_key:
            import os
            api_key = os.getenv('SERPER_API_KEY')

        if not api_key:
            raise ValueError("需要提供 Serper API Key")

        self.api_key = api_key
        self.base_url = "https://google.serper.dev/search"

    def search(self, query: str, **kwargs) -> List[SearchResult]:
        """
        执行 Serper 搜索

        Args:
            query: 搜索关键词
            **kwargs: 其他参数

        Returns:
            搜索结果列表
        """
        if not query:
            return []

        logger.info(f"Serper 搜索: {query}")

        try:
            import httpx

            headers = {
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json"
            }
            payload = {
                "q": query,
                "num": self.max_results
            }

            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    self.base_url,
                    headers=headers,
                    json=payload
                )
                resp.raise_for_status()
                data = resp.json()

            results = []
            for item in data.get('organic', []):
                results.append(SearchResult(
                    title=item.get('title', ''),
                    url=item.get('link', ''),
                    snippet=item.get('snippet', ''),
                    relevance=item.get('citeScore', 0.5)
                ))

            logger.info(f"Serper 返回 {len(results)} 条结果")
            return results

        except Exception as e:
            logger.error(f"Serper 搜索失败: {e}")
            return []
