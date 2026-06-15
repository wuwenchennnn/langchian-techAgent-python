import logging

from fastapi import FastAPI
from starlette.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from routers.ai_router import router as ai_router
from exception.global_exception_handler import global_exception_handler

# — 日志配置 —
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# 创建FastAPI应用
app = FastAPI(
    title="Langchain4j TechAgent",
    description="教育分析 Agent - 学生成绩数据分析与建议",
    version="0.0.1"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册异常处理器
app.add_exception_handler(Exception, global_exception_handler)

# 配置静态文件服务
app.mount("/static", StaticFiles(directory="resources/static"), name="static")

# 注册路由
app.include_router(ai_router)

# 根路径 - 重定向到前端页面
@app.get("/")
async def root():
    return RedirectResponse(url="/static/index.html")

# 前端页面路径
@app.get("/frontend")
async def frontend():
    return {"message": "Frontend page available at /static/index.html"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )