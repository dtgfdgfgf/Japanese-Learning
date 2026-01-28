"""FastAPI application entry point.

T023: Setup FastAPI app with health endpoint in src/main.py
DoD: GET /health 回傳 {"status": "ok"}；uvicorn 可啟動
"""

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.webhook import router as webhook_router
from src.config import settings
from src.database import close_db, init_db

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager.

    Handles startup and shutdown events.
    """
    # Startup
    logger.info(f"Starting application in {settings.app_env} mode")

    if settings.is_development:
        # In development, create tables if they don't exist
        # In production, use Alembic migrations
        await init_db()
        logger.info("Database initialized")

    yield

    # Shutdown
    logger.info("Shutting down application")
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

# Add CORS middleware
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
    """Health check endpoint.

    Returns:
        Status information for monitoring
    """
    return {
        "status": "ok",
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
