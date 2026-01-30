"""PracticeLog model - Record of a single practice attempt.

T012: Create PracticeLog model in src/models/practice_log.py
DoD: Model 定義符合 plan.md Data Model；FK 關聯 items 正確
"""

from datetime import datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


# Type aliases
PracticeType = Literal["vocab_recall", "grammar_cloze"]


class PracticeLog(Base):
    """Record of a single practice attempt.

    Tracks user answers, correctness, and feedback for each practice question.

    Attributes:
        log_id: Unique identifier (UUID)
        user_id: Hashed LINE user ID
        item_id: Reference to practiced item
        practice_type: Type of practice (vocab_recall/grammar_cloze)
        prompt_snapshot: Question text shown to user
        user_answer: User's response
        is_correct: Whether the answer was correct
        score: Optional numeric score (0-1)
        feedback: Optional feedback text
        created_at: Creation timestamp
        is_deleted: Soft delete flag
    """

    __tablename__ = "practice_logs"

    log_id: Mapped[str] = mapped_column(
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
    item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("items.item_id", ondelete="CASCADE"),
        nullable=False,
        comment="Reference to practiced item",
    )
    practice_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Practice type: vocab_recall, grammar_cloze",
    )
    prompt_snapshot: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Question text shown to user",
    )
    user_answer: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="User's response",
    )
    is_correct: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        comment="Whether answer was correct",
    )
    score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Optional numeric score 0-1",
    )
    feedback: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Optional feedback text",
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
        server_default=func.literal(False),
        comment="Soft delete flag",
    )

    # Relationships
    item: Mapped["Item"] = relationship(  # noqa: F821
        "Item",
        back_populates="practice_logs",
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_practice_logs_user_created", "user_id", created_at.desc()),
        Index(
            "idx_practice_logs_user_item_created",
            "user_id",
            "item_id",
            created_at.desc(),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<PracticeLog(log_id={self.log_id[:8]}..., "
            f"type={self.practice_type}, "
            f"correct={self.is_correct})>"
        )
