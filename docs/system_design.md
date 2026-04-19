# Test Strategy Generator 系统详细设计

## 1. 系统概述

### 1.1 系统定位
**Test Strategy Generator** 是一个基于 RAG + LLM 的测试策略自动生成系统，聚焦于将原子化需求文档转换为完整的测试策略文档。

### 1.2 核心能力
- **MCP 协议服务**：提供 RESTful API 供外部调用
- **两级 RAG 检索**：模块级（业务流视图）+ 原子级（校验点视图）
- **异步处理**：支持任务队列和轮询机制
- **动态过滤**：基于阈值的检索结果质量控制
- **延迟加载**：模型在首次请求时加载，减少启动内存

### 1.3 系统特点
- **单一知识库**：聚焦测试用例知识库 (kb_use_cases)
- **简化架构**：无多知识库、无复杂路由
- **专注核心**：原子化需求 → 测试策略生成

### 1.4 技术栈
| 层级 | 技术 |
|------|------|
| Web 框架 | Flask |
| 向量数据库 | FAISS |
| 嵌入模型 | BAAI/bge-large-zh-v1.5 |
| Reranker | CrossEncoder (CPU) |
| LLM | DeepSeek Chat |
| 缓存 | Python dict / 可扩展 Redis |

---

## 2. 系统架构

### 2.1 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    交互层 (API Layer)                        │
│  Flask REST API | MCP 协议 | 异步任务队列                   │
├─────────────────────────────────────────────────────────────┤
│                    业务层 (Business Layer)                   │
│  路由注册 | 缓存管理 | 性能监控 | 日志                      │
├─────────────────────────────────────────────────────────────┤
│                    AI核心层 (AI Core Layer)                  │
│  QAChain | Embedding | Retriever | Reranker | LLM         │
├─────────────────────────────────────────────────────────────┤
│                    数据层 (Data Layer)                      │
│  FAISS向量库 | 知识库 | 配置管理                           │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
rag/
├── app.py                      # Flask 应用入口
├── config/                     # 配置模块
│   ├── settings.py             # 统一配置入口
│   ├── models_config.py       # 模型配置
│   ├── prompts.py             # Prompt 模板
│   ├── logging_config.py      # 日志配置
│   └── __init__.py
├── ai_core/                    # AI 核心层
│   ├── chains.py              # QAChain 工作流编排
│   ├── embedding.py           # 嵌入模型
│   ├── retriever.py          # FAISS 检索器
│   ├── hybrid_retriever.py   # 混合检索
│   ├── reranker.py           # CrossEncoder 重排
│   ├── llm.py                # LLM 调用
│   ├── prompt.py             # Prompt 模板
│   ├── query_rewriter.py     # Query 改写
│   ├── knowledge_base.py     # 知识库管理 (单一)
│   └── __init__.py
├── api/routes/                 # API 路由
│   ├── mcp.py                # MCP 测试策略生成
│   ├── utils.py              # 工具接口
│   ├── register.py           # 路由注册
│   └── __init__.py
├── business/                   # 业务层
│   ├── cache.py              # 缓存管理
│   ├── logger.py             # 日志
│   └── __init__.py
├── data/                      # 数据目录
│   ├── test_requirements/    # 测试需求输入
│   ├── test_strategies/      # 测试策略输出
│   ├── kb_use_cases/        # 知识库 (单一)
│   └── faiss_db/            # FAISS 向量库
└── tests/                    # 单元测试
```

### 2.3 已移除组件
为保持系统简洁，已移除以下组件：
- ~~`api/routes/knowledge.py`~~ - 知识库管理路由
- ~~`api/routes/multi_kb.py`~~ - 多知识库路由
- ~~`ai_core/kb_router.py`~~ - 知识库路由器
- ~~`ai_core/web_search/`~~ - Web 搜索模块
- ~~`ai_core/crag.py`~~ - CRAG 评估模块

当前系统聚焦于**测试用例生成**单一场景。

### 3.1 MCP 测试策略生成 (api/routes/mcp.py)

#### 3.1.1 核心流程

```
用户输入 atoms
    │
    ▼
┌──────────────────────────────┐
│  1. 分组 (group_atoms_by_module)  │
│     按 module 字段分组              │
└──────────────────────────────┘
    │
    ▼
