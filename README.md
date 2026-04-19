# Test Strategy Generator

基于 RAG + LLM 的测试策略自动生成系统

---
## 0. 产品展示
.\product_show.md

## 1. 系统概述

### 1.1 系统定位

**Test Strategy Generator** 是一个基于 RAG + LLM 的测试策略自动生成系统，聚焦于将原子化需求文档转换为完整的测试策略文档。

### 1.2 核心能力

- **两级 RAG 检索**：模块级（业务流视图）+ 原子级（校验点视图）
- **LLM 扩展**：基于知识库补充测试场景
- **语义去重**：避免重复测试用例
- **Skill 集成**：Claude Code 一键调用

### 1.3 技术栈

| 层级 | 技术 |
|------|------|
| 向量数据库 | FAISS |
| 嵌入模型 | BAAI/bge-large-zh-v1.5 |
| Reranker | CrossEncoder (CPU) |
| LLM | DeepSeek Chat |

---

## 2. 快速开始

### 2.1 环境要求

- Python 3.8+
- DeepSeek API Key（在 [config/settings.py](config/settings.py) 中配置）

### 2.2 安装依赖

```bash
pip install -r requirements.txt
```

### 2.3 使用方式

本系统通过 **Claude Code Skill** 提供交互式使用。

#### 启动 Skill

在 Claude Code 中输入：

```
/test-plan-generator
```

然后描述你的需求，例如：

```
# 3．场景与功能需求

## 3.1业务场景过程

无

## 3.2业务场景列表

核心业务场景列表：

<table border="1" ><tr>
<td>场景名称</td>
<td>正常场景描述</td>
<td>异常场景描述</td>
</tr><tr>
<td>通道引擎流程优化</td>
<td>1 、对于车辆倒车事件后续记录业务闭环；<br>2 、伪车牌事件上传后，通过综合判断车道上车辆为真车，通过纠正方式二次鉴权，解决部分真车被识别成伪牌无法放行的场景</td>
<td>1 、对于车辆倒车事件，车辆再次出场不能正常计费，业务不闭环</td>
</tr><tr>
<td>防逃费业务优化</td>
<td>平台根据数据中心出场记录进行匹配并查询前端软件算费情况，前端软件生成对应的预补录信息</td>
<td>前端软件算费后不能生成对应的预补录信息</td>
</tr><tr>
<td>控制机交互设置</td>
<td>播放配置的闲时显示场景语音按照上位机下发的进行播报</td>
<td>闲时显示配置下发失败，导致无法显示1 、语音播报下发失败；<br>2 、语音文字播报显示延迟</td>
</tr></table>
```

系统会自动：
1. 解析需求为原子功能 (atoms)
2. 生成测试方案概述 (1 概述)
3. 调用 RAG + LLM 生成功能测试 (2.1 功能测试)
4. 推理生成非功能测试 (2.2 非功能测试)
5. 整合输出完整测试方案

---

## 3. 使用示例

### 3.1 输入需求

用户只需描述需求，例如：

> 智慧停车场系统通道引擎V4.0
> - 通道引擎对接：倒车检测、逆行事件、伪车牌、车牌纠正、撞杆告警、车辆滞留
> - 防逃费业务优化：V2.5算费、线上追缴
> - 停车场语音交互优化：闲时显示、场景语音配置

### 3.2 输出测试方案

系统生成完整的测试方案文档，包含：

#### 1 概述
- 测试目的
- 功能测试范围
- 受影响产品及业务
- 非功能测试

#### 2.1 功能测试
| 序号 | 模块功能项 | 测试方法及说明 |
| ---- | ---------- | -------------- |
| 1 | 车辆闸前/中倒车 | **正常场景：**<br>月租车在嵌套车场出口识别开闸，车辆驶离触发驶离通知后倒车... |

#### 2.2 非功能测试
- 兼容性测试
- 可靠性测试
- 用户体验

### 3.3 生成的文件

```
data/test_strategies/
├── test_plan_overview_xxxxxx.md      # 测试方案概述
├── test_plan_functional_xxxxxx.md    # 功能测试
├── test_plan_non_functional_xxxxxx.md # 非功能测试
└── test_plan_full_xxxxxx.md          # 完整测试方案
```

---

## 4. 核心模块

### 4.1 Skill 列表

| Skill | 职责 |
|-------|------|
| `test-plan-generator` | 完整测试方案生成（总控） |
| `test-strategy-overview` | 测试方案概述生成 |
| `test-strategy-functional` | 功能测试生成 |
| `test-strategy-non-functional` | 非功能测试生成 |
| `requirements-analysis` | 需求原子化解析 |

### 4.2 核心函数

```python
# RAG 检索
from ai_core.chains import get_qa_chain
qa_chain = get_qa_chain()
docs = qa_chain.retriever.search(query_vector, top_k=5)

# 两级检索
from api.routes.mcp import enrich_atoms_by_module
enriched = enrich_atoms_by_module(atoms)

# LLM 扩展
from api.routes.mcp import expand_single_atom
expanded = expand_single_atom(atom, all_atoms_info)
```

---

## 5. 数据格式

### 5.1 atoms 输入格式

```json
{
  "atoms": [
    {
      "module": "通道引擎对接",
      "function_id": "F-01",
      "function_name": "车辆闸前/中倒车",
      "business_logic": "针对倒车事件进行检测及后续记录闭环",
      "trigger_condition": "车辆在道闸前/中倒车",
      "rules": ["先有驶离通知再倒车", "只有倒车事件"],
      "tags": ["通道引擎", "倒车"]
    }
  ]
}
```

### 5.2 输出测试策略格式

```markdown
## 2 测试策略

### 2.1 功能测试

| 序号 | 模块功能项 | 测试方法及说明 |
| ---- | ---------- | -------------- |
| 1 | 车辆闸前/中倒车 | **正常场景：**<br>... |
```

---

## 6. 目录结构

```
rag/
├── app.py                      # Flask 应用入口
├── config/                     # 配置模块
│   ├── settings.py             # 配置入口
│   └── models_config.py        # 模型配置
├── ai_core/                    # AI 核心层
│   ├── chains.py              # QAChain
│   ├── embedding.py           # 嵌入模型
│   ├── retriever.py          # FAISS 检索器
│   ├── reranker.py           # CrossEncoder 重排
│   └── llm.py                # LLM 调用
├── api/routes/                 # API 路由
│   ├── mcp.py                # 测试策略生成
│   └── register.py           # 路由注册
├── data/                      # 数据目录
│   ├── kb_use_cases/        # 知识库
│   ├── faiss_db/            # FAISS 向量库
│   └── test_strategies/     # 测试策略输出
└── .claude/skills/          # Claude Code Skills
    ├── test-plan-generator/
    ├── test-strategy-overview/
    ├── test-strategy-functional/
    └── test-strategy-non-functional/
```

---

## 7. 配置说明

### 7.1 DeepSeek API 配置

在 [config/settings.py](config/settings.py) 中修改：

```python
DEEPSEEK_API_KEY = "sk-xxx"  # 你的 API Key
```

### 7.2 知识库配置

```python
DEFAULT_KB = "kb_use_cases"  # 知识库名称
```

知识库路径：`data/kb_use_cases/`

---

## 8. 常见问题

### Q: 如何查看日志？
A: 日志位于 `logs/` 目录

### Q: 首次调用较慢？
A: 首次请求需要加载模型（约30秒），后续会使用缓存

---

## 9. License

MIT
