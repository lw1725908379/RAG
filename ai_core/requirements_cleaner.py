# -*- coding: utf-8 -*-
"""
需求文档清洗与重构模块 - 增强版
专门处理停车场/门禁系统等复杂需求文档
"""

import re
from typing import List, Dict, Set


class RequirementsCleaner:
    """需求文档清洗器"""

    def __init__(self, min_length: int = 50):
        self.min_length = min_length

        # 图片链接正则
        self.img_pattern = re.compile(
            r'!\[?\]\([^)]+\)|'
            r'<img\s+[^>]*src="[^"]*"[^>]*>|'
            r'<img\s+[^>]*>',
            re.IGNORECASE
        )
        # 表格正则
        self.table_pattern = re.compile(r'<table[^>]*>.*?</table>', re.DOTALL | re.IGNORECASE)
        # 主题关键词
        self.topic_keywords = {
            '通道引擎': ['通道引擎', '倒车', '逆行', '伪车牌', '车牌纠正', '滞留'],
            '防逃费': ['防逃费', '欠费', '追缴', '预补录'],
            '语音交互': ['语音', '交互', '显示屏', 'LCD', 'LED'],
            '门禁': ['门禁', '门点', '鉴权', '凭证'],
            '数据一致性': ['数据一致性', '金额', '通行', '订单'],
            '性能': ['性能', 'TPS', '响应时间', '吞吐量']
        }

    def clean(self, text: str) -> str:
        """清洗文本"""
        if not text:
            return ""

        result = text

        # 0. 首先处理转义的星号（如 \* 或 \\*）
        result = re.sub(r'\\\*+', '', result)  # 移除 \*
        result = re.sub(r'\\\\\*+', '', result)  # 移除 \\*

        # 1. 移除图片链接和OCR残留
        result = self.img_pattern.sub('', result)

        # 2. 移除OCR噪声字符
        result = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', result)  # 控制字符
        result = re.sub(r'[■▓]{3,}', '', result)  # 过多填充符
        result = re.sub(r'_{5,}', '', result)  # 过多下划线

        # 3. 规范化Markdown格式 - 移除多余的 ** 加粗标记
        result = re.sub(r'\*{2,}', '', result)  # 移除所有多余的星号

        # 4. 规范化换行
        result = re.sub(r'\\n', '\n', result)
        result = re.sub(r'\n{3,}', '\n\n', result)  # 最多2个换行
        result = re.sub(r' {2,}', ' ', result)  # 最多1个空格

        # 5. 移除残留的HTML标签和片段
        # 先移除完整的HTML标签
        result = re.sub(r'<[^>]+>', '', result)
        # 再移除可能残留的HTML片段（如 td>, tr>, th> 等单独出现的）
        result = re.sub(r'td>|tr>|th>|table>|tbody>|thead>', '', result, flags=re.IGNORECASE)

        # 6. 清理特殊Unicode字符
        result = re.sub(r'[\u200b-\u200f\u2028-\u202f]', '', result)  # Zero-width chars

        # 7. 最后再清理一次多余的空白
        result = re.sub(r'\n{3,}', '\n\n', result)
        result = result.strip()

        return result

    def html_table_to_markdown(self, table_html: str) -> str:
        """HTML表格转Markdown"""
        try:
            # 预处理：移除图片链接
            table_html = self.img_pattern.sub('', table_html)

            # 提取行
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE)
            if not rows:
                return ""

            # 提取单元格
            all_cells = []
            for row in rows:
                cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL | re.IGNORECASE)
                cleaned_cells = []
                for cell in cells:
                    # 移除所有HTML标签
                    cell = re.sub(r'<[^>]+>', '', cell)
                    cell = cell.replace('&nbsp;', ' ').replace('<br>', '\n').replace('<br/>', '\n')
                    # 移除残留的HTML片段
                    cell = re.sub(r'td>|tr>|th>', '', cell, flags=re.IGNORECASE)
                    cell = re.sub(r'\s+', ' ', cell).strip()
                    cleaned_cells.append(cell)
                if cleaned_cells:
                    all_cells.append(cleaned_cells)

            if not all_cells:
                return ""

            # 构建Markdown表格
            md_lines = []
            max_cols = max(len(r) for r in all_cells) if all_cells else 0

            for i, row in enumerate(all_cells):
                row_padded = row + [''] * (max_cols - len(row))
                md_lines.append('| ' + ' | '.join(row_padded) + ' |')
                if i == 0:
                    md_lines.append('| ' + ' | '.join(['---'] * max_cols) + ' |')

            return '\n'.join(md_lines)
        except Exception:
            return "[表格内容]"

    def extract_section(self, text: str) -> str:
        """提取章节标题"""
        # 移除表格避免干扰
        clean = self.table_pattern.sub('', text)

        # 匹配【需求】标题
        match = re.search(r'【需求】([^\n\*]+)', clean)
        if match:
            return match.group(1).strip()

        # 匹配 **数字.标题** 格式
        match = re.search(r'\*\*([\d\.]+[^\n\*]+)\*\*', clean)
        if match:
            return match.group(1).strip()

        # 匹配 # 标题
        match = re.search(r'^#+\s*([^\n]+)$', clean, re.MULTILINE)
        if match:
            return match.group(1).strip()

        return ""

    def extract_topics(self, text: str) -> List[str]:
        """提取主题标签"""
        found_topics = []
        text_lower = text.lower()

        for topic, keywords in self.topic_keywords.items():
            if any(kw in text_lower for kw in keywords):
                found_topics.append(topic)

        return found_topics

    def is_valid_chunk(self, text: str) -> bool:
        """检查chunk是否有效"""
        # 移除表格和图片后检查
        clean = self.table_pattern.sub('', text)
        clean = self.img_pattern.sub('', clean)
        clean = clean.strip()

        return len(clean) >= self.min_length


