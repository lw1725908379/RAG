# -*- coding: utf-8 -*-
"""
AI核心层 - 数据清洗模块
根据用户规则对OCR文档进行数据清洗
优先级：P0> P1> P2> P3
"""
import re
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CleanerConfig:
    """清洗配置"""
    # P0 - 必须处理
    fullwidth_to_halfwidth: bool = True      # 全角转半角
    fix_punctuation: bool = True             # 标点符号规范
    fix_product_names: bool = True           # 产品名称规范

    # P1 - 推荐处理
    fix_ocr_errors: bool = True              # OCR错别字
    fix_duplicates: bool = True              # 重复词修正
    clean_directory: bool = True             # 目录清理

    # P2 - 需人工确认
    fix_chapter_numbers: bool = False        # 章节编号修复
    clean_tables: bool = False              # HTML表格处理

    # P3 - 可选
    clean_images: bool = False              # 图片链接清理
    clean_comments: bool = True             # 注释清理


class DataCleaner:
    """
    数据清洗器
    根据规则对文本进行清洗
    """

    # 全角转半角映射
    FULLWIDTH_MAP = {
        # 数字
        '０': '0', '１': '1', '２': '2', '３': '3', '４': '4',
        '５': '5', '６': '6', '７': '7', '８': '8', '９': '9',
        # 大写字母
        'Ａ': 'A', 'Ｂ': 'B', 'Ｃ': 'C', 'Ｄ': 'D', 'Ｅ': 'E',
        'Ｆ': 'F', 'Ｇ': 'G', 'Ｈ': 'H', 'Ｉ': 'I', 'Ｊ': 'J',
        'Ｋ': 'K', 'Ｌ': 'L', 'Ｍ': 'M', 'Ｎ': 'N', 'Ｏ': 'O',
        'Ｐ': 'P', 'Ｑ': 'Q', 'Ｒ': 'R', 'Ｓ': 'S', 'Ｔ': 'T',
        'Ｕ': 'U', 'Ｖ': 'V', 'Ｗ': 'W', 'Ｘ': 'X', 'Ｙ': 'Y', 'Ｚ': 'Z',
        # 小写字母
        'ａ': 'a', 'ｂ': 'b', 'ｃ': 'c', 'ｄ': 'd', 'ｅ': 'e',
        'ｆ': 'f', 'ｇ': 'g', 'ｈ': 'h', 'ｉ': 'i', 'ｊ': 'j',
        'ｋ': 'k', 'ｌ': 'l', 'ｍ': 'm', 'ｎ': 'n', 'ｏ': 'o',
        'ｐ': 'p', 'ｑ': 'q', 'ｒ': 'r', 'ｓ': 's', 'ｔ': 't',
        'ｕ': 'u', 'ｖ': 'v', 'ｗ': 'w', 'ｘ': 'x', 'ｙ': 'y', 'ｚ': 'z',
        # 符号
        '．': '.', '：': ':', '；': ';', '，': ',', '（': '(', '）': ')',
        '＋': '+', '－': '-', '＊': '*', '／': '/', '＝': '=',
        '！': '!', '？': '?', '【': '[', '】': ']', '－': '-',
    }

    # 产品名称映射
    PRODUCT_NAMES = {
        'jielink': 'JieLink',
        'jielink': 'JieLink',
        'jie.link': 'JieLink',
    }

    # 产品型号 (需要大写)
    PRODUCT_CODES = ['JSKT', 'JSM', 'JSPJ', 'JSRJ', 'JSQ', 'JST', 'JSFW']

    # OCR常见错别字
    OCR_ERRORS = {
        '下位几': '下位机',
        '上位几': '上位机',
        '坐曹': '坐席',
        '柑入': '录入',
        '车场': '停车场',
        '停停车场': '停车场',
    }

    # 重复词
    DUPLICATE_WORDS = [
        ('详细详情', '详情'),
        ('倒车倒车', '倒车'),
        ('试试', '试'),
        ('来来', '来'),
    ]

    def __init__(self, config: CleanerConfig = None):
        self.config = config or CleanerConfig()

    def clean(self, text: str) -> str:
        """
        清洗单条文本

        Args:
            text: 输入文本

        Returns:
            清洗后的文本
        """
        if not text:
            return text

        result = text

        # P0 - 必须处理
        if self.config.fullwidth_to_halfwidth:
            result = self._fix_fullwidth(result)

        if self.config.fix_punctuation:
            result = self._fix_punctuation(result)

        if self.config.fix_product_names:
            result = self._fix_product_names(result)

        # P1 - 推荐处理
        if self.config.fix_ocr_errors:
            result = self._fix_ocr_errors(result)

        if self.config.fix_duplicates:
            result = self._fix_duplicates(result)

        if self.config.clean_directory:
            result = self._clean_directory(result)

        # P2 - 需人工确认
        if self.config.clean_tables:
            result = self._clean_tables(result)

        # P3 - 可选
        if self.config.clean_images:
            result = self._clean_images(result)

        if self.config.clean_comments:
            result = self._clean_comments(result)

        return result

    def clean_batch(self, texts: List[str]) -> List[str]:
        """批量清洗"""
        return [self.clean(text) for text in texts]

    # ========== P0: 字符格式 ==========

    def _fix_fullwidth(self, text: str) -> str:
        """全角转半角"""
        result = []
        for char in text:
            result.append(self.FULLWIDTH_MAP.get(char, char))
        return ''.join(result)

    def _fix_punctuation(self, text: str) -> str:
        """标点符号规范"""
        # 多个句点变一个
        text = re.sub(r'\.{4,}', '', text)
        # 省略号变删除
        text = re.sub(r'\.{5,}', '', text)
        # 分号转英文
        text = text.replace('；', ';')
        # 多个分号变一个
        text = re.sub(r';+', ';', text)
        return text

    def _fix_product_names(self, text: str) -> str:
        """产品名称规范"""
        # 统一jielink
        text = re.sub(r'[Jj][Ii][Ee][Ll][Ii][Nn][Kk]', 'JieLink', text)

        # 产品型号大写
        for code in self.PRODUCT_CODES:
            # 匹配不区分大小写的型号
            pattern = re.compile(code.lower(), re.IGNORECASE)
            text = pattern.sub(code, text)

        return text

    # ========== P1: 错别字 ==========

    def _fix_ocr_errors(self, text: str) -> str:
        """OCR错别字修正"""
        for wrong, correct in self.OCR_ERRORS.items():
            text = text.replace(wrong, correct)
        return text

    def _fix_duplicates(self, text: str) -> str:
        """重复词修正"""
        for wrong, correct in self.DUPLICATE_WORDS:
            text = text.replace(wrong, correct)
        return text

    def _clean_directory(self, text: str) -> str:
        """目录清理 - 删除填充点号"""
        # 匹配: 需求背景................................5  或  需求背景.......
        # 删除连续点号和后面的数字
        text = re.sub(r'(\w+)\.{3,}\d*$', r'\1', text)
        return text

    # ========== P2: 需人工确认 ==========

    def _clean_tables(self, text: str) -> str:
        """HTML表格处理 - 转换为纯文本"""
        # 匹配HTML表格
        table_pattern = r'<table[^>]*>(.*?)</table>'
        tables = re.findall(table_pattern, text, re.DOTALL)

        for table_html in tables:
            # 提取表格内容
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL)
            lines = []
            for row in rows:
                cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL)
                # 清理单元格内容
                cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                if cells:
                    # 转换为 "列1: 内容1, 列2: 内容2" 格式
                    lines.append(' | '.join(cells))

            table_text = '\n'.join(lines)
            text = text.replace(table_html, table_text)

        return text

    # ========== P3: 可选 ==========

    def _clean_images(self, text: str) -> str:
        """图片链接清理"""
        # 删除OCR产生的外部API链接
        text = re.sub(r'https://web-api\.textin\.com[^\s]*', '[图片]', text)
        text = re.sub(r'https://[^\s]+\.(jpg|png|gif|bmp|jpeg|webp)[^\s]*', '[图片]', text)
        return text

    def _clean_comments(self, text: str) -> str:
        """注释清理"""
        # HTML注释
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        # Markdown注释
        text = re.sub(r'\[//\]:\s*#.*', '', text)
        return text


def clean_text(text: str, config: CleanerConfig = None) -> str:
    """
    便捷函数：清洗文本

    Args:
        text: 输入文本
        config: 清洗配置

    Returns:
        清洗后的文本
    """
    cleaner = DataCleaner(config)
    return cleaner.clean(text)


def clean_documents(documents: List[Dict], config: CleanerConfig = None) -> List[Dict]:
    """
    便捷函数：清洗文档列表

    Args:
        documents: 文档列表 [{"id": "...", "title": "...", "content": "..."}]
        config: 清洗配置

    Returns:
        清洗后的文档列表
    """
    cleaner = DataCleaner(config)
    cleaned = []

    for doc in documents:
        cleaned_doc = {
            "id": doc.get("id", ""),
            "title": cleaner.clean(doc.get("title", "")),
            "content": cleaner.clean(doc.get("content", "")),
        }
        cleaned.append(cleaned_doc)

    return cleaned
