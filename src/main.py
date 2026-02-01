"""FastAPI application entry point.

T023: Setup FastAPI app with health endpoint in src/main.py
DoD: GET /health 回傳 {"status": "ok"}；uvicorn 可啟動
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.middleware import RequestIdMiddleware
from src.api.webhook import router as webhook_router
from src.config import settings
from src.database import close_db, init_db

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def _keep_alive(interval: int = 300) -> None:
    """定時 ping 自己的公開 URL，防止 Render free tier spin down。"""
    hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if not hostname:
        logger.info("RENDER_EXTERNAL_HOSTNAME 未設定，跳過 keep-alive（非 Render 環境）")
        return
    url = f"https://{hostname}/health"
    logger.info("keep-alive 啟動，每 %d 秒 ping %s", interval, url)
    import httpx

    async with httpx.AsyncClient() as client:
        while True:
            await asyncio.sleep(interval)
            try:
                resp = await client.get(url, timeout=10)
                logger.debug("keep-alive ping: %s", resp.status_code)
            except Exception as e:
                logger.warning("keep-alive ping 失敗: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager.

    Handles startup and shutdown events.
    """
    # Startup
    logger.info(f"Starting application in {settings.app_env} mode")

    # Try to initialize database, but don't fail startup if it times out
    try:
        if settings.is_development:
            # In development, create tables if they don't exist
            # In production, use Alembic migrations
            await init_db()
            logger.info("Database initialized")
    except Exception as e:
        logger.warning(f"Database initialization skipped: {e}")
        # Don't fail startup - database will connect on first request

    # === Cold start 預熱：減少首次請求延遲 ===
    # 預熱 DB 連線池
    try:
        from sqlalchemy import text as sa_text

        from src.database import get_session

        async with get_session() as session:
            await session.execute(sa_text("SELECT 1"))
        logger.info("DB connection pool warmed up")
    except Exception as e:
        logger.warning(f"DB warmup skipped: {e}")

    # 預熱 LLM client（僅建立 HTTP client，不發真實請求）
    try:
        from src.lib.llm_client import get_llm_client

        get_llm_client()
        logger.info("LLM client initialized")
    except Exception as e:
        logger.warning(f"LLM client warmup skipped: {e}")

    # 預熱 LINE client singleton
    try:
        from src.lib.line_client import get_line_client

        get_line_client()
        logger.info("LINE client initialized")
    except Exception as e:
        logger.warning(f"LINE client warmup skipped: {e}")

    # 啟動 keep-alive task（僅 Render 環境生效）
    keep_alive_task = asyncio.create_task(_keep_alive())

    yield

    # 關閉 keep-alive
    keep_alive_task.cancel()
    try:
        await keep_alive_task
    except asyncio.CancelledError:
        pass

    # Shutdown
    logger.info("Shutting down application")
    from src.lib.llm_client import close_llm_client

    await close_llm_client()
    await close_db()


# Create FastAPI app
app = FastAPI(
    title="LINE 日語學習助教 Bot",
    description="Personal Japanese learning assistant via LINE",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
)

# Add request ID middleware
app.add_middleware(RequestIdMiddleware)

# Add CORS middleware
# 注意：allow_origins=["*"] 僅在 development 環境使用
# Production 環境會設為空列表，不允許跨域請求
# LINE Webhook 不需要 CORS，此設定主要用於本地開發測試
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_development else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(webhook_router)


@app.get("/health")
async def health_check() -> dict[str, Any]:
    """Health check endpoint，兼作 DB 連線池保溫。"""
    from sqlalchemy import text

    from src.database import get_session

    db_ok = False
    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        pass
    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "version": "0.1.0",
        "environment": settings.app_env,
    }


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint.

    Returns:
        Welcome message
    """
    return {"message": "LINE 日語學習助教 Bot API"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
    )