┌──────────────────────────────┐
│  2. 两级 RAG 检索               │
│  ├─ 模块级 (enrich_module_with_rag) │
│  │   Query: 业务流程 + 整体架构   │
│  │   缓存: _module_context_cache   │
│  └─ 原子级 (enrich_atom_with_rag)  │
│      Query: 功能名 + 规则 + 校验   │
└──────────────────────────────┘
    │
    ▼
┌──────────────────────────────┐
│  3. LLM 扩展 (expand_single_atom) │
│     Token 统计 | 语义去重         │
└──────────────────────────────┘
    │
    ▼
┌──────────────────────────────┐
│  4. 生成 Markdown               │
│     按模块输出测试表格              │
└──────────────────────────────┘
```

#### 3.1.2 关键函数

| 函数 | 职责 |
|------|------|
| `group_atoms_by_module()` | 按 module 字段分组 |
| `clear_module_cache()` | 清除模块级缓存 |
| `enrich_module_with_rag()` | 模块级 RAG 检索，带缓存 |
| `enrich_atom_with_rag_optimized()` | 原子级 RAG 检索，差异化 Query |
| `enrich_atoms_by_module()` | 两级检索主流程 |
| `expand_single_atom()` | LLM 扩展单原子 |
| `generate_strategy_markdown()` | 生成 Markdown |

#### 3.1.3 缓存机制

```python
# 模块级缓存（任务内复用）
_module_context_cache = {}

# Token 统计
_token_stats = {
    'total_input_tokens': 0,
    'total_output_tokens': 0,
    'llm_call_count': 0
}
```

### 3.2 QAChain 工作流 (ai_core/chains.py)

#### 3.2.1 支持模式

| 模式 | 说明 | 启用条件 |
|------|------|----------|
| Pipeline | 快速检索 + 自动质量评估 | 默认 |
| Agent | 完整流程 (Query改写+混合检索+CRAG) | enable_crag=True |
| 自动决策 | 根据质量选择最佳路径 | quality_threshold |

#### 3.2.2 配置参数

```python
FEATURE_FLAGS = {
    "enable_fusion": True,        # 混合检索
    "enable_hyde": True,         # HyDE 增强
    "enable_crag": False,        # CRAG 评估
    "enable_query_rewrite": True,# Query 改写
    "enable_rerank": True,       # 重排
    "enable_cache": True,        # 缓存
}
```

### 3.3 嵌入模型 (ai_core/embedding.py)

- **模型**: BAAI/bge-large-zh-v1.5
- **向量维度**: 1024
- **加载方式**: 延迟加载 (Lazy Loading)
- **用途**: 文本向量化、Query 编码

```python
def get_embedding_model():
    """延迟加载，首次调用时加载模型"""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = EmbeddingModel()
        _embedding_model.load(_embedding_model_path)
    return _embedding_model
```

### 3.1 AI 核心层模块

| 模块 | 文件 | 说明 |
|------|------|------|
| QAChain | `ai_core/chains.py` | 工作流编排 |
| 嵌入模型 | `ai_core/embedding.py` | BAAI/bge-large-zh-v1.5 |
| 检索器 | `ai_core/retriever.py` | FAISS 向量检索 |
| 混合检索 | `ai_core/hybrid_retriever.py` | 向量 + 关键词融合 |
| 重排 | `ai_core/reranker.py` | CrossEncoder 重排 |
| LLM | `ai_core/llm.py` | DeepSeek 调用 |
| Query改写 | `ai_core/query_rewriter.py` | 查询优化 |

### 3.5 Reranker (ai_core/reranker.py)

- **模型**: CrossEncoder
- **设备**: CPU
- **用途**: 对检索结果进行重排，提升质量

### 3.6 LLM (ai_core/llm.py)

- **供应商**: DeepSeek
- **模型**: deepseek-chat
- **特性**: Token 统计、流式输出支持

---

## 4. API 设计

### 4.1 MCP 测试策略 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/mcp/health` | GET | 健康检查 |
| `/api/mcp/generate-test-strategy` | POST | 同步生成 |
| `/api/mcp/generate-test-strategy-async` | POST | 异步生成 |
| `/api/mcp/task/<task_id>` | GET | 任务状态 |
| `/api/mcp/token-stats` | GET | Token 统计 |

### 4.2 请求格式

```json
{
  "atoms": [
    {
      "module": "通道引擎对接",
      "function_id": "F-01",
      "function_name": "车辆闸前/中倒车",
      "business_logic": "针对倒车事件进行检测...",
      "rules": ["规则1", "规则2"],
      "tags": ["通道引擎", "倒车"]
    }
  ]
}
```

