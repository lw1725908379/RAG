# -*- coding: utf-8 -*-
"""
AI核心层 - 知识库路由器
支持多知识库管理：用例库、需求库、测试方案库
"""
import os
import logging
from typing import Dict, List, Optional, Any
from .knowledge_base import KnowledgeBaseManager

logger = logging.getLogger(__name__)

# 默认知识库配置 - 只保留用例库
DEFAULT_KBS = {
    "use_cases": {
        "name": "用例库",
        "description": "禅道测试用例",
        "data_dir": "data/kb_use_cases",
        "faiss_path": "faiss_db/kb_use_cases"
    }
}


class KnowledgeBaseRouter:
    """
    知识库路由器
    管理多个知识库，支持指定库查询、跨库查询、智能路由
    """

    def __init__(self, base_dir: str = None, embedding_model=None):
        """
        初始化知识库路由器

        Args:
            base_dir: 基础目录
            embedding_model: 嵌入模型实例
        """
        self.base_dir = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.embedding_model = embedding_model
        self.kbs: Dict[str, KnowledgeBaseManager] = {}
        self.kb_configs = DEFAULT_KBS.copy()

        # 确保目录存在
        self._ensure_directories()

        # 初始化已注册的知识库
        for kb_id, config in self.kb_configs.items():
            faiss_path = os.path.join(self.base_dir, config["faiss_path"])
            data_dir = os.path.join(self.base_dir, config["data_dir"])

            # 只有当FAISS索引存在时才初始化
            if os.path.exists(faiss_path + "/index.faiss"):
                self.kbs[kb_id] = KnowledgeBaseManager(
                    embedding_model=embedding_model,
                    faiss_path=faiss_path,
                    data_dir=data_dir
                )
                logger.info(f"加载知识库: {kb_id} - {config['name']}")

    def _ensure_directories(self):
        """确保所有知识库目录存在"""
        for kb_id, config in self.kb_configs.items():
            data_dir = os.path.join(self.base_dir, config["data_dir"])
            faiss_path = os.path.join(self.base_dir, config["faiss_path"])
            os.makedirs(data_dir, exist_ok=True)
            os.makedirs(faiss_path, exist_ok=True)

    def register_kb(self, kb_id: str, name: str, description: str = "", data_dir: str = None, faiss_path: str = None):
        """
        注册新知识库

        Args:
            kb_id: 知识库ID
            name: 知识库名称
            description: 知识库描述
            data_dir: 数据目录
            faiss_path: FAISS索引目录
        """
        if kb_id in self.kbs:
            logger.warning(f"知识库 {kb_id} 已存在，将被覆盖")

        config = {
            "name": name,
            "description": description,
            "data_dir": data_dir or f"data/kb_{kb_id}",
            "faiss_path": faiss_path or f"faiss_db/kb_{kb_id}"
        }

        self.kb_configs[kb_id] = config
        os.makedirs(os.path.join(self.base_dir, config["data_dir"]), exist_ok=True)
        os.makedirs(os.path.join(self.base_dir, config["faiss_path"]), exist_ok=True)

        self.kbs[kb_id] = KnowledgeBaseManager(
            embedding_model=self.embedding_model,
            faiss_path=os.path.join(self.base_dir, config["faiss_path"]),
            data_dir=os.path.join(self.base_dir, config["data_dir"])
        )

        logger.info(f"注册知识库: {kb_id} - {name}")

    def get_kb(self, kb_id: str) -> Optional[KnowledgeBaseManager]:
        """获取指定知识库"""
        return self.kbs.get(kb_id)

    def list_kbs(self) -> List[Dict]:
        """列出所有知识库"""
        result = []
        for kb_id, config in self.kb_configs.items():
            kb = self.kbs.get(kb_id)
            doc_count = 0

            if kb and kb.faiss_retriever:
                doc_count = kb.faiss_retriever.count()

            result.append({
                "id": kb_id,
                "name": config["name"],
                "description": config["description"],
                "document_count": doc_count,
                "data_dir": config["data_dir"],
                "faiss_path": config["faiss_path"]
            })

        return result

    def query(self, query: str, kbs: List[str] = None, top_k: int = 3, mode: str = "auto", routing: str = "auto") -> Dict[str, Any]:
        """
        查询知识库

        Args:
            query: 查询文本
            kbs: 知识库ID列表，None表示全部
            top_k: 返回结果数
            mode: 查询模式
                - "single": 单库查询
                - "cross": 跨库查询
                - "auto": 自动选择
            routing: 路由模式
                - "auto": 自动选择路由策略
                - "logical": LLM逻辑路由
                - "semantic": 语义相似度路由
                - "cross": 跨库查询（忽略routing）
                - "none": 禁用智能路由

        Returns:
            查询结果字典
        """
        # DEBUG: 输出查询参数
        logger.debug(f"KB Router 查询参数: query='{query}', kbs={kbs}, top_k={top_k}, mode={mode}, routing={routing}")

        # 跨库模式：忽略routing，直接查询所有指定KB
        if mode == "cross" or routing == "cross":
            logger.info(f"KB Router: 跨库查询模式, kbs={kbs}")
            return self._cross_kb_query(query, kbs, top_k)

        # 智能路由模式：routing不为None时启用智能路由
        if routing != "none" and (routing in ("logical", "semantic") or routing == "auto"):
            logger.info(f"KB Router: 智能路由模式, routing={routing}")
            return self._smart_route_query(query, kbs, top_k, routing)

        # 原有逻辑：单库或跨库查询
        logger.info(f"KB Router: 基础查询模式, mode={mode}, kbs={kbs}")
        return self._basic_query(query, kbs, top_k, mode)

    def _smart_route_query(self, query: str, kbs: List[str], top_k: int, routing: str) -> Dict[str, Any]:
        """智能路由查询"""
        # 延迟导入，避免循环依赖
        from .rag_router import RAGRouter
        from .llm import get_llm

        # 初始化RAG路由器 (懒加载)
        if not hasattr(self, '_rag_router'):
            # 获取LLM实例 (如果环境变量DEEPSEEK_API_KEY已设置)
            try:
                llm = get_llm()
            except Exception:
                llm = None

            self._rag_router = RAGRouter(
                kb_router=self,
                embedding_model=self.embedding_model,
                llm=llm  # 传入LLM用于逻辑路由
            )

        # 执行路由查询
        return self._rag_router.route(query, mode=routing)

    def _cross_kb_query(self, query: str, kbs: List[str], top_k: int) -> Dict[str, Any]:
        """跨库查询"""
        # 确定要查询的知识库
        if kbs is None:
            target_kbs = list(self.kbs.keys())
        else:
            target_kbs = kbs

        if not target_kbs:
            return {"error": "没有可用的知识库"}

        # 并行查询各KB
        all_results = []
        for kb_id in target_kbs:
            kb = self.kbs.get(kb_id)
            if kb:
                docs = kb.search(query, top_k=top_k)
                for doc in docs:
                    doc["source_kb"] = kb_id
                all_results.extend(docs)

        # 按分数排序
        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        all_results = all_results[:top_k]

        return {
            "query": query,
            "kbs": target_kbs,
            "results": all_results,
            "count": len(all_results),
            "routing": {
                "strategy": "cross",
                "selected_kbs": target_kbs,
                "reasoning": "跨库查询模式"
            }
        }

    def _basic_query(self, query: str, kbs: List[str], top_k: int, mode: str) -> Dict[str, Any]:
        """基础查询逻辑（保持原有行为）"""
        # 确定要查询的知识库
        if kbs is None:
            target_kbs = list(self.kbs.keys())
        else:
            target_kbs = kbs

        logger.debug(f"KB Router 基础查询: 目标知识库={target_kbs}")

        if not target_kbs:
            return {"error": "没有可用的知识库"}

        # 单库查询
        if len(target_kbs) == 1:
            kb_id = target_kbs[0]
            kb = self.kbs.get(kb_id)
            if not kb:
                return {"error": f"知识库 {kb_id} 不存在"}

            logger.debug(f"KB Router: 查询知识库 '{kb_id}', top_k={top_k}")
            docs = kb.search(query, top_k=top_k)

            # DEBUG: 输出检索结果
            logger.debug(f"KB Router: 知识库 '{kb_id}' 返回 {len(docs)} 个结果")
            for i, doc in enumerate(docs[:3]):
                score = doc.get('score', 0)
                doc_preview = doc.get('document', '')[:80].replace('\n', ' ')
                logger.debug(f"  结果{i+1}: score={score:.4f}, {doc_preview}...")

            return {
                "query": query,
                "kb": kb_id,
                "results": docs,
                "count": len(docs)
            }

        # 跨库查询
        all_results = []
        for kb_id in target_kbs:
            kb = self.kbs.get(kb_id)
            if kb:
                docs = kb.search(query, top_k=top_k)
                logger.debug(f"KB Router: 知识库 '{kb_id}' 返回 {len(docs)} 个结果")
                for doc in docs:
                    doc["source_kb"] = kb_id
                all_results.extend(docs)

        # 按分数排序
        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        all_results = all_results[:top_k]

        return {
            "query": query,
            "kbs": target_kbs,
            "results": all_results,
            "count": len(all_results)
        }

    def import_data(self, kb_id: str, data: List[Dict] = None, file_path: str = None) -> Dict:
        """
        导入数据到知识库（追加模式）

        Args:
            kb_id: 知识库ID
            data: 数据列表
            file_path: 文件路径

        Returns:
            导入结果
        """
        kb = self.kbs.get(kb_id)
        if not kb:
            # 自动创建知识库
            logger.info(f"知识库 {kb_id} 不存在，自动创建")
            config = self.kb_configs.get(kb_id)
            if config:
                faiss_path = os.path.join(self.base_dir, config["faiss_path"])
                data_dir = os.path.join(self.base_dir, config["data_dir"])
            else:
                # 自定义知识库
                faiss_path = os.path.join(self.base_dir, f"faiss_db/kb_{kb_id}")
                data_dir = os.path.join(self.base_dir, f"data/kb_{kb_id}")
                # 更新配置
                self.kb_configs[kb_id] = {
                    "name": kb_id,
                    "description": "自动创建",
                    "data_dir": f"data/kb_{kb_id}",
                    "faiss_path": f"faiss_db/kb_{kb_id}"
                }

            os.makedirs(faiss_path, exist_ok=True)
            os.makedirs(data_dir, exist_ok=True)

            from .knowledge_base import KnowledgeBaseManager
            kb = KnowledgeBaseManager(
                embedding_model=self.embedding_model,
                faiss_path=faiss_path,
                data_dir=data_dir
            )
            self.kbs[kb_id] = kb

        if data:
            result = kb.import_from_json(data, clear_first=False)
        elif file_path:
            # 使用文档解析器处理不同格式
            try:
                from .document_parser import parse_documents
                documents = parse_documents(file_path)

                # 数据清洗（统一入口：根据KB类型自动选择清洗策略）
                from .doc_processor import clean_and_chunk

                # 根据KB类型确定文档类型
                kb_doc_type = {
                    "use_cases": "use_cases",
                    "requirements": "requirements"
                }.get(kb_id, "generic")

                # 清洗并切分每个文档
                processed_data = []
                for doc in documents:
                    doc_id = doc.get('id', '')
                    title = doc.get('title', '')
                    content = doc.get('content', '')

                    # 组合完整文本
                    full_text = f"{title}\n\n{content}" if title else content

                    # 清洗并切分
                    chunks = clean_and_chunk(full_text, kb_doc_type, doc_id)

                    # 转换为知识库格式
                    for chunk in chunks:
                        if kb_id == "use_cases":
                            # 用例库：测试用例格式
                            formatted_content = f"## 测试用例 (ID: {doc_id})\n\n{chunk['content']}"
                        elif kb_id == "requirements":
                            # 需求库：需求文档格式（带章节路径）
                            chapter_path = chunk['metadata'].get('chapter_path', '')
                            if chapter_path:
                                formatted_content = f"【需求】{chapter_path}\n\n{chunk['content']}"
                            else:
                                formatted_content = f"【需求】{title}\n\n{chunk['content']}"
                        else:
                            formatted_content = chunk['content']

                        processed_data.append({
                            'id': f"{doc_id}_{chunk['metadata'].get('chunk_id', 0)}",
                            'content': formatted_content,
                            'metadata': chunk['metadata']
                        })

                # 导入（默认追加）
                result = kb.import_from_json(
                    processed_data,
                    use_test_case_format=(kb_id == "use_cases"),
                    clear_first=False
                )

            except ImportError as e:
                return {"error": str(e)}
            except Exception as e:
                return {"error": f"文件处理失败: {str(e)}"}
        else:
            return {"error": "请提供数据或文件路径"}

        # 保存索引
        save_result = kb.save_index()

        return {
            "import": result,
            "save": save_result
        }

    def rebuild_index(self, kb_id: str, source_file: str = None) -> Dict:
        """
        重建知识库索引
        注意：此操作会清空现有索引，需要重新导入文档

        Args:
            kb_id: 知识库ID
            source_file: 源数据文件（可选）

        Returns:
            重建结果
        """
        kb = self.kbs.get(kb_id)
        if not kb:
            return {"error": f"知识库 {kb_id} 不存在"}

        # 清空现有索引
        if kb.faiss_retriever:
            kb.faiss_retriever.documents = []
            kb.faiss_retriever.metadatas = []
            kb.faiss_retriever.ids = []
            if kb.faiss_retriever.index:
                import faiss
                kb.faiss_retriever.index = faiss.IndexHNSWFlat(1024, 32)
            logger.info(f"已清空知识库 {kb_id} 的索引")

        # 如果提供了源文件，则重建
        if source_file:
            result = kb.rebuild_index(source_file=source_file)
        else:
            result = {"message": "索引已清空，请重新导入文档"}

        # 保存索引（清空状态）
        save_result = kb.save_index()

        return {
            "rebuild": result,
            "save": save_result,
            "message": "索引已清空，请重新导入文档"
        }

    def get_status(self, kb_id: str = None) -> Dict:
        """
        获取知识库状态

        Args:
            kb_id: 知识库ID，None表示全部

        Returns:
            状态信息
        """
        if kb_id:
            kb = self.kbs.get(kb_id)
            if not kb:
                return {"error": f"知识库 {kb_id} 不存在"}
            return kb.get_status()

        # 返回所有知识库状态
        return {
            "kbs": self.list_kbs(),
            "total": len(self.kbs)
        }

    def delete_kb(self, kb_id: str) -> Dict:
        """
        删除知识库

        Args:
            kb_id: 知识库ID

        Returns:
            删除结果
        """
        if kb_id not in self.kbs:
            return {"error": f"知识库 {kb_id} 不存在"}

        # 不能删除默认知识库
        if kb_id in DEFAULT_KBS:
            return {"error": "不能删除默认知识库，可重新导入文档重建索引"}

        # 删除内存中的实例
        kb = self.kbs.pop(kb_id)

        # 删除配置
        if kb_id in self.kb_configs:
            config = self.kb_configs.pop(kb_id)

            # 删除数据目录和索引目录
            import shutil
            try:
                if os.path.exists(config.get('data_dir', '')):
                    shutil.rmtree(os.path.join(self.base_dir, config['data_dir']))
            except Exception as e:
                logger.warning(f"删除数据目录失败: {e}")

            try:
                if os.path.exists(config.get('faiss_path', '')):
                    shutil.rmtree(os.path.join(self.base_dir, config['faiss_path']))
            except Exception as e:
                logger.warning(f"删除索引目录失败: {e}")

        logger.info(f"已删除知识库: {kb_id}")

        return {
            "success": True,
            "kb_id": kb_id,
            "message": f"知识库 {kb_id} 已删除"
        }

    def get_documents(self, kb_id: str) -> List[Dict]:
        """
        获取知识库文档列表

        Args:
            kb_id: 知识库ID

        Returns:
            文档列表
        """
        if kb_id not in self.kbs:
            return []
        return self.kbs[kb_id].get_documents()

    def add_document(self, kb_id: str, content: str, metadata: Dict = None) -> Dict:
        """
        添加文档到知识库

        Args:
            kb_id: 知识库ID
            content: 文档内容
            metadata: 元数据

        Returns:
            添加结果
        """
        if kb_id not in self.kbs:
            return {"success": False, "error": f"知识库 {kb_id} 不存在"}
        return self.kbs[kb_id].add_document(content, metadata)

    def update_document(self, kb_id: str, doc_idx: int, new_content: str) -> Dict:
        """
        更新知识库文档

        Args:
            kb_id: 知识库ID
            doc_idx: 文档索引
            new_content: 新内容

        Returns:
            更新结果
        """
        if kb_id not in self.kbs:
            return {"success": False, "error": f"知识库 {kb_id} 不存在"}
        return self.kbs[kb_id].update_document(doc_idx, new_content)

    def delete_document(self, kb_id: str, doc_idx: int) -> Dict:
        """
        删除知识库文档

        Args:
            kb_id: 知识库ID
            doc_idx: 文档索引

        Returns:
            删除结果
        """
        if kb_id not in self.kbs:
            return {"success": False, "error": f"知识库 {kb_id} 不存在"}
        return self.kbs[kb_id].delete_document(doc_idx)


# 全局路由器实例
_router = None


def get_router(base_dir: str = None, embedding_model=None, model_path: str = None) -> KnowledgeBaseRouter:
    """获取知识库路由器全局实例"""
    global _router
    if _router is None:
        # 初始化嵌入模型
        if model_path and os.path.exists(model_path):
            from .embedding import init_embedding_model
            init_embedding_model(model_path)
        _router = KnowledgeBaseRouter(base_dir=base_dir, embedding_model=embedding_model)
    return _router


def reset_router():
    """重置路由器（用于测试）"""
    global _router
    _router = None
