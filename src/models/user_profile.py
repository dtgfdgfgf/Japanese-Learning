"""UserProfile model — 使用者偏好與每日用量追蹤。

儲存使用者的 LLM 模式選擇、每日 token 使用量上限與累計。
daily_used_tokens 透過原子 SQL increment 更新，避免競態條件。
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class UserProfile(Base):
    """使用者偏好與用量追蹤。

    Attributes:
        user_id: Hashed LINE user ID (PK)
        mode: LLM 模式 (cheap/balanced/rigorous)
        daily_cap_tokens_free: 每日免費 token 上限
        daily_used_tokens: 今日已使用 token 數
        reset_at: 下一次日切重置時間 (Asia/Taipei 00:00)
        created_at: 建立時間
        updated_at: 更新時間
    """

    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="Hashed LINE user ID",
    )
    target_lang: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
        default="ja",
        server_default="ja",
        comment="目標學習語言: ja/en",
    )
    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="free",
        server_default="free",
        comment="LLM mode: free/cheap/rigorous",
    )
    input_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="query",
        server_default="query",
        comment="Input routing: query/ask",
    )
    daily_cap_tokens_free: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=50000,
        server_default="50000",
        comment="Daily free token cap",
    )
    daily_used_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Tokens used today",
    )
    reset_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Next daily reset time (Asia/Taipei 00:00)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sa.false(),
        comment="Soft delete flag",
    )

    def __repr__(self) -> str:
        uid = self.user_id[:8] if self.user_id else None
        return (
            f"<UserProfile(user_id={uid!r}..., "
            f"mode={self.mode!r}, "
            f"daily_used={self.daily_used_tokens}/{self.daily_cap_tokens_free})>"
        )
