# -*- coding: utf-8 -*-
"""
MCP 测试策略生成服务
接收 RATP-Engine 输出的原子功能 JSON，生成测试策略
优化版本：批量RAG + 异步处理 + 并行生成 + 原子级Rerank + 语义去重 + Token统计
"""
import json
import logging
import os
import uuid
import threading
import time
from flask import Blueprint, request, jsonify
from typing import Dict, List, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict, Counter
import re
from config import TEST_STRATEGIES_DIR

logger = logging.getLogger(__name__)

mcp_bp = Blueprint('mcp', __name__, url_prefix='/api/mcp')

# 全局变量
_qa_chain = None
_llm = None
_reranker = None

# 异步任务存储
_async_tasks = {}
_executor = ThreadPoolExecutor(max_workers=4)  # 增加到4个工作线程

# Token统计
_token_stats = {
    'total_input_tokens': 0,
    'total_output_tokens': 0,
    'llm_call_count': 0
}
_token_lock = threading.Lock()

# 模块级缓存（同一次任务不重复检索）
# 注意：非并发安全！如需支持多用户并发，请使用 contextvars 或参数传递
_module_context_cache = {}
_module_context_lock = threading.Lock()  # 简单线程锁（可选）


def init_mcp_routes(qa_chain, lazy=False):
    """初始化 MCP 路由的全局变量

    Args:
        qa_chain: QAChain 实例，如果为 None 则使用延迟加载
        lazy: 是否延迟加载（True=不在启动时加载模型）
    """
    global _qa_chain
    _qa_chain = qa_chain

    if not lazy:
        # 非延迟模式：预热 Reranker
        get_reranker()
        # 优化5: 重置 Token 统计
        reset_token_stats()
        logger.info("MCP 路由已初始化（立即加载模式）")
    else:
        # 延迟模式：只重置 Token 统计
        reset_token_stats()
        logger.info("MCP 路由已初始化（延迟加载模式）")


def get_qa_chain():
    """获取 QA Chain"""
    global _qa_chain
    if _qa_chain is not None:
        return _qa_chain
    from ai_core.chains import get_qa_chain as _get_qa_chain
    return _get_qa_chain()


def get_llm():
    """获取 LLM"""
    global _llm
    if _llm is None:
        from ai_core.llm import LLM
        _llm = LLM()
    return _llm


def get_reranker():
    """获取 Reranker（用于原子级 rerank）"""
    global _reranker
    if _reranker is None:
        try:
            from ai_core.reranker import CrossEncoderReranker
            _reranker = CrossEncoderReranker(top_k=3, device="cpu")
            logger.info("Reranker 初始化成功")
        except Exception as e:
            logger.warning(f"Reranker 初始化失败: {e}, 将跳过 rerank 步骤")
            _reranker = False  # 使用 False 表示不可用
    return _reranker if _reranker else None


def update_token_stats(input_tokens: int, output_tokens: int):
    """更新 Token 统计（线程安全）"""
    global _token_stats
    with _token_lock:
        _token_stats['total_input_tokens'] += input_tokens
        _token_stats['total_output_tokens'] += output_tokens
        _token_stats['llm_call_count'] += 1


def get_token_stats() -> dict:
    """获取 Token 统计"""
    with _token_lock:
        return _token_stats.copy()


def reset_token_stats():
    """重置 Token 统计"""
    global _token_stats
    with _token_lock:
        _token_stats = {
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'llm_call_count': 0
        }


def group_atoms_by_module(atoms: List[dict]) -> Dict[str, List[dict]]:
    """按模块分组原子功能"""
    modules = {}
    for atom in atoms:
        module = atom.get('module', '其他')
        if module not in modules:
            modules[module] = []
        modules[module].append(atom)
    return modules


# ============ 优化2: 语义去重函数 ============

def calculate_similarity(text1: str, text2: str) -> float:
    """计算两个文本的语义相似度（简化版：基于字符重叠）"""
    if not text1 or not text2:
        return 0.0

    # 简单相似度：字符级别的 Jaccard 相似度
    set1 = set(text1.lower())
    set2 = set(text2.lower())

    intersection = len(set1 & set2)
    union = len(set1 | set2)

    return intersection / union if union > 0 else 0.0


def deduplicate_scenarios(scenarios: List[str], similarity_threshold: float = 0.9) -> List[str]:
    """
    语义去重：过滤相似度高于阈值的场景
    优化5: 语义去重（相似度>0.9过滤）
    """
    if not scenarios:
        return []

    # 按长度排序，保留较长的场景
    sorted_scenarios = sorted(scenarios, key=len, reverse=True)
    unique_scenarios = []

    for scenario in sorted_scenarios:
        is_duplicate = False
        for existing in unique_scenarios:
            # 计算相似度
            sim = calculate_similarity(scenario, existing)
            if sim > similarity_threshold:
                is_duplicate = True
                break

        if not is_duplicate:
            unique_scenarios.append(scenario)

    logger.info(f"[去重] 原始场景数: {len(scenarios)}, 去重后: {len(unique_scenarios)}")
    return unique_scenarios


# ============ 改进1: 原子功能级 RAG 检索 + Rerank ============

def dynamic_filter(docs: List[dict], threshold: float = 0.7, max_k: int = 5) -> List[dict]:
    """
    动态筛选策略：
    1. 绝对阈值：Score > threshold 的才要
    2. 相对阈值：保留与最高分差距在 15% 以内的文档
    3. 数量限制：min=1, max=max_k
    4. 低置信度模式：当最高分 < 0.4 时，只取1条
    """
    if not docs:
        return []

    # 按得分排序
    sorted_docs = sorted(docs, key=lambda x: x.get('score', 0), reverse=True)
    max_score = sorted_docs[0].get('score', 1.0)

    # 低置信度模式：如果最高分都低于 0.4，只取1条
    low_confidence_mode = max_score < 0.4

    filtered = []
    for doc in sorted_docs:
        score = doc.get('score', 0)

        if low_confidence_mode:
            # 低置信度模式：只取第1个
            filtered.append(doc)
            break
        else:
            # 正常模式：绝对阈值 + 相对阈值
            relative_gap = (max_score - score) / max_score if max_score > 0 else 1.0
            if score >= threshold or relative_gap <= 0.15:
                filtered.append(doc)

        if len(filtered) >= max_k:
            break

    # 保证最少1个
    return filtered if filtered else [sorted_docs[0]]


