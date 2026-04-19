# -*- coding: utf-8 -*-
"""
MCP 测试策略服务客户端
"""
import requests
import time
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

MCP_BASE_URL = "http://localhost:5000/api/mcp"
DEFAULT_TIMEOUT = 300
MAX_RETRIES = 3
RETRY_DELAY = 2


class MCPClient:
    """MCP 测试策略服务客户端"""

    def __init__(self, base_url: str = MCP_BASE_URL):
        self.base_url = base_url

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """带重试的请求"""
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp
            except requests.exceptions.RequestException as e:
                last_error = e
                logger.warning(f"[MCP] 请求失败 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
        raise last_error

    def generate_test_strategy(self, atoms: List[Dict], timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
        """
        生成测试策略

        Args:
            atoms: 原子功能列表
            timeout: 超时时间（秒）

        Returns:
            {
                "success": bool,
                "test_strategy": str,  # Markdown 格式测试策略
                "output_file": str,   # 输出文件路径
                "stats": dict         # 统计信息
            }
        """
        logger.info(f"[MCP] 开始生成测试策略，原子功能数量: {len(atoms)}")

        # Step 1: 提交异步任务
        try:
            resp = self._request_with_retry(
                "POST",
                f"{self.base_url}/generate-test-strategy-async",
                json={"atoms": atoms},
                timeout=30
            )
            data = resp.json()

            if not data.get("success"):
                return {"success": False, "error": data.get("error", "提交任务失败")}

            task_id = data.get("task_id")
            logger.info(f"[MCP] 任务已提交，task_id: {task_id}")

        except requests.exceptions.RequestException as e:
            logger.error(f"[MCP] 提交任务失败: {e}")
            return {"success": False, "error": f"提交任务失败: {str(e)}"}
        except Exception as e:
            logger.error(f"[MCP] 未知错误: {e}")
            return {"success": False, "error": f"未知错误: {str(e)}"}

        # Step 2: 轮询任务状态
        start_time = time.time()
        poll_interval = 5  # 每5秒轮询

        while time.time() - start_time < timeout:
            try:
                status_resp = self._request_with_retry(
                    "GET",
                    f"{self.base_url}/task/{task_id}",
                    timeout=30
                )
                status_data = status_resp.json()

                if status_data.get("status") == "completed":
                    logger.info(f"[MCP] 任务完成，输出文件: {status_data.get('output_file')}")
                    return {
                        "success": True,
                        "test_strategy": status_data.get("result", ""),
                        "output_file": status_data.get("output_file", ""),
                        "atom_count": status_data.get("atom_count", 0),
                        "stats": status_data.get("stats", {})
                    }

                elif status_data.get("status") == "failed":
                    error_msg = status_data.get("error", "任务执行失败")
                    logger.error(f"[MCP] 任务失败: {error_msg}")
                    return {"success": False, "error": error_msg}

                else:
                    elapsed = int(time.time() - start_time)
                    logger.info(f"[MCP] 任务处理中... ({elapsed}s)")

            except requests.exceptions.RequestException as e:
                logger.warning(f"[MCP] 查询任务状态失败: {e}")
            except Exception as e:
                logger.warning(f"[MCP] 查询状态异常: {e}")

            time.sleep(poll_interval)

        logger.error(f"[MCP] 任务超时 ({timeout}s)")
        return {"success": False, "error": "任务超时"}

    def check_health(self) -> bool:
        """检查 MCP 服务健康状态"""
        try:
            resp = self._request_with_retry("GET", f"{self.base_url}/health", timeout=10)
            return resp.json().get("status") == "ok"
        except Exception as e:
            logger.error(f"[MCP] 健康检查失败: {e}")
            return False


def main():
    """测试入口"""
    # 示例 atoms 数据
    sample_atoms = [
        {
            "module": "通道引擎对接",
            "function_id": "D-01",
            "function_name": "闸前倒车-无驶离通知",
            "business_logic": "识别到车辆开闸后，A车行驶到出口道闸下，触发道闸地感但未过闸，A车倒车返场不出场，通道引擎只给倒车事件，不给驶离通知",
            "trigger_condition": "车辆开闸 + 未过闸 + 倒车",
            "rules": ["只给倒车事件", "不给驶离通知", "不生成出场记录"],
            "tags": ["倒车", "闸前", "无驶离通知"],
            "test_cases": {
                "normal": ["A车倒车返场不出场"],
                "exception": ["倒车后再次出场计费异常"]
            }
        },
        {
            "module": "通道引擎对接",
            "function_id": "D-02",
            "function_name": "闸后倒车-有驶离通知",
            "business_logic": "道闸开闸后A车快速倒车，触发道闸地感再次抬杆，通道引擎给驶离通知和倒车事件，先生成出场记录再生成入场记录",
            "trigger_condition": "车辆过闸 + 倒车 + 再次抬杆",
            "rules": ["先给驶离通知", "再给倒车事件", "先生成出场再生成入场"],
            "tags": ["倒车", "闸后", "驶离通知"],
            "test_cases": {
                "normal": ["A车闸后倒车生成新入场"],
                "exception": ["计费异常", "免费时长重复享受"]
            }
        }
    ]

    print("=" * 60)
    print("MCP 测试策略生成客户端")
    print("=" * 60)

    # 检查服务健康状态
    client = MCPClient()
    if not client.check_health():
        print("[ERROR] MCP 服务不可用，请检查服务是否启动")
        return

    print("[OK] MCP 服务健康检查通过")

    # 生成测试策略
    result = client.generate_test_strategy(sample_atoms, timeout=300)

    if result["success"]:
        print("\n[OK] Test strategy generated successfully!")
        print(f"Atom count: {result.get('atom_count', 0)}")
        print(f"Output file: {result.get('output_file', 'N/A')}")
        print(f"\nStats: {result.get('stats', {})}")
        print(f"\nPreview (first 500 chars):")
        print("-" * 60)
        print(result.get("test_strategy", "")[:500])
    else:
        print(f"\n[ERROR] Failed: {result.get('error')}")


if __name__ == "__main__":
    main()
