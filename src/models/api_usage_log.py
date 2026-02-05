"""ApiUsageLog model - API 使用記錄。

記錄每次 LLM API 呼叫的 token 使用量與費用，
供使用者查詢用量統計。
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class ApiUsageLog(Base):
    """API 使用記錄。

    記錄每次 LLM API 呼叫的詳細資訊，包含 token 數量與計算後的費用。

    Attributes:
        log_id: 唯一識別碼 (UUID)
        user_id: Hashed LINE user ID
        provider: LLM 提供者 (anthropic/openai)
        model: 模型名稱 (e.g., claude-sonnet-4-5-20250929)
        operation: 操作類型 (extraction/practice/router)
        input_tokens: 輸入 token 數量
        output_tokens: 輸出 token 數量
        cost_usd: 計算後的費用 (美元)
        latency_ms: API 回應延遲 (毫秒)
        is_fallback: 是否為 fallback 呼叫
        created_at: 建立時間
    """

    __tablename__ = "api_usage_logs"

    log_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Hashed LINE user ID",
    )
    provider: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="LLM provider: anthropic, openai",
    )
    model: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Model name",
    )
    operation: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Operation type: extraction, practice, router",
    )
    input_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Input token count",
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Output token count",
    )
    cost_usd: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="Calculated cost in USD",
    )
    latency_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="API response latency in milliseconds",
    )
    is_fallback: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether this was a fallback call",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Creation timestamp",
    )

    # 索引：加速使用者用量查詢
    __table_args__ = (
        Index("ix_api_usage_logs_user_id", "user_id"),
        Index("ix_api_usage_logs_created_at", "created_at"),
        Index("ix_api_usage_logs_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ApiUsageLog(log_id={self.log_id!r}, "
            f"user_id={self.user_id!r}, "
            f"model={self.model!r}, "
            f"cost_usd={self.cost_usd})>"
        )