# ============ 优化6: 分级检索（Two-Tier Retrieval）===========

def clear_module_cache():
    """清除模块级缓存（每次任务开始时调用）"""
    global _module_context_cache
    _module_context_cache = {}
    logger.info("[两级RAG] 模块缓存已清除")


def enrich_module_with_rag(module_name: str, module_atoms: List[dict]) -> dict:
    """
    模块级 RAG 检索（带缓存）
    - 输入：模块名 + 模块内所有原子
    - 输出：模块核心业务背景（≤800 tokens）

    注意：非并发安全！如需支持多用户并发，请使用 contextvars 或参数传递
    """
    # 缓存检查
    if module_name in _module_context_cache:
        logger.info(f"[Module-RAG] 缓存命中: {module_name}")
        return _module_context_cache[module_name]

    # 1. 构建模块级查询（差异化：业务流程 + 整体架构）
    all_tags = []
    all_business_logic = []
    all_function_names = []  # 优化点3：加入 function_name 提高检索精度
    for atom in module_atoms:
        all_tags.extend(atom.get('tags', []))
        all_business_logic.append(atom.get('business_logic', '')[:100])
        all_function_names.append(atom.get('function_name', ''))

    # 取高频标签
    tag_counts = Counter(all_tags)
    top_tags = [tag for tag, _ in tag_counts.most_common(5)]

    # 优化点3：模块级 Query 加入所有 function_name（限长）
    func_names_str = ' '.join(all_function_names[:5])  # 最多5个
    # 模块级 Query：业务流程 + 整体架构 + 模块对接关系 + 功能名
    module_query = f"{module_name} {func_names_str} {' '.join(top_tags)} 业务流程 整体架构"

    # 2. RAG 检索 (top_k=3)
    qa_chain = get_qa_chain()
    retriever = qa_chain.retriever
    query_vector = qa_chain.embedding_model.encode_query(module_query)
    docs = retriever.search(query_vector, top_k=3)

    # 3. Rerank + 动态筛选（应用 dynamic_filter）
    reranker = get_reranker()
    if reranker and docs:
        reranked = reranker.rerank(module_query, docs, top_k=3)
        docs_with_score = [{'document': doc.get('document', ''), 'score': doc.get('score', 0)} for doc in reranked]
        # 应用 dynamic_filter（复用已有函数）
        filtered_docs = dynamic_filter(docs_with_score, threshold=0.7, max_k=3)
        docs = [{'document': doc.get('document', ''), 'score': doc.get('score', 0)} for doc in filtered_docs]
        logger.info(f"[Module-RAG] {module_name} - rerank后: {len(docs)} 条")

    # 4. 提取上下文 + Token 限制（800 tokens ≈ 2000 字符）
    module_context = '\n\n'.join([doc.get('document', '') for doc in docs if doc.get('document')])[:2000]

    result = {
        'module_name': module_name,
        'module_query': module_query,
        'module_rag_context': module_context
    }

    # 缓存
    _module_context_cache[module_name] = result
    logger.info(f"[Module-RAG] {module_name} 检索完成: {len(module_context)} 字符")

    return result


def enrich_atom_with_rag_optimized(atom: dict, module_context: str) -> dict:
    """
    原子级 RAG 检索（优化版 + dynamic_filter + Token 限制）
    - 输入：原子 + 模块级上下文
    - 输出：原子特定逻辑 + 合并后的完整上下文
    """
    # 1. 构建原子级查询（差异化：边界值 + 异常场景 + 逻辑校验）
    rules = atom.get('rules', [])
    func_name = atom.get('function_name', '')

    rules_text = ' '.join(rules[:3]) if rules else ''
    # 原子级 Query：功能名 + 规则 + 边界值/异常场景
    atom_query = f"{func_name} {rules_text} 边界值 异常场景 逻辑校验"

    # 2. RAG 检索 (top_k=5)
    qa_chain = get_qa_chain()
    retriever = qa_chain.retriever
    query_vector = qa_chain.embedding_model.encode_query(atom_query)
    docs = retriever.search(query_vector, top_k=5)

    # 3. Rerank + 动态筛选（应用 dynamic_filter）
    reranker = get_reranker()
    if reranker and docs:
        reranked = reranker.rerank(atom_query, docs, top_k=5)
        docs_with_score = [{'document': doc.get('document', ''), 'score': doc.get('score', 0)} for doc in reranked]
        # 应用 dynamic_filter
        filtered_docs = dynamic_filter(docs_with_score, threshold=0.7, max_k=3)
        docs = [{'document': doc.get('document', ''), 'score': doc.get('score', 0)} for doc in filtered_docs]
        logger.info(f"[Atom-RAG] {func_name} - rerank后: {len(docs)} 条")

    # 4. 提取原子上下文 + Token 限制（1500 tokens ≈ 4000 字符）
    atom_context = '\n\n'.join([doc.get('document', '') for doc in docs if doc.get('document')])[:4000]

    # 5. 合并上下文（添加"锚点"引导 LLM）
    # 优化点2：增加意图标签，防止"长上下文迷失"
    final_context = f"""【背景知识库 - 业务流视图（供理解大局）】
{module_context[:1500] if len(module_context) > 1500 else module_context}

【背景知识库 - 逻辑校验视图（供生成场景参考）】
{atom_context}"""

    logger.info(f"[Atom-RAG] {func_name} - 模块背景: {len(module_context)} 字符, 原子逻辑: {len(atom_context)} 字符")

    return {
        **atom,
        'rag_context': final_context,
        'module_context': module_context,
        'atom_context': atom_context
    }


