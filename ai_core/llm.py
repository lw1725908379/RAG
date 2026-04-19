# -*- coding: utf-8 -*-
"""
AI核心层 - 大语言模型模块
第3层：AI核心层
"""
import requests
import os
import time
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# 配置 - 从环境变量读取，禁止硬编码
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")  # 必须设置环境变量
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# 检查API密钥是否配置
if not DEEPSEEK_API_KEY:
    logger.warning("警告: DEEPSEEK_API_KEY 未设置，请设置环境变量 export DEEPSEEK_API_KEY=your_key")


class LLM:
    """大语言模型封装"""

    def __init__(
        self,
        model: str = DEEPSEEK_MODEL,
        api_key: str = DEEPSEEK_API_KEY,
        base_url: str = DEEPSEEK_URL,
        temperature: float = 0.3,
        max_tokens: int = 1500
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate(self, prompt: str) -> str:
        """生成回答"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False
        }

        start_time = time.time()
        try:
            logger.info("调用 LLM API...")
            # DEBUG: 输出请求信息
            logger.debug(f"LLM 请求 - model: {self.model}, temperature: {self.temperature}, max_tokens: {self.max_tokens}")
            logger.debug(f"LLM 请求 Prompt (前500字):\n{prompt[:500]}...")

            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=60
            )

            duration = time.time() - start_time

            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']

                # 提取 Token 使用量
                usage = result.get('usage', {})
                prompt_tokens = usage.get('prompt_tokens', 0)
                completion_tokens = usage.get('completion_tokens', 0)
                total_tokens = usage.get('total_tokens', 0)

                # 显式记录性能指标
                logger.info(
                    f"LLM 响应完成: 耗时 {duration:.2f}s, "
                    f"Usage: prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}"
                )

                # DEBUG: 输出响应内容
                logger.debug(f"LLM 响应 (前500字):\n{content[:500]}...")
                return content
            else:
                error = f"API错误 ({response.status_code})"
                logger.error(f"LLM API错误: {response.text}, 耗时 {duration:.2f}s")
                return error

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"LLM 调用异常: {e}, 耗时 {duration:.2f}s", exc_info=True)
            return f"调用异常: {str(e)}"

    def stream_generate(self, prompt: str):
        """流式生成"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True
        }

        try:
            logger.info("开始流式调用 LLM...")
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=60
            )

            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]':
                            break

                        try:
                            import json
                            chunk = json.loads(data)
                            if 'choices' in chunk and len(chunk['choices']) > 0:
                                delta = chunk['choices'][0].get('delta', {})
                                content = delta.get('content', '')
                                if content:
                                    yield content
                        except:
                            pass

        except Exception as e:
            logger.error(f"流式调用异常: {e}")
            yield f"错误: {str(e)}"


# 全局单例
_llm = None


def get_llm() -> LLM:
    """获取LLM单例"""
    global _llm
    if _llm is None:
        _llm = LLM()
    return _llm
