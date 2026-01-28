"""RawMessage model - Immutable record of user input.

T009: Create RawMessage model in src/models/raw_message.py
DoD: Model 定義符合 plan.md Data Model；可 import 無錯誤
"""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


class RawMessage(Base):
    """Immutable record of user input.

    Never modified after creation. Stores the original message
    exactly as received from LINE.

    Attributes:
        raw_id: Unique identifier (UUID)
        user_id: Hashed LINE user ID
        channel: Source channel (always "line")
        raw_text: Original message content
        raw_meta: LINE message metadata (message_id, timestamp, etc.)
        created_at: Creation timestamp
        is_deleted: Soft delete flag
    """

    __tablename__ = "raw_messages"

    raw_id: Mapped[str] = mapped_column(
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
    channel: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="line",
        comment="Source channel",
    )
    raw_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Original message content",
    )
    raw_meta: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="LINE message metadata",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Soft delete flag",
    )

    # Relationships
    document: Mapped["Document"] = relationship(  # noqa: F821
        "Document",
        back_populates="raw_message",
        uselist=False,
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_raw_messages_user_created", "user_id", created_at.desc()),
    )

    def __repr__(self) -> str:
        return (
            f"<RawMessage(raw_id={self.raw_id[:8]}..., "
            f"user_id={self.user_id[:8]}..., "
            f"text_len={len(self.raw_text)})>"
        )
