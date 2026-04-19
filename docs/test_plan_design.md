# 测试方案详细设计

## 1. 整体架构

```
用户需求 → test-plan-generator (总控 Skill)
                    │
                    ├─→ requirements-analysis (需求解析)
                    │       ↓ 输出: atoms JSON
                    │
                    ├─→ test-strategy-overview (生成概述)
                    │       ↓ 输出: 1 概述 Markdown
                    │
                    ├─→ test-strategy-functional (功能测试)
                    │       ↓ 调用 MCP API
                    │           ├─→ RAG 检索知识库
                    │           ├─→ LLM 生成测试用例
                    │           └─→ 输出: 2.1 功能测试 Markdown
                    │
                    └─→ test-strategy-non-functional (非功能测试)
                            ↓ 输出: 2.2 非功能测试 Markdown
```

---

## 2. Skill 体系

### 2.1 Skill 列表

| Skill | 路径 | 职责 |
|-------|------|------|
| `test-plan-generator` | `.claude/skills/test-plan-generator/` | 总控 Skill，调用子 Skill |
| `requirements-analysis` | `.claude/skills/requirements-analysis/` | 需求原子化解析 |
| `test-strategy-overview` | `.claude/skills/test-strategy-overview/` | 测试方案概述生成 |
| `test-strategy-functional` | `.claude/skills/test-strategy-functional/` | 功能测试生成（调用 MCP） |
| `test-strategy-non-functional` | `.claude/skills/test-strategy-non-functional/` | 非功能测试生成 |

### 2.2 test-plan-generator Skill

**文件**: `.claude/skills/test-plan-generator/SKILL.md`

```markdown
# 完整测试方案生成专家

## 交互流程

### Step 0: 获取用户需求（必做）
直接询问用户需求，等待用户输入

### Step 1: 需求原子化解析
调用 requirements-analysis Skill

### Step 2: 生成测试方案概述
调用 test-strategy-overview Skill

### Step 3: 生成功能测试
调用 test-strategy-functional Skill → MCP API

### Step 4: 生成非功能测试
调用 test-strategy-non-functional Skill

### Step 5: 整合输出
合并为完整测试方案文档
```

---

## 3. MCP 服务

### 3.1 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/mcp/health` | GET | 健康检查 |
| `/api/mcp/generate-test-strategy` | POST | 同步生成测试策略 |
| `/api/mcp/generate-test-strategy-async` | POST | 异步生成测试策略 |
| `/api/mcp/task/<task_id>` | GET | 查询异步任务状态 |
| `/api/mcp/token-stats` | GET | Token 统计 |

### 3.2 异步处理流程

```
POST /api/mcp/generate-test-strategy-async
    ↓
提交任务到线程池 (task_id)
    ↓
返回 task_id
    ↓
GET /api/mcp/task/{task_id} (轮询)
    ↓
status: processing → completed/failed
```

---

## 4. MCP 核心流程

### 4.1 主函数: process_test_strategy_async

```python
def process_test_strategy_async(task_id: str, atoms: List[dict]):
    """
    异步处理测试策略生成
    """
    # Step 1: RAG 检索
    enriched_modules = enrich_atoms_by_module(atoms)
    
    # Step 2: LLM 扩展测试用例
    for module_name, module_data in enriched_modules.items():
        expanded = expand_single_atom(atom, all_atoms_info, rag_context)
        final_modules[module_name] = expanded
    
    # Step 3: 生成 Markdown
    test_strategy = generate_strategy_markdown(all_atoms)
```

---

## 5. RAG 检索流程

### 5.1 流程图

```
atoms (输入)
    │
    ↓
group_atoms_by_module(atoms)
    │
    ↓
对每个模块:
    │
    ├─→ enrich_single_atom_with_rag(atom)
    │       │
    │       ├─→ get_qa_chain()
    │       │
    │       ├─→ 构建查询 (func_name + tags + business_logic + rules)
    │       │
    │       ├─→ qa_chain.embedding_model.encode_query(query)
    │       │
    │       ├─→ retriever.search(query_vector, top_k=5)
    │       │       │
    │       │       └─→ FAISS 向量数据库检索
    │       │
    │       ├─→ reranker.rerank(query, docs, top_k=3)
    │       │       │
    │       │       └─→ CrossEncoder 重排序
    │       │
    │       └─→ 返回 enriched_atom (包含 rag_context)
    │
    ↓
enriched_modules (输出)
```

