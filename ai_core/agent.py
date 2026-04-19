# -*- coding: utf-8 -*-
"""
AI核心层 - ReAct Agent控制器
实现推理-行动循环模式
"""
import logging
import json
import re
from typing import Dict, Any, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class AgentAction(str, Enum):
    """Agent可执行的行动"""
    RETRIEVE = "retrieve"      # 检索知识库
    SEARCH_WEB = "search"     # 外部搜索
    SQL_QUERY = "sql"         # SQL查询
    REFLECT = "reflect"       # 反思/改写查询
    CLARIFY = "clarify"       # 澄清问题
    ANSWER = "answer"         # 生成最终答案
    ASK_USER = "ask"          # 询问用户


class AgentThought:
    """Agent推理结果"""

    def __init__(
        self,
        thought: str,
        action: str,
        action_input: Dict[str, Any],
        observation: str = None
    ):
        self.thought = thought      # 思考过程
        self.action = action        # 行动类型
        self.action_input = action_input  # 行动参数
        self.observation = observation  # 观察结果

    def to_dict(self) -> Dict:
        return {
            "thought": self.thought,
            "action": self.action,
            "action_input": self.action_input,
            "observation": self.observation
        }


class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self.tools: Dict[str, Any] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        """注册默认工具"""
        # RAG工具在运行时注册
        pass

    def register(self, name: str, tool: Any):
        """注册工具"""
        self.tools[name] = tool
        logger.info(f"已注册工具: {name}")

    def get(self, name: str) -> Optional[Any]:
        """获取工具"""
        return self.tools.get(name)

    def list_tools(self) -> List[str]:
        """列出所有工具"""
        return list(self.tools.keys())

    def get_schemas(self) -> List[Dict]:
        """获取工具的JSON Schema"""
        schemas = []
        for name, tool in self.tools.items():
            if hasattr(tool, 'get_schema'):
                schema = tool.get_schema()
                schema["name"] = name
                schemas.append(schema)
        return schemas


