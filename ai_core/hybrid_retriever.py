# -*- coding: utf-8 -*-
"""
AI核心层 - 混合检索模块
支持：
- 稀疏检索 (BM25/关键词)
- 密集检索 (向量相似度)
- 混合检索策略 (RRF融合)
- HyDE (Hypothetical Document Embeddings)
"""
import logging
import hashlib
import time
import math
import re
import os
import json
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter, defaultdict

logger = logging.getLogger(__name__)

# 导入配置
try:
    from config import FEATURE_FLAGS
except ImportError:
    FEATURE_FLAGS = {"enable_onnx": False}


class BM25Retriever:
    """
    BM25 稀疏检索器
    基于词频和逆文档频率的传统信息检索算法
    支持索引持久化
    """

    def __init__(
        self,
        documents: List[str] = None,
        k1: float = 1.5,  # 词频饱和参数
        b: float = 0.75,   # 文档长度归一化参数
        index_path: str = None  # 索引持久化路径
    ):
        self.k1 = k1
        self.b = b
        self.documents = documents or []
        self.doc_lengths = []
        self.avg_doc_length = 0
        self.doc_freqs = {}  # 词 -> 出现该词的文档数
        self.idf = {}        # 逆文档频率
        self._inverted_index = defaultdict(list)  # 词 -> [(doc_id, freq), ...]
        self.index_path = index_path

        if documents:
            # 尝试加载已有索引
            if index_path and self._load_index():
                logger.info(f"BM25索引已从磁盘加载: {len(self.documents)} 文档")
            else:
                self._build_index()
                # 保存索引
                if index_path:
                    self._save_index()

    def _get_index_files(self) -> Tuple[str, str]:
        """获取索引文件路径"""
        if not self.index_path:
            return None, None
        index_file = f"{self.index_path}.bm25"
        docs_file = f"{self.index_path}.docs.json"
        return index_file, docs_file

    def _load_index(self) -> bool:
        """从磁盘加载索引"""
        index_file, docs_file = self._get_index_files()
        if not index_file or not os.path.exists(index_file):
            return False

        try:
            # 加载文档
            if os.path.exists(docs_file):
                with open(docs_file, 'r', encoding='utf-8') as f:
                    self.documents = json.load(f)
            else:
                return False

            # 加载索引数据
            with open(index_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.doc_lengths = data.get('doc_lengths', [])
            self.avg_doc_length = data.get('avg_doc_length', 0)
            self.doc_freqs = data.get('doc_freqs', {})
            self.idf = data.get('idf', {})

            # 重建倒排索引
            self._inverted_index = defaultdict(list)
            for word, posting_list in data.get('inverted_index', {}).items():
                self._inverted_index[word] = [tuple(p) for p in posting_list]

            logger.info(f"BM25索引加载成功: {len(self.documents)} 文档, {len(self.idf)} 词条")
            return True

        except Exception as e:
            logger.warning(f"BM25索引加载失败: {e}")
            return False

    def _save_index(self):
        """保存索引到磁盘"""
        index_file, docs_file = self._get_index_files()
        if not index_file:
            return

        try:
            os.makedirs(os.path.dirname(index_file), exist_ok=True)

            # 保存文档
            with open(docs_file, 'w', encoding='utf-8') as f:
                json.dump(self.documents, f, ensure_ascii=False)

            # 保存索引数据
            data = {
                'doc_lengths': self.doc_lengths,
                'avg_doc_length': self.avg_doc_length,
                'doc_freqs': self.doc_freqs,
                'idf': self.idf,
                'inverted_index': {word: list(postings) for word, postings in self._inverted_index.items()}
            }
            with open(index_file, 'w', encoding='utf-8') as f:
                json.dump(data, f)

            logger.info(f"BM25索引已保存: {index_file}")

        except Exception as e:
            logger.warning(f"BM25索引保存失败: {e}")

    def _tokenize(self, text: str) -> List[str]:
        """简单中文分词"""
        # 移除非字母数字字符，转小写
        text = re.sub(r'[^\w\s]', ' ', text.lower())
        # 按空格分割，过滤空字符串
        tokens = [t.strip() for t in text.split() if t.strip()]
        return tokens

    def _build_index(self):
        """构建BM25索引"""
        self.doc_lengths = []
        self.doc_freqs = defaultdict(int)

        for doc in self.documents:
            tokens = self._tokenize(doc)
            self.doc_lengths.append(len(tokens))

            # 词频统计
            freq = Counter(tokens)
            for word, count in freq.items():
                self._inverted_index[word].append((len(self.doc_lengths) - 1, count))
                self.doc_freqs[word] += 1

        self.avg_doc_length = sum(self.doc_lengths) / max(len(self.doc_lengths), 1)

        # 计算IDF
        N = len(self.documents)
        for word, df in self.doc_freqs.items():
            self.idf[word] = math.log((N - df + 0.5) / (df + 0.5) + 1)

        logger.info(f"BM25索引构建完成: {len(self.documents)} 文档, {len(self.idf)} 词条")

        # 保存索引
        if self.index_path:
            self._save_index()

    def add_documents(self, documents: List[str]):
        """添加文档并重建索引"""
        self.documents.extend(documents)
        self._build_index()

    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        """BM25检索"""
        if not self.documents:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores = []

        for doc_id, doc in enumerate(self.documents):
            doc_tokens = self._tokenize(doc)
            doc_len = self.doc_lengths[doc_id]
            doc_freq_counter = Counter(doc_tokens)

            score = 0.0
            for q_token in query_tokens:
                if q_token in doc_freq_counter:
                    tf = doc_freq_counter[q_token]
                    idf = self.idf.get(q_token, 0)

                    # BM25公式
                    numerator = tf * (self.k1 + 1)
                    denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self.avg_doc_length)
                    score += idf * numerator / denominator

            if score > 0:
                scores.append({
                    "document": doc,
                    "score": score,
                    "doc_id": doc_id
                })

        # 按分数排序
        scores.sort(key=lambda x: x["score"], reverse=True)
        return scores[:top_k]