### 5.2 检索代码详解

**文件**: `api/routes/mcp.py` 第 168-220 行

```python
def enrich_single_atom_with_rag(atom: dict) -> dict:
    """为单个原子功能进行 RAG 检索"""
    
    # 1. 获取 qa_chain 和 retriever
    qa_chain = get_qa_chain()
    retriever = qa_chain.retriever
    
    # 2. 构建查询字符串
    func_name = atom.get('function_name', '')      # 功能名称
    tags = atom.get('tags', [])                    # 标签
    business_logic = atom.get('business_logic', '')[:150]  # 业务逻辑
    rules = atom.get('rules', [])                  # 业务规则
    
    query = f"{func_name} {', '.join(tags[:5])} {business_logic} {' '.join(rules[:3])} 测试场景"
    
    # 3. 向量编码
    query_vector = qa_chain.embedding_model.encode_query(query)
    
    # 4. FAISS 向量检索 (top-5)
    docs = retriever.search(query_vector, top_k=5)
    
    # 5. Rerank 重排序 (top-3)
    reranker = get_reranker()
    if reranker and docs:
        reranked = reranker.rerank(query, docs, top_k=3)
        docs = [{'document': doc.get('document', '')} for doc in reranked]
    
    # 6. 提取上下文
    contexts = [doc.get('document', '') for doc in docs if doc.get('document')]
    rag_context = '\n\n'.join(contexts)
    
    return {**atom, 'rag_context': rag_context}
```

### 5.3 RAG 检索优化

| 优化项 | 说明 |
|--------|------|
| **并行检索** | 使用 ThreadPoolExecutor 并行处理多个 atoms |
| **跳过 HyDE** | 直接使用原始查询，不使用 HyDE 假设性文档 |
| **跳过 CRAG** | 不使用动态路由，简单直接检索 |
| **原子级 Rerank** | 使用 CrossEncoder 对检索结果重排序 |

---

## 6. LLM 生成流程

### 6.1 流程图

```
atoms + rag_context
    │
    ↓
expand_single_atom(atom, all_atoms_info, rag_context)
    │
    ├─→ 构建 Prompt (包含 RAG 上下文)
    │
    ├─→ llm.generate(prompt)
    │
    ├─→ parse_simple_test_cases(result)
    │
    ├─→ 语义去重 (deduplicate_scenarios)
    │
    └─→ 合并 RATP 已有 + LLM 生成
```

### 6.2 Prompt 设计

```python
prompt = f"""
你是一名资深测试架构师。请基于 RAG 知识库中的业务知识，
为以下功能补充更多测试场景。

## 当前功能信息
### 功能名称：{func_name}
### 业务逻辑：{business_logic}
### 触发条件：{trigger_condition}
### 业务规则：{', '.join(rules)}

## RAG 知识库检索的业务知识
{atom_rag_context}

## 场景要求
1. 包含车辆类型、操作步骤、预期结果
2. 验证点：记录类型、备注字段、车位数变化

## 输出格式
{{
    "normal": ["场景1", "场景2", "场景3"],
    "exception": ["异常1", "异常2", "异常3"]
}}
"""
```

---

## 7. Markdown 生成

### 7.1 函数: generate_strategy_markdown

**文件**: `api/routes/mcp.py` 第 674-706 行

```python
def generate_strategy_markdown(atoms: List[dict]) -> str:
    """生成测试策略 Markdown 格式"""
    
    # 按模块分组
    modules = group_atoms_by_module(atoms)
    
    output = []
    output.append("## 2 测试策略")
    output.append("### 2.1 功能测试")
    
    for module_name, module_atoms in modules.items():
        output.append(f"#### {module_name}")
        output.append("| 序号 | 模块功能项 | 测试方法及说明 |")
        output.append("| ---- | ---------- | -------------- |")
        
        for idx, atom in enumerate(module_atoms, 1):
            func_name = atom.get('function_name', '')
            test_desc = format_test_description(atom)
            output.append(f"| {idx} | {func_name} | {test_desc} |")
    
    return '\n'.join(output)
```

### 7.2 输出格式示例

