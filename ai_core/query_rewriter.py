# -*- coding: utf-8 -*-
"""
AI核心层 - Query 改写模块
包括：意图识别、同义词扩展、LLM改写
"""
import logging
import re
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)


class IntentDetectorLLM:
    """
    基于 LLM 的意图识别器
    """

    # 意图类型定义
    INTENT_TYPES = [
        "测试方法",      # 如何测试、怎么测试
        "流程说明",      # 流程、步骤
        "异常处理",      # 错误、失败、异常
        "对比分析",      # 区别、差异、比较
        "边界条件",      # 极端、特殊、边界
        "概念咨询",      # 什么是、定义
        "一般查询"       # 其他
    ]

    def __init__(self, llm):
        self.llm = llm

    def detect(self, query: str) -> Dict[str, Any]:
        """
        识别查询意图

        Returns:
            {
                "primary_intent": "测试方法",
                "intents": ["测试方法", "边界条件"],
                "keywords": ["如何", "测试"],
                "entities": {"车牌": "A车"}
            }
        """
        prompt = f"""分析以下用户查询的意图。

**重要背景**：知识库中存储的是**停车场智慧停车系统**的测试用例，业务领域包括：
- 道闸通行：车牌识别、入场出场、抬杆落杆
- 收费计费：月租、临停、储值、微信/支付宝支付
- 异常处理：跟车逃费、冲关、重复入场、车牌识别失败
- 设备检查：控制机、摄像头、显示屏、语音播报

**特别注意**：
- "跟车"指的是停车场跟车逃费场景，不是汽车自动驾驶
- "抬杆"指的是道闸开闸，不是车门开门
- "出场/入场"指的是停车场车辆进出，不是高铁/地铁

查询：{query}

请从以下意图类型中选择：
- 测试方法：询问测试方法、验证方式
- 流程说明：询问流程、步骤、顺序
- 异常处理：询问异常情况、错误处理、失败处理
- 对比分析：询问区别、差异、比较
- 边界条件：询问极端情况、特殊条件
- 概念咨询：询问定义、概念、什么是
- 一般查询：其他类型

要求：
1. 识别主要意图（primary_intent）
2. 列出所有相关意图（intents，最多3个）
3. 提取关键词（keywords，2-5个）- 只能使用用户问题中已有的词，禁止添加新词
4. 识别实体（entities，如车牌、金额等）

输出格式（JSON）：
{{
    "primary_intent": "意图类型",
    "intents": ["意图1", "意图2"],
    "keywords": ["关键词1", "关键词2"],
    "entities": {{"实体类型": "实体值"}}
}}"""

        try:
            response = self.llm.generate(prompt)

            # DEBUG: 输出原始 LLM 响应
            logger.debug(f"意图识别 LLM 原始响应:\n{response[:500]}...")

            result = self._parse_response(response)

            # DEBUG: 输出解析后的结果
            logger.info(f"意图识别: {query[:20]}... → {result.get('primary_intent', '一般查询')}")
            logger.debug(f"意图详情: intents={result.get('intents')}, keywords={result.get('keywords')}, entities={result.get('entities')}")
            return result

        except Exception as e:
            logger.warning(f"意图识别失败: {e}")
            return {
                "primary_intent": "一般查询",
                "intents": ["一般查询"],
                "keywords": [],
                "entities": {}
            }

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """解析LLM响应"""
        import json

        # 尝试提取JSON
        try:
            # 查找JSON块
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass

        # 降级解析
        result = {
            "primary_intent": "一般查询",
            "intents": ["一般查询"],
            "keywords": [],
            "entities": {}
        }

        for intent in self.INTENT_TYPES:
            if intent in response:
                if result["primary_intent"] == "一般查询":
                    result["primary_intent"] = intent
                if intent not in result["intents"]:
                    result["intents"].append(intent)

        return result