def enrich_single_atom_with_rag(atom: dict) -> dict:
    """
    为单个原子功能进行 RAG 检索（优化版：单次查询、跳过HyDE、跳过CRAG）
    优化3: 动态 Top-K 与阈值过滤
    """
    try:
        # 使用 qa_chain 获取 retriever
        qa_chain = get_qa_chain()
        retriever = qa_chain.retriever

        # 构建单次查询
        func_name = atom.get('function_name', '')
        tags = atom.get('tags', [])
        business_logic = atom.get('business_logic', '')[:150]
        rules = atom.get('rules', [])

        # 合并为一个查询
        query = f"{func_name} {', '.join(tags[:5])} {business_logic} {' '.join(rules[:3])} 测试场景"

        # 优化3: 初始多召回一些 (5 -> 10)
        query_vector = qa_chain.embedding_model.encode_query(query)
        docs = retriever.search(query_vector, top_k=10)

        # 如果有 reranker，进行原子级 rerank
        reranker = get_reranker()
        if reranker and docs:
            try:
                # Rerank 返回更多结果供动态筛选
                reranked = reranker.rerank(query, docs, top_k=10)
                # 提取文档和得分
                docs_with_score = []
                for doc in reranked:
                    doc_content = doc.get('document', '')
                    doc_score = doc.get('score', 0.0)
                    docs_with_score.append({'document': doc_content, 'score': doc_score})

                # 优化3: 动态筛选
                filtered_docs = dynamic_filter(docs_with_score, threshold=0.7, max_k=5)
                docs = [{'document': doc.get('document', ''), 'score': doc.get('score', 0)} for doc in filtered_docs]

                # 记录置信度模式
                max_score = filtered_docs[0].get('score', 0) if filtered_docs else 0
                confidence_mode = "低置信度" if max_score < 0.4 else "正常"
                logger.info(f"[Rerank] {func_name} - rerank后: {len(docs)} 条, 模式: {confidence_mode}, 最高分: {max_score:.3f}")
            except Exception as e:
                logger.warning(f"[Rerank] {func_name} 失败: {e}, 使用原始检索结果")

        # 提取文档内容
        contexts = []
        for doc in docs:
            content = doc.get('document', '')
            if content:
                contexts.append(content)

        rag_context = '\n\n'.join(contexts)

        logger.info(f"[RAG] {func_name} - 召回: {len(docs)} 条, {len(rag_context)} 字符")

        return {
            **atom,
            'rag_context': rag_context
        }
    except Exception as e:
        logger.warning(f"原子功能 {atom.get('function_name', '')} RAG 检索失败: {e}")
        return {**atom, 'rag_context': ''}


def enrich_atoms_by_module(atoms: List[dict]) -> Dict[str, List[dict]]:
    """
    分级检索流程（优化版）
    Step 1: 模块级初探（缓存）
    Step 2: 原子级精搜
    Step 3: 合并上下文

    优化6: Two-Tier Retrieval - 分级检索
    """
    # 清除缓存（每次任务重新开始）
    clear_module_cache()

    modules = group_atoms_by_module(atoms)
    enriched_modules = {}

    for module_name, module_atoms in modules.items():
        logger.info(f"[两级RAG] 开始处理模块 '{module_name}'，共 {len(module_atoms)} 个原子")

        # ========== Step 1: 模块级初探（带缓存）==========
        module_enriched = enrich_module_with_rag(module_name, module_atoms)
        module_context = module_enriched.get('module_rag_context', '')

        # ========== Step 2: 原子级精搜 ==========
        enriched_atoms = []

        if len(module_atoms) > 1:
            with ThreadPoolExecutor(max_workers=min(4, len(module_atoms))) as pool:
                futures = {
                    pool.submit(enrich_atom_with_rag_optimized, atom, module_context): atom
                    for atom in module_atoms
                }
                for future in as_completed(futures):
                    try:
                        enriched_atom = future.result()
                        enriched_atoms.append(enriched_atom)
                    except Exception as e:
                        atom = futures[future]
                        logger.warning(f"[Atom-RAG] {atom.get('function_name', '')} 失败: {e}")
                        enriched_atoms.append({**atom, 'rag_context': module_context})
        else:
            enriched_atoms = [enrich_atom_with_rag_optimized(atom, module_context) for atom in module_atoms]

        # 保持原始顺序
        atom_map = {a.get('function_name', ''): a for a in enriched_atoms}
        enriched_atoms = [atom_map.get(a.get('function_name', ''), a) for a in module_atoms]

        enriched_modules[module_name] = {
            'module': module_name,
            'atoms': enriched_atoms,
            'rag_context': '\n\n'.join([a.get('rag_context', '') for a in enriched_atoms])
        }

    return enriched_modules


# ============ LLM 异常推导（批量+并行） ============

