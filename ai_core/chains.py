# -*- coding: utf-8 -*-
"""
AI核心层 - 工作流编排模块
四层架构：交互层 → 业务层 → AI核心层 → 数据层
"""
import logging
import os
from typing import List, Dict, Any
import re

from .embedding import get_embedding_model
from .retriever import get_faiss_retriever, FAISSRetriever
from .hybrid_retriever import FusionRetriever
from .crag import CRAGEvaluator, KnowledgeRefiner
from .query_rewriter import QueryRewriter
from .llm import get_llm, LLM
from .prompt import PromptTemplate

logger = logging.getLogger(__name__)

# 尝试导入缓存模块
try:
    from business.cache import get_question_cache
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False
    logger.warning("缓存模块不可用")


class QAChain:
    """
    问答链
    支持：
    - Pipeline 模式：快速检索 + 自动质量评估
    - Agent 模式：完整流程（Query改写 + 混合检索 + CRAG）
    - 自动决策：根据检索质量选择最佳路径
    """

    def __init__(
        self,
        embedding_model=None,
        retriever: FAISSRetriever = None,
        llm: LLM = None,
        top_k: int = 3,
        retrieve_top_k: int = 10,
        enable_fusion: bool = True,
        enable_hyde: bool = True,
        enable_crag: bool = True,
        enable_query_rewrite: bool = True,
        reranker_model_path: str = None
    ):
        self.embedding_model = embedding_model or get_embedding_model()
        self.retriever = retriever
        self.llm = llm or get_llm()
        self.top_k = top_k
        self.retrieve_top_k = retrieve_top_k
        self.enable_fusion = enable_fusion
        self.enable_hyde = enable_hyde
        self.enable_crag = enable_crag
        self.enable_query_rewrite = enable_query_rewrite
        self.reranker_model_path = reranker_model_path
        self.prompt_template = PromptTemplate()

        # 缓存
        self.cache = None
        if CACHE_AVAILABLE:
            try:
                self.cache = get_question_cache()
                logger.info("问答缓存初始化成功")
            except Exception as e:
                logger.warning(f"缓存初始化失败: {e}")

        # Query改写器
        self.query_rewriter = None
        if enable_query_rewrite:
            # 从配置读取rewrite_mode
            from config.settings import FEATURE_FLAGS
            rewrite_mode = FEATURE_FLAGS.get("rewrite_mode", "fast")
            self.query_rewriter = QueryRewriter(self.llm, rewrite_mode=rewrite_mode)
            logger.info(f"Query改写器初始化成功, 模式={rewrite_mode}")

        # CRAG 评估器
        self.crag_evaluator = None
        self.crag_refiner = None
        if enable_crag:
            self.crag_evaluator = CRAGEvaluator(self.llm)
            self.crag_refiner = KnowledgeRefiner(self.llm)
            logger.info("CRAG评估器初始化成功")

        # 初始化混合检索器
        self.fusion_retriever = None
        if enable_fusion:
            self._init_fusion_retriever()

    def _pipeline_retrieve(self, query: str) -> List[Dict]:
        """
        Pipeline 快速检索模式
        跳过 Query 改写，直接使用混合检索

        Returns:
            检索结果列表
        """
        logger.info(f"[Pipeline模式] 快速检索: {query[:30]}...")

        if self.enable_fusion and self.fusion_retriever:
            # 使用混合检索，跳过 HyDE（简单查询）
            strategy = "fusion" if len(query) < 20 else "auto"
            docs = self.fusion_retriever.search(
                query,
                top_k=self.retrieve_top_k,
                strategy=strategy
            )
        else:
            # 降级到直接向量检索
            query_vector = self.embedding_model.encode_query(query)
            docs = self.retriever.search(query_vector, top_k=self.retrieve_top_k)

        logger.info(f"[Pipeline模式] 检索完成: {len(docs)} 个结果")
        return docs

    def _assess_quality(self, docs: List[Dict]) -> Dict[str, Any]:
        """
        评估检索结果质量

        Args:
            docs: 检索结果列表

        Returns:
            {
                "quality": "good" | "poor",
                "top_score": 最高分数,
                "avg_score": 平均分数,
                "reason": 评估原因
            }
        """
        # 从配置读取阈值
        from config.settings import FEATURE_FLAGS
        threshold = FEATURE_FLAGS.get("quality_threshold", 0.7)

        if not docs:
            return {
                "quality": "poor",
                "top_score": 0,
                "avg_score": 0,
                "reason": "无检索结果"
            }

        # 获取分数（优先使用 rerank_score）
        scores = []
        for doc in docs:
            score = doc.get('rerank_score', doc.get('score', 0))
            scores.append(score)

        top_score = max(scores) if scores else 0
        avg_score = sum(scores) / len(scores) if scores else 0

        # 质量判断
        if top_score >= threshold:
            quality = "good"
            reason = f"Top分数 {top_score:.3f} >= 阈值 {threshold}"
        elif avg_score >= 0.5 and top_score >= 0.6:
            quality = "good"
            reason = f"平均分数 {avg_score:.3f} 良好，Top分数 {top_score:.3f}"
        else:
            quality = "poor"
            reason = f"Top分数 {top_score:.3f} < 阈值 {threshold}"

        logger.info(f"[质量评估] {quality}: {reason}, Top={top_score:.3f}, Avg={avg_score:.3f}")

        return {
            "quality": quality,
            "top_score": top_score,
            "avg_score": avg_score,
            "reason": reason
        }

    def _is_simple_query(self, query: str) -> bool:
        """
        判断是否为简单问题，简单问题跳过Query改写以提升速度

        注意：对于可能产生歧义的查询（如"跟车"），需要启用 Query 改写进行领域过滤
        """
        from config.settings import FEATURE_FLAGS
        threshold = FEATURE_FLAGS.get("simple_query_length", 30)

        # 0. 歧义关键词列表 - 这些词可能产生多个领域的理解，需要 Query 改写进行过滤
        ambiguous_keywords = ["跟车", "启动", "开门", "出场", "入场", "收费", "支付"]
        if any(kw in query for kw in ambiguous_keywords):
            # 包含歧义关键词，需要 Query 改写来过滤不相关领域
            return False

        # 1. 长度判断
        if len(query) <= threshold:
            # 2. 关键词判断（复杂词）
            complex_keywords = ["比较", "vs", "差异", "区别", "分析", "为什么", "如何实现", "原理"]
            for kw in complex_keywords:
                if kw in query:
                    return False
            return True

        # 3. 检查是否包含复杂特征
        if any(kw in query for kw in ["比较", "vs", "差异", "区别"]):
            return False

        return False

    def _rrf_fusion(self, results_list: List[List[Dict]], top_k: int = 10, k: int = 60) -> List[Dict]:
        """
        RRF (Reciprocal Rank Fusion) 融合多个检索结果

        Args:
            results_list: 多个检索结果列表
            top_k: 返回数量
            k: RRF参数

        Returns:
            融合后的结果
        """
        if not results_list:
            return []

        doc_scores = {}

        for results in results_list:
            for rank, doc in enumerate(results):
                # 使用文档内容作为key
                doc_key = doc.get('document', '')[:100]
                if not doc_key:
                    continue

                if doc_key not in doc_scores:
                    doc_scores[doc_key] = {
                        'score': 0,
                        'document': doc.get('document', ''),
                        'metadata': doc.get('metadata', {}),
                        'distance': doc.get('distance', 0),
                        'score_val': doc.get('score', 0)
                    }

                # RRF公式
                doc_scores[doc_key]['score'] += 1.0 / (k + rank + 1)

        # 按分数排序
        sorted_docs = sorted(doc_scores.values(), key=lambda x: x['score'], reverse=True)

        # 转换为结果格式
        fusion_results = []
        for i, item in enumerate(sorted_docs[:top_k]):
            fusion_results.append({
                'document': item['document'],
                'metadata': item['metadata'],
                'distance': item['distance'],
                'score': item['score_val'],
                'rerank_score': item['score'],
                'index': i
            })

        return fusion_results

    def _search_with_intent(self, queries: List[str], intent_info: Dict, top_k: int = 10) -> List[Dict]:
        """
        基于意图的检索

        Args:
            queries: 查询列表
            intent_info: 意图信息
            top_k: 返回数量

        Returns:
            检索结果
        """
        primary_intent = intent_info.get('primary_intent', '一般查询')

        # 根据意图调整检索参数
        use_hyde = True
        use_rerank = True

        if primary_intent == "对比分析":
            # 对比分析需要更多候选
            parallel_top_k = 15
            rerank_top_k = 15
        elif primary_intent == "测试方法":
            # 测试方法需要精确用例
            parallel_top_k = 8
            rerank_top_k = 8
            use_hyde = True
        elif primary_intent == "边界条件":
            # 边界条件需要广泛召回
            parallel_top_k = 12
            rerank_top_k = 10
        else:
            parallel_top_k = 10
            rerank_top_k = 10

        # 并行检索（最多3个查询）
        all_results = []
        search_queries = queries[:3]

        # 使用原始查询字符数判断策略，避免意图改写结果过长导致误判
        original_query_len = len(queries[0]) if queries else 0
        use_hyde_for_all = original_query_len >= 20

        logger.info(f"并行检索 {len(search_queries)} 个查询版本, 原始查询长度={original_query_len}, 统一HyDE={use_hyde_for_all}")

        for q in search_queries:
            # 优先使用基于原始查询的策略，避免改写结果过长触发不必要的HyDE
            if use_hyde_for_all:
                strategy = "hyde"
            else:
                strategy = "fusion"

            results = self.fusion_retriever.search(
                q,
                top_k=parallel_top_k,
                strategy=strategy
            )
            all_results.append(results)

        # RRF融合
        fusion_results = self._rrf_fusion(all_results, top_k=top_k)

        logger.info(f"RRF融合: {len(all_results)} x {parallel_top_k} -> {len(fusion_results)} 结果")

        return fusion_results

    def _init_fusion_retriever(self):
        """初始化混合检索器 (BM25 + 向量 + HyDE + 重排)"""
        try:
            # 获取文档列表
            documents = []
            if self.retriever:
                documents = self.retriever.documents

            # BM25索引持久化路径（与FAISS路径关联）
            bm25_index_path = None
            if hasattr(self.retriever, 'index_path') and self.retriever.index_path:
                import os
                # 从FAISS index_path派生BM25索引路径
                # 例如: faiss_db/kb_use_cases -> faiss_db/kb_use_cases_bm25
                base = self.retriever.index_path.rstrip('/').rstrip('\\')
                bm25_index_path = f"{base}_bm25"

            self.fusion_retriever = FusionRetriever(
                embedding_model=self.embedding_model,
                vector_store=self.retriever,
                llm=self.llm,
                documents=documents,
                use_bm25=True,
                use_hyde=self.enable_hyde,
                use_rerank=True,
                sparse_weight=0.4,   # BM25权重
                dense_weight=0.6,   # 向量权重
                hyde_threshold=20,  # 启用HyDE的阈值(字符数)
                rerank_top_k=5,     # 重排返回数量（减少以提升速度）
                coarse_top_k=30,     # 粗排检索数量（减少以提升速度）
                reranker_model_path=self.reranker_model_path,
                bm25_index_path=bm25_index_path
            )
            logger.info("混合检索器初始化成功 (BM25 + 向量 + HyDE + 重排)")
        except Exception as e:
            logger.warning(f"混合检索器初始化失败: {e}")

    def format_docs(self, docs: List[Dict]) -> List[str]:
        """格式化文档为上下文"""
        return [doc.get('document', '')[:600] for doc in docs]

    def parse_case(self, document: str) -> Dict[str, Any]:
        """解析测试用例文档"""
        import html
        document = html.unescape(document)

        # 提取标题和ID
        title_match = re.search(r'##\s*(.+?)\s*\(ID:\s*(\d+)\)', document)
        title = title_match.group(1).strip() if title_match else "测试用例"
        case_id = title_match.group(2) if title_match else "未知"

        # 提取步骤
        steps = []
        for match in re.findall(
            r'步骤[：:]\s*(.+?)\s*->\s*预期[：:]\s*(.+?)(?=\n|步骤:|$)',
            document,
            re.DOTALL
        ):
            action = match[0].strip()[:100]
            expect = match[1].strip()[:100]
            if action:
                steps.append({'action': action, 'expect': expect})

        return {
            'title': title,
            'case_id': case_id,
            'steps': steps[:3],
            'content': document[:500]
        }

    def invoke(self, query: str, return_contexts: bool = False, force_agent: bool = False) -> Dict[str, Any]:
        """
        执行问答链（优化版 - 自动决策模式）

        工作流程：
        1. 缓存检查
        2. Pipeline 快速检索（跳过 Query 改写）
        3. 质量评估（Rerank 分数 >= 0.7?）
        4. 是 → 直接生成答案；否 → Agent 完整流程

        Args:
            query: 用户查询
            return_contexts: 是否返回上下文
            force_agent: 强制使用 Agent 模式（跳过自动决策和缓存）
        """
        logger.info(f"=== QAChain 执行: {query} ===")

        # ========== Step 0: 缓存检查 ==========
        if self.cache and not force_agent:
            cached = self.cache.get_answer(query)
            if cached:
                logger.info(f"[缓存命中] 直接返回缓存结果")
                return {
                    "query": query,
                    "answer": cached.get("answer", ""),
                    "cases": cached.get("cases", []),
                    "doc_count": cached.get("doc_count", 0),
                    "strategy": "cache",
                    "crag": {},
                    "rewrite": {},
                    "retrieved_docs": [],
                    "contexts": []
                }

        # ========== 决策点：自动判断模式 ==========
        # 先尝试 Pipeline 模式，如果质量不够再走 Agent 流程
        docs = None
        strategy = None

        if not force_agent:
            # Step 1: Pipeline 快速检索（跳过 Query 改写）
            docs = self._pipeline_retrieve(query)

            # Step 2: 质量评估
            quality_info = self._assess_quality(docs)

            if quality_info["quality"] == "good":
                # Pipeline 模式质量合格，直接生成答案
                strategy = "pipeline"
                logger.info(f"[自动决策] Pipeline模式质量合格，直接生成答案")
            else:
                # Pipeline 模式质量不合格，切换到 Agent 完整流程
                logger.info(f"[自动决策] Pipeline模式质量不合格，切换到Agent完整流程")
                strategy = "agent"
                docs = None  # 重新检索
        else:
            strategy = "agent"

        # ========== Agent 完整流程 ==========
        if strategy == "agent" or docs is None:
            # Step A: Query 改写
            rewrite_info = {}
            is_simple = self._is_simple_query(query)
            use_multi_search = False

            if is_simple:
                logger.info(f"[优化] 检测为简单问题，跳过Query改写")
                rewritten_queries = [query]
                intent_info = {}
            elif self.enable_query_rewrite and self.query_rewriter:
                logger.info("执行Query改写...")
                rewritten_queries, intent_info = self.query_rewriter.rewrite(query)

                rewrite_info = {
                    "original": query,
                    "rewritten": rewritten_queries,
                    "intent": intent_info
                }

                # 输出改写详情
                logger.info(f"Query改写: 意图={intent_info.get('primary_intent', 'N/A')}, 生成{len(rewritten_queries)}个版本")
                logger.info(f"Query改写详情:")
                logger.info(f"  - 原始查询: {query}")
                logger.info(f"  - 识别意图: {intent_info.get('intents')}")
                logger.info(f"  - 提取关键词: {intent_info.get('keywords')}")
                logger.info(f"  - 提取实体: {intent_info.get('entities')}")
                logger.info(f"  - 改写查询: {rewritten_queries}")

                # 启用多查询并行检索 + 意图指导
                use_multi_search = True
            else:
                use_multi_search = False
                rewritten_queries = [query]
                intent_info = {}

            # Step B: 检索
            word_count = len(query)

            if self.enable_fusion and self.fusion_retriever:
                if use_multi_search:
                    # 多查询并行检索 + RRF融合 + 意图指导
                    docs = self._search_with_intent(
                        rewritten_queries,
                        intent_info,
                        top_k=self.retrieve_top_k
                    )
                    strategy = "agent_multi_query"
                else:
                    # 原有逻辑
                    logger.info(f"策略: 混合检索 (字符数={word_count})")
                    docs = self.fusion_retriever.search(
                        rewritten_queries[0],
                        top_k=self.retrieve_top_k,
                        strategy="auto"
                    )
                    strategy = "agent_fusion"
            else:
                # 降级到直接向量检索
                logger.info(f"策略: 直接向量检索 (字符数={word_count})")
                query_vector = self.embedding_model.encode_query(rewritten_queries[0])
                docs = self.retriever.search(query_vector, top_k=self.retrieve_top_k)
                strategy = "agent_direct"

        # Step 2: CRAG 评估（仅 Agent 模式）
        crag_info = {}
        rewrite_info = {}  # Pipeline 模式没有 Query 改写

        # 只有 Agent 模式才执行 CRAG 评估
        if strategy.startswith("agent") and self.enable_crag and self.crag_evaluator and docs:
            logger.info("执行CRAG评估...")

            # 输出检索到的文档
            logger.info(f"CRAG评估输入 - 检索到 {len(docs)} 个文档:")
            for i, doc in enumerate(docs[:5]):
                logger.info(f"  文档{i+1}: {doc.get('document', '')[:100]}...")

            # 评估文档相关性
            evaluated_docs = self.crag_evaluator.evaluate(query, docs)

            # 统计分类结果
            correct = sum(1 for d in evaluated_docs if d.get('relevance') == 'correct')
            ambiguous = sum(1 for d in evaluated_docs if d.get('relevance') == 'ambiguous')
            incorrect = sum(1 for d in evaluated_docs if d.get('relevance') == 'incorrect')

            crag_info = {
                "correct": correct,
                "ambiguous": ambiguous,
                "incorrect": incorrect
            }

            logger.info(f"CRAG评估结果: CORRECT={correct}, AMBIGUOUS={ambiguous}, INCORRECT={incorrect}")

            # 输出每个文档的评估结果
            logger.info(f"CRAG评估详情:")
            for i, doc in enumerate(evaluated_docs):
                relevance = doc.get('relevance', 'N/A')
                doc_preview = doc.get('document', '')[:50].replace('\n', ' ')
                logger.info(f"  文档{i+1}: [{relevance}] {doc_preview}...")

            # 如果有精炼器，对文档进行精炼
            if self.crag_refiner and correct >= 1:
                refined_context = self.crag_refiner.refine(query, evaluated_docs)
                crag_info["refined"] = True

            # 关键修复：根据 CRAG 评估结果过滤文档
            # 如果所有文档都不相关(INCORRECT)，过滤掉不相关文档
            if incorrect > 0 and correct == 0:
                # 所有文档都不相关，使用 ambiguous 以上的文档
                filtered_docs = [d for d in evaluated_docs if d.get('relevance') in ['correct', 'ambiguous']]
                if filtered_docs:
                    docs = filtered_docs[:self.top_k]
                    logger.warning(f"CRAG过滤: 原始{len(evaluated_docs)}个文档中{incorrect}个不相关，过滤后{len(docs)}个")
                else:
                    # 没有相关文档，记录警告
                    logger.warning(f"CRAG警告: 所有{len(evaluated_docs)}个文档都被判定为不相关，可能导致回答不准确")

        docs = docs[:self.top_k]

        # Step 3: 解析文档
        cases = [self.parse_case(doc['document']) for doc in docs]
        contexts = self.format_docs(docs)

        # Step 4: 构建提示 (根据查询类型选择模板)
        # 检测是否为测试相关查询
        is_test_query = self.prompt_template.is_test_query(query)
        if is_test_query:
            logger.info("检测到测试查询，使用结构化输出模板")
            logger.info(f"TEST_CASE_TEMPLATE 长度: {len(self.prompt_template.TEST_CASE_TEMPLATE)}")
            logger.info(f"TEST_CASE_TEMPLATE 内容预览:\n{self.prompt_template.TEST_CASE_TEMPLATE[:500]}...")

        prompt = self.prompt_template.test_case_prompt(query, contexts)
        logger.info(f"生成的 Prompt 长度: {len(prompt)}")

        # Step 5: 调用LLM
        answer = self.llm.generate(prompt)

        # Step 6: 如果是测试查询，格式化输出
        if is_test_query:
            answer = self.prompt_template.format_test_response(answer)
            logger.info("已格式化测试回答为标准格式")

        logger.info(f"=== 完成, 答案长度: {len(answer)}, 策略: {strategy} ===")

        # ========== Step 7: 缓存结果 ==========
        if self.cache:
            try:
                self.cache.set_answer(query, answer, cases)
            except Exception as e:
                logger.warning(f"缓存写入失败: {e}")

        return {
            "query": query,
            "answer": answer,
            "cases": cases,
            "doc_count": len(docs),
            "strategy": strategy,
            "crag": crag_info,
            "rewrite": rewrite_info,
            "retrieved_docs": docs,  # 添加原始检索结果
            "contexts": docs  # 添加上下文
        }

    def stream_invoke(self, query: str):
        """流式执行"""
        logger.info(f"=== QAChain 流式执行: {query} ===")

        # 混合检索
        word_count = len(query.split())

        if self.enable_fusion and self.fusion_retriever:
            docs = self.fusion_retriever.search(
                query,
                top_k=self.retrieve_top_k,
                strategy="auto"
            )
        else:
            query_vector = self.embedding_model.encode_query(query)
            docs = self.retriever.search(query_vector, top_k=self.retrieve_top_k)

        docs = docs[:self.top_k]
        cases = [self.parse_case(doc['document']) for doc in docs]
        contexts = self.format_docs(docs)

        # 检测是否为测试查询
        is_test_query = self.prompt_template.is_test_query(query)

        # 构建提示
        prompt = self.prompt_template.test_case_prompt(query, contexts)

        # 流式生成
        full_answer = ""
        for chunk in self.llm.stream_generate(prompt):
            full_answer += chunk

        # 如果是测试查询，格式化输出
        if is_test_query:
            full_answer = self.prompt_template.format_test_response(full_answer)

        yield {
            "type": "chunk",
            "chunk": chunk,
            "full": full_answer,
            "cases": cases
        }

        yield {"type": "done", "cases": cases}


