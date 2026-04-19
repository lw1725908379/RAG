# -*- coding: utf-8 -*-
"""
AI核心层 - 知识库管理模块
支持：
- 手动导入新文档
- 增量更新向量库
- 重建索引
"""
import os
import json
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from .retriever import FAISSRetriever

logger = logging.getLogger(__name__)

# 禁用SSL验证
os.environ['HF_HUB_DISABLE_SSL_VERIFY'] = '1'


class KnowledgeBaseManager:
    """
    知识库管理器
    负责文档导入、索引更新
    """

    def __init__(
        self,
        embedding_model=None,
        faiss_retriever=None,
        data_dir: str = None,
        faiss_path: str = None
    ):
        """
        初始化知识库管理器

        Args:
            embedding_model: 嵌入模型
            faiss_retriever: FAISS检索器
            data_dir: 数据目录
            faiss_path: FAISS索引目录
        """
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = data_dir or os.path.join(base_dir, "data")
        self.faiss_path = faiss_path or os.path.join(base_dir, "faiss_db")

        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.faiss_path, exist_ok=True)

        # 延迟导入，避免循环依赖
        from .embedding import get_embedding_model
        from .retriever import get_faiss_retriever

        # 初始化嵌入模型和检索器
        if embedding_model is None:
            embedding_model = get_embedding_model()
            if hasattr(embedding_model, 'model') and embedding_model.model is None:
                embedding_model.load()

        self.embedding_model = embedding_model

        if faiss_retriever is None:
            # 创建独立的FAISS retriever，而不是使用全局共享实例
            faiss_retriever = FAISSRetriever(dimension=1024)
            if self.faiss_path and os.path.exists(os.path.join(self.faiss_path, "documents.json")):
                faiss_retriever.load(self.faiss_path)

        self.faiss_retriever = faiss_retriever

        logger.info(f"知识库管理器初始化: data_dir={self.data_dir}, faiss_path={self.faiss_path}")

    def parse_test_case(self, content: str, case_id: str = None) -> Dict[str, Any]:
        """
        解析测试用例

        Args:
            content: 测试用例内容
            case_id: 用例ID

        Returns:
            {"document": "...", "metadata": {...}}
        """
        # 清理HTML实体
        import html
        content = html.unescape(content)

        # 提取标题
        title_match = re.search(r'测试项[：:]\s*(.+?)(?:\n|$)', content)
        title = title_match.group(1).strip() if title_match else "未命名测试用例"

        # 构建文档格式
        case_id = case_id or "unknown"
        document = f"## 测试用例 (ID: {case_id})\n{content}"

        metadata = {
            "case_id": case_id,
            "title": title,
            "imported_at": datetime.now().isoformat()
        }

        return {
            "document": document,
            "metadata": metadata
        }

    def import_from_json(
        self,
        json_data: List[Dict],
        case_id_key: str = "case_id",
        content_key: str = "content",
        title_key: str = "title",
        use_test_case_format: bool = True,
        clear_first: bool = False
    ) -> Dict[str, Any]:
        """
        从JSON导入文档

        Args:
            json_data: JSON数据列表
            case_id_key: 用例ID的键名
            content_key: 内容的键名
            title_key: 标题的键名
            use_test_case_format: 是否使用测试用例格式(默认True)
            clear_first: 是否先清空现有数据(默认False)

        Returns:
            {"added": 数量, "errors": 数量, "total": 总数}
        """
        # 清空现有数据
        if clear_first and self.faiss_retriever:
            self.faiss_retriever.documents = []
            self.faiss_retriever.metadatas = []
            self.faiss_retriever.ids = []
            if self.faiss_retriever.index:
                import faiss
                self.faiss_retriever.index = faiss.IndexHNSWFlat(1024, 32)
            logger.info("已清空现有数据")

        documents = []
        metadatas = []
        ids = []

        errors = 0
        added = 0

        for i, item in enumerate(json_data):
            try:
                # 优先从 metadata 中获取 case_id，否则从顶层获取
                metadata = item.get('metadata', {})
                doc_id = metadata.get(case_id_key) or item.get(case_id_key, f"case_{i+1}")
                content = item.get(content_key, "")

                if not content:
                    errors += 1
                    continue

                # 根据格式参数选择处理方式
                if use_test_case_format:
                    parsed = self.parse_test_case(content, doc_id)
                    # 保留原始 metadata 中的信息
                    if metadata:
                        parsed["metadata"]["source"] = metadata.get("source", "zentao_cases")
                    documents.append(parsed["document"])
                    metadatas.append(parsed["metadata"])
                    ids.append(f"case_{doc_id}")
                else:
                    # 通用格式：直接使用原始内容
                    import html
                    content = html.unescape(content)
                    documents.append(content)
                    metadatas.append({
                        "doc_id": doc_id,
                        "imported_at": datetime.now().isoformat()
                    })
                    ids.append(doc_id)

                added += 1

            except Exception as e:
                logger.warning(f"解析第{i+1}条失败: {e}")
                errors += 1

        # 添加到FAISS
        if documents:
            self._add_documents(documents, metadatas, ids)

        logger.info(f"导入完成: 添加={added}, 错误={errors}, 总数={len(json_data)}")

        return {
            "added": added,
            "errors": errors,
            "total": len(json_data),
            "total_vectors": self.faiss_retriever.count() if self.faiss_retriever else 0
        }

    def import_from_file(
        self,
        file_path: str,
        file_type: str = None
    ) -> Dict[str, Any]:
        """
        从文件导入测试用例

        Args:
            file_path: 文件路径
            file_type: 文件类型 (json/txt), 默认自动检测

        Returns:
            导入结果
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 自动检测文件类型
        if file_type is None:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".json":
                file_type = "json"
            elif ext in [".txt", ".md"]:
                file_type = "txt"
            else:
                raise ValueError(f"不支持的文件类型: {ext}")

        logger.info(f"从文件导入: {file_path}, 类型: {file_type}")

        if file_type == "json":
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 支持两种格式：列表 或 {"cases": [...], "data": [...]}
            if isinstance(data, dict):
                if "cases" in data:
                    data = data["cases"]
                elif "data" in data:
                    data = data["data"]
                elif "test_cases" in data:
                    data = data["test_cases"]

            return self.import_from_json(data)

        elif file_type == "txt":
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 按分隔符分割
            cases = re.split(r'--+-+--+|\n={3,}\n', content)
            cases = [c.strip() for c in cases if c.strip()]

            json_data = [{"case_id": f"imported_{i+1}", "content": c} for i, c in enumerate(cases)]
            return self.import_from_json(json_data)

    def _add_documents(
        self,
        documents: List[str],
        metadatas: List[Dict],
        ids: List[str]
    ):
        """添加文档到向量库"""
        # 批量编码
        embeddings = self.embedding_model.encode(documents)

        # 添加到FAISS
        import numpy as np
        self.faiss_retriever.index.add(embeddings.astype('float32'))
        self.faiss_retriever.documents.extend(documents)
        self.faiss_retriever.metadatas.extend(metadatas)
        self.faiss_retriever.ids.extend(ids)

        logger.info(f"已添加 {len(documents)} 个文档到FAISS")

    def save_index(self) -> Dict[str, Any]:
        """保存索引到磁盘"""
        if not self.faiss_retriever:
            return {"error": "索引器未初始化"}

        # 保存FAISS
        self.faiss_retriever.save(self.faiss_path)

        # 保存文档列表
        docs_file = os.path.join(self.faiss_path, "documents.json")
        with open(docs_file, 'w', encoding='utf-8') as f:
            json.dump({
                'documents': self.faiss_retriever.documents,
                'metadatas': self.faiss_retriever.metadatas,
                'ids': self.faiss_retriever.ids,
                'dimension': self.faiss_retriever.dimension,
                'updated_at': datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)

        logger.info(f"索引已保存: {self.faiss_path}")

        return {
            "success": True,
            "path": self.faiss_path,
            "vector_count": self.faiss_retriever.count()
        }

    def rebuild_index(
        self,
        source_file: str = None,
        batch_size: int = 100
    ) -> Dict[str, Any]:
        """
        重建整个索引

        Args:
            source_file: 源数据文件路径
            batch_size: 批处理大小

        Returns:
            重建结果
        """
        import faiss
        import numpy as np

        # 加载数据
        if source_file is None:
            source_file = os.path.join(self.data_dir, "zentao_rag.json")

        if not os.path.exists(source_file):
            return {"error": f"源文件不存在: {source_file}"}

        logger.info(f"重建索引: 从 {source_file}")

        with open(source_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        logger.info(f"加载数据: {len(data)} 条记录")

        # 重建索引
        dimension = 1024
        self.faiss_retriever.index = faiss.IndexHNSWFlat(dimension, 32)
        self.faiss_retriever.documents = []
        self.faiss_retriever.metadatas = []
        self.faiss_retriever.ids = []

        # 批量编码
        for i in range(0, len(data), batch_size):
            batch = data[i:i+batch_size]
            documents = []
            metadatas = []
            ids = []

            for j, item in enumerate(batch):
                case_id = item.get('metadata', {}).get('case_id', str(i+j+1))
                content = item.get('content', '')

                if content:
                    parsed = self.parse_test_case(content, case_id)
                    documents.append(parsed["document"])
                    metadatas.append(parsed["metadata"])
                    ids.append(f"case_{case_id}")

            if documents:
                embeddings = self.embedding_model.encode(documents)
                self.faiss_retriever.index.add(embeddings.astype('float32'))
                self.faiss_retriever.documents.extend(documents)
                self.faiss_retriever.metadatas.extend(metadatas)
                self.faiss_retriever.ids.extend(ids)

            if (i + batch_size) % 500 == 0:
                logger.info(f"进度: {min(i+batch_size, len(data))}/{len(data)}")

        # 保存
        result = self.save_index()

        result.update({
            "source_file": source_file,
            "total_documents": len(data),
            "indexed_documents": len(self.faiss_retriever.documents),
            "vector_count": self.faiss_retriever.count()
        })

        logger.info(f"索引重建完成: {result}")
        return result

    def search(self, query: str, top_k: int = 3) -> List[Dict]:
        """
        搜索知识库

        Args:
            query: 查询文本
            top_k: 返回结果数

        Returns:
            检索结果列表
        """
        if not self.faiss_retriever or self.faiss_retriever.count() == 0:
            logger.warning(f"知识库为空或未加载: {self.faiss_path}")
            return []

        # 编码查询
        query_vector = self.embedding_model.encode(query)

        # 检索
        results = self.faiss_retriever.search(query_vector, top_k=top_k)

        return results

    def get_status(self) -> Dict[str, Any]:
        """获取知识库状态"""
        vector_count = self.faiss_retriever.count() if self.faiss_retriever else 0
        doc_count = len(self.faiss_retriever.documents) if self.faiss_retriever else 0

        # 检查源文件
        source_file = os.path.join(self.data_dir, "zentao_rag.json")
        source_exists = os.path.exists(source_file)
        source_count = 0
        if source_exists:
            try:
                with open(source_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    source_count = len(data)
            except:
                pass

        return {
            "vector_count": vector_count,
            "document_count": doc_count,
            "dimension": 1024,
            "source_file": source_file,
            "source_exists": source_exists,
            "source_count": source_count,
            "faiss_path": self.faiss_path
        }

    def get_documents(self) -> List[Dict]:
        """获取所有文档列表"""
        if not self.faiss_retriever:
            return []

        documents = []
        for i, (doc, meta, doc_id) in enumerate(zip(
            self.faiss_retriever.documents,
            self.faiss_retriever.metadatas,
            self.faiss_retriever.ids
        )):
            documents.append({
                "index": i,
                "id": doc_id,
                "content": doc[:500] if len(doc) > 500 else doc,  # 截断显示
                "full_content": doc,
                "metadata": meta
            })
        return documents

    def add_document(self, content: str, metadata: Dict = None) -> Dict[str, Any]:
        """添加单个文档"""
        if not self.faiss_retriever:
            return {"success": False, "error": "向量库未初始化"}

        try:
            # 解析测试用例格式
            parsed = self.parse_test_case(content, f"manual_{len(self.faiss_retriever.documents)+1}")

            # 编码
            embeddings = self.embedding_model.encode([parsed["document"]])

            # 添加到FAISS
            import numpy as np
            self.faiss_retriever.index.add(embeddings.astype('float32'))
            self.faiss_retriever.documents.append(parsed["document"])
            self.faiss_retriever.metadatas.append(parsed["metadata"])
            self.faiss_retriever.ids.append(parsed["metadata"]["case_id"])

            # 保存
            self.save_index()

            return {
                "success": True,
                "index": len(self.faiss_retriever.documents) - 1,
                "doc_id": parsed["metadata"]["case_id"]
            }
        except Exception as e:
            logger.error(f"添加文档失败: {e}")
            return {"success": False, "error": str(e)}

    def update_document(self, doc_idx: int, new_content: str) -> Dict[str, Any]:
        """更新指定文档"""
        if not self.faiss_retriever:
            return {"success": False, "error": "向量库未初始化"}

        if doc_idx < 0 or doc_idx >= len(self.faiss_retriever.documents):
            return {"success": False, "error": "文档索引超出范围"}

        try:
            # 解析新内容
            old_id = self.faiss_retriever.ids[doc_idx]
            parsed = self.parse_test_case(new_content, old_id)

            # 更新文档内容
            self.faiss_retriever.documents[doc_idx] = parsed["document"]
            self.faiss_retriever.metadatas[doc_idx] = parsed["metadata"]

            # 重建索引（因为向量需要重新生成）
            # 注意：这里简化处理，实际应该更新对应向量
            logger.info(f"文档 {doc_idx} 已更新，需要重建索引以生效")

            return {
                "success": True,
                "message": "文档已更新，请重建索引"
            }
        except Exception as e:
            logger.error(f"更新文档失败: {e}")
            return {"success": False, "error": str(e)}

    def delete_document(self, doc_idx: int) -> Dict[str, Any]:
        """删除指定文档"""
        if not self.faiss_retriever:
            return {"success": False, "error": "向量库未初始化"}

        if doc_idx < 0 or doc_idx >= len(self.faiss_retriever.documents):
            return {"success": False, "error": "文档索引超出范围"}

        try:
            # 删除文档
            del self.faiss_retriever.documents[doc_idx]
            del self.faiss_retriever.metadatas[doc_idx]
            del self.faiss_retriever.ids[doc_idx]

            # 注意：FAISS索引不支持直接删除，需要重建
            logger.info(f"文档 {doc_idx} 已删除，需要重建索引")

            return {
                "success": True,
                "message": "文档已删除，需要重建索引"
            }
        except Exception as e:
            logger.error(f"删除文档失败: {e}")
            return {"success": False, "error": str(e)}


# 全局单例
_kb_manager = None


def get_kb_manager() -> KnowledgeBaseManager:
    """获取知识库管理器"""
    global _kb_manager

    if _kb_manager is None:
        _kb_manager = KnowledgeBaseManager()

    return _kb_manager


def init_kb_manager(
    embedding_model=None,
    faiss_retriever=None,
    data_dir: str = None,
    faiss_path: str = None
) -> KnowledgeBaseManager:
    """初始化知识库管理器"""
    global _kb_manager

    _kb_manager = KnowledgeBaseManager(
        embedding_model=embedding_model,
        faiss_retriever=faiss_retriever,
        data_dir=data_dir,
        faiss_path=faiss_path
    )

    return _kb_manager