class SparseDenseFusion:
    """
    稀疏+密集检索融合器
    使用 Reciprocal Rank Fusion (RRF) 和分数归一化融合
    """

    def __init__(
        self,
        sparse_weight: float = 0.5,
        dense_weight: float = 0.5,
        rrf_k: int = 60
    ):
        """
        Args:
            sparse_weight: 稀疏检索权重
            dense_weight: 密集检索权重
            rrf_k: RRF参数
        """
        self.sparse_weight = sparse_weight
        self.dense_weight = dense_weight
        self.rrf_k = rrf_k

    def fuse_results(
        self,
        sparse_results: List[Dict],
        dense_results: List[Dict],
        top_k: int = 10
    ) -> List[Dict]:
        """
        融合稀疏和密集检索结果

        方法：
        1. RRF (Reciprocal Rank Fusion): 基于排名的融合
        2. 分数归一化加权: 基于分数的融合
        """
        if not sparse_results and not dense_results:
            return []

        # 方法1: RRF融合
        rrf_scores = defaultdict(float)

        for rank, result in enumerate(sparse_results):
            doc = result.get('document', '')
            rrf_scores[doc] += 1.0 / (self.rrf_k + rank + 1)

        for rank, result in enumerate(dense_results):
            doc = result.get('document', '')
            rrf_scores[doc] += 1.0 / (self.rrf_k + rank + 1)

        # 方法2: 分数归一化加权
        normalized_scores = defaultdict(float)

        # 归一化稀疏分数
        if sparse_results:
            max_sparse = max(r.get('score', 0) for r in sparse_results) or 1
            for result in sparse_results:
                doc = result.get('document', '')
                norm_score = result.get('score', 0) / max_sparse
                normalized_scores[doc] += norm_score * self.sparse_weight

        # 归一化密集分数
        if dense_results:
            max_dense = max(r.get('score', 0) for r in dense_results) or 1
            for result in dense_results:
                doc = result.get('document', '')
                norm_score = result.get('score', 0) / max_dense
                normalized_scores[doc] += norm_score * self.dense_weight

        # 综合两种方法
        final_scores = {}
        for doc in set(list(rrf_scores.keys()) + list(normalized_scores.keys())):
            # RRF分数归一化
            max_rrf = max(rrf_scores.values()) or 1
            rrf_norm = rrf_scores.get(doc, 0) / max_rrf

            # 组合分数 (RRF 40% + 归一化分数 60%)
            final_scores[doc] = 0.4 * rrf_norm + 0.6 * normalized_scores.get(doc, 0)

        # 排序并返回top_k
        sorted_results = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)

        # 构建最终结果
        doc_data = {}
        for result in sparse_results + dense_results:
            doc = result.get('document', '')
            if doc not in doc_data:
                doc_data[doc] = result

        final_results = []
        for doc, score in sorted_results[:top_k]:
            result = doc_data.get(doc, {}).copy()
            result['score'] = score
            result['fusion'] = 'hybrid'
            final_results.append(result)

        return final_results