def chunk_document(text: str, doc_id: str = "", min_length: int = 50) -> List[Dict]:
    """
    清洗并切分文档

    Args:
        text: 原始文本
        doc_id: 文档ID
        min_length: 最小chunk长度

    Returns:
        [{"content": str, "metadata": dict}, ...]
    """
    cleaner = RequirementsCleaner(min_length=min_length)

    # 提取章节标题
    section = cleaner.extract_section(text)

    # 提取主题标签
    topics = cleaner.extract_topics(text)

    # 提取所有表格
    tables = cleaner.table_pattern.findall(text)

    # 清洗文本
    cleaned_text = cleaner.clean(text)

    # 过滤无效文档（太短）
    if not cleaner.is_valid_chunk(cleaned_text):
        return []

    # 如果没有表格，直接返回
    if not tables:
        return [{
            "content": cleaned_text,
            "metadata": {
                "chapter_path": section,
                "section": section,
                "doc_id": doc_id,
                "chunk_id": 0,
                "topics": topics
            }
        }]

    # 有表格时：拆分为多个块
    chunks = []
    chunk_id = 0

    # 1. 添加文本内容块（如果有效）
    text_content = cleaned_text
    # 移除表格部分，只保留纯文本
    for table in tables:
        text_content = text_content.replace(table, '')

    if cleaner.is_valid_chunk(text_content):
        chunks.append({
            "content": text_content,
            "metadata": {
                "chapter_path": section,
                "section": section,
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "has_table": True,
                "topics": topics
            }
        })
        chunk_id += 1

    # 2. 添加独立的表格块
    for i, table_html in enumerate(tables):
        md_table = cleaner.html_table_to_markdown(table_html)
        if md_table and cleaner.is_valid_chunk(md_table):
            chunks.append({
                "content": f"【表格{i+1}】\n{md_table}",
                "metadata": {
                    "chapter_path": section,
                    "section": section,
                    "doc_id": doc_id,
                    "chunk_id": chunk_id,
                    "has_table": True,
                    "is_table": True,
                    "topics": topics
                }
            })
            chunk_id += 1

    # 如果所有chunks都太短，尝试合并
    if not chunks and cleaned_text:
        # 返回整个清洗后的文档，不强制过滤
        chunks.append({
            "content": cleaned_text,
            "metadata": {
                "chapter_path": section,
                "section": section,
                "doc_id": doc_id,
                "chunk_id": 0,
                "topics": topics
            }
        })

    return chunks


def clean_requirements_text(text: str) -> str:
    """清洗需求文档文本"""
    cleaner = RequirementsCleaner()
    return cleaner.clean(text)


def deduplicate_chunks(chunks: List[Dict], threshold: float = 0.9) -> List[Dict]:
    """
    去除重复或高度相似的chunks

    Args:
        chunks: chunk列表
        threshold: 相似度阈值（保留，为未来扩展）

    Returns:
        去重后的chunks
    """
    if not chunks:
        return []

    unique_chunks = []
    seen_contents: Set[str] = set()

    for chunk in chunks:
        content = chunk['content'].strip()
        # 简化比较：取前100字符
        signature = content[:100].lower()

        if signature not in seen_contents:
            seen_contents.add(signature)
            unique_chunks.append(chunk)

    return unique_chunks


if __name__ == "__main__":
    # 测试
    test_cases = [
        # 正常文档
        """【需求】3.1.1 通道引擎对接

**3.1.1.1车辆闸前/中倒车**<table border="1"><tr><td>功能概述</td><td>车辆闸前/中倒车</td></tr><tr><td>业务规则</td><td>倒车事件共两种情况</td></tr></table>

这是通道引擎的详细业务规则说明，用于处理车辆倒车检测。""",

        # 短文档
        "【需求】测试",

        # 含图片
        """【需求】3.3.3 数据一致性

![](https://example.com/img.jpg)

数据一致性要求说明。""",

        # 空文档
        "",
    ]

    print("=" * 70)
    for i, test in enumerate(test_cases):
        print(f"\n=== 测试 {i+1} ===")
        results = chunk_document(test, f"test_{i+1}")
        print(f"输入: {test[:80]}...")
        print(f"输出: {len(results)} chunks")
        for j, r in enumerate(results):
            print(f"  Chunk {j}: {r['content'][:60]}... (topics: {r['metadata'].get('topics', [])})")