def expand_single_atom(atom: dict, all_atoms_info: str, rag_context_limit: int = 3000) -> dict:
    """
    优化1: 单个原子功能的 LLM 扩展（用于并行处理）
    包含：Token统计、语义去重、多样化约束Prompt

    Returns:
        扩展后的 atom
    """
    llm = get_llm()
    func_name = atom.get('function_name', '')
    business_logic = atom.get('business_logic', '')
    trigger_condition = atom.get('trigger_condition', '')
    rules = atom.get('rules', [])
    tags = atom.get('tags', [])

    existing_test_cases = atom.get('test_cases', {})
    existing_normal = existing_test_cases.get('normal', [])
    existing_exception = existing_test_cases.get('exception', [])

    logger.info(f"[LLM] 处理功能: {func_name}, RATP已有-正常:{len(existing_normal)}, 异常:{len(existing_exception)}")

    # 构建 test_cases 结构（保留 RATP 原有数据）
    atom['test_cases'] = existing_test_cases.copy() if existing_test_cases else {}

    # 始终调用 RAG+LLM 补充更多场景
    atom_rag_context = atom.get('rag_context', '')[:rag_context_limit]

    # 构建扩展 prompt - 根据 RAG 结果决定补充策略
    has_rag_context = bool(atom_rag_context and len(atom_rag_context) > 100)

    # 优化3: Prompt多样化约束 - 边界值、并发、异常中断场景
    diversity_requirements = """
## 多样化场景约束（重要 - 必须包含以下类型的场景）：
1. 边界值场景：
   - 时间边界（如免费时长临界点 59秒/60秒/61秒）
   - 金额边界（如免费金额临界点）
   - 车辆数量边界（如车位满时）
2. 并发场景：
   - 多车同时识别
   - 前后车跟进
   - 并行支付
3. 异常中断场景：
   - 支付中断
   - 网络超时
   - 识别中断
   - 道闸异常
"""

    if has_rag_context:
        # RAG 有结果：基于知识库补充
        prompt = f"""
你是一名资深测试架构师。请基于 RAG 知识库中的业务知识，为以下功能**补充**更多测试场景。

## 当前功能信息
### 功能名称：{func_name}
### 业务逻辑：{business_logic}
### 触发条件：{trigger_condition}
### 业务规则：{', '.join(rules)}
### tags：{', '.join(tags)}

### RATP 已有的测试点（必须保留，但不要重复输出）：
- 正常场景：{existing_normal if existing_normal else '无'}
- 异常场景：{existing_exception if existing_exception else '无'}

## RAG 知识库检索的业务知识（重要参考，用于补充新场景）：
{atom_rag_context}

## 整体需求上下文（参考此信息了解完整业务场景）：
{all_atoms_info}

{diversity_requirements}

## 场景要求（重要）：
1. 每个场景必须包含：
   - 车辆类型（临时车/月租车/无牌车/免费车）
   - 完整操作步骤（识别→处理→结果）
   - 预期结果（生成的记录类型、备注字段、车位数变化）
2. 验证点必须包含：
   - 是否生成出场记录/入场记录
   - 记录类型（系统补录/正常）
   - 入场备注（倒车返场/系统纠正车牌）
   - 剩余车位数变化
3. 嵌套车场场景（如适用）：
   - 大车场/小车场的出入场顺序
   - 计费时段计算
4. 场景格式示例（重要 - 不要包含编号，直接输出场景描述）：
   正常场景示例（不要写编号，直接写描述）：
   临时车A识别出场弹窗收费，不交费直接倒车，岗亭弹窗自动消失，控制机屏幕自动恢复到闲时显示
   月租车有效期内识别出场，自动开闸，不过闸倒车，不生成出场记录，场内记录保持不变
   月租车有效期内识别出场，自动开闸，先过闸产生通行事件，再倒车，先生成出场记录，再生成新的疑似入场记录，入场时间为倒车事件的时间

   异常场景示例（不要写编号，直接写描述）：
   入口临时车确认开闸，临时车识别入场弹确认开闸窗，不点确认，车辆倒车，岗亭弹窗自动消失
   入口临时车自动开闸，临时车识别入场自动开闸，车辆不通行倒车，场内记录保留不删除

## 补充要求：
1. 保留 RATP 已有的测试点（不要重复列出）
2. 基于 RAG 知识库的测试用例，补充新的正常场景和异常场景
3. 参考人工撰写的测试用例格式，确保场景描述完整
4. 必须输出至少 3 个新的正常场景和 3 个新的异常场景（不包含 RATP 已有的）

请按以下 JSON 格式输出（不要包含 RATP 已有的场景，只输出新补充的场景）：
{{
    "normal": ["新场景1", "新场景2", "新场景3"],
    "exception": ["新异常1", "新异常2", "新异常3"]
}}
"""
    else:
        # RAG 无结果：基于业务背景让 LLM 补充
        prompt = f"""
你是一名资深测试架构师。请根据以下业务信息，为功能**设计**完整的测试场景。

## 当前功能信息
### 功能名称：{func_name}
### 业务逻辑：{business_logic}
### 触发条件：{trigger_condition}
### 业务规则：{', '.join(rules)}
### tags：{', '.join(tags)}

### RATP 已有的测试点（必须保留，但不要重复输出）：
- 正常场景：{existing_normal if existing_normal else '无'}
- 异常场景：{existing_exception if existing_exception else '无'}

## 整体需求上下文（参考此信息了解完整业务场景）：
{all_atoms_info}

{diversity_requirements}

## 场景要求（重要）：
1. 每个场景必须包含：
   - 车辆类型（临时车/月租车/无牌车/免费车）
   - 完整操作步骤（识别→处理→结果）
   - 预期结果（生成的记录类型、备注字段、车位数变化）
2. 验证点必须包含：
   - 是否生成出场记录/入场记录
   - 记录类型（系统补录/正常）
   - 入场备注（倒车返场/系统纠正车牌）
   - 剩余车位数变化
3. 正常场景设计要点：
   - 不同车型（临时车，月租车、无牌车、免费车）
   - 不同付费方式（现金、扫码、线上）
   - 不同时间段（免费时间内、免费时间外）
   - 正常流程和边界条件
4. 异常场景设计要点：
   - 超时、识别失败、并发冲突
   - 嵌套车场边界条件
   - 记录生成异常情况
5. 场景格式示例（重要 - 不要包含编号，直接输出场景描述）：
   正常场景示例（不要写编号，直接写描述）：
   临时车A识别出场弹窗收费，不交费直接倒车，岗亭弹窗自动消失
   月租车有效期内识别出场，自动开闸，不过闸倒车，不生成出场记录
   月租车有效期内识别出场，自动开闸，先过闸产生通行事件，再倒车，先生成出场记录

   异常场景示例（不要写编号，直接写描述）：
   入口临时车确认开闸，车辆倒车，岗亭弹窗自动消失
   入口临时车自动开闸，车辆不通行倒车，场内记录保留不删除

## 补充要求：
1. 保留 RATP 已有的测试点（不要重复列出）
2. 根据业务逻辑、触发条件、业务规则，设计新的测试场景
3. 参考人工撰写的测试用例格式，确保场景描述完整
4. 必须输出至少 3 个新的正常场景和 3 个新的异常场景（不包含 RATP 已有的）

请按以下 JSON 格式输出（不要包含 RATP 已有的场景，只输出新设计的场景）：
{{
    "normal": ["新场景1", "新场景2", "新场景3"],
    "exception": ["新异常1", "新异常2", "新异常3"]
}}
"""

    try:
        # 优化5: 记录 Token 消耗
        input_tokens = len(prompt) // 4  # 简单估算
        result = llm.generate(prompt)
        output_tokens = len(result) // 4  # 简单估算
        update_token_stats(input_tokens, output_tokens)

        # 记录 LLM 返回结果（前500字符）
        logger.info(f"[LLM] {func_name} 返回结果: {result[:500]}...")

        test_cases = parse_simple_test_cases(result)

        # 记录解析结果
        llm_normal = test_cases.get('normal', [])
        llm_exception = test_cases.get('exception', [])
        logger.info(f"[LLM] {func_name} 解析结果: normal={len(llm_normal)}, exception={len(llm_exception)}")

        # 优化4: 语义去重 - 先对 LLM 生成的场景进行去重
        llm_normal = deduplicate_scenarios(llm_normal, similarity_threshold=0.9)
        llm_exception = deduplicate_scenarios(llm_exception, similarity_threshold=0.9)

        # 合并：RATP 已有 + LLM 新增
        # 合并正常场景（去重）
        all_normal = existing_normal.copy()
        for n in llm_normal:
            if n not in all_normal:
                all_normal.append(n)

        # 合并异常场景（去重，重点补充）
        all_exception = existing_exception.copy()
        for e in llm_exception:
            if e not in all_exception:
                all_exception.append(e)

        # 优化4: 最终去重
        all_normal = deduplicate_scenarios(all_normal, similarity_threshold=0.9)
        all_exception = deduplicate_scenarios(all_exception, similarity_threshold=0.9)

        atom['test_cases']['normal'] = all_normal[:10]
        atom['test_cases']['exception'] = all_exception[:10]

        logger.info(f"[LLM] {func_name} - 最终正常:{len(all_normal)}, 异常:{len(all_exception)}")

    except Exception as e:
        logger.warning(f"[LLM] {func_name} 生成失败: {e}, 保留RATP数据")
        # 保留 RATP 数据

    # 转换为 detail 格式（用于显示）
    normal = atom['test_cases'].get('normal', [])
    exception = atom['test_cases'].get('exception', [])

    if normal:
        atom['test_cases']['normal_detail'] = [{"steps": [s], "expected": []} for s in normal[:5]]
    if exception:
        atom['test_cases']['exception_detail'] = [{"steps": [s], "expected": []} for s in exception[:5]]

    return atom