class FusionRetriever:
    """
    混合检索器
    结合 BM25(稀疏) + 向量检索(密集) + HyDE + Cross-Encoder重排

    四阶段检索流程：
    1. 向量检索 (Top-100) - 密集检索
    2. BM25检索 (Top-50) - 稀疏检索
    3. RRF融合 (Top-30) - 结果融合
    4. Cross-Encoder重排 (Top-K) - 精确排序
    """

    def __init__(
        self,
        embedding_model,
        vector_store,
        llm=None,
        documents: List[str] = None,
        use_bm25: bool = True,
        use_hyde: bool = True,
        use_rerank: bool = True,
        sparse_weight: float = 0.4,
        dense_weight: float = 0.6,
        hyde_threshold: int = 20,
        rerank_top_k: int = 10,
        coarse_top_k: int = 50,
        reranker_model_path: str = None,
        bm25_index_path: str = None  # BM25索引持久化路径
    ):
        """
        初始化混合检索器

        Args:
            embedding_model: 嵌入模型
            vector_store: 向量存储
            llm: 大语言模型 (用于HyDE)
            documents: 文档列表 (用于BM25)
            use_bm25: 是否启用BM25
            use_hyde: 是否启用HyDE
            use_rerank: 是否启用重排
            sparse_weight: 稀疏检索权重
            dense_weight: 密集检索权重
            hyde_threshold: 启用HyDE的查询复杂度阈值
            rerank_top_k: 重排后返回数量
            coarse_top_k: 粗排检索数量
            reranker_model_path: 重排器本地模型路径
        """
        self.embedding_model = embedding_model
        self.vector_store = vector_store
        self.llm = llm
        self.use_bm25 = use_bm25
        self.use_hyde = use_hyde
        self.use_rerank = use_rerank
        self.hyde_threshold = hyde_threshold
        self.rerank_top_k = rerank_top_k
        self.reranker_model_path = reranker_model_path
        self.coarse_top_k = coarse_top_k

        # BM25检索器
        self.bm25_retriever = None
        if use_bm25 and documents:
            self.bm25_retriever = BM25Retriever(
                documents,
                index_path=bm25_index_path
            )

        # 融合器
        self.fusion = SparseDenseFusion(
            sparse_weight=sparse_weight,
            dense_weight=dense_weight
        )

        # 重排器
        self.reranker = None
        if use_rerank:
            try:
                from .reranker import get_reranker
                use_onnx = FEATURE_FLAGS.get("enable_onnx", False)
                self.reranker = get_reranker(
                    model_path=self.reranker_model_path,
                    top_k=rerank_top_k,
                    use_onnx=use_onnx
                )
            except Exception as e:
                logger.warning(f"重排器初始化失败: {e}")
                self.use_rerank = False

        # HyDE检索器
        self.hyde_retriever = None
        if llm and use_hyde:
            from .hybrid_retriever import HyDERetriever
            self.hyde_retriever = HyDERetriever(
                llm=llm,
                embedding_model=embedding_model,
                vector_store=vector_store,
                num_generations=3,
                use_cache=True
            )

        logger.info(f"混合检索初始化: BM25={use_bm25}, HyDE={use_hyde}, 重排={use_rerank}, 权重(sparse={sparse_weight}, dense={dense_weight})")

    def search(
        self,
        query: str,
        top_k: int = 10,
        strategy: str = "auto",
        use_rerank: bool = None
    ) -> List[Dict]:
        """
        混合检索

        Args:
            query: 查询
            top_k: 返回数量
            strategy: 检索策略
                - "auto": 自动选择 (BM25+向量+HyDE)
                - "bm25": 仅BM25
                - "dense": 仅向量
                - "fusion": BM25+向量融合
                - "hyde": 仅HyDE
                - "rerank": 融合+重排
            use_rerank: 是否使用重排（覆盖默认设置）

        Returns:
            检索结果列表
        """
        # 决定是否使用重排
        do_rerank = use_rerank if use_rerank is not None else self.use_rerank
        word_count = len(query)  # 中文用字符数

        if strategy == "auto":
            # 优化策略：
            # 1. 默认使用 fusion 混合检索（BM25 + 向量）
            # 2. 只有当 fusion 结果少于 1 个时才启用 HyDE
            # 3. 避免 HyDE 幻觉导致的检索偏离

            # 先执行 BM25 + 向量混合检索
            if self.bm25_retriever:
                strategy = "fusion"
            else:
                strategy = "dense"

        logger.info(f"混合检索策略: {strategy}, 查询字符数: {word_count}, 重排={do_rerank}")

        # 1. BM25 稀疏检索
        sparse_results = []
        if strategy in ["bm25", "fusion", "rerank"] and self.bm25_retriever:
            sparse_results = self.bm25_retriever.search(query, top_k=self.coarse_top_k)
            logger.info(f"BM25检索: {len(sparse_results)} 结果")
            # DEBUG: 输出BM25结果
            for i, r in enumerate(sparse_results[:3]):
                score = r.get('score', 0)
                doc = r.get('document', '')[:60].replace('\n', ' ')
                logger.debug(f"  BM25[{i+1}]: score={score:.4f}, {doc}...")

        # 2. 向量密集检索
        dense_results = []
        if strategy in ["dense", "fusion", "hyde", "rerank"]:
            query_vector = self.embedding_model.encode_query(query)
            dense_results = self.vector_store.search(query_vector, top_k=self.coarse_top_k)
            logger.info(f"向量检索: {len(dense_results)} 结果")
            # DEBUG: 输出向量检索结果
            for i, r in enumerate(dense_results[:3]):
                score = r.get('score', 0)
                doc = r.get('document', '')[:60].replace('\n', ' ')
                logger.debug(f"  Vector[{i+1}]: score={score:.4f}, {doc}...")

        # 3. HyDE检索 (用于复杂查询)
        hyde_results = []
        if strategy == "hyde" and self.hyde_retriever:
            hyde_results, _ = self.hyde_retriever.retrieve(query, top_k=self.coarse_top_k)
            logger.info(f"HyDE检索: {len(hyde_results)} 结果")
            # DEBUG: 输出HyDE结果
            for i, r in enumerate(hyde_results[:3]):
                score = r.get('score', 0)
                doc = r.get('document', '')[:60].replace('\n', ' ')
                logger.debug(f"  HyDE[{i+1}]: score={score:.4f}, {doc}...")

        # 4. 融合结果
        if strategy == "fusion" or strategy == "rerank":
            # RRF融合 (Top-30)
            fused_results = self.fusion.fuse_results(sparse_results, dense_results, top_k=30)
            logger.info(f"RRF融合: {len(fused_results)} 结果")
            # DEBUG: 输出融合结果
            for i, r in enumerate(fused_results[:5]):
                score = r.get('score', 0)
                doc = r.get('document', '')[:60].replace('\n', ' ')
                logger.debug(f"  RRF[{i+1}]: score={score:.4f}, {doc}...")

            # 5. Cross-Encoder重排
            if do_rerank and self.reranker:
                logger.info(f"Cross-Encoder重排: 30 -> {top_k}")
                final_results = self.reranker.rerank(query, fused_results, top_k=top_k)
                # DEBUG: 输出重排结果
                for i, r in enumerate(final_results):
                    score = r.get('score', 0)
                    doc = r.get('document', '')[:60].replace('\n', ' ')
                    logger.debug(f"  Rerank[{i+1}]: score={score:.4f}, {doc}...")
            else:
                final_results = fused_results[:top_k]

            # 记录检索效果概览
            if final_results:
                scores = [r.get('rerank_score', r.get('score', 0)) for r in final_results]
                doc_ids = [r.get('id', r.get('doc_id', f'doc_{i}')) for i, r in enumerate(final_results)]
                top1 = scores[0] if scores else 0
                mean = sum(scores) / len(scores) if scores else 0
                logger.info(
                    f"检索总结: Query='{query[:30]}...', Top1={top1:.4f}, Mean={mean:.4f}, "
                    f"结果数={len(final_results)}, IDs={doc_ids[:3]}"
                )

            # 如果 fusion 结果少于 1 个，启用 HyDE 进行二次检索
            if strategy == "fusion" and len(final_results) < 1 and self.hyde_retriever:
                logger.info("Fusion 结果少于 1 个，启用 HyDE 进行二次检索...")
                hyde_results_fallback, _ = self.hyde_retriever.retrieve(query, top_k=top_k)
                # 合并 HyDE 结果
                final_results = hyde_results_fallback[:top_k]
                logger.info(f"HyDE 二次检索结果: {len(final_results)} 条")

            logger.info(f"最终结果: {len(final_results)} 条")
            return final_results
        elif strategy == "hyde":
            return hyde_results[:top_k]
        elif strategy == "bm25":
            return sparse_results[:top_k]
        else:
            return dense_results[:top_k]

    def set_documents(self, documents: List[str]):
        """设置文档列表"""
        # 获取BM25的索引路径
        index_path = getattr(self.bm25_retriever, 'index_path', None) if self.bm25_retriever else None

        if self.bm25_retriever:
            self.bm25_retriever.add_documents(documents)
        else:
            self.bm25_retriever = BM25Retriever(documents, index_path=index_path)
        logger.info(f"已更新BM25文档: {len(documents)} 篇")


