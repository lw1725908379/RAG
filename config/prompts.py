# -*- coding: utf-8 -*-
"""
Prompt 模板配置 - 只保留用例检索
"""
import logging
import re

logger = logging.getLogger(__name__)


def format_test_response(text: str) -> str:
    """
    格式化测试相关回答为标准格式
    从 LLM 输出中提取结构化信息
    """
    if not text:
        return text

    # 如果已经包含标准格式，直接返回
    if re.search(r'用例名称:', text) and re.search(r'前置条件:', text):
        return text

    # 否则尝试格式化
    lines = text.split('\n')
    result = []
    current_section = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 检测章节标题
        if '用例名称' in line or re.match(r'^[#\-*]?\s*用例', line):
            current_section = '用例名称'
            result.append(line)
        elif '前置条件' in line or re.match(r'^[#\-*]?\s*前置', line):
            current_section = '前置条件'
            result.append(line)
        elif '步骤' in line or re.match(r'^[#\-*]?\s*步骤', line):
            current_section = '步骤'
            result.append('\n步骤:')
        elif '预期' in line or re.match(r'^[#\-*]?\s*预期', line):
            current_section = '预期'
            result.append('\n预期:')
        elif '优先级' in line or re.match(r'^[#\-*]?\s*优先级', line):
            current_section = '优先级'
            result.append(line)
        elif current_section == '步骤' and re.match(r'^\d+[\.、]', line):
            result.append(line)
        elif current_section == '预期' and re.match(r'^\d+[\.、]', line):
            result.append(line)
        else:
            result.append(line)

    return '\n'.join(result)


# ===== Prompt 模板 =====
PROMPTS = {
    # 测试相关查询 prompt - 强制结构化输出
    "test_query": """你是一名高级测试工程师。请基于以下参考文档，按标准格式输出测试用例。

【重要】必须严格按以下格式输出，不要输出任何其他内容：

用例名称:{测试项名称}
前置条件:{详细的前置条件描述}
步骤:
1. 第一步操作
2. 第二步操作
3. 第三步操作
预期:
1. 第一个预期结果
2. 第二个预期结果
优先级:P1

【关键要求】
- 每个用例都要包含：用例名称、前置条件、步骤(至少2步)、预期(至少1条)、优先级
- 步骤用1.2.3.序号排列
- 预期用1.2.3.序号排列
- 如果有多个用例，每个用例按上述格式独立输出
- 不要输出"详细说明"、"注意事项"等其他内容

参考文档：
{context}

用户问题：{query}

请按格式输出：""",

    # 用例库 prompt - 关注测试步骤和预期结果
    "use_cases": """你是一个专业的测试用例分析助手。请基于以下测试用例文档回答用户问题。

要求：
1. 重点关注测试步骤、前置条件、预期结果
2. 如果文档中有相关的测试用例，请详细说明测试流程
3. 如果没有找到相关测试用例，如实说明

参考文档：
{context}

用户问题：{query}

请提供详细的回答：""",

    # 默认 prompt
    "default": """基于以下参考文档回答用户问题。如果文档中没有相关信息，请如实说明。

参考文档：
{context}

用户问题：{query}

回答："""
}


# ===== Query 意图分类 =====
QUERY_TYPES = {
    # 测试相关查询 - 优先使用结构化输出
    "test": ["如何测试", "测试用例", "生成用例", "怎么测", "测试步骤", "测试项", "测试方法", "测试"],
}


def classify_query(query: str) -> str:
    """根据查询内容分类返回合适的 prompt 类型"""
    # 优先检查测试相关查询（优先级最高）
    for keyword in QUERY_TYPES["test"]:
        if keyword in query:
            return "test_query"

    return "use_cases"  # 默认使用用例库


def select_prompt(docs: list, query: str = "") -> str:
    """根据检索结果和查询内容选择合适的 prompt 模板"""
    if not docs:
        logger.debug("Prompt选择: 无文档，返回默认模板")
        return PROMPTS["default"]

    # 如果有查询内容，先进行意图分类
    if query:
        query_type = classify_query(query)
        logger.debug(f"Prompt选择: 查询意图分类结果 = {query_type}")

        # 测试相关查询，使用结构化输出
        if query_type == "test_query" and "test_query" in PROMPTS:
            logger.info(f"Prompt选择: 测试查询，使用 test_query 模板")
            return PROMPTS["test_query"]

    # 判断知识库类型 - 只使用用例库
    if "use_cases" in PROMPTS:
        logger.info(f"Prompt选择: 使用用例库模板")
        return PROMPTS["use_cases"]

    return PROMPTS["default"]
