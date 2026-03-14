"""
FastAPI 应用定义
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Re-export for backwards compatibility
from .state import AppState, app_state, init_app_state

__all__ = ["AppState", "app_state", "create_app", "init_app_state"]


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""
    # 延迟导入路由，避免循环导入
    from .routers import downloads, fs, organize, search, status, subscriptions
    from .websocket import router as ws_router

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        yield
        # Shutdown

    app = FastAPI(
        title="PT Downloader API",
        description="Web API for PT Downloader",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS 配置（允许前端跨域访问）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应限制为特定域名
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(status.router, prefix="/api", tags=["Status"])
    app.include_router(search.router, prefix="/api", tags=["Search"])
    app.include_router(downloads.router, prefix="/api", tags=["Downloads"])
    app.include_router(subscriptions.router, prefix="/api", tags=["Subscriptions"])
    app.include_router(organize.router, prefix="/api", tags=["Organize"])
    app.include_router(fs.router, prefix="/api", tags=["FileSystem"])
    app.include_router(ws_router, tags=["WebSocket"])

    return app