# 以下是原有的 HyDE 类，保持向后兼容


class HyDERetriever:
    """
    HyDE 检索器
    通过生成假设文档来改进检索效果

    核心思想：
    - 让LLM生成一个"假设"的理想文档
    - 用这个假设文档去检索，而不是原始查询
    - 假设文档包含了正确的语义信息
    """

    def __init__(
        self,
        llm,
        embedding_model,
        vector_store,
        num_generations: int = 3,  # 生成3-5个假设文档效果最好
        use_cache: bool = True
    ):
        """
        初始化 HyDE 检索器

        Args:
            llm: 大语言模型
            embedding_model: 嵌入模型
            vector_store: 向量存储
            num_generations: 生成假设文档的数量 (建议3-5)
            use_cache: 是否缓存假设文档
        """
        self.llm = llm
        self.embedding_model = embedding_model
        self.vector_store = vector_store
        self.num_generations = num_generations
        self.use_cache = use_cache

        # 假设文档缓存
        self._hyde_cache = {}
        self._cache_ttl = 3600  # 缓存1小时

        # 简单查询判断阈值
        self.simple_query_threshold = 20  # 少于20字符视为简单查询

    def _is_simple_query(self, query: str) -> bool:
        """
        判断是否为简单查询

        简单查询特征：
        - 字符数少 (< threshold)
        - 关键词明确
        - 不包含复杂逻辑关系
        """
        # 字符数判断（中文）
        word_count = len(query)

        # 复杂查询的关键词
        complex_indicators = [
            '比较', '对比', '差异', '区别',
            '为什么', '原因', '如何解决',
            '如果', '那么', '或者',
            '且', '并且', '而且',
            '流程', '步骤', '顺序',
            '哪些', '什么情况', '什么时候'
        ]

        # 检查是否包含复杂逻辑
        has_complex_logic = any(indicator in query for indicator in complex_indicators)

        # 简单查询：字符数少且不包含复杂逻辑
        is_simple = word_count < self.simple_query_threshold and not has_complex_logic

        logger.info(f"查询复杂度判断: '{query[:20]}...' -> 字符数={word_count}, 复杂逻辑={has_complex_logic}, 结果={is_simple}")
        return is_simple

    def _generate_hypothetical_documents(
        self,
        query: str,
        num_docs: int = None
    ) -> List[str]:
        """
        生成假设文档

        Args:
            query: 用户查询
            num_docs: 生成数量（默认使用self.num_generations）

        Returns:
            假设文档列表
        """
        num_docs = num_docs or self.num_generations

        # 检查缓存
        cache_key = self._get_cache_key(query, num_docs)
        if self.use_cache and cache_key in self._hyde_cache:
            cached = self._hyde_cache[cache_key]
            if time.time() - cached['timestamp'] < self._cache_ttl:
                logger.info(f"使用缓存的假设文档: {len(cached['docs'])} 个")
                return cached['docs']

        # 构建prompt
        prompt = self._build_hyde_prompt(query, num_docs)

        # 调用LLM生成
        logger.info(f"生成 {num_docs} 个假设文档...")
        response = self.llm.generate(prompt)

        # 解析生成的假设文档
        hyde_docs = self._parse_hyde_response(response, num_docs)

        # 缓存
        if self.use_cache:
            self._hyde_cache[cache_key] = {
                'docs': hyde_docs,
                'timestamp': time.time()
            }

        logger.info(f"HyDE: 生成了 {len(hyde_docs)} 个假设文档")
        return hyde_docs

    def _build_hyde_prompt(self, query: str, num_docs: int) -> str:
        """构建HyDE prompt"""
        prompt = f"""请根据用户问题，生成 {num_docs} 个最可能的理想测试用例文档。

用户问题: {query}

要求：
1. 每个假设文档应该包含完整的测试用例信息
2. 格式：测试项标题、前置条件、测试步骤、预期结果
3. 内容要专业、准确，符合测试用例规范

生成格式：
---
假设文档1：
测试项：xxx
前置条件：xxx
测试步骤：xxx
预期结果：xxx

假设文档2：
...
---
"""
        return prompt

    def _parse_hyde_response(self, response: str, num_docs: int) -> List[str]:
        """解析LLM响应，提取假设文档"""
        docs = []

        # 按分隔符分割
        parts = response.split('---')

        for part in parts:
            part = part.strip()
            if part and '假设文档' in part or '文档' in part:
                # 清理并添加到列表
                doc = part.replace('假设文档', '').replace('文档', '').strip()
                if doc and len(doc) > 20:
                    docs.append(doc)

        # 如果解析失败，使用整个响应
        if not docs and len(response) > 20:
            docs = [response]

        # 确保返回指定数量
        while len(docs) < num_docs:
            docs.append(docs[0] if docs else response)

        return docs[:num_docs]

    def _get_cache_key(self, query: str, num_docs: int) -> str:
        """获取缓存键"""
        key_str = f"{query}_{num_docs}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        use_hyde: bool = True
    ) -> Tuple[List[Dict], str]:
        """
        混合检索主方法

        Args:
            query: 用户查询
            top_k: 返回结果数量
            use_hyde: 是否使用HyDE

        Returns:
            (检索结果, 检索策略)
        """
        # Step 1: 判断查询复杂度
        is_simple = self._is_simple_query(query)

        # Step 2: 选择检索策略
        if is_simple or not use_hyde:
            # 简单查询：直接使用原始查询检索
            logger.info("策略: 直接向量检索 (简单查询)")
            query_vector = self.embedding_model.encode_query(query)
            results = self.vector_store.search(query_vector, top_k=top_k)
            strategy = "direct"
        else:
            # 复杂查询：使用HyDE
            logger.info("策略: HyDE检索 (复杂查询)")

            # 生成假设文档
            hyde_docs = self._generate_hypothetical_documents(
                query,
                num_docs=self.num_generations  # 3-5个效果最好
            )

            # 用假设文档进行检索
            all_results = []
            for hyde_doc in hyde_docs:
                hyde_vector = self.embedding_model.encode_query(hyde_doc)
                doc_results = self.vector_store.search(hyde_vector, top_k=top_k)
                all_results.extend(doc_results)  # 展平结果

            # 直接返回所有结果，不需要RRF合并
            results = all_results[:top_k]
            strategy = "hyde"

        logger.info(f"检索完成: {len(results)} 个结果, 策略: {strategy}")
        return results, strategy

    def _rrf_merge(
        self,
        results: List[Dict],
        top_k: int,
        k: int = 60
    ) -> List[Dict]:
        """
        RRF (Reciprocal Rank Fusion) 合并结果

        Args:
            results: 多个检索结果列表
            top_k: 返回数量
            k: RRF参数

        Returns:
            合并后的结果
        """
        if not results:
            return []

        # 按文档分组，使用排名而非分数
        doc_scores = {}
        doc_data = {}

        for result_list in results:
            # 每个result_list是一个检索结果列表
            for rank, result in enumerate(result_list):
                # 防御性处理：处理各种可能的结果格式
                try:
                    if isinstance(result, str):
                        # 如果是字符串，直接作为文档内容
                        doc = result
                        result = {'document': doc, 'score': 0}
                    elif isinstance(result, dict):
                        # 如果是字典，提取文档内容
                        doc = result.get('document', '')
                        if not doc:
                            # 尝试其他可能的字段名
                            doc = result.get('text', '') or result.get('content', '') or str(result)
                    else:
                        # 其他类型尝试转换为字符串
                        doc = str(result)
                        result = {'document': doc, 'score': 0}
                except Exception as e:
                    logger.warning(f"处理检索结果时出错: {e}, result类型: {type(result)}")
                    continue

                if doc not in doc_data:
                    doc_data[doc] = result
                    doc_scores[doc] = 0

                # 使用RRF公式: 1 / (k + rank + 1)
                doc_scores[doc] += 1.0 / (k + rank + 1)

        # 按RRF分数排序
        sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)

        # 返回top_k
        final_results = []
        for doc, score in sorted_docs[:top_k]:
            result = doc_data[doc].copy()
            result['score'] = score
            final_results.append(result)

        return final_results

    def clear_cache(self):
        """清空缓存"""
        self._hyde_cache = {}
        logger.info("HyDE缓存已清空")