class SynonymExpander:
    """
    同义词扩展器
    基于禅道测试用例数据的领域词表
    """

    # 领域专用词表 - 基于zentao_rag.json (5450条测试用例)
    SYNONYMS = {
        # 车辆类型
        "跟车": ["连续通过", "连续入场", "追尾入场", "紧跟"],
        "月租": ["月卡", "月租用户", "月租车辆", "月租卡", "月租车"],
        "临时车": ["临时车辆", "临停", "临时用户", "临时入场", "临时计费"],
        "储值卡": ["储值", "充值卡", "钱包"],
        "预定车": ["预约车", "预订车", "预约"],
        "贵宾车": ["VIP", "VIP车", "贵宾"],
        "黑名单": ["灰名单", "异常名单"],
        "白名单": ["允许列表"],

        # 业务流程
        "延期": ["续费", "续期", "续租", "延长", "延期缴费"],
        "出场": ["离场", "驶离", "出场", "出场"],
        "入场": ["进场", "驶入", "入场", "进入"],
        "收费": ["计费", "扣费", "收费", "计费方式", "收费方式"],
        "开闸": ["开道闸", "抬杆", "开杆"],
        "出场": ["离场", "驶离"],
        "离场": ["出场", "驶离"],

        # 车牌识别
        "车牌": ["车牌号", "车辆号", "车牌信息", "车辆牌照", "车牌识别"],
        "识别": ["检测", "读取", "抓拍", "识别到", "比对"],
        "ETC": ["电子不停车", "ETC扣费", "电子收费", "速通"],

        # 支付相关
        "优惠": ["打折", "减免", "折扣", "满减"],
        "时长券": ["时间券", "优惠券", "折扣券"],
        "打折": ["折扣", "优惠", "减免"],
        "全免": ["免费", "免收"],
        "扣费": ["收费", "计费", "扣除"],

        # 异常处理
        "异常": ["错误", "失败", "故障", "问题", "异常情况"],
        "脱机": ["离线", "脱机状态", "离线状态"],
        "补录": ["补交", "补充记录", "人工补录"],

        # 设备相关
        "控制机": ["设备", "道闸", "闸机"],
        "地感": ["地感线圈", "感应器", "压感"],
        "摄像头": ["相机", "监控", "识别仪"],
        "超眸": ["车牌识别", "算法识别"],

        # 测试相关
        "测试": ["验证", "检查", "校验", "测试用例", "验证"],
        "流程": ["步骤", "顺序", "过程"],
        "场景": ["情况", "用例", "测试场景"],

        # APP/小程序
        "小程序": ["微信小程序", "移动端", "APP", "捷服务", "捷E"],
        "APP": ["小程序", "手机端", "移动应用"],

        # 版本相关
        "版本": ["3.0", "3.4", "系统版本"],
    }

    def expand(self, query: str) -> List[str]:
        """扩展查询"""
        results = [query]
        expand_details = []

        # 查表扩展
        for word, synonyms in self.SYNONYMS.items():
            if word in query:
                for syn in synonyms:
                    new_query = query.replace(word, syn)
                    if new_query not in results:
                        results.append(new_query)
                        expand_details.append(f"'{word}' -> '{syn}'")

        # 反向扩展
        for word, synonyms in self.SYNONYMS.items():
            for syn in synonyms:
                if syn in query:
                    if word not in query:
                        new_query = query.replace(syn, word)
                        if new_query not in results:
                            results.append(new_query)
                            expand_details.append(f"'{syn}' -> '{word}'")

        logger.info(f"同义词扩展: {query[:15]}... → {len(results)} 个版本")
        if expand_details:
            logger.debug(f"同义词扩展详情: {expand_details}")
        return results[:5]  # 最多5个

    def expand_with_llm(self, query: str, llm) -> List[str]:
        """LLM扩展更多同义词"""
        prompt = f"""为以下查询生成同义词/替代表达：

查询：{query}

要求：生成3-5个不同的表达方式，保持原意。
输出格式：每行一个"""

        try:
            response = llm.generate(prompt)
            synonyms = [query]

            for line in response.split('\n'):
                line = line.strip().lstrip('0123456789.）').strip()
                if line and len(line) > 3 and line != query:
                    synonyms.append(line)

            return synonyms[:5]

        except Exception as e:
            logger.warning(f"LLM扩展失败: {e}")
            return [query]


