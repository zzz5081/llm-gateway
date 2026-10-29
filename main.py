from fastapi import FastAPI
from routers.auth import router as auth_router
from routers.chat import router as chat_router
import time 
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from routers.usage import router as usage_route
app = FastAPI(title="Todo API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],   # 允许哪些前端来源
    allow_credentials=True,                    # 允许带 cookie
    allow_methods=["*"],                       # 允许哪些方法
    allow_headers=["*"],                       # 允许哪些请求头（含 Authorization）
)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(usage_route)

@app.get("/health")
def health():
    return {'status':'ok'}

@app.middleware("http")
async def add_process_time(request: Request,call_next):
    start = time.perf_counter()
    response = await call_next(request)
    cost = time.perf_counter() - start
    response.headers["X-Process-Time"] = f"{cost:.4f}"
    return response