# 全局单例（延迟加载）
_qa_chain = None
_qa_chain_config = None  # 保存配置参数


def get_qa_chain() -> QAChain:
    """获取问答链单例（延迟加载，首次调用时初始化）"""
    global _qa_chain, _qa_chain_config

    if _qa_chain is None:
        from config.settings import FEATURE_FLAGS

        # 延迟加载：如果没有预配置，则创建默认配置
        if _qa_chain_config is None:
            _qa_chain_config = {
                'enable_crag': FEATURE_FLAGS.get("enable_crag", False),
                'enable_hyde': FEATURE_FLAGS.get("enable_hyde", True),
                'enable_query_rewrite': FEATURE_FLAGS.get("enable_query_rewrite", True),
                'enable_fusion': FEATURE_FLAGS.get("enable_fusion", True),
                'retrieve_top_k': FEATURE_FLAGS.get("default_top_k", 5)
            }

        # 首次调用时加载模型和检索器
        from .embedding import init_embedding_model
        # 使用默认模型（从 HuggingFace 加载）
        init_embedding_model(None)

        retriever = get_faiss_retriever()

        _qa_chain = QAChain(
            retriever=retriever,
            **_qa_chain_config
        )

    return _qa_chain


def init_qa_chain(model_path: str = None, chroma_path: str = None, reranker_model_path: str = None) -> QAChain:
    """初始化问答链（预加载模型）"""
    global _qa_chain, _qa_chain_config

    # 保存配置参数（但不立即加载）
    from config.settings import FEATURE_FLAGS
    _qa_chain_config = {
        'enable_crag': FEATURE_FLAGS.get("enable_crag", False),
        'enable_hyde': FEATURE_FLAGS.get("enable_hyde", True),
        'enable_query_rewrite': FEATURE_FLAGS.get("enable_query_rewrite", True),
        'enable_fusion': FEATURE_FLAGS.get("enable_fusion", True),
        'retrieve_top_k': FEATURE_FLAGS.get("default_top_k", 5)
    }

    # 立即加载模型
    from .embedding import init_embedding_model
    init_embedding_model(model_path)

    retriever = get_faiss_retriever(chroma_path)

    _qa_chain = QAChain(
        retriever=retriever,
        reranker_model_path=reranker_model_path,
        **_qa_chain_config
    )

    return _qa_chain