class LLMRewriter:
    """
    LLM 查询改写器
    """

    def __init__(self, llm):
        self.llm = llm

    def rewrite(self, query: str, num_versions: int = 3) -> List[str]:
        """生成多个改写版本"""
        prompt = f"""将这个问题改写成{num_versions}个不同表达方式，保留核心语义：

原问题：{query}

要求：
1. 使用不同的词汇和句式
2. 保持语义不变
3. 从不同角度描述

输出格式：每行一个版本"""

        try:
            response = self.llm.generate(prompt)

            versions = [query]
            for line in response.split('\n'):
                line = line.strip().lstrip('0123456789.）').strip()
                if line and len(line) > 5 and line != query:
                    versions.append(line)

            return versions[:num_versions]

        except Exception as e:
            logger.warning(f"LLM改写失败: {e}")
            return [query]

    def rewrite_for_intent(self, query: str, intent: str, mode: str = "fast") -> str:
        """
        根据意图改写

        Args:
            query: 原始查询
            intent: 识别的意图
            mode: 模式选择
                - "fast": 简短输出（优化响应速度）
                - "quality": 完整输出（保留更多语义）
        """

        if mode == "quality":
            # 完整模式：生成详细改写，保留更多语义信息
            intent_prompts = {
                "测试方法": f"将问题改写为明确的测试需求，描述需要的测试用例：{query}",
                "流程说明": f"将问题改写为流程描述，说明步骤：{query}",
                "对比分析": f"将问题改写为对比分析需求：{query}",
                "异常处理": f"将问题改写为异常处理需求：{query}",
                "边界条件": f"将问题改写为边界条件测试需求：{query}",
                "概念咨询": f"将问题改写为概念解释需求：{query}"
            }
            prompt = intent_prompts.get(intent, f"改写以下问题使其更清晰：{query}")

            try:
                return self.llm.generate(prompt)
            except Exception as e:
                logger.warning(f"意图改写失败: {e}")
                return query

        # 快速模式（默认）：简短输出，大幅减少LLM调用时间
        intent_prompts = {
            "测试方法": f"将问题简化为测试用例描述（不超过30字）：{query}",
            "流程说明": f"将问题简化为流程描述（不超过30字）：{query}",
            "对比分析": f"将问题简化为对比要点（不超过30字）：{query}",
            "异常处理": f"将问题简化为异常场景描述（不超过30字）：{query}",
            "边界条件": f"将问题简化为边界情况描述（不超过30字）：{query}",
            "概念咨询": f"将问题简化为概念关键词（不超过20字）：{query}"
        }

        prompt = intent_prompts.get(intent, f"简化问题（不超过20字）：{query}")

        # 限制max_tokens，避免过长输出
        original_max_tokens = self.llm.max_tokens if hasattr(self.llm, 'max_tokens') else 1500
        if hasattr(self.llm, 'max_tokens'):
            self.llm.max_tokens = 100  # 限制输出长度

        try:
            result = self.llm.generate(prompt)
            # 截取第一行或前50字，避免过长
            result = result.strip().split('\n')[0][:50]
            return result if result else query
        except Exception as e:
            logger.warning(f"意图改写失败: {e}")
            return query
        finally:
            # 恢复原始max_tokens
            if hasattr(self.llm, 'max_tokens'):
                self.llm.max_tokens = original_max_tokens


