# -*- coding: utf-8 -*-
"""
第2层：应用逻辑层 - 缓存模块
Redis 缓存层：常见问题快速响应
"""
import os
import json
import time
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

# 尝试导入 Redis
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis 未安装，使用内存缓存")


class CacheConfig:
    """缓存配置"""

    # 缓存配置
    DEFAULT_TTL = 3600  # 默认缓存1小时
    COMMON_QUESTIONS_TTL = 86400  # 常见问题缓存24小时
    MAX_CACHE_SIZE = 1000  # 最大缓存条目

    # 常见问题（可配置）
    COMMON_QUESTIONS = [
        "如何测试跟车",
        "临时车如何收费",
        "月租车怎么延期",
        "如何测试入场",
        "如何测试出场",
    ]


class Cache:
    """缓存基类"""

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl: int = None):
        """设置缓存"""
        raise NotImplementedError

    def delete(self, key: str):
        """删除缓存"""
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        """检查缓存是否存在"""
        raise NotImplementedError

    def clear(self):
        """清空缓存"""
        raise NotImplementedError


class RedisCache(Cache):
    """Redis缓存"""

    def __init__(self, host: str = None, port: int = 6379, db: int = 0, password: str = None):
        self.host = host or os.environ.get('REDIS_HOST', 'localhost')
        self.port = port
        self.db = db
        self.password = password
        self.client = None

    def connect(self):
        """连接Redis"""
        if not REDIS_AVAILABLE:
            raise RuntimeError("Redis 未安装")

        try:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5
            )
            self.client.ping()
            logger.info(f"Redis 连接成功: {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.warning(f"Redis 连接失败: {e}")
            return False

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        try:
            value = self.client.get(key)
            if value:
                return json.loads(value)
        except Exception as e:
            logger.error(f"Redis get 失败: {e}")
        return None

    def set(self, key: str, value: Any, ttl: int = None):
        """设置缓存"""
        try:
            ttl = ttl or CacheConfig.DEFAULT_TTL
            self.client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Redis set 失败: {e}")

    def delete(self, key: str):
        """删除缓存"""
        try:
            self.client.delete(key)
        except Exception as e:
            logger.error(f"Redis delete 失败: {e}")

    def exists(self, key: str) -> bool:
        """检查缓存是否存在"""
        try:
            return bool(self.client.exists(key))
        except Exception as e:
            return False

    def clear(self):
        """清空缓存"""
        try:
            self.client.flushdb()
        except Exception as e:
            logger.error(f"Redis clear 失败: {e}")


class MemoryCache(Cache):
    """内存缓存（备用）"""

    def __init__(self):
        self.cache = {}
        self.expire_times = {}

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        # 检查是否过期
        if key in self.expire_times:
            if time.time() > self.expire_times[key]:
                self.delete(key)
                return None

        return self.cache.get(key)

    def set(self, key: str, value: Any, ttl: int = None):
        """设置缓存"""
        ttl = ttl or CacheConfig.DEFAULT_TTL

        # 检查缓存大小
        if len(self.cache) >= CacheConfig.MAX_CACHE_SIZE:
            # 删除最早的缓存
            oldest_key = min(self.expire_times.items(), key=lambda x: x[1])[0]
            self.delete(oldest_key)

        self.cache[key] = value
        self.expire_times[key] = time.time() + ttl

    def delete(self, key: str):
        """删除缓存"""
        self.cache.pop(key, None)
        self.expire_times.pop(key, None)

    def exists(self, key: str) -> bool:
        """检查缓存是否存在"""
        if key in self.expire_times:
            if time.time() > self.expire_times[key]:
                self.delete(key)
                return False
        return key in self.cache

    def clear(self):
        """清空缓存"""
        self.cache.clear()
        self.expire_times.clear()


class QuestionCache:
    """问答缓存管理器"""

    # 会话上下文有效期（秒）
    SESSION_TTL = 300  # 5分钟

    def __init__(self, use_redis: bool = True):
        self.use_redis = use_redis and REDIS_AVAILABLE

        if self.use_redis:
            try:
                self.redis_cache = RedisCache()
                if self.redis_cache.connect():
                    self.cache = self.redis_cache
                    logger.info("使用 Redis 缓存")
                else:
                    self.cache = MemoryCache()
                    logger.warning("Redis 连接失败，使用内存缓存")
            except Exception as e:
                logger.warning(f"Redis 初始化失败: {e}，使用内存缓存")
                self.cache = MemoryCache()
        else:
            self.cache = MemoryCache()
            logger.info("使用内存缓存")

    def get_answer(self, query: str) -> Optional[dict]:
        """获取缓存的回答"""
        key = self._make_key(query)
        return self.cache.get(key)

    def set_answer(self, query: str, answer: str, cases: list):
        """缓存回答"""
        key = self._make_key(query)
        value = {
            "answer": answer,
            "cases": cases,
            "timestamp": time.time()
        }

        # 常见问题缓存更长时间
        if self._is_common_question(query):
            ttl = CacheConfig.COMMON_QUESTIONS_TTL
        else:
            ttl = CacheConfig.DEFAULT_TTL

        self.cache.set(key, value, ttl)
        logger.info(f"缓存回答: {query[:30]}, TTL: {ttl}秒")

    def set_session_context(self, session_id: str, query: str, contexts: list):
        """设置会话上下文（用于追问）"""
        key = f"session:{session_id}"
        value = {
            "query": query,
            "contexts": contexts,
            "timestamp": time.time()
        }
        self.cache.set(key, value, self.SESSION_TTL)
        logger.info(f"会话上下文已保存: session={session_id}, query={query[:20]}")

    def get_session_context(self, session_id: str) -> Optional[dict]:
        """获取会话上下文"""
        key = f"session:{session_id}"
        return self.cache.get(key)

    def is_continuation(self, query: str) -> bool:
        """判断是否为追问（继续之前的对话）"""
        # 检测追问关键词
        continuation_keywords = ["还有呢", "继续", "还有吗", "然后呢", "还有", "其他", "更多", "还有没有", "补充"]
        return any(kw in query for kw in continuation_keywords)

    def _make_key(self, key: str) -> str:
        """生成缓存key（优化：标准化查询以提高缓存命中率）"""
        # 标准化查询：去除多余空格、转小写
        normalized = " ".join(key.lower().split())
        return f"qa:{hash(normalized)}"

    def _is_common_question(self, query: str) -> bool:
        """检查是否是常见问题（优化：标准化后检查）"""
        query_normalized = " ".join(query.lower().split())
        return any(cq in query_normalized for cq in CacheConfig.COMMON_QUESTIONS)

    def clear(self):
        """清空缓存"""
        self.cache.clear()
        logger.info("缓存已清空")


# 全局缓存实例
_question_cache = None


def get_question_cache() -> QuestionCache:
    """获取问答缓存实例"""
    global _question_cache
    if _question_cache is None:
        _question_cache = QuestionCache()
    return _question_cache
