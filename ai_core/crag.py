# -*- coding: utf-8 -*-
"""
AI核心层 - CRAG 检索评估器
使用 LLM 评估文档相关性，实现纠错检索
"""
import logging
import re
from typing import List, Dict, Any, Tuple, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class DocumentRelevance(Enum):
    """文档相关性分类"""
    CORRECT = "correct"      # 相关且准确
    AMBIGUOUS = "ambiguous" # 模糊不清
    INCORRECT = "incorrect"  # 不相关


class CRAGEvaluator:
    """
    CRAG 检索评估器
    使用 LLM 评估每个检索文档的相关性
    """

    def __init__(
        self,
        llm,
        threshold_correct: float = 0.7,
        threshold_incorrect: float = 0.3,
        max_docs_evaluate: int = 10
    ):
        """
        初始化评估器

        Args:
            llm: 大语言模型
            threshold_correct: 相关阈值 (>此值为CORRECT)
            threshold_incorrect: 不相关阈值 (<此值为INCORRECT)
            max_docs_evaluate: 最多评估的文档数
        """
        self.llm = llm
        self.threshold_correct = threshold_correct
        self.threshold_incorrect = threshold_incorrect
        self.max_docs_evaluate = max_docs_evaluate

    def evaluate(self, query: str, documents: List[Dict]) -> List[Dict]:
        """
        评估文档相关性 (批量处理)

        Args:
            query: 用户查询
            documents: 检索到的文档列表

        Returns:
            带评估结果的文档列表
        """
        if not documents:
            return documents

        # 限制评估数量
        docs_to_evaluate = documents[:self.max_docs_evaluate]

        logger.info(f"CRAG评估: {len(docs_to_evaluate)} 个文档")

        # 使用批量评估（一次LLM调用评估所有文档）
        results = self._evaluate_batch(query, docs_to_evaluate)

        # 统计
        correct = sum(1 for r in results if r['relevance'] == 'correct')
        ambiguous = sum(1 for r in results if r['relevance'] == 'ambiguous')
        incorrect = sum(1 for r in results if r['relevance'] == 'incorrect')

        logger.info(f"CRAG评估结果: CORRECT={correct}, AMBIGUOUS={ambiguous}, INCORRECT={incorrect}")
        logger.debug(f"CRAG评估详情: {[(r['relevance'], r.get('document', '')[:50]) for r in results]}")

        return results

    def _evaluate_batch(self, query: str, documents: List[Dict]) -> List[Dict]:
        """
        批量评估多个文档（一次LLM调用）

        Args:
            query: 查询
            documents: 文档列表

        Returns:
            带评估结果的文档列表
        """
        # 构建批量评估提示
        doc_list_text = ""
        for i, doc in enumerate(documents):
            doc_content = doc.get('document', '')[:600]  # 限制每个文档长度以适应上下文
            doc_list_text += f"""
文档{i+1}:
{doc_content}
"""

        prompt = f"""评估以下{len(documents)}个文档是否回答了查询问题。

查询：{query}
{doc_list_text}

请对每个文档进行评估，返回格式如下（只返回JSON）：
[
    {{"index": 1, "relevance": "CORRECT/AMBIGUOUS/INCORRECT"}},
    {{"index": 2, "relevance": "CORRECT/AMBIGUOUS/INCORRECT"}},
    ...
]

评估标准：
- CORRECT：文档直接回答了查询，信息相关且准确
- AMBIGUOUS：文档部分相关但信息不够完整或模糊
- INCORRECT：文档不相关或包含错误信息

只返回JSON数组，不要其他内容。"""

        try:
            response = self.llm.generate(prompt).strip()

            # 解析JSON响应
            import json
            json_match = re.search(r'\[[\s\S]*\]', response)
            if json_match:
                evaluations = json.loads(json_match.group())

                # 构建结果映射
                eval_map = {item['index']: item['relevance'].lower() for item in evaluations}

                # 应用评估结果
                results = []
                for i, doc in enumerate(documents):
                    relevance = eval_map.get(i + 1, 'ambiguous')
                    # 验证有效性
                    if relevance not in ['correct', 'ambiguous', 'incorrect']:
                        relevance = 'ambiguous'

                    doc['relevance'] = relevance
                    doc['relevance_score'] = relevance
                    results.append(doc)

                    logger.debug(f"文档{i+1}: {relevance}")

                return results
            else:
                # JSON解析失败，回退到逐个评估
                logger.warning("批量评估JSON解析失败，回退到逐个评估")
                return self._evaluate_sequential(query, documents)

        except Exception as e:
            logger.warning(f"批量评估失败: {e}, 回退到逐个评估")
            return self._evaluate_sequential(query, documents)

    def _evaluate_sequential(self, query: str, documents: List[Dict]) -> List[Dict]:
        """
        逐个评估文档（回退方案）

        Args:
            query: 查询
            documents: 文档列表

        Returns:
            带评估结果的文档列表
        """
        results = []

        for i, doc in enumerate(documents):
            doc_content = doc.get('document', '')[:800]

            logger.debug(f"CRAG评估文档 {i+1}: {doc_content[:100]}...")

            relevance = self._evaluate_single(query, doc_content)

            doc['relevance'] = relevance.value
            doc['relevance_score'] = relevance.value

            results.append(doc)

            logger.debug(f"文档{i+1}: {relevance.value}")

        return results

    def _evaluate_single(self, query: str, document: str) -> DocumentRelevance:
        """
        评估单个文档

        Args:
            query: 查询
            document: 文档内容

        Returns:
            相关性分类
        """
        prompt = f"""评估以下文档是否回答了查询问题。

查询：{query}

文档：
{document}

请评估文档的相关性，返回以下类别之一：
- CORRECT：文档直接回答了查询，信息相关且准确
- AMBIGUOUS：文档部分相关但信息不够完整或模糊
- INCORRECT：文档不相关或包含错误信息

只返回类别名称，不要解释。"""

        try:
            response = self.llm.generate(prompt).strip().lower()

            if 'correct' in response and 'ambiguous' not in response:
                return DocumentRelevance.CORRECT
            elif 'incorrect' in response:
                return DocumentRelevance.INCORRECT
            else:
                return DocumentRelevance.AMBIGUOUS

        except Exception as e:
            logger.warning(f"评估失败: {e}, 默认返回AMBIGUOUS")
            return DocumentRelevance.AMBIGUOUS

    def filter_documents(
        self,
        query: str,
        documents: List[Dict],
        use_web_search_fallback: bool = False
    ) -> Tuple[List[Dict], bool]:
        """
        过滤文档

        Args:
            query: 查询
            documents: 文档列表
            use_web_search_fallback: 是否触发网络搜索

        Returns:
            (过滤后的文档, 是否需要网络搜索)
        """
        # 评估
        evaluated = self.evaluate(query, documents)

        # 分类
        correct_docs = [d for d in evaluated if d['relevance'] == 'correct']
        ambiguous_docs = [d for d in evaluated if d['relevance'] == 'ambiguous']
        incorrect_count = sum(1 for d in evaluated if d['relevance'] == 'incorrect')

        # 决策
        need_web_search = False

        if len(correct_docs) >= 2:
            # 有足够的正确答案
            final_docs = correct_docs
        elif len(correct_docs) + len(ambiguous_docs) >= 2:
            # 有正确答案+模糊答案，保留并精炼
            final_docs = correct_docs + ambiguous_docs[:2]
        elif incorrect_count >= len(evaluated) * 0.6:
            # 大部分不相关，触发网络搜索
            need_web_search = True
            final_docs = []
        else:
            # 其他情况，保留所有
            final_docs = evaluated

        logger.info(f"CRAG过滤: 最终{len(final_docs)}文档, 需要网络搜索={need_web_search}")

        return final_docs, need_web_search