def expand_module_exceptions(module_data: dict, all_atoms: List[dict] = None) -> dict:
    """
    为每个原子功能生成测试点
    1. 优先使用 RATP 提供的测试用例
    2. 同时调用 RAG+LLM 补充更多异常场景
    优化1: 支持并行 LLM 处理

    Args:
        module_data: 模块数据，包含 atoms 和 rag_context
        all_atoms: 完整的 atoms 列表，用于让 LLM 了解整体需求上下文
    """
    module_name = module_data['module']
    atoms = module_data['atoms']
    rag_context = module_data.get('rag_context', '')

    # 如果没有传入 all_atoms，使用当前模块的 atoms
    if all_atoms is None:
        all_atoms = atoms

    # 格式化完整的 atoms 信息（用于给 LLM 提供整体上下文）
    all_atoms_info = ""
    for idx, a in enumerate(all_atoms, 1):
        all_atoms_info += f"""
### {idx}. {a.get('function_name', '未知')}
- 模块: {a.get('module', '')}
- 功能ID: {a.get('function_id', '')}
- 业务逻辑: {a.get('business_logic', '')}
- 触发条件: {a.get('trigger_condition', '')}
- 业务规则: {', '.join(a.get('rules', []))}
- 已有测试用例:
  - 正常: {a.get('test_cases', {}).get('normal', [])}
  - 异常: {a.get('test_cases', {}).get('exception', [])}
"""

    # 优化1: 并行处理多个 atoms 的 LLM 扩展
    enriched_atoms = []
    if len(atoms) > 1:
        logger.info(f"[LLM] 并行处理 {len(atoms)} 个原子功能")
        # 使用 ThreadPoolExecutor 并行处理
        with ThreadPoolExecutor(max_workers=min(4, len(atoms))) as pool:
            futures = {pool.submit(expand_single_atom, atom, all_atoms_info): atom for atom in atoms}
            for future in as_completed(futures):
                try:
                    enriched_atom = future.result()
                    enriched_atoms.append(enriched_atom)
                except Exception as e:
                    atom = futures[future]
                    logger.warning(f"[LLM] {atom.get('function_name', '')} 处理失败: {e}")
                    enriched_atoms.append(atom)
    else:
        # 单个 atom 直接处理
        enriched_atoms = [expand_single_atom(atom, all_atoms_info) for atom in atoms]

    # 保持原始顺序
    atom_map = {a.get('function_name', ''): a for a in enriched_atoms}
    enriched_atoms = [atom_map.get(a.get('function_name', ''), a) for a in atoms]

    return {'module': module_name, 'atoms': enriched_atoms, 'rag_context': rag_context}


