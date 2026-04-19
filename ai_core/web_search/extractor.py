# -*- coding: utf-8 -*-
"""
网页内容提取器
从 URL 提取正文内容，支持 HTML 清洗
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional, List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 尝试导入 trafilatura (更好的提取)
try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False
    logger.warning("trafilatura 未安装，使用 BeautifulSoup 备用方案")


@dataclass
class ExtractedContent:
    """提取的网页内容"""
    url: str
    title: str
    content: str
    raw_html: str = ""
    length: int = 0

    def to_dict(self):
        return {
            'url': self.url,
            'title': self.title,
            'content': self.content,
            'length': self.length
        }


class ContentExtractor:
    """
    网页内容提取器
    """

    def __init__(
        self,
        timeout: int = 30,
        max_length: int = 8000,
        min_length: int = 100
    ):
        """
        初始化提取器

        Args:
            timeout: 请求超时时间
            max_length: 最大提取字符数
            min_length: 最小有效内容长度
        """
        self.timeout = timeout
        self.max_length = max_length
        self.min_length = min_length

    def extract(self, url: str) -> Optional[ExtractedContent]:
        """
        从 URL 提取内容

        Args:
            url: 目标 URL

        Returns:
            提取的内容，失败返回 None
        """
        if not url:
            return None

        # 验证 URL
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            logger.warning(f"无效 URL: {url}")
            return None

        logger.info(f"提取网页内容: {url}")

        try:
            if TRAFILATURA_AVAILABLE:
                return self._extract_with_trafilatura(url)
            else:
                return self._extract_with_beautifulsoup(url)
        except Exception as e:
            logger.error(f"提取失败: {url}, 错误: {e}")
            return None

    def _extract_with_trafilatura(self, url: str) -> Optional[ExtractedContent]:
        """使用 trafilatura 提取"""
        try:
            # 提取内容
            result = trafilatura.fetch_url(url)
            if not result:
                logger.warning(f"trafilatura 未获取到内容: {url}")
                return self._extract_with_beautifulsoup(url)

            # 提取元数据
            metadata = trafilatura.extract_metadata(
                result,
                output_format='json'
            )

            # 提取正文
            content = trafilatura.extract(
                result,
                output_format='text',
                include_comments=False,
                include_tables=True
            )

            if not content:
                return self._extract_with_beautifulsoup(url)

            # 截断
            content = content[:self.max_length]

            return ExtractedContent(
                url=url,
                title=metadata.get('title', '') if metadata else '',
                content=content,
                raw_html=result,
                length=len(content)
            )

        except Exception as e:
            logger.warning(f"trafilatura 提取失败: {e}")
            return self._extract_with_beautifulsoup(url)

    def _extract_with_beautifulsoup(self, url: str) -> Optional[ExtractedContent]:
        """使用 BeautifulSoup 提取 (备用方案)"""
        try:
            import httpx
            from bs4 import BeautifulSoup

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }

            # 允许重定向
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()

            soup = BeautifulSoup(resp.text, 'html.parser')

            # 移除脚本和样式
            for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                tag.decompose()

            # 提取标题
            title = ''
            if soup.title:
                title = soup.title.string or ''
            elif soup.find('h1'):
                title = soup.find('h1').get_text(strip=True)

            # 提取正文
            content = ''
            main_content = soup.find('main') or soup.find('article') or soup.body

            if main_content:
                # 获取所有段落
                paragraphs = main_content.find_all('p')
                content = ' '.join(p.get_text(strip=True) for p in paragraphs)

            if not content:
                # 备用：获取所有文本
                content = soup.get_text(separator=' ', strip=True)

            # 清洗内容
            content = self._clean_text(content)

            # 截断
            content = content[:self.max_length]

            if len(content) < self.min_length:
                logger.warning(f"内容太短: {url}, 长度={len(content)}")
                return None

            return ExtractedContent(
                url=url,
                title=title,
                content=content,
                raw_html=resp.text,
                length=len(content)
            )

        except Exception as e:
            logger.error(f"BeautifulSoup 提取失败: {e}")
            return None

    def _clean_text(self, text: str) -> str:
        """
        清洗文本

        Args:
            text: 原始文本

        Returns:
            清洗后的文本
        """
        # 移除多余空白
        text = re.sub(r'\s+', ' ', text)
        # 移除特殊字符
        text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
        # 清理 HTML 实体
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')

        return text.strip()

    def extract_batch(self, urls: List[str], max_workers: int = 3) -> List[ExtractedContent]:
        """
        批量提取多个 URL

        Args:
            urls: URL 列表
            max_workers: 最大并发数

        Returns:
            提取的内容列表
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.extract, url): url for url in urls}

            for future in as_completed(futures):
                url = futures[future]
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                except Exception as e:
                    logger.warning(f"提取 {url} 失败: {e}")

        return results
