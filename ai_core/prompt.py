# -*- coding: utf-8 -*-
"""
AI核心层 - 提示工程模块
已优化：移除机械化标题，增强自然语言过渡，删除冗余建议部分
"""
import logging
from typing import List
import re

logger = logging.getLogger(__name__)

# 测试相关查询关键词
TEST_QUERY_KEYWORDS = ["如何测试", "测试用例", "生成用例", "怎么测", "测试步骤", "测试项", "测试方法", "测试"]

class PromptTemplate:
    """提示模板"""

    # 优化后的测试输出格式 - 模拟真实专家对话感
    TEST_CASE_TEMPLATE = """你是一名资深的高级测试工程师。请直接回答用户的测试需求。

【交互要求】
1. **自然开场**：不要使用"第一部分"、"思路如下"之类的标题。请用 1-2 句专业的话直接切入主题。
2. **用例展示**：直接列出测试用例，格式必须严谨，方便阅读。
3. **禁止冗余**：不要输出"专家建议"、"小贴士"或"总结"等画蛇添足的内容。
4. **禁止提及来源**：不要提及"根据文档"、"来源于"、"参考信息"等任何关于来源的表述。

【重要格式规范】
- **必须使用Markdown表格**展示测试场景，表格头使用英文竖线 `|` 分隔，例如：`| 测试场景 | 测试目的 | 测试步骤 | 验证重点 |`
- **禁止**使用中文竖线或其他字符替代英文竖线
- 表格分隔线必须使用英文 `-` 符号，例如：`|---|---|---|---|`
- 禁止使用列表（如1. 2. 或*）形式输出测试场景，必须全部使用表格

【用例标准格式】
用例名称: xxx
前置条件: xxx
步骤:
1.
2.
预期:
1.
优先级: P1/P2

---
相关上下文：
{context}

用户问题：{query}

请开始你的回答："""

    # 角色设定
    ROLE_SYSTEM = "你是一名专业的高级测试工程师，擅长结合业务文档编写高质量的测试用例。"

    def __init__(self, template: str = None):
        self.template = template or self.TEST_CASE_TEMPLATE

    def format(self, **kwargs) -> str:
        """格式化模板"""
        return self.template.format(**kwargs)

    def is_test_query(self, query: str) -> bool:
        """判断是否为测试相关查询"""
        for keyword in TEST_QUERY_KEYWORDS:
            if keyword in query:
                return True
        return False

    def format_test_response(self, text: str) -> str:
        """
        格式化测试回答：
        确保用例核心字段前的换行，增加可读性，同时过滤掉可能出现的机械标题。
        """
        if not text:
            return text

        # 修复markdown表格格式异常：{| → |
        text = text.replace("{|", "|")

        # 过滤可能出现的机械标题（防止模型复发）
        text = re.sub(r'【?第[一二三]部分.*】?', '', text)
        text = re.sub(r'思路与开场[:：]?', '', text)
        text = re.sub(r'专家建议[:：]?', '', text)
        # 移除"根据参考信息"等来源提示
        text = re.sub(r'根据[\u4e00-\u9fa5]+[:：]?', '', text)
        text = re.sub(r'参考[\u4e00-\u9fa5]+[:：]?', '', text)

        # 检测并分隔表格和详细用例内容
        # 如果表格后面紧跟着用例名称，需要在它们之间添加分隔
        lines = text.split('\n')
        result = []
        prev_was_table_sep = False  # 上一行是否是表格分隔线

        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                result.append("")
                prev_was_table_sep = False
                continue

            # 检测表格分隔线（如 |---|---|---|）
            if re.match(r'\|[\s\-:|]+\|', line):
                prev_was_table_sep = True
                result.append(line)
                continue

            # 如果上一行是表格分隔线，且当前行不是表格内容开头，
            # 且当前行是用例相关内容，则添加分隔
            if prev_was_table_sep and not line.startswith('|'):
                # 检测是否是新的用例内容开始
                if line.startswith("用例名称") or line.startswith("**用例名称"):
                    result.append("\n" + line)
                    prev_was_table_sep = False
                    continue

            # 在每个用例名称前增加空行，提升视觉区分度
            if line.startswith("用例名称") or line.startswith("**用例名称"):
                result.append("\n" + line)
            elif any(line.startswith(k) for k in ["前置条件", "步骤", "预期", "优先级", "用例名称"]):
                result.append(line)
            else:
                result.append(line)

            # 重置表格分隔线状态（当遇到非表格相关内容后）
            if not prev_was_table_sep and not line.startswith('|'):
                prev_was_table_sep = False

        return '\n'.join(result).strip()

    @classmethod
    def test_case_prompt(cls, query: str, contexts: List[str]) -> str:
        """生成测试用例的初始提示"""
        context_text = "\n\n---\n\n".join([
            f"相关文档片段 {i+1}:\n{ctx[:800]}"
            for i, ctx in enumerate(contexts)
        ])

        return cls.TEST_CASE_TEMPLATE.format(
            context=context_text,
            query=query
        )

    @classmethod
    def build_continuation_prompt(cls, query: str, previous_query: str, contexts: List[str]) -> str:
        """构建追问的 Prompt"""
        context_text = "\n\n---\n\n".join([
            f"参考文档:\n{ctx[:800]}"
            for ctx in contexts[:3]
        ])

        return f"""你是一名高级测试工程师。请结合上下文和追问需求，继续补充或细化测试方案。
要求：
1. 不要使用机械的标题，直接用自然语言衔接。
2. 保持用例格式：用例名称、前置条件、步骤、预期、优先级。
3. 移除所有无关的建议和总结。

之前的讨论：{previous_query}
用户的追问：{query}

参考文档：
{context_text}

请开始你的回答："""

# 全局提示模板
prompt_template = PromptTemplate()