class KnowledgeRefiner:
    """
    知识精炼器
    将文档分解为知识条，重组为精炼上下文
    """

    def __init__(
        self,
        llm,
        max_context_length: int = 1000
    ):
        self.llm = llm
        self.max_context_length = max_context_length

    def refine(self, query: str, documents: List[Dict]) -> str:
        """
        精炼文档

        Args:
            query: 查询
            documents: 文档列表

        Returns:
            精炼后的上下文
        """
        if not documents:
            return ""

        # 合并文档内容
        combined_docs = "\n\n---\n\n".join([
            doc.get('document', '')[:600]
            for doc in documents
        ])

        # 使用LLM精炼
        prompt = f"""从以下文档中提取与问题相关的信息，去除冗余内容。

问题：{query}

文档：
{combined_docs}

请提取与问题直接相关的关键信息，组成简洁的上下文（不超过{self.max_context_length}字符）：

相关要点："""

        try:
            refined = self.llm.generate(prompt)
            logger.info(f"知识精炼: {len(combined_docs)} -> {len(refined)} 字符")
            return refined
        except Exception as e:
            logger.warning(f"知识精炼失败: {e}, 使用原始文档")
            return combined_docs[:self.max_context_length]

    def decompose_document(self, document: str) -> List[str]:
        """
        分解文档为知识条

        Args:
            document: 文档内容

        Returns:
            知识条列表
        """
        # 按句子分割
        sentences = re.split(r'[。！？\n]', document)
        sentences = [s.strip() for s in sentences if s.strip()]

        return sentences[:10]  # 最多10条

    def recompose_knowledge(
        self,
        query: str,
        knowledge_strips: List[str],
        max_length: int = 500
    ) -> str:
        """
        重组知识条

        Args:
            query: 查询
            knowledge_strips: 知识条列表
            max_length: 最大长度

        Returns:
            重组后的上下文
        """
        if not knowledge_strips:
            return ""

        # 简单实现：直接拼接
        result = []
        current_length = 0

        for strip in knowledge_strips:
            if current_length + len(strip) <= max_length:
                result.append(strip)
                current_length += len(strip)
            else:
                break

        return "".join(result)


