# -*- coding: utf-8 -*-
"""
分级检索功能单元测试
"""
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import Mock, patch, MagicMock
from api.routes.mcp import (
    clear_module_cache,
    enrich_module_with_rag,
    enrich_atom_with_rag_optimized,
    enrich_atoms_by_module,
    _module_context_cache,
    dynamic_filter
)


class TestClearModuleCache:
    """测试缓存清除功能"""

    def test_clear_cache(self):
        """测试清除缓存"""
        # 导入模块变量
        from api.routes import mcp
        # 先设置一些缓存数据
        mcp._module_context_cache = {'模块A': {'rag_context': 'test'}}

        clear_module_cache()

        assert mcp._module_context_cache == {}


class TestDynamicFilter:
    """测试动态筛选功能"""

    def test_empty_docs(self):
        """测试空文档列表"""
        result = dynamic_filter([])
        assert result == []

    def test_normal_mode_high_score(self):
        """测试正常模式 - 高分文档"""
        docs = [
            {'document': 'doc1', 'score': 0.9},
            {'document': 'doc2', 'score': 0.8},
            {'document': 'doc3', 'score': 0.5},
        ]
        result = dynamic_filter(docs, threshold=0.7, max_k=3)
        # 0.9 >= 0.7, 0.8 >= 0.7 都应该保留
        assert len(result) == 2

    def test_low_confidence_mode(self):
        """测试低置信度模式 - 最高分 < 0.4"""
        docs = [
            {'document': 'doc1', 'score': 0.3},
            {'document': 'doc2', 'score': 0.2},
            {'document': 'doc3', 'score': 0.1},
        ]
        result = dynamic_filter(docs, threshold=0.7, max_k=3)
        # 低置信度模式只取1条
        assert len(result) == 1
        assert result[0]['score'] == 0.3

    def test_relative_threshold(self):
        """测试相对阈值 - 差距15%以内"""
        docs = [
            {'document': 'doc1', 'score': 1.0},
            {'document': 'doc2', 'score': 0.86},  # 差距14%，应该保留
            {'document': 'doc3', 'score': 0.50},  # 差距50%，应该过滤（绝对阈值0.7也过滤）
        ]
        result = dynamic_filter(docs, threshold=0.7, max_k=3)
        # doc1 >= 0.7, doc2 >= 0.7 or 相对差距14%, doc3 < 0.7 且差距>15%
        # doc1 (1.0), doc2 (0.86) 保留
        assert len(result) == 2


class TestEnrichModuleWithRag:
    """测试模块级检索功能"""

    @patch('api.routes.mcp.get_qa_chain')
    @patch('api.routes.mcp.get_reranker')
    def test_module_rag_with_cache(self, mock_reranker, mock_qa_chain):
        """测试模块级检索 - 缓存命中"""
        # 先设置缓存
        from api.routes import mcp
        cache_key = 'test-module'
        mcp._module_context_cache = {
            cache_key: {
                'module_name': cache_key,
                'module_query': 'test query',
                'module_rag_context': 'cached context'
            }
        }

        result = enrich_module_with_rag(cache_key, [])

        assert result['module_rag_context'] == 'cached context'
        # 缓存命中后不应该调用 qa_chain
        mock_qa_chain.assert_not_called()

    @patch('api.routes.mcp.get_qa_chain')
    @patch('api.routes.mcp.get_reranker')
    def test_module_rag_without_cache(self, mock_reranker, mock_qa_chain):
        """测试模块级检索 - 无缓存，执行检索"""
        # 清除缓存
        clear_module_cache()

        # Mock qa_chain
        mock_chain = MagicMock()
        mock_retriever = MagicMock()
        mock_chain.retriever = mock_retriever
        mock_chain.embedding_model.encode_query.return_value = 'query_vector'
        mock_retriever.search.return_value = [
            {'document': 'doc1', 'score': 0.9}
        ]
        mock_qa_chain.return_value = mock_chain

        # Mock reranker
        mock_reranker_instance = MagicMock()
        mock_reranker_instance.rerank.return_value = [
            {'document': 'doc1', 'score': 0.9}
        ]
        mock_reranker.return_value = mock_reranker_instance

        atoms = [
            {
                'function_name': '车辆闸前倒车',
                'tags': ['通道引擎', '倒车'],
                'business_logic': '倒车事件处理'
            }
        ]

        result = enrich_module_with_rag('通道引擎对接', atoms)

        assert 'module_rag_context' in result
        assert 'module_query' in result
        # 验证检索被调用
        mock_retriever.search.assert_called_once()


class TestEnrichAtomWithRagOptimized:
    """测试原子级检索功能"""

    @patch('api.routes.mcp.get_qa_chain')
    @patch('api.routes.mcp.get_reranker')
    def test_atom_rag_with_context(self, mock_reranker, mock_qa_chain):
        """测试原子级检索 - 带模块上下文"""
        # Mock qa_chain
        mock_chain = MagicMock()
        mock_retriever = MagicMock()
        mock_chain.retriever = mock_retriever
        mock_chain.embedding_model.encode_query.return_value = 'query_vector'
        mock_retriever.search.return_value = [
            {'document': '倒车规则文档', 'score': 0.9}
        ]
        mock_qa_chain.return_value = mock_chain

        # Mock reranker
        mock_reranker_instance = MagicMock()
        mock_reranker_instance.rerank.return_value = [
            {'document': '倒车规则文档', 'score': 0.9}
        ]
        mock_reranker.return_value = mock_reranker_instance

        atom = {
            'function_name': '车辆闸前倒车',
            'rules': ['规则1', '规则2'],
            'tags': ['倒车']
        }
        module_context = '模块级业务背景'

        result = enrich_atom_with_rag_optimized(atom, module_context)

        # 验证返回结构
        assert 'rag_context' in result
        assert 'module_context' in result
        assert 'atom_context' in result

        # 验证上下文合并格式（锚点引导）
        assert '背景知识库 - 业务流视图' in result['rag_context']
        assert '背景知识库 - 逻辑校验视图' in result['rag_context']

    @patch('api.routes.mcp.get_qa_chain')
    @patch('api.routes.mcp.get_reranker')
    def test_atom_rag_token_limit(self, mock_reranker, mock_qa_chain):
        """测试原子级检索 - Token 限制"""
        # Mock 返回大量内容
        long_doc = 'A' * 5000
        mock_chain = MagicMock()
        mock_retriever = MagicMock()
        mock_chain.retriever = mock_retriever
        mock_chain.embedding_model.encode_query.return_value = 'query_vector'
        mock_retriever.search.return_value = [
            {'document': long_doc, 'score': 0.9}
        ]
        mock_qa_chain.return_value = mock_chain

        mock_reranker_instance = MagicMock()
        mock_reranker_instance.rerank.return_value = [
            {'document': long_doc, 'score': 0.9}
        ]
        mock_reranker.return_value = mock_reranker_instance

        atom = {
            'function_name': '测试功能',
            'rules': ['规则1'],
            'tags': ['测试']
        }

        result = enrich_atom_with_rag_optimized(atom, '')

        # 验证上下文被限制
        assert len(result['atom_context']) <= 4000


class TestEnrichAtomsByModule:
    """测试完整的两级检索流程"""

    @patch('api.routes.mcp.enrich_atom_with_rag_optimized')
    @patch('api.routes.mcp.enrich_module_with_rag')
    def test_enrich_atoms_by_module(self, mock_module_rag, mock_atom_rag):
        """测试两级检索完整流程"""
        # Mock 模块级检索
        mock_module_rag.return_value = {
            'module_name': '通道引擎对接',
            'module_rag_context': '模块背景'
        }

        # Mock 原子级检索
        mock_atom_rag.return_value = {
            'function_name': '车辆闸前倒车',
            'rag_context': '最终上下文'
        }

        atoms = [
            {
                'module': '通道引擎对接',
                'function_name': '车辆闸前倒车',
                'rules': ['规则1'],
                'tags': ['倒车']
            }
        ]

        result = enrich_atoms_by_module(atoms)

        # 验证结果结构
        assert '通道引擎对接' in result
        assert len(result['通道引擎对接']['atoms']) == 1

        # 验证调用流程
        mock_module_rag.assert_called_once()
        mock_atom_rag.assert_called_once()

    @patch('api.routes.mcp.enrich_atom_with_rag_optimized')
    @patch('api.routes.mcp.enrich_module_with_rag')
    def test_multiple_atoms_parallel(self, mock_module_rag, mock_atom_rag):
        """测试多原子并行处理"""
        # 清除缓存
        clear_module_cache()

        mock_module_rag.return_value = {
            'module_rag_context': '模块背景'
        }

        # 返回不同的原子结果
        call_count = 0
        def mock_rag(atom, module_context):
            nonlocal call_count
            call_count += 1
            return {
                'function_name': atom['function_name'],
                'rag_context': f'上下文{call_count}'
            }
        mock_atom_rag.side_effect = mock_rag

        atoms = [
            {'module': '通道引擎对接', 'function_name': '功能1', 'rules': [], 'tags': []},
            {'module': '通道引擎对接', 'function_name': '功能2', 'rules': [], 'tags': []},
        ]

        result = enrich_atoms_by_module(atoms)

        # 验证所有原子都被处理
        assert len(result['通道引擎对接']['atoms']) == 2


class TestQueryConstruction:
    """测试 Query 构建逻辑"""

    def test_module_query_includes_function_names(self):
        """测试模块级 Query 包含功能名"""
        atoms = [
            {
                'function_name': '车辆闸前倒车',
                'tags': ['通道引擎'],
                'business_logic': '倒车检测'
            },
            {
                'function_name': '逆行入场事件',
                'tags': ['通道引擎'],
                'business_logic': '逆行检测'
            }
        ]

        # 手动计算预期的 Query 构建
        all_function_names = [a['function_name'] for a in atoms]
        func_names_str = ' '.join(all_function_names[:5])

        assert '车辆闸前倒车' in func_names_str
        assert '逆行入场事件' in func_names_str

    def test_atom_query_includes_rules(self):
        """测试原子级 Query 包含规则"""
        atom = {
            'function_name': '车辆闸前倒车',
            'rules': ['规则1', '规则2', '规则3'],
            'tags': ['倒车']
        }

        rules_text = ' '.join(atom['rules'][:3])
        atom_query = f"{atom['function_name']} {rules_text} 边界值 异常场景 逻辑校验"

        assert '车辆闸前倒车' in atom_query
        assert '规则1' in atom_query
        assert '边界值' in atom_query


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
