# langchain4j-techAgent-python

一个基于 FastAPI + LangGraph 构建的教育成绩分析 Agent 项目。支持上传学生成绩文档（PDF / Excel），通过智能列识别引擎自动解析为结构化数据，结合混合检索（向量 + BM25 + RRF）+ BGE 重排序实现精准 RAG，最终由 ReAct Agent 自主调用分析工具生成深度报告与 ECharts 图表。

## 项目简介

本项目面向"学生成绩分析"场景，核心能力包括：

- 上传学生成绩文档（PDF / `.xlsx` / `.xls`）
- 智能列识别引擎：自动适配宽表/长表布局，解析科目、学生、分数
- 结构化语义分块（按学生 / 科目 / 班级粒度）
- 调用 Embedding 模型生成向量
- 基于（年级 + 班级）桶做数据隔离，原文、解析记录、切块与向量按桶存储；同一桶内支持多份考试（期中/期末/月考）
- 混合检索（余弦相似度 + BM25 关键词 + RRF 融合）+ BGE 重排序
- LangGraph ReAct Agent：自主推理并调用分析工具（班级概览、学生详情、偏科检测、图表生成等）
- SSE 流式对话，逐 token / 逐分析步骤实时返回
- 支持清理会话数据与文档数据

当前项目使用：

- `FastAPI` 提供 Web API
- `LangGraph` 编排 ReAct Agent 推理循环
- `PyPDF2` / `openpyxl` / `xlrd` 解析 PDF 与 Excel
- `Redis` 存储聊天记忆、成绩原文、解析记录、文本切块与向量（成绩数据按「年级 + 班级」桶隔离）
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
支持按（年级 + 班级）桶查看/删除成绩数据，按 `memoryId` 清理会话聊天记忆。

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
│   ├── bucket_analyzer.py      #   桶分析器（多考试聚合 + 跨考试对比）
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
3. 原文、解析记录与 chunk 按（年级 + 班级 + 考试名）为键存入 Redis
4. `GradeTextSplitter` 按"学生 / 科目 / 班级"语义粒度切分为 chunk
5. 调用 Embedding 模型生成每个 chunk 的向量（chunk 前置「年级班级·考试名」元数据）→ 存入 Redis
6. `HybridRetriever` 构建 BM25 索引（中文 bigram 分词）
7. 用户发起分析问题
8. ReAct Agent 自主推理：判断是否需要调用工具 → 调用工具获取结构化数据 → 汇总生成回复
9. 若需 RAG 补充上下文，走混合检索管线 → BGE 重排序 → 注入 Agent 上下文
10. SSE 流式返回分析结果 / 图表数据，前端实时渲染

### 会话数据流程

- 成绩文档原文 + 解析记录 + chunk + 向量（Redis，key 含「年级+班级」桶前缀，桶内按考试名区分多份文档）
- 聊天记忆（Redis List，`chat:memory:{memoryId}`，保留最近 N 条原文，超出部分滚动摘要到 `...:summary`）
- 桶分析器（多考试聚合）实例 + 混合检索引擎实例（进程内存，按桶映射；重启后从 Redis 惰性重建）
- 成绩数据永久保留（不设置过期，手动删除）；聊天记忆 TTL 由 `REDIS_TTL_SECONDS` 配置（默认 2592000s = 30 天）

## 记忆架构

- **短期记忆（对话上下文）**：按会话存在 `chat:memory:{memoryId}`（List，最近 N 条原文，`CHAT_HISTORY_TURNS` 默认 20 条 = 10 轮）；历史超过阈值时，把最旧的溢出部分交给 LLM 生成**滚动摘要**存入 `...:summary`，问答上下文 = 摘要 + 最近 N 轮原文；删除会话时聊天记忆与摘要一并清除。
- **长期记忆（成绩知识库）**：按「年级+班级」桶存储原文 / 解析记录 / chunk / 向量，跨会话共享，问答通过 RAG 召回；删除文档/桶才清除。
- **生命周期**：长期记忆（成绩知识库）**永久保留**，不设置过期，仅通过数据管理删除文档/桶清理；短期记忆（聊天记忆）TTL 由 `REDIS_TTL_SECONDS` 配置（默认 30 天），写入时刷新；会话列表在浏览器 localStorage，无过期。

## 当前接口说明

接口统一前缀：`/ai`

### 1. 上传成绩单
`POST /ai/upload`

表单参数：

- `memoryId`: 会话 ID
- `grade`: 年级（如：高一）
- `className`: 班级（如：3班）
- `examName`: 考试名称（如：期中考试 / 期末，同一（年级+班级）可上传多份）
- `file`: PDF / Excel（`.xlsx` / `.xls`）文件

功能：

- 上传并解析文档（自动识别格式），按（年级+班级+考试名）存储
- 同一（年级+班级+考试名）重复上传视为替换该份考试，不影响同桶其他考试
- 结构化分析 + 文本/记录/向量存入 Redis，并重建桶内聚合检索源

### 2. 已有数据列表
`GET /ai/buckets`

功能：

- 返回所有（年级 + 班级）桶及其考试文档列表（考试名、文件名、上传时间、人数等）
- 供前端展示已有数据、按桶新建会话、删除文档/桶

### 3. 成绩分析对话
`GET /ai/chat`

请求参数：

- `memoryId`: 会话 ID
- `message`: 用户问题
- `grade`: 年级
- `className`: 班级（可选；为空时范围为整个年级，支持跨班对比，检索合并该年级全部班级数据）

功能：

- ReAct Agent 自主调用工具获取分析数据
- 数据含多次考试时，工具支持 `exam` 参数指定考试，支持跨考试对比
- 多班级（全年级）范围下工具支持 `className` 参数指定班级，并新增 `compare_classes` 跨班对比
- 非流式返回完整分析结果

