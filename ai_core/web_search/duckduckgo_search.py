# -*- coding: utf-8 -*-
"""
DuckDuckGo 搜索引擎实现
"""
import logging
from typing import List, Optional
from .search_engine import SearchEngine, SearchResult

logger = logging.getLogger(__name__)

# 尝试导入 duckduckgo_search
try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False
    logger.warning("duckduckgo-search 未安装，将使用备用方案")


class DuckDuckGoSearch(SearchEngine):
    """
    DuckDuckGo 搜索引擎
    免费、稳定、无需API Key
    """

    def __init__(
        self,
        max_results: int = 10,
        timeout: int = 30,
        language: str = "zh-CN",
        region: str = "cn"
    ):
        """
        初始化 DuckDuckGo 搜索

        Args:
            max_results: 最大返回结果数
            timeout: 超时时间(秒)
            language: 搜索语言
            region: 搜索区域 (cn, tw, hk, us)
        """
        super().__init__(max_results, timeout, language)
        self.region = region
        self._ddgs = None

    def _get_ddgs(self):
        """获取 DDGS 实例"""
        if DDGS_AVAILABLE and self._ddgs is None:
            self._ddgs = DDGS(timeout=self.timeout)
        return self._ddgs

    def search(self, query: str, **kwargs) -> List[SearchResult]:
        """
        执行 DuckDuckGo 搜索

        Args:
            query: 搜索关键词
            **kwargs: 其他参数

        Returns:
            搜索结果列表
        """
        if not query:
            return []

        logger.info(f"DuckDuckGo 搜索: {query}")

        try:
            if DDGS_AVAILABLE:
                return self._search_with_ddgs(query, **kwargs)
            else:
                return self._search_fallback(query, **kwargs)
        except Exception as e:
            logger.error(f"DuckDuckGo 搜索失败: {e}")
            return []

    def _search_with_ddgs(self, query: str, **kwargs) -> List[SearchResult]:
        """使用 duckduckgo_search 库搜索"""
        ddgs = self._get_ddgs()
        if ddgs is None:
            return self._search_fallback(query, **kwargs)

        results = []
        try:
            # 获取文本结果
            for r in ddgs.text(
                query,
                region=self.region,
                max_results=self.max_results
            ):
                result = SearchResult(
                    title=r.get('title', ''),
                    url=r.get('href', ''),
                    snippet=r.get('body', ''),
                    relevance=self._calculate_relevance(query, r)
                )
                results.append(result)

            logger.info(f"DuckDuckGo 返回 {len(results)} 条结果")
            return results

        except Exception as e:
            logger.warning(f"DDGS 搜索异常: {e}, 尝试备用方案")
            return self._search_fallback(query, **kwargs)

    def _search_fallback(self, query: str, **kwargs) -> List[SearchResult]:
        """
        备用搜索方案 - 使用 httpx 请求 Bing/Google HTML
        """
        # 由于网络问题，备用方案暂时返回空列表
        # 可以实现为使用其他搜索API
        logger.warning("DuckDuckGo 网络不可用，请检查网络连接或配置代理")
        return []

    def _calculate_relevance(self, query: str, result: dict) -> float:
        """
        计算搜索结果与查询的相关性

        Args:
            query: 查询词
            result: 搜索结果

        Returns:
            相关性评分 0-1
        """
        query_lower = query.lower()
        title = result.get('title', '').lower()
        body = result.get('body', '').lower()

        # 简单关键词匹配
        score = 0.0
        query_words = query_lower.split()

        for word in query_words:
            if word in title:
                score += 0.4
            elif word in body:
                score += 0.2

        # 归一化
        return min(score, 1.0)
