# -*- coding: utf-8 -*-
"""
AI核心层 - 多粒度摘要模块
为测试用例生成不同粒度的摘要：
- 关键词摘要（最短）
- 一句话摘要（中等）
- 段落摘要（较详细）
- 原始文档
"""
import logging
import hashlib
import json
import os
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class MultiGranularitySummarizer:
    """
    多粒度摘要生成器

    为测试用例生成多种粒度的摘要，
    检索时可根据查询类型选择合适粒度
    """

    def __init__(
        self,
        llm=None,
        cache_dir: str = None,
        enable_cache: bool = True
    ):
        """
        初始化摘要生成器

        Args:
            llm: 大语言模型
            cache_dir: 缓存目录
            enable_cache: 是否启用缓存
        """
        self.llm = llm
        self.cache_dir = cache_dir or os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data", "summaries"
        )
        self.enable_cache = enable_cache

        # 内存缓存
        self._memory_cache = {}

        # 确保缓存目录存在
        if self.enable_cache:
            os.makedirs(self.cache_dir, exist_ok=True)

    def _get_cache_path(self, doc_id: str) -> str:
        """获取缓存文件路径"""
        return os.path.join(self.cache_dir, f"{doc_id}.json")

    def _get_doc_hash(self, content: str) -> str:
        """计算文档hash"""
        return hashlib.md5(content.encode()).hexdigest()

    def summarize(
        self,
        content: str,
        doc_id: str = None,
        levels: List[str] = None
    ) -> Dict[str, str]:
        """
        生成多粒度摘要

        Args:
            content: 原始文档内容
            doc_id: 文档ID
            levels: 需要生成的粒度级别
                    ["keywords", "one_sentence", "paragraph"]

        Returns:
            {
                "keywords": "关键词摘要",
                "one_sentence": "一句话摘要",
                "paragraph": "段落摘要",
                "original": "原始文档"
            }
        """
        if levels is None:
            levels = ["keywords", "one_sentence", "paragraph"]

        # 生成doc_id
        doc_id = doc_id or self._get_doc_hash(content)[:16]

        # 尝试从缓存加载
        if self.enable_cache:
            cached = self._load_from_cache(doc_id)
            if cached:
                logger.info(f"从缓存加载摘要: {doc_id}")
                return cached

        # 生成各粒度摘要
        result = {
            "original": content,
            "doc_id": doc_id
        }

        if "keywords" in levels:
            result["keywords"] = self._extract_keywords(content)

        if "one_sentence" in levels and self.llm:
            result["one_sentence"] = self._generate_one_sentence(content)

        if "paragraph" in levels and self.llm:
            result["paragraph"] = self._generate_paragraph(content)

        # 缓存结果
        if self.enable_cache:
            self._save_to_cache(doc_id, result)

        return result

    def _extract_keywords(self, content: str) -> str:
        """
        提取关键词摘要
        从测试用例中提取关键信息
        """
        lines = content.split('\n')
        keywords = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 提取冒号后的内容
            if ':' in line or '：' in line:
                key = line.split(':')[0].split('：')[0].strip()
                keywords.append(key)

        # 提取操作步骤中的关键词
        import re
        steps = re.findall(r'操作[：:]\s*(.+?)(?:->|预期)', content)
        keywords.extend(steps)

        # 去重并返回
        unique_keywords = list(set(keywords))[:10]
        return ", ".join(unique_keywords)

    def _generate_one_sentence(self, content: str) -> str:
        """生成一句话摘要"""
        prompt = f"""用一句话简洁总结以下测试用例的核心内容，
只保留最关键的信息：测试目标和主要验证点。

测试用例：
{content[:500]}

一句话摘要："""

        try:
            summary = self.llm.generate(prompt)
            return summary.strip()[:200]
        except Exception as e:
            logger.warning(f"一句话摘要生成失败: {e}")
            return content[:200]

    def _generate_paragraph(self, content: str) -> str:
        """生成段落摘要"""
        prompt = f"""总结以下测试用例的关键信息：
- 测试目标
- 前置条件
- 关键操作步骤
- 预期结果

保持专业术语，准确描述测试逻辑。

测试用例：
{content[:800]}

详细摘要："""

        try:
            summary = self.llm.generate(prompt)
            return summary.strip()[:500]
        except Exception as e:
            logger.warning(f"段落摘要生成失败: {e}")
            return content[:500]

    def _load_from_cache(self, doc_id: str) -> Optional[Dict]:
        """从缓存加载"""
        # 先检查内存缓存
        if doc_id in self._memory_cache:
            return self._memory_cache[doc_id]

        # 检查文件缓存
        cache_path = self._get_cache_path(doc_id)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._memory_cache[doc_id] = data
                    return data
            except Exception as e:
                logger.warning(f"加载缓存失败: {e}")

        return None

    def _save_to_cache(self, doc_id: str, data: Dict):
        """保存到缓存"""
        # 保存到内存
        self._memory_cache[doc_id] = data

        # 保存到文件
        cache_path = self._get_cache_path(doc_id)
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"保存缓存失败: {e}")

    def batch_summarize(
        self,
        documents: List[Dict],
        doc_id_key: str = "case_id",
        content_key: str = "content"
    ) -> List[Dict]:
        """
        批量生成摘要

        Args:
            documents: 文档列表 [{"content": "...", "metadata": {"case_id": "..."}}, ...]
            doc_id_key: 文档ID的键名
            content_key: 内容键名

        Returns:
            带摘要的文档列表
        """
        results = []

        for i, doc in enumerate(documents):
            content = doc.get(content_key, '')
            metadata = doc.get('metadata', {})
            doc_id = metadata.get(doc_id_key, f"doc_{i}")

            summary = self.summarize(content, doc_id)

            results.append({
                **doc,
                "summary": summary,
                "keywords": summary.get("keywords", ""),
                "one_sentence": summary.get("one_sentence", ""),
                "paragraph": summary.get("paragraph", "")
            })

            if (i + 1) % 100 == 0:
                logger.info(f"已处理 {i+1}/{len(documents)} 个文档")

        return results

    def clear_cache(self):
        """清空缓存"""
        self._memory_cache = {}
        logger.info("内存缓存已清空")

        # 可选：清空文件缓存
        if os.path.exists(self.cache_dir):
            import shutil
            for f in os.listdir(self.cache_dir):
                if f.endswith('.json'):
                    os.remove(os.path.join(self.cache_dir, f))
        logger.info("文件缓存已清空")


