# langchain4j-techAgent-python

一个基于 FastAPI + LangGraph 构建的教育成绩分析 Agent 项目。支持上传学生成绩文档（PDF / Excel），通过智能列识别引擎自动解析为结构化数据，结合混合检索（向量 + BM25 + RRF）+ BGE 重排序实现精准 RAG，最终由 ReAct Agent 自主调用分析工具生成深度报告与 ECharts 图表。

## 项目简介

本项目面向"学生成绩分析"场景，核心能力包括：

- 上传学生成绩文档（PDF / `.xlsx` / `.xls`）
- 智能列识别引擎：自动适配宽表/长表布局，解析科目、学生、分数
- 结构化语义分块（按学生 / 科目 / 班级粒度）
- 调用 Embedding 模型生成向量
- 基于 `memoryId` 做会话隔离，原文、切块与向量按会话维度缓存
- 混合检索（余弦相似度 + BM25 关键词 + RRF 融合）+ BGE 重排序
- LangGraph ReAct Agent：自主推理并调用分析工具（班级概览、学生详情、偏科检测、图表生成等）
- SSE 流式对话，逐 token / 逐分析步骤实时返回
- 支持清理会话数据与文档数据

当前项目使用：

- `FastAPI` 提供 Web API
- `LangGraph` 编排 ReAct Agent 推理循环
- `PyPDF2` / `openpyxl` / `xlrd` 解析 PDF 与 Excel
- `Redis` 存储聊天记忆、成绩原文、文本切块与向量（全部按 `memoryId` 隔离）
- `langchain-openai` 调用 OpenAI 兼容聊天模型与 Embedding 模型
- `FlagEmbedding` 加载 BGE-Reranker-v2-M3 做本地重排序
- 默认对话模型：DeepSeek 兼容接口；默认 Embedding 模型：智谱 AI

## 项目功能

### 1. 成绩单上传
通过接口上传 PDF 或 Excel（`.xlsx` / `.xls`）成绩单，自动通过魔数检测分流解析器，提取文本内容。

### 2. 结构化成绩分析引擎
内置 `GradeAnalyzer`：自动识别表头行、分类列类型（姓名 / 学号 / 科目 / 分数），自适应宽表（一行一学生）与长表（一行一科目成绩）布局，解析后直接支持统计计算——无需 LLM 参与，毫秒级响应。

### 3. 混合检索 RAG
提取后的文本先按结构化语义切分为 chunk（按学生 / 科目 / 班级粒度），再调用 Embedding 生成向量。查询时走**混合检索管线**：

- 向量语义检索（余弦相似度）
- BM25 关键词检索（中文 bigram 分词）
- RRF（Reciprocal Rank Fusion）融合双路排名，候选池放大 3 倍
- BGE-Reranker-v2-M3 本地精排（失败时回退 LLM 打分）

### 4. ReAct Agent 智能问答
基于 LangGraph `create_react_agent`，将分析能力封装为 7 个 `@tool` 工具，LLM 自主判断调用哪个工具获取数据，再生成自然语言回复。支持流式输出，前端可实时看到"正在分析：xxx"的过程状态。

### 5. 图表生成
内置 `ChartGenerator`，可将分析数据转为 ECharts 配置 JSON，支持 6 种图表类型：各科平均分柱状图、学生雷达图、分数段分布、总分排名、偏科差距、班级总览。

### 6. 会话与文档清理
支持按 `memoryId` 一键清理：聊天记忆 + 成绩文档 + 向量数据 + 分析器实例。

## 项目结构

```text
langchain4j-techAgent-python/
├── ai_service/                 # Agent 服务层（ReAct Agent + 工具集）
│   └── consultant_service.py
├── config/                     # 配置加载与生产密文处理
│   ├── encrypt_config.py
│   └── settings.py
├── exception/                  # 自定义异常与全局异常处理
│   ├── bad_request_exception.py
│   └── global_exception_handler.py
├── models/                     # 数据模型（预留）
├── rag/                        # RAG 检索管线
│   ├── hybrid_retriever.py     #   混合检索：向量 + BM25 + RRF
│   ├── reranker.py             #   重排序：BGE 本地精排 / LLM 兜底
│   ├── retriever.py            #   向量检索 + Embedding 生成
│   └── text_splitter.py        #   文本切块 + 成绩语义分块
├── repository/                 # Redis 数据读写层
│   ├── redis_chat_memory_store.py
│   └── redis_grade_document_store.py
├── resources/                  # 系统提示词与静态资源
│   ├── static/
│   │   └── index.html
│   └── system.txt
├── routers/                    # 接口路由
│   └── ai_router.py
├── schemas/                    # 请求/响应模型
│   ├── analysis.py             #   成绩分析数据结构
│   ├── request.py
│   └── response.py
├── service/                    # 业务服务层
│   ├── chart_generator.py      #   图表数据生成（ECharts JSON）
│   ├── grade_analyzer.py       #   智能成绩分析引擎（列识别 + 统计）
│   └── grade_document_service.py
├── .env.dev                    # 本地开发配置（已忽略，不上传）
├── .env.prod.example           # 生产配置模板
├── .gitignore
├── main.py                     # 应用入口
└── requirements.txt
```