class CRAGRetriever:
    """
    CRAG 检索器
    整合评估器 + 知识精炼器 + Web搜索
    """

    def __init__(
        self,
        embedding_model,
        vector_store,
        llm,
        use_crag: bool = True,
        use_rerank: bool = True,
        use_refine: bool = True,
        use_web_search: bool = False,
        web_search_provider: str = "duckduckgo"
    ):
        self.embedding_model = embedding_model
        self.vector_store = vector_store
        self.llm = llm
        self.use_crag = use_crag
        self.use_rerank = use_rerank
        self.use_refine = use_refine
        self.use_web_search = use_web_search

        # 初始化组件
        self.evaluator = CRAGEvaluator(llm) if use_crag else None
        self.refiner = KnowledgeRefiner(llm) if use_refine else None

        # 初始化 Web 搜索 (按需)
        self.web_searcher = None
        if use_web_search:
            try:
                self.web_searcher = WebSearchRetriever(
                    llm=llm,
                    search_provider=web_search_provider
                )
                logger.info("Web 搜索已启用")
            except Exception as e:
                logger.warning(f"Web 搜索初始化失败: {e}")

        logger.info(f"CRAG检索器初始化: 评估={use_crag}, 重排={use_rerank}, 精炼={use_refine}, Web搜索={use_web_search}")

    def search(
        self,
        query: str,
        top_k: int = 10
    ) -> List[Dict]:
        """
        CRAG 检索

        Args:
            query: 查询
            top_k: 返回数量

        Returns:
            检索结果
        """
        # 1. 初始向量检索
        query_vector = self.embedding_model.encode_query(query)
        documents = self.vector_store.search(query_vector, top_k=top_k * 2)

        if not self.use_crag:
            return documents[:top_k]

        # 2. CRAG 评估
        evaluated_docs = self.evaluator.evaluate(query, documents)

        # 3. 过滤
        filtered_docs, need_web_search = self.evaluator.filter_documents(
            query, evaluated_docs
        )

        # 4. 如果需要 Web 搜索
        if need_web_search and self.web_searcher:
            logger.info("触发 Web 搜索...")
            web_results = self.web_searcher.search(query)
            if web_results:
                # 合并 Web 结果
                documents.extend(web_results)
                logger.info(f"添加 {len(web_results)} 条 Web 结果")

        # 5. 知识精炼
        if self.use_refine and filtered_docs:
            refined_context = self.refiner.refine(query, filtered_docs)
            # 将精炼结果添加到文档
            for doc in filtered_docs:
                doc['refined'] = refined_context

        # 6. 返回结果
        return filtered_docs[:top_k] if filtered_docs else documents[:top_k]