def parse_detailed_test_cases(result: str) -> dict:
    """解析详细的测试用例结果"""
    import re
    import json

    # 尝试提取 JSON
    json_match = re.search(r'\{[\s\S]*\}', result)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return data
        except:
            pass

    # 如果 JSON 解析失败，尝试解析文本格式
    test_cases = {'normal': [], 'exception': []}

    # 简单解析：查找 "正常场景" 和 "异常场景" 部分
    normal_match = re.search(r'正常场景[：:]*([\s\S]*?)(?=异常场景|边界场景|$)', result, re.IGNORECASE)
    exception_match = re.search(r'异常场景[：:]*([\s\S]*)', result, re.IGNORECASE)

    if normal_match:
        normal_text = normal_match.group(1)
        # 提取步骤
        steps = re.findall(r'\d+[.、]\s*([^\n]+)', normal_text)
        if steps:
            test_cases['normal'] = [{'name': '正常场景', 'steps': steps, 'expected': []}]

    if exception_match:
        exception_text = exception_match.group(1)
        steps = re.findall(r'\d+[.、]\s*([^\n]+)', exception_text)
        if steps:
            test_cases['exception'] = [{'name': '异常场景', 'steps': steps, 'expected': []}]

    return test_cases


def parse_simple_test_cases(result: str) -> dict:
    """解析简化的测试用例（场景描述）"""
    import re
    import json

    test_cases = {'normal': [], 'exception': []}

    # 尝试提取 JSON（改进：支持多行 JSON）
    # 查找 { ... } 块，可能包含多行
    json_match = re.search(r'\{[\s\S]*\}', result)
    if json_match:
        try:
            json_str = json_match.group()
            # 尝试修复常见 JSON 格式问题
            json_str = json_str.strip()
            data = json.loads(json_str)
            # 确保返回格式正确
            normal = data.get('normal', [])
            exception = data.get('exception', [])
            if isinstance(normal, list) and isinstance(exception, list):
                logger.info(f"[Parse] JSON解析成功: normal={len(normal)}, exception={len(exception)}")
                return {
                    'normal': normal,
                    'exception': exception
                }
        except json.JSONDecodeError as e:
            logger.warning(f"[Parse] JSON解析失败: {e}, 尝试文本解析")
        except Exception as e:
            logger.warning(f"[Parse] 解析异常: {e}")

    # 备用：解析文本格式
    logger.info("[Parse] 使用文本格式解析")
    normal_match = re.search(r'正常场景[：:\s]*([\s\S]*?)(?=异常场景|$)', result, re.IGNORECASE)
    exception_match = re.search(r'异常场景[：:\s]*([\s\S]*)', result, re.IGNORECASE)

    if normal_match:
        normal_text = normal_match.group(1)
        # 提取描述（支持多种格式）
        scenarios = re.findall(r'\d+[.、]\s*([^\n]+)', normal_text)
        if not scenarios:
            # 尝试不分编号的格式
            scenarios = [s.strip() for s in normal_text.split('\n') if s.strip()]
        if scenarios:
            test_cases['normal'] = scenarios[:5]
            logger.info(f"[Parse] 文本解析正常场景: {len(scenarios)} 个")

    if exception_match:
        exception_text = exception_match.group(1)
        scenarios = re.findall(r'\d+[.、]\s*([^\n]+)', exception_text)
        if not scenarios:
            scenarios = [s.strip() for s in exception_text.split('\n') if s.strip()]
        if scenarios:
            test_cases['exception'] = scenarios[:5]
            logger.info(f"[Parse] 文本解析异常场景: {len(scenarios)} 个")

    return test_cases


def parse_batch_llm_result(result: str) -> List[dict]:
    """解析批量 LLM 返回结果"""
    import re

    # 尝试提取 JSON 数组
    json_match = re.search(r'\[[\s\S]*\]', result)
    if json_match:
        try:
            data = json.loads(json_match.group())
            if isinstance(data, list):
                return data
        except:
            pass

    return []


# ============ Markdown 生成（详细步骤版） ============

def generate_strategy_markdown(atoms: List[dict]) -> str:
    """生成测试策略 Markdown 格式（包含详细测试步骤和预期结果）"""
    modules = group_atoms_by_module(atoms)

    output = []

    # 标题
    output.append("## 2 测试策略")
    output.append("")
    output.append("### 2.1 功能测试")
    output.append("")
    output.append("根据测试目的及范围，本次功能测试主要验证通道引擎对接，防逃费功能、语音交互等功能是否符合需求规格说明书，产品主流程是否正常，受影响的产品及关联的业务场景是否闭环，遗留缺陷是否修复等。")
    output.append("")

    for module_name, module_atoms in modules.items():
        # 模块标题
        output.append(f"#### {module_name}")
        output.append("")
        output.append("| 序号 | 模块功能项 | 测试方法及说明 |")
        output.append("| ---- | ---------- | -------------- |")

        # 每个原子功能
        for idx, atom in enumerate(module_atoms, 1):
            func_name = atom.get('function_name', '')
            test_desc = format_test_description(atom)
            output.append(f"| {idx} | {func_name} | {test_desc} |")

        output.append("")

    # 2.2 非功能测试部分由 Skill 指导用户手动添加
    # 参考 test-strategy-generator/SKILL.md 中的 2.2 模板

    return '\n'.join(output)