## 核心流程

### 成绩分析流程

1. 用户上传成绩文档（PDF / `.xlsx` / `.xls`）→ 魔数检测 → 分流到对应解析器
2. 提取文本 → `GradeAnalyzer` 智能列识别 + 宽表/长表自适应解析 → 生成结构化成绩记录
3. 原文以 `memoryId` 为键存入 Redis
4. `GradeTextSplitter` 按"学生 / 科目 / 班级"语义粒度切分为 chunk
5. 调用 Embedding 模型生成每个 chunk 的向量 → 存入 Redis
6. `HybridRetriever` 构建 BM25 索引（中文 bigram 分词）
7. 用户发起分析问题
8. ReAct Agent 自主推理：判断是否需要调用工具 → 调用工具获取结构化数据 → 汇总生成回复
9. 若需 RAG 补充上下文，走混合检索管线 → BGE 重排序 → 注入 Agent 上下文
10. SSE 流式返回分析结果 / 图表数据，前端实时渲染

### 会话数据流程

- 成绩文档原文 + chunk + 向量（Redis，key 含 `memoryId` 前缀）
- 聊天记忆（Redis List，`chat:memory:{memoryId}`，LRU 保留最近 20 轮）
- 结构化分析器实例 + 混合检索引擎实例（进程内存，按 `memoryId` 映射）
- 全部数据支持一键删除 + TTL 自动过期（86400s）

## 当前接口说明

接口统一前缀：`/ai`

### 1. 上传成绩单
`POST /ai/upload`

表单参数：

- `memoryId`: 会话 ID
- `file`: PDF / Excel（`.xlsx` / `.xls`）文件

功能：

- 上传并解析文档（自动识别格式）
- 结构化分析 + 文本提取存入 Redis

### 2. 成绩分析对话
`GET /ai/chat`

请求参数：

- `memoryId`: 会话 ID
- `message`: 用户问题

功能：

- ReAct Agent 自主调用工具获取分析数据
- 非流式返回完整分析结果

### 3. 流式对话（SSE）
`GET /ai/chat/stream`

请求参数：

- `memoryId`: 会话 ID
- `message`: 用户问题

功能：

- 逐 token 流式返回 LLM 回复
- 工具调用阶段返回"[正在分析：xxx]"状态提示
- 支持前端实时展示分析过程

### 4. 关闭会话
`DELETE /ai/session`

请求参数：

- `memoryId`: 会话 ID

功能：

- 删除 Redis 聊天记忆 + 成绩文档 + 向量数据
- 清理进程内存中的分析器与检索引擎实例

### 5. 删除成绩文档
`DELETE /ai/document`

请求参数：

- `memoryId`: 会话 ID

功能：

- 删除该会话对应的成绩文档与向量数据

## 配置说明

项目使用环境配置文件区分开发与生产环境。

### 开发环境

默认读取：

- `.env.dev`

主要配置项包括：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL_NAME`
- `EMBEDDING_API_KEY`
- `EMBEDDING_BASE_URL`
- `EMBEDDING_MODEL_NAME`
- `RAG_TOP_K`
- `RAG_CHUNK_SIZE`
- `RAG_CHUNK_OVERLAP`
- `REDIS_HOST`
- `REDIS_PORT`
- `REDIS_DATABASE`
- `REDIS_PASSWORD`
- `DATABASE_URL`
- `DATABASE_USERNAME`
- `DATABASE_PASSWORD`

说明：

- 当前模型调用通过 `langchain-openai` 的 OpenAI 兼容接口实现
- 聊天模型由 `OPENAI_*` 配置控制
- Embedding 模型由 `EMBEDDING_*` 配置控制；如果没有单独配置，会默认复用 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`
- 当 `OPENAI_BASE_URL=https://api.deepseek.com` 且模型为 `deepseek-v4-flash` 时，实际调用的是 DeepSeek 兼容接口
- 需要确认所配置的模型服务支持 Embedding 接口，否则上传文档时会在向量化阶段失败

### 生产环境

默认读取：

- `.env.prod`

生产环境下支持密文字段：