class TestCaseSummarizer(MultiGranularitySummarizer):
    """
    测试用例专用摘要生成器
    针对测试用例优化了摘要策略
    """

    def __init__(self, llm=None, cache_dir: str = None):
        super().__init__(llm, cache_dir)

        # 测试用例专用的摘要模板
        self.summary_prompts = {
            "tech": """
提取以下测试用例的核心技术要点：
1. 测试目标和验证点
2. 关键操作步骤
3. 重要参数和配置
4. 测试环境要求

保持测试用例术语的准确性。

测试用例：{doc}
""",
            "step": """
提取测试用例的操作步骤：
只列出关键操作，按顺序编号。

测试用例：{doc}

步骤摘要：
""",
            "result": """
提取测试用例的预期结果：
只保留验证点和期望输出。

测试用例：{doc}

预期结果：
"""
        }

    def summarize_test_case(
        self,
        content: str,
        doc_id: str = None,
        summary_type: str = "all"
    ) -> Dict[str, str]:
        """
        生成测试用例摘要

        Args:
            content: 测试用例内容
            doc_id: 用例ID
            summary_type: 摘要类型
                - "all": 完整摘要
                - "tech": 技术要点
                - "step": 步骤摘要
                - "result": 结果摘要

        Returns:
            摘要结果
        """
        doc_id = doc_id or self._get_doc_hash(content)[:16]

        if summary_type == "all":
            return self.summarize(content, doc_id)
        else:
            # 特定类型摘要
            prompt = self.summary_prompts.get(summary_type, self.summary_prompts["tech"])
            prompt = prompt.format(doc=content[:500])

            try:
                result = self.llm.generate(prompt)
                return {
                    "doc_id": doc_id,
                    summary_type: result.strip()
                }
            except Exception as e:
                logger.warning(f"测试用例摘要生成失败: {e}")
                return {"doc_id": doc_id, summary_type: content[:200]}


# 全局单例
_summarizer = None


def get_summarizer(llm=None) -> MultiGranularitySummarizer:
    """获取摘要生成器"""
    global _summarizer

    if _summarizer is None:
        from .llm import get_llm
        _llm = llm or get_llm()
        _summarizer = MultiGranularitySummarizer(llm=_llm)

    return _summarizer