```markdown
## 2 测试策略

### 2.1 功能测试

#### 通道引擎对接

| 序号 | 模块功能项 | 测试方法及说明 |
| ---- | ---------- | -------------- |
| 1 | 车辆闸前/中倒车 | **正常场景：**<br>1、场景描述...<br><br>**异常场景：**<br>1、异常描述... |
| 2 | 逆行入场事件 | **正常场景：**<br>1、... |
```

---

## 8. 数据流总结

```
用户输入需求
    │
    ↓
test-plan-generator (Skill)
    │
    ├─→ requirements-analysis → atoms JSON
    │
    ├─→ test-strategy-overview → 1 概述
    │
    ├─→ MCP API → RAG + LLM → 2.1 功能测试
    │       │
    │       ├─→ enrich_atoms_by_module()
    │       │       └─→ enrich_single_atom_with_rag()
    │       │               ├─→ embedding_model.encode_query()
    │       │               ├─→ retriever.search() → FAISS
    │       │               └─→ reranker.rerank()
    │       │
    │       └─→ expand_single_atom()
    │               ├─→ build prompt
    │               ├─→ llm.generate()
    │               └─→ parse_test_cases()
    │
    └─→ test-strategy-non-functional → 2.2 非功能测试
    │
    ↓
完整测试方案 (Markdown)
```

---

## 10. 实际示例：智慧停车场通道引擎V4.0需求

### 10.1 用户输入的原始需求

用户提供了智慧停车场系统通道引擎V4.0的完整需求文档，包含：

**业务场景列表：**
| 场景名称 | 正常场景描述 | 异常场景描述 |
|---------|-------------|-------------|
| 通道引擎流程优化 | 1、对于车辆倒车事件后续记录业务闭环；2、伪车牌事件上传后，通过综合判断车道上车辆为真车，通过纠正方式二次鉴权 | 1、对于车辆倒车事件，车辆再次出场不能正常计费，业务不闭环 |
| 防逃费业务优化 | 平台根据数据中心出场记录进行匹配并查询前端软件算费情况 | 前端软件算费后不能生成对应的预补录信息 |
| 控制机交互设置 | 播放配置的闲时显示场景语音按照上位机下发的进行播报 | 1、语音播报下发失败；2、语音文字播报显示延迟 |

**功能列表（14个功能）：**

| 模块 | 功能名称 | 类型 |
|------|---------|------|
| 通道引擎对接 | 车辆倒车检测优化 | 优化 |
| 通道引擎对接 | 逆行入场事件 | 优化 |
| 通道引擎对接 | 逆行出场事件 | 优化 |
| 通道引擎对接 | 伪车牌事件上传 | 新增 |
| 通道引擎对接 | 车牌纠正事件处理 | 新增 |
| 通道引擎对接 | 撞杆告警事件上传 | 优化 |
| 通道引擎对接 | AI识别车辆滞留事件上传 | 优化 |
| 防逃费业务优化 | 逃费事件判断 | 新增 |
| 防逃费业务优化 | 防逃费线上追缴 | 新增 |
| 防逃费业务优化 | 前端软件算费 | 新增 |
| 防逃费业务优化 | 防逃费新增字段 | 新增 |
| 防逃费业务优化 | 防逃费线上鉴权 | 新增 |
| 防逃费业务优化 | 防逃费优惠优化 | 新增 |
| 停车场语音交互优化 | 控制机屏幕闲时显示配置 | 新增 |
| 停车场语音交互优化 | 控制机场景语音配置 | 优化 |

### 10.2 Step 1: 需求原子化解析 (atoms)

`requirements-analysis` Skill 将需求解析为 14 个 atoms，输出文件：`atoms_20260418_172000.json`

**示例 atoms：**

```json
{
  "module": "通道引擎对接",
  "function_id": "F-01",
  "function_name": "车辆闸前/中倒车",
  "business_logic": "针对倒车事件进行检测及后续记录闭环。倒车事件共两种情况：一种是下位机给了先驶离通知再给倒车事件，另一种是只给了倒车事件。闸前倒车：只给倒车事件不给驶离通知；闸后倒车：给驶离通知和倒车事件。",
  "trigger_condition": "车辆在道闸前/中倒车，触发道闸地感/雷达",
  "rules": [
    "先有驶离通知再倒车：先生成出场记录，再生成新入场记录",
    "只有倒车事件：按现有压地感倒车逻辑处理",
    "倒车生成入场记录时间晚于场内最早月转临入场时间，月转临车辆转为月卡车"
  ],
  "tags": ["通道引擎", "倒车", "闸前", "闸后"],
  "test_cases": {
    "normal": ["A车闸前倒车只生成倒车事件", "A车闸后倒车先生成出场再生成入场"],
    "exception": ["倒车后再次出场计费异常", "多位多车倒车场景"]
  }
}
```