### 4.3 响应格式

```json
{
  "success": true,
  "status": "completed",
  "result": "## 2 测试策略\n\n### 2.1 功能测试\n...",
  "atom_count": 11,
  "output_file": "data/test_strategies/test_strategy_xxx.md"
}
```

---

## 5. 数据流设计

### 5.1 测试策略生成流程

```
1. 输入验证
   └─> atoms JSON 格式校验

2. 任务创建
   └─> 生成 task_id
   └─> 存入 _async_tasks
   └─> 提交到 ThreadPoolExecutor

3. 分组处理
   └─> group_atoms_by_module(atoms)
   └─> 输出: {module_name: [atoms]}

4. 两级 RAG
   ├─ 模块级 (每个模块1次)
   │   ├─ enrich_module_with_rag()
   │   ├─ 缓存检查
   │   └─ 输出: module_context
   │
   └─ 原子级 (每个原子1次)
       ├─ enrich_atom_with_rag_optimized()
       ├─ 合并 module_context + atom_context
       └─ 输出: rag_context

5. LLM 扩展
   ├─ expand_single_atom()
   ├─ Token 统计
   └─ 输出: test_cases

6. Markdown 生成
   └─ generate_strategy_markdown()

7. 文件保存
   └─> data/test_strategies/test_strategy_{timestamp}.md
```

### 5.2 异步任务状态机

```
pending → processing → completed
                   └─> failed
```

---

## 6. 配置管理

### 6.1 配置层级

| 层级 | 来源 | 优先级 |
|------|------|--------|
| 环境变量 | os.environ | 最高 |
| settings.py | 硬编码配置 | 中 |
| 模型配置 | models_config.py | 低 |

### 6.2 关键配置项

```python
# 目录配置
DATA_DIR = "data"
TEST_REQUIREMENTS_DIR = "test_requirements"
TEST_STRATEGIES_DIR = "test_strategies"
FAISS_DIR = "faiss_db"

# 知识库配置 (单一)
DEFAULT_KB = "kb_use_cases"

# 模型配置
EMBEDDING_MODEL = "BAAI/bge-large-zh-v1.5"
EMBEDDING_DIM = 1024

# API 配置
DEEPSEEK_API_KEY = "sk-xxx"
DEEPSEEK_MODEL = "deepseek-chat"

# 功能开关
FEATURE_FLAGS = {
    "enable_fusion": True,
    "enable_hyde": True,
    "enable_rerank": True,
    ...
}
```

---

## 7. 扩展点设计

### 7.1 缓存扩展

当前使用 dict，可扩展为 Redis：

```python
# business/cache.py
class Cache:
    def get(self, key):
        # 可替换为 Redis
        return self._cache.get(key)
```

### 7.2 模型扩展

- 嵌入模型: 修改 `embedding.py`
- LLM: 修改 `llm.py`
- Reranker: 修改 `reranker.py`

### 7.3 知识库扩展

- 知识库配置: `config/settings.py` 中的 `DEFAULT_KB`
- 知识库路径: `data/kb_use_cases/`
- FAISS 索引: `faiss_db/kb_use_cases/`

---

## 8. 部署配置

### 8.1 启动方式

```bash
# 延迟加载模式 (推荐，内存占用小)
python app.py

# 立即加载模式
# 修改 app.py: init(lazy=False)
```

### 8.2 端口配置

```python
FLASK_CONFIG = {
    "PORT": 5000,
    "THREADED": True,
}
```

### 8.3 日志

```
logs/
├── app_20260419.log
└── error_20260419.log
```

---

## 9. 性能优化

### 9.1 已实现优化

| 优化项 | 说明 |
|--------|------|
| 延迟加载 | 模型在首次请求时加载 |
| 模块级缓存 | 同模块不重复 RAG |
| Query 改写 | 简化 Query 提升检索精度 |
| 异步处理 | 任务队列 + 轮询 |
| Token 限制 | 模块 ≤2000 字符，原子 ≤4000 字符 |

### 9.2 可选优化

- Redis 缓存
- ONNX 加速
- 并行 RAG (ThreadPoolExecutor)

---

## 10. 测试

### 10.1 单元测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定测试
pytest tests/test_two_tier_rag.py -v
```

### 10.2 测试覆盖

- 两级 RAG 检索
- 动态过滤
- 模块缓存
- Token 限制