class QueryRewriter:
    """
    Query 改写流水线
    整合意图识别、同义词扩展、LLM改写
    支持缓存
    """

    # 停车场领域无关的关键词黑名单
    DOMAIN_BLACKLIST = [
        "自动驾驶", "ACC", "自适应巡航", "车道保持", "自动泊车",
        "变道辅助", "盲区监测", "前碰撞预警", "自动紧急制动",
        "定速巡航", "限速巡航", "智能驾驶", "辅助驾驶",
        "行车记录仪", "车载导航", "车载雷达", "超声波雷达",
        "毫米波雷达", "激光雷达", "摄像头", "传感器"
    ]

    def __init__(
        self,
        llm,
        use_intent: bool = True,
        use_synonym: bool = True,
        use_llm_rewrite: bool = True,
        cache_size: int = 500,
        rewrite_mode: str = "fast"  # "fast" or "quality"
    ):
        self.llm = llm

        # 各模块开关
        self.use_intent = use_intent
        self.use_synonym = use_synonym
        self.use_llm_rewrite = use_llm_rewrite
        self.rewrite_mode = rewrite_mode

        # 缓存
        self._cache = {}
        self._cache_size = cache_size

        # 初始化模块
        if use_intent:
            self.intent_detector = IntentDetectorLLM(llm)
        else:
            self.intent_detector = None

        if use_synonym:
            self.synonym_expander = SynonymExpander()
        else:
            self.synonym_expander = None

        if use_llm_rewrite:
            self.llm_rewriter = LLMRewriter(llm)
        else:
            self.llm_rewriter = None

        logger.info(f"Query改写器初始化: 意图={use_intent}, 同义词={use_synonym}, LLM改写={use_llm_rewrite}, 缓存={cache_size}, 模式={rewrite_mode}")

    def _get_cache(self, query: str) -> Optional[Tuple[List[str], Dict]]:
        """获取缓存"""
        if query in self._cache:
            logger.info(f"Query改写缓存命中: {query[:20]}...")
            return self._cache[query]
        return None

    def _set_cache(self, query: str, result: Tuple[List[str], Dict]):
        """设置缓存"""
        # 简单缓存：超过容量清空
        if len(self._cache) >= self._cache_size:
            # 清空最旧的50%
            keys = list(self._cache.keys())[:self._cache_size // 2]
            for k in keys:
                del self._cache[k]

    def _filter_blacklist(self, query: str) -> str:
        """
        过滤掉与停车场领域无关的关键词

        Args:
            query: 原始查询

        Returns:
            过滤后的查询
        """
        filtered = query
        removed = []

        for keyword in self.DOMAIN_BLACKLIST:
            if keyword in filtered:
                # 移除关键词（替换为空格，避免连续空格）
                filtered = filtered.replace(keyword, ' ')
                removed.append(keyword)

        # 清理多余空格
        filtered = ' '.join(filtered.split())

        if removed:
            logger.info(f"Query过滤: 移除不相关关键词 {removed}，原始: '{query}' → 过滤后: '{filtered}'")

        return filtered

        self._cache[query] = result

    def rewrite(self, query: str) -> Tuple[List[str], Dict]:
        """
        改写查询

        Returns:
            (改写后的查询列表, 意图信息)
        """
        # Step 0: 过滤黑名单关键词（停车场领域无关）
        filtered_query = self._filter_blacklist(query)

        all_queries = [filtered_query]
        intent_info = {}

        # Step 1: 意图识别
        if self.use_intent and self.intent_detector:
            intent_result = self.intent_detector.detect(filtered_query)
            intent_info = intent_result

            # 根据意图可能需要额外改写
            if self.use_llm_rewrite and self.llm_rewriter:
                intent_query = self.llm_rewriter.rewrite_for_intent(
                    filtered_query,
                    intent_result.get("primary_intent", "一般查询"),
                    mode=self.rewrite_mode  # 传递模式参数
                )
                if intent_query != filtered_query:
                    all_queries.append(intent_query)

        # Step 2: 同义词扩展
        if self.use_synonym and self.synonym_expander:
            synonym_queries = self.synonym_expander.expand(filtered_query)
            all_queries.extend(synonym_queries)

        # Step 3: LLM改写
        if self.use_llm_rewrite and self.llm_rewriter:
            llm_queries = self.llm_rewriter.rewrite(filtered_query, num_versions=2)
            all_queries.extend(llm_queries)

        # 去重
        all_queries = list(dict.fromkeys(all_queries))

        logger.info(f"Query改写完成: {filtered_query[:15]}... → {len(all_queries)} 个版本")

        return all_queries, intent_info


# 全局单例
_query_rewriter = None


def get_query_rewriter(llm=None) -> QueryRewriter:
    """获取Query改写器"""
    global _query_rewriter

    if _query_rewriter is None:
        from .llm import get_llm
        llm = llm or get_llm()
        _query_rewriter = QueryRewriter(llm)

    return _query_rewriter


def init_query_rewriter(llm=None, **kwargs) -> QueryRewriter:
    """初始化Query改写器"""
    global _query_rewriter

    if llm is None:
        from .llm import get_llm
        llm = get_llm()

    _query_rewriter = QueryRewriter(llm, **kwargs)

    return _query_rewriter