def format_test_description(atom: dict) -> str:
    """
    格式化测试描述
    直接输出场景描述，不添加额外后缀
    """
    test_cases = atom.get('test_cases', {})

    # 优先使用详细版本（已转换为场景描述）
    normal_detail = test_cases.get('normal_detail', [])
    exception_detail = test_cases.get('exception_detail', [])

    # 备用：获取简单列表
    normal = test_cases.get('normal', [])
    exception = test_cases.get('exception', [])

    parts = []

    # 清理函数
    def clean_text(text):
        text = str(text)
        # 去除常见的格式标记
        text = text.replace('预期：', '').replace('**', '').replace('*', '')
        text = text.replace('正常处理', '').replace('异常处理', '')
        # 去除开头的编号如 "1、" 或 "1、"
        import re
        text = re.sub(r'^[\d]+[、，,]\s*', '', text)
        return text.strip('，。、 ')

    # 正常场景 - 直接使用完整描述
    if normal_detail:
        normal_scenarios = []
        for tc in normal_detail[:10]:
            steps = tc.get('steps', [])
            expected = tc.get('expected', [])
            # 直接组合步骤和预期作为完整场景
            parts_list = [clean_text(s) for s in steps[:3]]
            parts_list.extend([clean_text(e) for e in expected[:3]])
            scenario = '，'.join([p for p in parts_list if p])
            if scenario and scenario not in normal_scenarios:
                normal_scenarios.append(scenario)
        if normal_scenarios:
            normal_str = '<br>'.join([f"{i+1}、{s}" for i, s in enumerate(normal_scenarios)])
            parts.append(f"**正常场景：**<br>{normal_str}")
    elif normal:
        # 清理每个场景描述
        normal_str = '<br>'.join([f"{i+1}、{clean_text(t)}" for i, t in enumerate(normal[:10])])
        parts.append(f"**正常场景：**<br>{normal_str}")

    # 异常场景 - 直接使用完整描述
    if exception_detail:
        exception_scenarios = []
        for tc in exception_detail[:10]:
            steps = tc.get('steps', [])
            expected = tc.get('expected', [])
            parts_list = [clean_text(s) for s in steps[:3]]
            parts_list.extend([clean_text(e) for e in expected[:3]])
            scenario = '，'.join([p for p in parts_list if p])
            if scenario and scenario not in exception_scenarios:
                exception_scenarios.append(scenario)
        if exception_scenarios:
            exception_str = '<br>'.join([f"{i+1}、{s}" for i, s in enumerate(exception_scenarios)])
            parts.append(f"**异常场景：**<br>{exception_str}")
    elif exception:
        exception_str = '<br>'.join([f"{i+1}、{clean_text(t)}" for i, t in enumerate(exception[:10])])
        parts.append(f"**异常场景：**<br>{exception_str}")

    return '<br><br>'.join(parts) if parts else "待补充"


# ============ 优化3: 异步任务处理 ============

def process_test_strategy_async(task_id: str, atoms: List[dict]):
    """异步处理测试策略生成"""
    try:
        logger.info(f"="*60)
        logger.info(f"[MCP-{task_id}] 异步任务开始处理")
        logger.info(f"[MCP-{task_id}] 原子功能数量: {len(atoms)}")
        logger.info(f"[MCP-{task_id}] 模块列表: {list(set(a.get('module', '其他') for a in atoms))}")

        # Step 1: 批量 RAG 检索
        logger.info(f"[MCP-{task_id}] ========== Step 1: RAG 检索 ==========")
        enriched_modules = enrich_atoms_by_module(atoms)

        # 统计 RAG 检索结果
        rag_stats = {}
        for module_name in enriched_modules:
            rag_context = enriched_modules[module_name].get('rag_context', '')
            rag_stats[module_name] = len(rag_context)
            if rag_context:
                # 显示前200字符作为样例
                sample = rag_context[:200].replace('\n', ' ')
                logger.info(f"[MCP-{task_id}] ✓ 模块 '{module_name}' RAG 检索成功 (长度: {len(rag_context)})")
                logger.info(f"[MCP-{task_id}]   样例: {sample}...")
            else:
                logger.warning(f"[MCP-{task_id}] ✗ 模块 '{module_name}' RAG 检索无结果")
        logger.info(f"[MCP-{task_id}] RAG 统计: {rag_stats}")

        # Step 2: LLM 为每个原子功能生成详细测试用例
        logger.info(f"[MCP-{task_id}] ========== Step 2: LLM 生成详细测试用例 ==========")
        logger.info(f"[MCP-{task_id}] 注意: 每个原子功能单独调用LLM，预计需要 {len(atoms)} 次调用，请耐心等待...")
        final_modules = {}
        for module_name, module_data in enriched_modules.items():
            expanded = expand_module_exceptions(module_data, all_atoms=atoms)
            final_modules[module_name] = expanded
            # 统计每个模块的测试点数量
            atom_count = len(module_data.get('atoms', []))
            total_normal = sum(len(a.get('test_cases', {}).get('normal', [])) for a in module_data.get('atoms', []))
            total_exception = sum(len(a.get('test_cases', {}).get('exception', [])) for a in module_data.get('atoms', []))

            # 统计详细测试用例数量
            detailed_normal = sum(len(a.get('test_cases', {}).get('normal_detail', [])) for a in module_data.get('atoms', []))
            detailed_exception = sum(len(a.get('test_cases', {}).get('exception_detail', [])) for a in module_data.get('atoms', []))

            logger.info(f"[MCP-{task_id}] ✓ 模块 '{module_name}' 推导完成 (正常:{total_normal}, 异常:{total_exception}, 详细用例:{detailed_normal+detailed_exception})")

        # 收集所有 atoms
        all_atoms = []
        for module_data in final_modules.values():
            all_atoms.extend(module_data.get('atoms', []))

        # Step 3: 生成 Markdown
        logger.info(f"[MCP-{task_id}] ========== Step 3: 生成 Markdown ==========")

        # 统计总体测试点
        total_normal = sum(len(a.get('test_cases', {}).get('normal', [])) for a in all_atoms)
        total_exception = sum(len(a.get('test_cases', {}).get('exception', [])) for a in all_atoms)
        logger.info(f"[MCP-{task_id}] 汇总: {len(all_atoms)} 个功能, {total_normal} 个正常场景, {total_exception} 个异常场景")

        test_strategy = generate_strategy_markdown(all_atoms)

        # 保存到文件
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', TEST_STRATEGIES_DIR)
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f'test_strategy_{timestamp}.md')
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(test_strategy)
        logger.info(f"[MCP-{task_id}] ✓ 测试策略已保存到: {output_file}")

        # 保存结果
        # 优化5: 获取 Token 统计
        token_stats = get_token_stats()
        _async_tasks[task_id] = {
            'status': 'completed',
            'result': test_strategy,
            'atom_count': len(atoms),
            'stats': {
                'modules': len(enriched_modules),
                'total_normal': total_normal,
                'total_exception': total_exception,
                'rag_stats': rag_stats,
                'token_stats': token_stats
            },
            'output_file': output_file
        }
        logger.info(f"[MCP-{task_id}] ✓ 任务完成! Markdown 长度: {len(test_strategy)} 字符")
        logger.info(f"[MCP-{task_id}] ✓ Token统计: input={token_stats['total_input_tokens']}, output={token_stats['total_output_tokens']}, 调用次数={token_stats['llm_call_count']}")
        logger.info(f"="*60)

    except Exception as e:
        logger.error(f"[MCP-{task_id}] ✗ 任务失败: {e}")
        _async_tasks[task_id] = {
            'status': 'failed',
            'error': str(e)
        }


