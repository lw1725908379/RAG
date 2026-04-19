# -*- coding: utf-8 -*-
"""
Web Search 模块
提供搜索引擎抽象和多种实现
"""
from .search_engine import SearchEngine, SearchResult
from .duckduckgo_search import DuckDuckGoSearch
from .extractor import ContentExtractor
from .router import SearchRouter

__all__ = [
    'SearchEngine',
    'SearchResult',
    'DuckDuckGoSearch',
    'ContentExtractor',
    'SearchRouter',
    'get_search_engine'
]


def get_search_engine(
    provider: str = "duckduckgo",
    **kwargs
) -> SearchEngine:
    """
    获取搜索引擎实例

    Args:
        provider: 搜索引擎提供商 (duckduckgo, tavily, serper)
        **kwargs: 其他参数

    Returns:
        搜索引擎实例
    """
    if provider == "duckduckgo":
        return DuckDuckGoSearch(**kwargs)
    elif provider == "tavily":
        from .tavily_search import TavilySearch
        return TavilySearch(**kwargs)
    elif provider == "serper":
        from .serper_search import SerperSearch
        return SerperSearch(**kwargs)
    else:
        raise ValueError(f"Unknown search provider: {provider}")
