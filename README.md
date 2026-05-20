# langchain4j-techAgent-python

一个基于 FastAPI 构建的教育成绩分析 Agent 项目，用于上传学生成绩 PDF、提取文本内容、进行文本切块与向量化检索，并结合大模型对成绩数据进行分析与建议输出。

## 项目简介

本项目面向“学生成绩分析”场景，核心目标是：

- 上传学生成绩 PDF
- 提取成绩文本内容
- 对成绩文本进行切块
- 调用 Embedding 模型生成向量
- 按会话维度缓存原文、切块与向量
- 根据用户问题进行相似度检索
- 结合检索片段与系统提示词进行成绩分析问答
- 支持清理会话数据与文档数据

当前项目使用：

- `FastAPI` 提供 Web API
- `PyPDF2` 提取 PDF 文本
- `Redis` 存储聊天记忆、成绩原文、文本切块与向量
- `langchain-openai` 调用 OpenAI 兼容聊天模型与 Embedding 模型
- `DeepSeek` 兼容接口作为当前默认模型调用方式

## 项目功能

### 1. 成绩单上传
通过接口上传 PDF 成绩单，并提取其中的文本内容。

### 2. 标准 RAG 检索
提取后的成绩文本会先按配置切分为多个 chunk，再调用 Embedding 模型生成向量。原文、切块与向量都会按 `memoryId` 存储到 Redis 中，用户提问时会基于问题向量召回最相关的 top-k 文本片段。

### 3. 智能问答分析
用户可基于同一个 `memoryId` 发起提问，系统会读取对应成绩内容，并将其与用户问题一起发送给大模型，返回分析建议。

### 4. 会话与文档清理
支持删除：

- 当前会话聊天记忆
- 当前成绩文档内容

## 项目结构

```text
langchain4j-techAgent-python/
├── ai_service/                 # 大模型调用服务
│   └── consultant_service.py
├── config/                     # 配置加载与生产密文处理
│   ├── encrypt_config.py
│   └── settings.py
├── exception/                  # 自定义异常与全局异常处理
│   ├── bad_request_exception.py
│   └── global_exception_handler.py
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
│   ├── request.py
│   └── response.py
├── service/                    # 业务服务层
│   └── grade_document_service.py
├── .env.dev                    # 本地开发配置（已忽略，不上传）
├── .env.prod.example           # 生产配置模板
├── .gitignore
├── main.py                     # 应用入口
└── requirements.txt
```

## 核心流程

### 成绩分析流程

1. 用户上传成绩 PDF
2. 服务端使用 `PyPDF2` 解析 PDF 文本
3. 提取出的文本以 `memoryId` 为键存入 Redis
4. 按 `rag_chunk_size` 与 `rag_chunk_overlap` 切分文本
5. 调用 Embedding 模型生成每个 chunk 的向量
6. 将 chunk 内容与向量存入 Redis
7. 用户发起分析问题
8. 对用户问题生成 query embedding
9. 对 query embedding 与文档 chunk embedding 做余弦相似度计算
10. 召回 top-k 相关片段
11. 将“检索片段 + 用户问题 + 系统提示词”一起发送给大模型
12. 返回分析结果

### 会话数据流程

- 成绩文档存储在 Redis 中
- 聊天记忆也可存储在 Redis 中
- 当前代码中对成绩文档做了 Redis 持久化
- 聊天服务当前仍主要使用进程内 `memories` 字典缓存对话历史

## 当前接口说明

接口统一前缀：`/ai`

### 1. 上传成绩单
`POST /ai/upload`

表单参数：

- `memoryId`: 会话 ID
- `file`: PDF 文件

功能：

- 上传并解析 PDF
- 将提取文本存入 Redis

### 2. 成绩分析对话
`GET /ai/chat`

请求参数：

- `memoryId`: 会话 ID
- `message`: 用户问题

功能：

- 根据 `memoryId` 读取对应成绩内容
- 与用户问题一起交给模型分析
- 返回分析结果

### 3. 关闭会话
`DELETE /ai/session`

请求参数：

- `memoryId`: 会话 ID

功能：

- 删除 Redis 中的聊天记忆
- 删除当前会话相关成绩文档

### 4. 删除成绩文档
`DELETE /ai/document`

请求参数：

- `memoryId`: 会话 ID

功能：

- 删除该会话对应的成绩文档

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
- 当 `OPENAI_BASE_URL=https://api.deepseek.com` 且模型为 `deepseek-chat` 时，实际调用的是 DeepSeek 兼容接口
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
- 切块与向量键：`document:grade:{memoryId}:chunks`
- 用于缓存成绩单原文、chunk 文本和 embedding 向量

### 2. 聊天记忆缓存
- 键前缀：`chat:memory:{memoryId}`
- 用于缓存会话消息

说明：

- 当前聊天主流程中，`ConsultantService` 内部仍使用进程内字典 `memories` 管理历史消息
- Redis 聊天存储类已存在，但尚未完全接入当前对话主链路

## 系统提示词说明

系统提示词位于：

- `resources/system.txt`

其作用包括：

- 约束模型聚焦学生成绩分析
- 在未上传成绩单时提示用户先上传 PDF
- 要求分析必须基于已上传的成绩数据
- 限制模型避免虚构成绩信息

## 当前实现特点与注意事项

### 已实现
- 成绩 PDF 上传
- PDF 文本提取
- 文本切块
- Embedding 向量化
- Redis 文档与向量缓存
- 基于余弦相似度的 top-k 检索
- 成绩分析问答
- 基础异常处理
- 开发/生产配置分离

### 当前简化点
- 当前向量检索使用 Redis 存储向量数据，并在 Python 侧计算余弦相似度，适合小规模文档场景
- 聊天历史目前主要保存在进程内内存中
- 生产配置加密方案仍可进一步增强

### 后续可优化方向
- 接入 Redis Vector、FAISS、Milvus、Chroma 等专业向量检索引擎
- 将聊天记忆统一接入 Redis
- 增加 Swagger 使用说明或接口示例
- 完善鉴权、日志与部署配置
- 优化 PDF 文本抽取质量

## 依赖说明

当前依赖包括：

- `fastapi`
- `uvicorn`
- `langchain`
- `langchain-openai`
- `redis`
- `pydantic-settings`
- `PyPDF2`
- `python-multipart`
- `numpy`

## 适用场景

本项目适合用于：

- 学生成绩单智能分析演示
- 教育数据问答原型系统
- 基于 FastAPI + Redis + LLM 的轻量 Agent 实践
- 学习 OpenAI 兼容接口接入方式

## 声明

本项目仅供学习、研究与参考使用，不得用于任何商业用途，亦不得允许他人进行商用。
