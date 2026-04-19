# -*- coding: utf-8 -*-
"""
搜索路由器
管理多个搜索引擎，支持故障转移
"""
import logging
from typing import List, Optional, Dict, Any
from .search_engine import SearchEngine, SearchResult
from .extractor import ContentExtractor, ExtractedContent

logger = logging.getLogger(__name__)


class SearchRouter:
    """
    搜索路由器
    支持多引擎并行搜索、故障转移
    """

    def __init__(
        self,
        engines: List[SearchEngine] = None,
        use_extractor: bool = True,
        max_content_results: int = 5,
        timeout: int = 30
    ):
        """
        初始化搜索路由器

        Args:
            engines: 搜索引擎列表
            use_extractor: 是否提取网页内容
            max_content_results: 最大内容提取数
            timeout: 超时时间
        """
        self.engines = engines or []
        self.use_extractor = use_extractor
        self.max_content_results = max_content_results
        self.timeout = timeout

        self.extractor = ContentExtractor(timeout=timeout) if use_extractor else None

        logger.info(f"搜索路由器初始化: 引擎数={len(self.engines)}, 内容提取={use_extractor}")

    def add_engine(self, engine: SearchEngine):
        """添加搜索引擎"""
        self.engines.append(engine)
        logger.info(f"添加搜索引擎: {engine.__class__.__name__}")

    def search(
        self,
        query: str,
        extract_content: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行搜索

        Args:
            query: 查询词
            extract_content: 是否提取网页内容
            **kwargs: 其他参数

        Returns:
            {
                'results': List[SearchResult],  # 搜索结果
                'contents': List[ExtractedContent],  # 提取的内容
                'success': bool,
                'error': str
            }
        """
        if not query:
            return {'results': [], 'contents': [], 'success': False, 'error': 'Empty query'}

        # 尝试各个引擎
        for engine in self.engines:
            try:
                logger.info(f"尝试搜索引擎: {engine.__class__.__name__}")
                results = engine.search(query, **kwargs)

                if results:
                    contents = []
                    if extract_content and self.extractor:
                        # 提取前 N 个结果的内容
                        urls = [r.url for r in results[:self.max_content_results]]
                        contents = self.extractor.extract_batch(urls)

                    return {
                        'results': results,
                        'contents': contents,
                        'success': True,
                        'engine': engine.__class__.__name__
                    }

            except Exception as e:
                logger.warning(f"搜索引擎 {engine.__class__.__name__} 失败: {e}")
                continue

        # 所有引擎都失败
        return {
            'results': [],
            'contents': [],
            'success': False,
            'error': 'All search engines failed'
        }

    def search_with_keywords(
        self,
        keywords: List[str],
        extract_content: bool = True
    ) -> Dict[str, Any]:
        """
        使用多个关键词搜索

        Args:
            keywords: 关键词列表
            extract_content: 是否提取内容

        Returns:
            搜索结果
        """
        all_results = []
        all_contents = []
        seen_urls = set()

        for kw in keywords:
            result = self.search(kw, extract_content=False)

            if result['success']:
                for r in result['results']:
                    if r.url not in seen_urls:
                        all_results.append(r)
                        seen_urls.add(r.url)

        # 按相关性排序
        all_results.sort(key=lambda x: x.relevance, reverse=True)

        # 提取内容
        contents = []
        if extract_content and self.extractor:
            urls = [r.url for r in all_results[:self.max_content_results]]
            contents = self.extractor.extract_batch(urls)

        return {
            'results': all_results,
            'contents': contents,
            'success': True,
            'total_results': len(all_results)
        }