class WebSearchRetriever:
    """
    Web 搜索检索器
    当本地知识库检索结果不足时，使用网络搜索补充
    """

    def __init__(
        self,
        llm,
        search_provider: str = "duckduckgo",
        max_results: int = 5,
        max_content: int = 3,
        use_extractor: bool = True
    ):
        """
        初始化 Web 搜索检索器

        Args:
            llm: 大语言模型 (用于摘要生成)
            search_provider: 搜索提供商 (duckduckgo, tavily, serper)
            max_results: 最大搜索结果数
            max_content: 最大提取内容的 URL 数
            use_extractor: 是否提取网页内容
        """
        self.llm = llm
        self.max_results = max_results
        self.max_content = max_content

        # 初始化搜索路由器
        from .web_search import get_search_engine, SearchRouter

        try:
            engine = get_search_engine(provider=search_provider)
            self.search_router = SearchRouter(
                engines=[engine],
                use_extractor=use_extractor,
                max_content_results=max_content
            )
            logger.info(f"WebSearchRetriever 初始化成功: {search_provider}")
        except Exception as e:
            logger.error(f"WebSearchRetriever 初始化失败: {e}")
            self.search_router = None

    def search(self, query: str) -> List[Dict]:
        """
        执行 Web 搜索

        Args:
            query: 查询词

        Returns:
            Web 搜索结果列表
        """
        if not query or not self.search_router:
            return []

        logger.info(f"Web 搜索: {query}")

        # 执行搜索
        result = self.search_router.search(
            query,
            extract_content=True
        )

        if not result['success']:
            logger.warning(f"Web 搜索失败: {result.get('error')}")
            return []

        # 转换为统一格式
        web_docs = []

        # 添加搜索结果
        for r in result['results'][:self.max_results]:
            web_docs.append({
                'document': r.snippet,
                'source': 'web',
                'url': r.url,
                'title': r.title,
                'relevance': r.relevance,
                'type': 'web_search'
            })

        # 添加提取的内容
        for c in result.get('contents', []):
            if c and c.content:
                # 生成摘要
                summary = self._summarize_content(query, c.content)

                web_docs.append({
                    'document': summary,
                    'source': 'web',
                    'url': c.url,
                    'title': c.title,
                    'full_content': c.content[:2000],  # 保留部分全文
                    'relevance': 0.8,
                    'type': 'web_content'
                })

        logger.info(f"Web 搜索返回 {len(web_docs)} 条结果")
        return web_docs

    def _summarize_content(self, query: str, content: str) -> str:
        """
        使用 LLM 摘要内容

        Args:
            query: 查询词
            content: 原始内容

        Returns:
            摘要文本
        """
        if not content or not self.llm:
            return content[:500]

        # 截取需要摘要的部分
        content_to_summarize = content[:3000]

        prompt = f"""请根据以下查询关键词，从内容中提取最相关的信息，生成50字左右的摘要。

查询关键词: {query}

内容:
{content_to_summarize}

摘要:"""

        try:
            summary = self.llm.chat(prompt)
            if summary and len(summary) > 10:
                return summary.strip()
        except Exception as e:
            logger.warning(f"摘要生成失败: {e}")

        # 失败则返回原文截取
        return content[:500]


# 全局单例
_crag_retriever = None


def get_crag_retriever(
    embedding_model=None,
    vector_store=None,
    llm=None,
    use_crag: bool = True
) -> CRAGRetriever:
    """获取CRAG检索器"""
    global _crag_retriever

    if _crag_retriever is None:
        from .embedding import get_embedding_model
        from .llm import get_llm

        embedding_model = embedding_model or get_embedding_model()
        llm = llm or get_llm()

        _crag_retriever = CRAGRetriever(
            embedding_model=embedding_model,
            vector_store=vector_store,
            llm=llm,
            use_crag=use_crag
        )

    return _crag_retriever