class HybridRetriever:
    """
    混合检索器
    结合多种检索策略：
    - 关键词检索
    - 向量检索
    - HyDE检索
    """

    def __init__(
        self,
        embedding_model,
        vector_store,
        keyword_store=None,
        llm=None,
        use_hyde: bool = True,
        hyde_threshold: int = 10
    ):
        self.embedding_model = embedding_model
        self.vector_store = vector_store
        self.keyword_store = keyword_store
        self.use_hyde = use_hyde
        self.hyde_threshold = hyde_threshold

        # HyDE检索器（可选）
        self.hyde_retriever = None
        if llm and use_hyde:
            self.hyde_retriever = HyDERetriever(
                llm=llm,
                embedding_model=embedding_model,
                vector_store=vector_store,
                num_generations=3,  # 3-5个效果最好
                use_cache=True
            )

    def search(
        self,
        query: str,
        top_k: int = 3,
        strategy: str = "auto"
    ) -> List[Dict]:
        """
        检索

        Args:
            query: 查询
            top_k: 返回数量
            strategy: 检索策略
                - "auto": 自动选择
                - "keyword": 关键词检索
                - "vector": 向量检索
                - "hyde": HyDE检索

        Returns:
            检索结果
        """
        if strategy == "auto":
            # 自动选择策略
            if len(query.split()) < self.hyde_threshold:
                strategy = "vector"
            else:
                strategy = "hyde" if self.use_hyde else "vector"

        if strategy == "keyword" and self.keyword_store:
            return self.keyword_store.search(query, top_k=top_k)

        elif strategy == "hyde" and self.hyde_retriever:
            results, _ = self.hyde_retriever.retrieve(query, top_k=top_k)
            return results

        else:
            # 默认向量检索
            query_vector = self.embedding_model.encode_query(query)
            return self.vector_store.search(query_vector, top_k=top_k)


# 全局单例
_hyde_retriever = None


def get_hyde_retriever(
    llm=None,
    embedding_model=None,
    vector_store=None,
    num_generations: int = 3
) -> HyDERetriever:
    """获取HyDE检索器"""
    global _hyde_retriever

    if _hyde_retriever is None:
        from .llm import get_llm
        from .embedding import get_embedding_model
        from .retriever import get_faiss_retriever

        _llm = llm or get_llm()
        _embedding = embedding_model or get_embedding_model()
        _vector_store = vector_store or get_faiss_retriever()

        _hyde_retriever = HyDERetriever(
            llm=_llm,
            embedding_model=_embedding,
            vector_store=_vector_store,
            num_generations=num_generations
        )

    return _hyde_retriever