- `ZHIPU_API_KEY_ENC`
- `OPENAI_API_KEY_ENC`
- `EMBEDDING_API_KEY_ENC`
- `REDIS_PASSWORD_ENC`
- `DATABASE_PASSWORD_ENC`

并要求设置环境变量：

- `APP_CONFIG_SECRET`

说明：

- 当前仓库中的生产加密实现为轻量示例方案
- 如需正式上线，建议替换为更规范的密钥管理方案

## 本地运行

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 准备开发配置

在项目根目录创建 `.env.dev` 文件，并填写开发环境配置。

### 3. 设置运行环境

Windows PowerShell 示例：

```powershell
$env:APP_ENV="dev"
python .\main.py
```

或使用 uvicorn：

```powershell
$env:APP_ENV="dev"
uvicorn main:app --reload
```

### 4. 访问地址

默认启动后访问：

- 前端页面：`http://127.0.0.1:8000/static/index.html`
- 根路径：`http://127.0.0.1:8000/`

## Redis 说明

当前 Redis 主要承担两类数据：

### 1. 成绩文档缓存
- 原文键：`document:grade:{memoryId}`
- 切块与向量键：`document:grade:{memoryId}:chunks`（List 结构，每项为包含 index / content / embedding 的 JSON）

### 2. 聊天记忆缓存
- 键前缀：`chat:memory:{memoryId}`
- 以 List 存储每轮 user / assistant 消息

数据生命周期：

- 写入时自动设置 86400 秒 TTL
- `/ai/session` 接口主动删除 + 清理内存对象

## Agent 架构说明

### ReAct Agent
基于 LangGraph 的 `create_react_agent`，将分析能力封装为以下 `@tool` 工具：

| 工具名 | 功能 |
|---|---|
| `get_class_overview` | 班级整体概览（均分、最高/低分、及格率、优秀率、前5名） |
| `get_student_detail` | 学生详细分析（各科成绩、排名、优弱势科目、偏科检测） |
| `get_subject_distribution` | 科目分数段分布 |
| `get_top_students` | 总分前 N 名 |
| `get_pianke_students` | 偏科学生检测（极差 >30 分） |
| `get_weakest_subject` | 全班最弱科目 |
| `get_chart_data` | 生成 ECharts 图表 JSON |

系统提示词内置于 `ConsultantService`，核心约束：分析前必须先调用工具获取数据，严禁凭空编造。

### 重排序策略

- 优先：`BAAI/bge-reranker-v2-m3`（FlagEmbedding 本地推理，零 API 成本，每对约 15ms）
- 回退：LLM 0-10 分相关性评估（`LLMReranker`）

## 当前实现特点与注意事项

### 已实现
- 成绩文档上传（PDF / `.xlsx` / `.xls`）
- 智能列识别 + 宽表/长表自适应解析
- 结构化语义分块（学生 / 科目 / 班级粒度）
- 混合检索（向量 + BM25 + RRF 融合）
- BGE 本地重排序 + LLM 重排兜底
- Embedding 向量化
- Redis 文档与向量缓存
- LangGraph ReAct Agent（7 个分析工具 + 图表生成）
- 成绩分析问答（流式 SSE + 非流式）
- 图表数据生成（ECharts 兼容 JSON）
- 聊天记忆 Redis 持久化
- 基础异常处理
- 开发/生产配置分离

### 当前简化点
- 当前向量检索使用 Redis 存储向量数据，并在 Python 侧计算余弦相似度，适合小规模文档场景
- 生产配置加密方案仍可进一步增强

### 后续可优化方向
- 接入 Redis Vector Search、FAISS、Milvus 等专业向量数据库，支持 ANN 近似检索
- 增加 Swagger 使用说明或接口示例
- 完善鉴权、日志与部署配置
- 支持多文档会话（同一 memoryId 上传多次考试成绩，做跨次对比分析）

## 依赖说明

当前依赖包括：

- `fastapi`
- `uvicorn`
- `langchain`
- `langchain-openai`
- `langgraph`
- `redis`
- `pydantic-settings`
- `PyPDF2`
- `openpyxl`
- `xlrd`
- `python-multipart`
- `numpy`
- `FlagEmbedding`

## 适用场景

本项目适合用于：

- 学生成绩单智能分析演示
- 教育数据问答原型系统
- 基于 FastAPI + LangGraph + Redis 的 ReAct Agent 实践
- 混合检索 RAG（向量 + BM25 + RRF + 重排序）学习参考
- OpenAI 兼容接口多模型接入（DeepSeek + 智谱）示例

## 声明

本项目仅供学习、研究与参考使用，不得用于任何商业用途，亦不得允许他人进行商用。