### 10.3 Step 2: 生成测试方案概述

`test-strategy-overview` Skill 生成 1 概述部分，输出文件：`test_plan_overview_20260418_172000.md`

```markdown
# 1 概述

本次版本主要实现智慧停车场系统通道引擎V4.0优化，对接防逃费V2.5业务，
同时优化控制机语音交互功能...

## 1.1 测试目的
通过对软件全面检查和测试，可以验证系统的功能与非功能与需求规格是否一致...

## 1.2 测试范围
### 1.2.1 功能测试
#### ◆ 通道引擎对接
1) 车辆闸前/中倒车 - 区分闸前/闸中倒车场景，验证记录闭环逻辑
2) 逆行入场事件 - 逆行入场触发录像抓拍，上传天启平台
...
```

### 10.4 Step 3: 生成功能测试 (MCP + RAG + LLM)

`test-strategy-functional` Skill 调用 MCP API：
1. **RAG 检索** - 查询知识库获取相关测试用例
2. **LLM 扩展** - 基于 RAG 结果生成详细测试场景
3. **Markdown 生成** - 输出测试表格

**MCP 调用的 RAG 检索日志：**
```
[MCP-xxxxxx] ========== Step 1: RAG 检索 ==========
[RAG] 开始检索模块 '通道引擎对接'，共 7 个原子功能
[RAG] 车辆闸前/中倒车 - 召回: 3 条, 1500 字符
[Rerank] 车辆闸前/中倒车 - rerank后: 3 条
[RAG] 逆行入场事件 - 召回: 3 条, 1200 字符
...

[MCP-xxxxxx] ========== Step 2: LLM 生成详细测试用例 ==========
[LLM] 处理功能: 车辆闸前/中倒车, RATP已有-正常:2, 异常:2
[LLM] 车辆闸前/中倒车 返回结果: 正常场景：1、...
[LLM] 车辆闸前/中倒车 - 最终正常:5, 异常:4

[MCP-xxxxxx] ========== Step 3: 生成 Markdown ==========
```

**输出文件：** `test_strategy_functional_20260418_172000.md`

### 10.5 Step 4: 生成非功能测试

`test-strategy-non-functional` Skill 生成 2.2 非功能测试部分

**输出文件：** `test_strategy_non_functional_20260418_172000.md`

```markdown
### 2.2.3 兼容性测试
| 序号 | 模块功能项 | 测试方法及说明 |
| --- | --- | --- |
| 1 | 防逃费版本兼容 | 验证防逃费V2.0和V2.5版本混用兼容性 |
| 2 | 控制机版本兼容 | 验证控制机JSQ1104 3.0.0及以上版本兼容性 |

### 2.2.4 可靠性测试
| 序号 | 功能项 | 测试描述 |
| --- | --- | --- |
| 1 | Jielink长时间运行稳定性 | 通道引擎长时间运行稳定性测试 |
| 2 | 倒车事件处理可靠性 | 倒车事件多次触发时的记录闭环 |
```

### 10.6 Step 5: 整合输出

最终完整测试方案输出文件：`test_plan_full_20260418_172000.md`

**文档结构：**
```markdown
# 智慧停车场系统通道引擎V4.0测试方案

## 1 概述
## 1.1 测试目的
## 1.2 测试范围
    ### 1.2.1 功能测试（14个功能模块）
    ### 1.2.2 非功能测试

## 2 测试策略
    ### 2.1 功能测试（详细测试用例）
    ### 2.2 非功能测试

## 1.3 风险及规避措施
## 1.4 测试依据及参考
```

---

## 11. 生成的输出文件列表

| 文件名 | 说明 |
|--------|------|
| `atoms_20260418_172000.json` | 需求原子化解析结果 |
| `test_plan_overview_20260418_172000.md` | 测试方案概述 |
| `test_strategy_functional_20260418_172000.md` | 功能测试详细用例 |
| `test_strategy_non_functional_20260418_172000.md` | 非功能测试 |
| `test_plan_full_20260418_172000.md` | 完整测试方案（整合版） |
