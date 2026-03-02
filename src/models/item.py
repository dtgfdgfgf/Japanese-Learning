"""Item model - Learning unit extracted from document.

T011: Create Item model in src/models/item.py
DoD: Model 定義符合 plan.md Data Model；unique constraint on (user_id, item_type, key)
"""

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


# Type aliases
ItemType = Literal["vocab", "grammar"]


class Item(Base):
    """Learning unit extracted from a document.

    Can be either a vocabulary item or a grammar item.
    Supports deduplication via unique constraint on (user_id, item_type, key).

    Attributes:
        item_id: Unique identifier (UUID)
        user_id: Hashed LINE user ID
        doc_id: Reference to source document
        item_type: Type of item (vocab/grammar)
        key: Deduplication key (vocab:surface or grammar:pattern)
        payload: Type-specific data (JSONB)
        source_quote: Original text snippet
        confidence: Extraction confidence (0-1)
        created_at: Creation timestamp
        is_deleted: Soft delete flag
    """

    __tablename__ = "items"

    item_id: Mapped[str] = mapped_column(
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
    doc_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("documents.doc_id", ondelete="RESTRICT"),
        nullable=False,
        comment="Reference to source document",
    )
    item_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="Type: vocab or grammar",
    )
    key: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        index=True,
        comment="Deduplication key",
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="Type-specific data",
    )
    source_quote: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Original text snippet",
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
        comment="Extraction confidence 0-1",
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
        server_default=sa.false(),
        comment="Soft delete flag",
    )

    # Relationships
    document: Mapped["Document"] = relationship(  # noqa: F821
        "Document",
        back_populates="items",
        lazy="selectin",
    )
    # 注意：selectin 會載入已 soft-delete 的子物件，查詢結果需自行過濾
    practice_logs: Mapped[list["PracticeLog"]] = relationship(  # noqa: F821
        "PracticeLog",
        back_populates="item",
        lazy="selectin",
        cascade="save-update, merge",
    )

    __table_args__ = (
        # Partial unique index for deduplication (only for non-deleted items)
        # Using Index with unique=True and postgresql_where instead of UniqueConstraint
        Index(
            "uq_items_user_type_key",
            "user_id",
            "item_type",
            "key",
            unique=True,
            postgresql_where="is_deleted = false",
        ),
        # Confidence must be between 0 and 1
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_items_confidence_range",
        ),
        # 注意：冗餘 index idx_items_user_type_key 已移除
        # partial unique index uq_items_user_type_key 已涵蓋常用查詢
    )

    def __repr__(self) -> str:
        return (
            f"<Item(item_id={self.item_id[:8]}..., "
            f"type={self.item_type}, key={self.key[:20]}..., "
            f"confidence={self.confidence:.2f})>"
        )

    @property
    def is_vocab(self) -> bool:
        """Check if this is a vocabulary item."""
        return self.item_type == "vocab"

    @property
    def is_grammar(self) -> bool:
        """Check if this is a grammar item."""
        return self.item_type == "grammar"

    @property
    def surface(self) -> str | None:
        """Get vocab surface form (for vocab items)."""
        if self.is_vocab:
            return self.payload.get("surface")
        return None

    @property
    def reading(self) -> str | None:
        """Get vocab reading (for vocab items)."""
        if self.is_vocab:
            return self.payload.get("reading")
        return None

    @property
    def pattern(self) -> str | None:
        """Get grammar pattern (for grammar items)."""
        if self.is_grammar:
            return self.payload.get("pattern")
        return None

    @property
    def meaning_zh(self) -> str | list[str] | None:
        """Get Chinese meaning/glossary."""
        if self.is_vocab:
            return self.payload.get("glossary_zh")
        return self.payload.get("meaning_zh")
