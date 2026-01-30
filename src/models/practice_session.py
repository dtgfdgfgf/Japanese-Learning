"""PracticeSession model - 持久化練習 session 狀態。

將 in-memory session dict 改為 DB-backed，解決重啟遺失與並發安全問題。
"""

from datetime import datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class PracticeSessionModel(Base):
    """持久化的練習 session 記錄。

    Attributes:
        session_id: UUID PK
        user_id: Hashed LINE user ID
        state: PracticeSession.model_dump() 的 JSONB 快照
        created_at: 建立時間
        expires_at: 過期時間
        is_deleted: Soft delete flag
    """

    __tablename__ = "practice_sessions"

    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="Hashed LINE user ID",
    )
    state: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="PracticeSession.model_dump() snapshot",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Session 過期時間",
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sa.false(),
        comment="Soft delete flag",
    )

    def __repr__(self) -> str:
        return (
            f"<PracticeSessionModel(session_id={self.session_id[:8]}..., "
            f"user_id={self.user_id[:8]}...)>"
        )