# ============ API 端点 ============

@mcp_bp.route('/generate-test-strategy', methods=['POST'])
def generate_test_strategy():
    """
    同步接口：接收 ratp_output.json，生成测试策略
    简化版本，跳过 RAG 和 LLM 扩展，直接生成 Markdown
    """
    try:
        data = request.json
        atoms = data.get('atoms', [])

        if not atoms:
            return jsonify({
                "success": False,
                "error": "atoms 不能为空"
            }), 400

        logger.info(f"="*50)
        logger.info(f"[MCP] 开始生成测试策略，共 {len(atoms)} 个原子功能")
        logger.info(f"[MCP] 模式: sync (跳过RAG/LLM)")

        # 直接生成 Markdown（使用已有的 test_cases）
        test_strategy = generate_strategy_markdown(atoms)

        logger.info(f"[MCP] 测试策略生成完成，共 {len(atoms)} 个功能")
        logger.info(f"[MCP] 如需调用 RAG 检索知识库，请使用异步接口 /generate-test-strategy-async")
        logger.info(f"="*50)

        return jsonify({
            "success": True,
            "data": test_strategy,
            "atom_count": len(atoms),
            "mode": "sync",
            "note": "同步模式跳过RAG，如需RAG检索请使用异步接口"
        })

    except Exception as e:
        logger.error(f"生成测试策略失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@mcp_bp.route('/generate-test-strategy-async', methods=['POST'])
def generate_test_strategy_async_api():
    """
    异步接口：接收 ratp_output.json，后台处理
    """
    try:
        data = request.json
        atoms = data.get('atoms', [])

        if not atoms:
            return jsonify({
                "success": False,
                "error": "atoms 不能为空"
            }), 400

        # 创建任务
        task_id = str(uuid.uuid4())[:8]
        _async_tasks[task_id] = {'status': 'processing'}

        # 提交异步任务
        _executor.submit(process_test_strategy_async, task_id, atoms)

        logger.info(f"异步任务 {task_id} 已提交")

        return jsonify({
            "success": True,
            "task_id": task_id,
            "status": "processing",
            "message": "任务已提交，请使用 task_id 查询结果"
        })

    except Exception as e:
        logger.error(f"提交异步任务失败: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@mcp_bp.route('/task/<task_id>', methods=['GET'])
def get_task_status(task_id: str):
    """查询异步任务状态"""
    task = _async_tasks.get(task_id)

    if not task:
        return jsonify({
            "success": False,
            "error": "任务不存在"
        }), 404

    if task['status'] == 'completed':
        return jsonify({
            "success": True,
            "status": "completed",
            "result": task['result'],
            "atom_count": task.get('atom_count', 0),
            "stats": task.get('stats', {}),
            "output_file": task.get('output_file', '')
        })
    elif task['status'] == 'failed':
        return jsonify({
            "success": False,
            "status": "failed",
            "error": task.get('error', '未知错误')
        })
    else:
        return jsonify({
            "success": True,
            "status": "processing"
        })


@mcp_bp.route('/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({"status": "ok"})


@mcp_bp.route('/token-stats', methods=['GET'])
def get_token_stats_api():
    """
    优化5: 获取 Token 消耗统计
    """
    stats = get_token_stats()
    return jsonify({
        "success": True,
        "stats": stats
    })


@mcp_bp.route('/token-stats/reset', methods=['POST'])
def reset_token_stats_api():
    """
    优化5: 重置 Token 消耗统计
    """
    reset_token_stats()
    return jsonify({
        "success": True,
        "message": "Token 统计已重置"
    })


@mcp_bp.route('/routes', methods=['GET'])
def list_routes():
    """列出所有路由（调试用）"""
    from flask import current_app
    routes = []
    for rule in current_app.url_map.iter_rules():
        if 'mcp' in str(rule):
            routes.append(f"{rule.rule} -> {rule.endpoint}")
    return jsonify({"routes": routes})


# 注册路由
def register_mcp_routes(app):
    """注册 MCP 路由到 Flask 应用"""
    app.register_blueprint(mcp_bp)
    logger.info("MCP 路由已注册")
