"""Document model - Parsed or pending document from raw message.

T010: Create Document model in src/models/document.py
DoD: Model 定義符合 plan.md Data Model；FK 關聯 raw_messages 正確
"""

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

# Type aliases for document fields
LangType = Literal["ja", "en", "mixed", "unknown"]
DocType = Literal["vocab", "grammar", "mixed", "text"]
ParseStatus = Literal["parsed", "deferred", "failed"]


class Document(Base):
    """Parsed or pending document derived from a raw message.

    Represents a single "save" action by the user. Contains metadata
    about the language, type, and parsing status.

    Attributes:
        doc_id: Unique identifier (UUID)
        raw_id: Reference to source raw_message
        user_id: Hashed LINE user ID
        lang: Detected language (ja/mixed/unknown)
        doc_type: Content type (vocab/grammar/mixed/text)
        summary: Optional summary text
        tags: Array of string tags
        parse_status: Parsing status (parsed/deferred/failed)
        parser_version: Version of parser used
        llm_trace: LLM call metadata
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    raw_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("raw_messages.raw_id", ondelete="RESTRICT"),
        nullable=False,
        comment="Reference to source raw_message",
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="Hashed LINE user ID",
    )
    lang: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="unknown",
        comment="Detected language: ja, mixed, unknown",
    )
    doc_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="text",
        comment="Content type: vocab, grammar, mixed, text",
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Optional summary",
    )
    tags: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="Array of string tags",
    )
    parse_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="deferred",
        comment="Status: parsed, deferred, failed",
    )
    parser_version: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="Parser version, e.g., canon_v1",
    )
    llm_trace: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="LLM call metadata",
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

    # Relationships
    raw_message: Mapped["RawMessage"] = relationship(  # noqa: F821
        "RawMessage",
        back_populates="document",
        lazy="selectin",
    )
    # 注意：selectin 會載入已 soft-delete 的子物件，查詢結果需自行過濾
    items: Mapped[list["Item"]] = relationship(  # noqa: F821
        "Item",
        back_populates="document",
        lazy="selectin",
        cascade="save-update, merge",
    )

    __table_args__ = (
        Index("idx_documents_user_created", "user_id", created_at.desc()),
    )

    def __repr__(self) -> str:
        return (
            f"<Document(doc_id={self.doc_id[:8]}..., "
            f"lang={self.lang}, type={self.doc_type}, "
            f"status={self.parse_status})>"
        )

    @property
    def is_parsed(self) -> bool:
        """Check if document has been parsed."""
        return self.parse_status == "parsed"

    @property
    def is_deferred(self) -> bool:
        """Check if document is waiting for parsing."""
        return self.parse_status == "deferred"