class ReActAgent:
    """
    ReAct模式Agent控制器

    核心循环:
    1. Thought: LLM分析当前情况
    2. Action: LLM决定下一步行动
    3. Observation: 执行行动获取结果
    4. 判断是否完成或继续
    """

    def __init__(
        self,
        llm,
        tools: ToolRegistry = None,
        max_steps: int = 5,
        verbose: bool = True,
        session_id: str = "default",
        enable_memory: bool = True
    ):
        self.llm = llm
        self.tools = tools or ToolRegistry()
        self.max_steps = max_steps
        self.verbose = verbose
        self.session_id = session_id
        self.enable_memory = enable_memory

        # 初始化记忆模块
        self.memory = None
        if enable_memory:
            self._init_memory()

        # 初始化RAG工具
        self._init_rag_tool()

    def _init_memory(self):
        """初始化记忆模块"""
        try:
            from .memory import get_memory_manager
            self.memory_manager = get_memory_manager()
            self.memory = self.memory_manager.get_session(self.session_id)
            logger.info(f"[Agent] 记忆模块已初始化, 会话: {self.session_id}")
        except Exception as e:
            logger.warning(f"记忆模块初始化失败: {e}")
            self.enable_memory = False

    def _init_rag_tool(self):
        """初始化RAG工具"""
        try:
            from .tool import rag_tool, RAG_TOOL_SCHEMA
            self.rag_tool_func = rag_tool
            self.tools.register("rag", {"func": rag_tool, "schema": RAG_TOOL_SCHEMA})
            logger.info("RAG工具注册成功")
        except Exception as e:
            logger.warning(f"RAG工具初始化失败: {e}")

        # 初始化Memory_Tool
        try:
            from .memory import MemoryTool
            self.memory_tool = MemoryTool()
            self.tools.register("memory", {"func": self.memory_tool, "schema": self.memory_tool.get_schema()})
            logger.info("Memory_Tool注册成功")
        except Exception as e:
            logger.warning(f"Memory_Tool初始化失败: {e}")

    def run(self, query: str, session_id: str = None) -> Dict[str, Any]:
        """
        执行Agent推理

        Args:
            query: 用户问题
            session_id: 会话ID（可选）

        Returns:
            {
                "success": bool,
                "answer": str,           # 最终答案
                "thoughts": List[Dict],  # 推理过程
                "sources": List[str],    # 参考来源
                "clarification": str     # 澄清问题(如有)
            }
        """
        # 更新会话ID
        if session_id:
            self.session_id = session_id
            if self.enable_memory:
                self.memory = self.memory_manager.get_session(session_id)

        # 记录原始查询（用于记忆）
        original_query = query

        # 检查是否为追问
        is_continuation = False
        original_query = query

        if self.enable_memory and self.memory:
            is_continuation = self.memory.is_continuation(query)
            if is_continuation:
                logger.info(f"[Agent] 检测为追问，上轮问题: {self.memory.short_term.get_recent_queries()[-1][:30]}...")

                # 增强查询
                query = self.memory.get_augmented_query(query)
                logger.info(f"[Agent] 增强查询: {query[:50]}...")
        result = {
            "success": False,
            "answer": "",
            "thoughts": [],
            "sources": [],
            "clarification": None,
            "error": None
        }

        context = []  # 推理上下文

        try:
            logger.info(f"[ReAct Agent] 开始处理: {query}")
            logger.debug(f"[Agent] session_id={self.session_id}, enable_memory={self.enable_memory}")

            for step in range(self.max_steps):
                # 1. LLM决策
                thought = self._decide(query, context)

                if self.verbose:
                    logger.info(f"[Step {step+1}] Thought: {thought.thought[:50]}...")
                    logger.info(f"[Step {step+1}] Action: {thought.action}")
                    logger.debug(f"[Step {step+1}] ActionInput: {thought.action_input}")

                # 2. 执行行动
                if thought.action == AgentAction.ANSWER.value:
                    # 生成最终答案
                    answer = self._generate_answer(query, context)
                    result["answer"] = answer
                    result["success"] = True
                    break

                elif thought.action == AgentAction.RETRIEVE.value:
                    # 检索知识库
                    observation = self._execute_rag(thought.action_input.get("query", query))
                    thought.observation = observation
                    context.append(thought.to_dict())

                    # ===== CRAG增强：分析检索质量 =====
                    crag_result = self._analyze_crag_result(observation)

                    if self.verbose:
                        logger.info(f"[CRAG分析] CORRECT={crag_result['correct']}, AMBIGUOUS={crag_result['ambiguous']}, INCORRECT={crag_result['incorrect']}")

                    # 根据CRAG结果决定下一步
                    if crag_result["correct"] >= 2:
                        # 检索质量好，可以生成答案
                        if self.verbose:
                            logger.info("[CRAG] 检索质量良好，准备生成答案")
                        # 不自动生成答案，让LLM决策是否answer

                    elif crag_result["incorrect"] >= crag_result["total"] * 0.6:
                        # 大部分不相关，需要改写重试
                        context.append({
                            "thought": f"CRAG评估显示{crag_result['incorrect']}个文档不相关，需要改写查询",
                            "action": "reflect",
                            "action_input": {"reason": "检索结果不相关"},
                            "observation": f"CORRECT={crag_result['correct']}, INCORRECT={crag_result['incorrect']}"
                        })
                        if self.verbose:
                            logger.info(f"[CRAG] 检索质量差，将改写重试")

                    elif crag_result["ambiguous"] >= crag_result["total"] * 0.8 and crag_result["correct"] < 2:
                        # 大部分模糊(>=80%)且正确文档少于2个，需要澄清
                        clarification = self._generate_clarification(query, observation)
                        context.append({
                            "thought": "检索结果模糊，需要澄清用户意图",
                            "action": "clarify",
                            "action_input": {"question": clarification},
                            "observation": f"AMBIGUOUS={crag_result['ambiguous']}"
                        })
                        # 同时生成答案（基于现有检索结果）
                        result["answer"] = self._generate_answer(query, context)
                        result["clarification"] = clarification
                        result["thoughts"] = context
                        if self.verbose:
                            logger.info(f"[CRAG] 结果模糊但有答案，将澄清: {clarification}")
                        break

                elif thought.action == AgentAction.REFLECT.value:
                    # 反思/改写查询
                    new_query = thought.action_input.get("query", query)
                    observation = f"查询已改写为: {new_query}"
                    thought.observation = observation
                    context.append(thought.to_dict())

                elif thought.action == AgentAction.CLARIFY.value:
                    # 澄清问题
                    result["clarification"] = thought.action_input.get("question", "请提供更多信息")
                    result["thoughts"] = context
                    break

                elif thought.action == AgentAction.ASK_USER.value:
                    # 询问用户
                    result["clarification"] = thought.action_input.get("question", "请提供更多信息")
                    result["thoughts"] = context
                    break

                else:
                    # 未知行动，结束
                    logger.warning(f"未知行动: {thought.action}")
                    break

            # 如果达到最大步数仍未完成
            if not result["success"] and not result["answer"]:
                result["answer"] = self._generate_answer(query, context)
                result["success"] = True

            # 提取参考来源
            for ctx in context:
                if ctx.get("action") == "retrieve" and ctx.get("observation"):
                    obs = ctx["observation"]
                    if isinstance(obs, dict) and obs.get("sources"):
                        result["sources"].extend(obs["sources"][:2])

            result["thoughts"] = context

            # 记录到记忆模块
            if self.enable_memory and self.memory:
                self.memory.add_turn(
                    query=original_query,
                    answer=result.get("answer", ""),
                    metadata={"success": result.get("success", False)}
                )
                logger.info(f"[Agent] 已记录到记忆: {original_query[:30]}...")

            logger.info(f"[ReAct Agent] 完成: 步骤数={len(context)}")

        except Exception as e:
            logger.error(f"[ReAct Agent] 异常: {e}", exc_info=True)
            result["error"] = str(e)

        return result

    def stream_run(self, query: str, session_id: str = None):
        """
        流式执行Agent推理，实时yield事件

        Args:
            query: 用户问题
            session_id: 会话ID（可选）

        Yields:
            dict: 事件对象，包含type和data
        """
        # 更新会话ID
        if session_id:
            self.session_id = session_id
            if self.enable_memory:
                self.memory = self.memory_manager.get_session(session_id)

        original_query = query
        is_continuation = False

        if self.enable_memory and self.memory:
            is_continuation = self.memory.is_continuation(query)
            if is_continuation:
                logger.info(f"[Agent Stream] 检测为追问")
                query = self.memory.get_augmented_query(query)
                yield {"type": "thinking", "data": {"step": 0, "action": "memory", "text": "检测到追问，检索对话历史"}}

        yield {"type": "thinking", "data": {"step": 0, "action": "start", "text": f"开始处理: {query[:20]}..."}}

        context = []
        result = {
            "success": False,
            "answer": "",
            "thoughts": [],
            "sources": [],
            "clarification": None
        }

        try:
            for step in range(self.max_steps):
                # 1. LLM决策
                yield {"type": "thinking", "data": {"step": step + 1, "action": "deciding", "text": "LLM思考中..."}}
                thought = self._decide(query, context)

                yield {"type": "thinking", "data": {
                    "step": step + 1,
                    "action": thought.action,
                    "text": f"决策: {thought.thought[:50]}..."
                }}

                # 2. 执行行动
                if thought.action == AgentAction.ANSWER.value:
                    yield {"type": "thinking", "data": {"step": step + 1, "action": "answering", "text": "生成答案中..."}}
                    answer = self._generate_answer_streaming(query, context)
                    result["answer"] = ""
                    result["success"] = True

                    # 流式输出答案
                    for chunk in answer:
                        result["answer"] += chunk
                        yield {"type": "answer", "data": chunk}

                    # 应用格式化（针对测试查询）
                    from .prompt import PromptTemplate
                    pt = PromptTemplate()
                    if pt.is_test_query(query):
                        formatted = pt.format_test_response(result["answer"])
                        # 发送格式化后的完整答案（替换之前的）
                        yield {"type": "answer", "data": "\n\n" + formatted[len(result["answer"]):]}
                        result["answer"] = formatted

                    yield {"type": "done", "data": {"success": True}}
                    break

                elif thought.action == AgentAction.RETRIEVE.value:
                    search_query = thought.action_input.get("query", query)
                    yield {"type": "thinking", "data": {"step": step + 1, "action": "retrieving", "text": f"检索知识库: {search_query[:20]}..."}}

                    observation = self._execute_rag(search_query)
                    thought.observation = observation
                    context.append(thought.to_dict())

                    # 获取检索结果摘要
                    if isinstance(observation, dict):
                        doc_count = observation.get("doc_count", 0)
                        yield {"type": "thinking", "data": {"step": step + 1, "action": "retrieved", "text": f"检索完成，找到 {doc_count} 个相关文档"}}

                elif thought.action == AgentAction.REFLECT.value:
                    yield {"type": "thinking", "data": {"step": step + 1, "action": "reflecting", "text": "反思查询..."}}
                    context.append(thought.to_dict())

                elif thought.action == AgentAction.CLARIFY.value:
                    clarification = thought.action_input.get("question", "请提供更多信息")
                    yield {"type": "thinking", "data": {"step": step + 1, "action": "clarifying", "text": f"需要澄清: {clarification}"}}

                    answer = self._generate_answer(query, context)
                    result["answer"] = answer
                    result["clarification"] = clarification
                    result["thoughts"] = context
                    yield {"type": "done", "data": {"success": True, "clarification": clarification}}
                    break

                elif thought.action == AgentAction.ASK_USER.value:
                    question = thought.action_input.get("question", "请提供更多信息")
                    yield {"type": "done", "data": {"success": False, "question": question}}
                    break

                else:
                    yield {"type": "thinking", "data": {"step": step + 1, "action": "unknown", "text": f"未知行动: {thought.action}"}}
                    break

            # 如果达到最大步数
            if not result["success"] and not result["answer"]:
                yield {"type": "thinking", "data": {"step": self.max_steps, "action": "final", "text": "达到最大步数，生成答案..."}}
                answer = self._generate_answer_streaming(query, context)
                for chunk in answer:
                    result["answer"] += chunk
                    yield {"type": "answer", "data": chunk}

                # 应用格式化（针对测试查询）
                from .prompt import PromptTemplate
                pt = PromptTemplate()
                if pt.is_test_query(query):
                    formatted = pt.format_test_response(result["answer"])
                    yield {"type": "answer", "data": "\n\n" + formatted[len(result["answer"]):]}
                    result["answer"] = formatted

                yield {"type": "done", "data": {"success": True}}

        except Exception as e:
            logger.error(f"[Agent Stream] 异常: {e}", exc_info=True)
            yield {"type": "error", "data": str(e)}

    def _generate_answer_streaming(self, query: str, context: List[Dict]) -> str:
        """流式生成答案"""
        # 构建提示
        from .prompt import PromptTemplate
        prompt_template = PromptTemplate()

        # 提取上下文
        contexts = []
        for ctx in context:
            obs = ctx.get("observation", "")
            if isinstance(obs, dict):
                docs = obs.get("contexts", [])
                for doc in docs[:3]:
                    contexts.append(doc.get("document", "")[:500])
            elif isinstance(obs, str):
                contexts.append(obs[:500])

        prompt = prompt_template.test_case_prompt(query, contexts)

        # 流式生成
        for chunk in self.llm.stream_generate(prompt):
            yield chunk

    def _decide(self, query: str, context: List[Dict]) -> AgentThought:
        """
        LLM决策下一步行动

        返回格式化的JSON，包含thought、action和action_input
        """
        # 构建上下文描述
        context_str = ""
        if context:
            ctx_lines = []
            for i, ctx in enumerate(context[-3:]):  # 只取最近3轮
                action = ctx.get("action", "unknown")
                obs = ctx.get("observation", "")
                if isinstance(obs, dict):
                    obs = f"检索到{obs.get('doc_count', 0)}个文档"
                ctx_lines.append(f"Step {i+1}: {action} -> {obs[:100]}")
            context_str = "\n".join(ctx_lines)

        # ===== 新增: 检索相关记忆 =====
        memory_context = ""
        if self.enable_memory:
            try:
                # 1. 检索长期记忆（向量检索）
                if hasattr(self, 'memory_tool'):
                    result = self.memory_tool.retrieve(query, top_k=2)
                    memories = result.get("memories", []) if isinstance(result, dict) else result
                    if memories:
                        memory_lines = []
                        for m in memories:
                            if isinstance(m, dict):
                                content = m.get("content", m.get("answer", ""))
                            else:
                                content = str(m)
                            memory_lines.append(f"- 长期记忆: {content[:80]}...")
                        memory_context = "\n相关记忆:\n" + "\n".join(memory_lines)
                        logger.debug(f"[决策] 检索到{len(memories)}条长期记忆")

                # 2. 检索短期记忆（对话历史）- 关键修复
                if hasattr(self, 'memory') and self.memory:
                    # 检查是否是 ConversationMemory 类型
                    if hasattr(self.memory, 'short_term'):
                        short_term = self.memory.short_term
                        if hasattr(short_term, 'get_context'):
                            short_term_context = short_term.get_context()
                            if short_term_context:
                                memory_context += f"\n对话历史:\n{short_term_context}"
                                logger.debug(f"[决策] 检索到短期记忆")

            except Exception as e:
                logger.debug(f"记忆检索失败: {e}")

        # 构建prompt
        prompt = self._build_decision_prompt(query, context_str, memory_context)

        try:
            response = self.llm.generate(prompt)
            return self._parse_decision(response)
        except Exception as e:
            logger.warning(f"决策失败，使用默认: {e}")
            return AgentThought(
                thought="执行检索",
                action=AgentAction.RETRIEVE.value,
                action_input={"query": query}
            )

    def _build_decision_prompt(self, query: str, context: str, memory_context: str = "") -> str:
        """构建决策prompt"""

        available_tools = self.tools.list_tools()
        tools_desc = ", ".join(available_tools) if available_tools else "无"

        prompt = f"""你是一个智能问答Agent。请分析用户问题，决定下一步行动。

**重要背景**：知识库中存储的是**停车场智慧停车系统**的测试用例，包括：设备硬件基础、设备组网、车牌识别、入场出场、收费计费、闸机控制、扫码支付等功能。

**核心规则**：
- 禁止在检索关键词中添加用户问题中未提及的专业术语
- 例如：用户问"跟车"，优先检索"跟车"，不能添加"ACC"、"自动驾驶"等用户未提及的词
- 如果你认为问题有歧义，可以使用clarify询问用户
"""  """
用户问题: {query}
{memory_context}

当前上下文:
{context if context else "无（这是第一轮）"}

可选行动:
- retrieve: 检索知识库获取信息（适用于需要从文档中查找答案的问题）
- reflect: 反思并改写查询（适用于检索结果不相关需要调整关键词）
- clarify: 澄清用户意图（适用于问题有多种理解需要确认）
- ask: 询问用户更多信息（适用于信息不足无法回答）
- answer: 生成最终答案（适用于已有足够信息回答问题）

决策规则:
1. 如果是第一次回答，必须先retrieve获取知识
2. **关键**: retrieve时只能使用用户原始问题中的关键词，禁止添加任何新术语
3. 如果检索结果不相关，使用reflect改写查询后重新retrieve
4. 如果问题有歧义，使用clarify询问用户
5. 如果已有足够信息，使用answer生成答案
6. **重要**: 如果Observation中已经包含了问题的具体答案或测试步骤，请直接选择answer行动，不要重复检索

请以JSON格式输出决策:
{{
    "thought": "简短描述你的思考过程",
    "action": "选择的行动",
    "action_input": {{"行动参数"}}
}}

只输出JSON，不要其他内容。
"""
        return prompt

    def _parse_decision(self, response: str) -> AgentThought:
        """解析LLM决策响应"""
        try:
            # 尝试提取JSON
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())

                # 验证必要字段
                thought = data.get("thought", "分析问题")
                action = data.get("action", AgentAction.RETRIEVE.value)
                action_input = data.get("action_input", {})

                # 验证action有效
                valid_actions = [a.value for a in AgentAction]
                if action not in valid_actions:
                    action = AgentAction.RETRIEVE.value

                return AgentThought(
                    thought=thought,
                    action=action,
                    action_input=action_input
                )
        except Exception as e:
            logger.warning(f"解析决策失败: {e}")

        # 解析失败，默认检索
        return AgentThought(
            thought="执行检索获取信息",
            action=AgentAction.RETRIEVE.value,
            action_input={}
        )

    def _execute_rag(self, query: str) -> Dict[str, Any]:
        """执行RAG检索"""
        try:
            result = self.rag_tool_func(query=query, top_k=5)
            return result
        except Exception as e:
            logger.error(f"RAG执行失败: {e}")
            return {"success": False, "error": str(e), "doc_count": 0}

    def _analyze_crag_result(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析CRAG评估结果

        Returns:
            {
                "correct": int,    # 相关文档数
                "ambiguous": int, # 模糊文档数
                "incorrect": int, # 不相关文档数
                "total": int      # 总数
            }
        """
        # 尝试从observation中提取CRAG信息
        if not isinstance(observation, dict):
            return {"correct": 1, "ambiguous": 0, "incorrect": 0, "total": 1}

        crag = observation.get("crag", {})

        if not crag:
            # 没有CRAG信息，假设全部correct
            doc_count = observation.get("doc_count", 0)
            return {
                "correct": doc_count,
                "ambiguous": 0,
                "incorrect": 0,
                "total": max(doc_count, 1)
            }

        return {
            "correct": crag.get("correct", 0),
            "ambiguous": crag.get("ambiguous", 0),
            "incorrect": crag.get("incorrect", 0),
            "total": crag.get("correct", 0) + crag.get("ambiguous", 0) + crag.get("incorrect", 0)
        }

    def _generate_clarification(self, query: str, observation: Dict[str, Any]) -> str:
        """
        根据检索结果模糊性生成澄清问题
        """
        # 从observation中提取关键词
        keywords = observation.get("keywords", [])
        query_type = observation.get("query_type", "")

        # 基于query_type生成澄清问题
        clarification_templates = {
            "测试方法": [
                "您是指功能测试、性能测试还是接口测试？",
                "您想了解哪个具体场景的测试方法？"
            ],
            "流程说明": [
                "您想了解完整的流程还是某个特定环节？",
                "这是针对哪个系统或模块的流程？"
            ],
            "对比分析": [
                "您想对比哪两个选项？",
                "您更关注价格、功能还是其他方面？"
            ],
            "异常处理": [
                "您遇到的具体错误信息是什么？",
                "这是发生在哪个操作环节？"
            ],
            "概念咨询": [
                "您是想了解基本概念还是具体实现？",
                "您是在什么场景下遇到这个问题？"
            ]
        }

        templates = clarification_templates.get(query_type, [
            "您能提供更多具体信息吗？",
            "您是指...还是...?"
        ])

        # 如果有关键词，结合生成
        if keywords:
            return f"您关于【{keywords[0] if keywords else query}】的问题，具体是指{templates[0]}"

        return templates[0]

    def _generate_answer(self, query: str, context: List[Dict]) -> str:
        """基于上下文生成最终答案"""
        # 收集所有检索结果
        contexts = []
        for ctx in context:
            if ctx.get("action") == "retrieve" and ctx.get("observation"):
                obs = ctx["observation"]
                if isinstance(obs, dict):
                    answer = obs.get("answer", "")
                    if answer:
                        contexts.append(answer)

        if not contexts:
            # 无检索结果，使用通用回答
            prompt = f"""用户问题: {query}

请根据你的知识回答这个问题。"""
        else:
            # 有检索结果
            contexts_text = "\n\n".join(contexts[:3])
            prompt = f"""用户问题: {query}

参考信息:
{contexts_text}

请根据参考信息回答用户问题。如果参考信息不足，请说明并基于一般知识回答。
"""

        try:
            answer = self.llm.generate(prompt)
            return answer
        except Exception as e:
            logger.error(f"答案生成失败: {e}")
            return f"抱歉，处理您的问题时遇到错误: {str(e)}"


# ===== 便捷函数 =====

_agent_instance = None


def get_react_agent(
    llm=None,
    max_steps: int = 3
) -> ReActAgent:
    """获取ReAct Agent实例"""
    global _agent_instance
    if _agent_instance is None:
        if llm is None:
            from .llm import get_llm
            llm = get_llm()
        _agent_instance = ReActAgent(
            llm=llm,
            max_steps=max_steps
        )
    return _agent_instance


def react_query(query: str) -> Dict[str, Any]:
    """便捷函数：执行ReAct查询"""
    agent = get_react_agent()
    return agent.run(query)