### 4. 流式对话（SSE）
`GET /ai/chat/stream`

请求参数：

- `memoryId`: 会话 ID
- `message`: 用户问题
- `grade`: 年级
- `className`: 班级（可选；为空时范围为整个年级，支持跨班对比）

功能：

- 逐 token 流式返回 LLM 回复
- 工具调用阶段返回"[正在分析：xxx]"状态提示
- 支持前端实时展示分析过程

### 5. 关闭会话
`DELETE /ai/session`

请求参数：

- `memoryId`: 会话 ID

功能：

- 只清除该会话的 Redis 聊天记忆
- 桶数据可能被多个会话共享，关闭会话不会删除成绩文档

### 6. 删除成绩文档
`DELETE /ai/document`

请求参数：

- `grade`: 年级
- `className`: 班级
- `examName`: 考试名称

功能：

- 删除（年级+班级）桶内单份考试的成绩文档与向量数据，并重建桶聚合检索源

### 7. 删除整个桶
`DELETE /ai/bucket`

请求参数：

- `grade`: 年级
- `className`: 班级

功能：

- 删除整个（年级+班级）桶及其全部考试文档、向量数据与内存缓存

### 8. Swagger 接口文档

FastAPI 内置 Swagger UI 与 ReDoc，无需额外依赖，启动服务后直接访问：

- Swagger UI（可交互调试）：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

## 接口调用示例

### 1. 上传成绩单（表单 multipart）

```bash
curl -X POST http://127.0.0.1:8000/ai/upload \
  -F "memoryId=session-001" \
  -F "grade=高一" \
  -F "className=3班" \
  -F "examName=期中考试" \
  -F "file=@高一3班期中.xlsx"
```

成功响应示例：

```json
{
  "success": true,
  "message": "成绩单上传成功（10名学生），可在该班级会话中请求分析",
  "textLength": 268,
  "grade": "高一",
  "className": "3班",
  "examName": "期中考试",
  "bucketId": "高一::3班"
}
```

### 2. 单班问答

```text
GET /ai/chat?memoryId=session-001&message=各科平均分是多少&grade=高一&className=3班
```

### 3. 全年级跨班对比（className 留空）

```text
GET /ai/chat?memoryId=session-001&message=对比3班和5班的语文平均分&grade=高一
```

### 4. 数据管理

```text
GET    /ai/buckets
DELETE /ai/document?grade=高一&className=3班&examName=期中考试
DELETE /ai/bucket?grade=高一&className=3班
DELETE /ai/session?memoryId=session-001
```

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


### LangSmith 可观测性

项目集成了 [LangSmith](https://smith.langchain.com/) 用于 LLM 全链路追踪与调试。

开发环境配置（.env.dev）：

- LANGSMITH_API_KEY: LangSmith API Key（例如 lsv2_pt_...）
- LANGSMITH_TRACING_V2: 是否开启 Tracing，默认 	rue
- LANGSMITH_PROJECT: 项目名称，默认 langchain4j-techAgent-python
- LANGSMITH_ENDPOINT: API 端点，默认 https://api.smith.langchain.com

启动后可在 [LangSmith 控制台](https://smith.langchain.com/) 查看每次 Agent 调用的完整 Trace，包括：

- LLM 请求/响应内容与时延
- ReAct Agent 推理链（Thought → Action → Observation）
- 工具调用（@tool）的入参与返回值
- Embedding 与检索耗时

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
- 桶标识：`bucket_id = 年级 + "::" + 班级`（原生 UTF-8，如 `高一::3班`，便于在 Redis 工具中直接查看）
- 桶元数据键：`document:grade:bucket:{bucket_id}`（JSON，含 docs 列表：考试名 / 文件名 / 上传时间 / 人数等）
- 单份考试键：`document:grade:bucket:{bucket_id}:doc:{考试名}`（原文）、`...:records`（解析记录）、`...:chunks`（切块与向量，每项含 grade / className / examName 元数据）
- 桶聚合检索源：`document:grade:bucket:{bucket_id}:chunks`（各考试 chunk 平铺合并，上传/删除后自动重建）
- 服务启动时自动将旧版百分号编码 key（如 `%E4%BA%8C%E5%B9%B4%E7%BA%A7::5%E7%8F%AD`）迁移为可读格式（幂等，不丢失数据）

### 2. 聊天记忆缓存
- 键前缀：`chat:memory:{memoryId}`（List，每轮 user / assistant 消息）与 `chat:memory:{memoryId}:summary`（String，滚动摘要）

数据生命周期：

- 成绩文档：永久保留，不设置过期（写入时 `PERSIST` 清除旧 TTL，启动时自动清除历史数据 TTL），仅手动删除
- 聊天记忆：TTL 由 `REDIS_TTL_SECONDS` 配置（默认 2592000s = 30 天），写入时刷新
- `/ai/document` 删除单份考试、`/ai/bucket` 删除整个桶，并同步清理内存对象
- `/ai/session` 只清聊天记忆，不影响桶数据

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
| `compare_exams` | 跨考试对比（按科目 / 学生 / 班级整体，如期中 vs 期末） |
| `compare_classes` | 跨班级对比（同考试名口径，各科指标 + 总分均分排名 + 单科排名） |
| `get_chart_data` | 生成 ECharts 图表 JSON |

说明：数据工具均支持可选 `exam` 参数（考试名称），未指定时默认使用最近一次上传的考试；多班级（全年级）范围下涉及班级的工具需通过 `className` 指定班级；检索片段会标注「年级班级·考试名」。

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
