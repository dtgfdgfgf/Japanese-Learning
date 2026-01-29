"""Document repository for database operations.

T017: Implement DocumentRepository in src/repositories/document_repo.py
DoD: 可 create/get document；get_deferred_by_user 回傳 parse_status=deferred 的文件
"""

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.document import Document
from src.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    """Repository for Document entity operations."""

    model = Document
    pk_field = "doc_id"

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session."""
        super().__init__(session)

    async def create_document(
        self,
        raw_id: str,
        user_id: str,
        lang: str = "unknown",
        doc_type: str = "text",
        parse_status: str = "deferred",
        tags: list[str] | None = None,
        summary: str | None = None,
        llm_trace: dict[str, Any] | None = None,
    ) -> Document:
        """Create a new document.

        Args:
            raw_id: Reference to source raw_message
            user_id: Hashed LINE user ID
            lang: Detected language (default: "unknown")
            doc_type: Content type (default: "text")
            parse_status: Parsing status (default: "deferred")
            tags: Optional list of tags
            summary: Optional summary text
            llm_trace: Optional LLM call metadata

        Returns:
            Created Document instance
        """
        return await self.create(
            raw_id=raw_id,
            user_id=user_id,
            lang=lang,
            doc_type=doc_type,
            parse_status=parse_status,
            tags=tags or [],
            summary=summary,
            llm_trace=llm_trace,
        )

    async def get_deferred_by_user(
        self,
        user_id: str,
        limit: int = 1,
    ) -> list[Document]:
        """Get documents with deferred parse status for a user.

        Args:
            user_id: Hashed LINE user ID
            limit: Maximum number of documents to return

        Returns:
            List of Document instances with parse_status='deferred'
        """
        stmt = (
            select(Document)
            .where(Document.user_id == user_id)
            .where(Document.parse_status == "deferred")
            .where(Document.is_deleted.is_(False))
            .order_by(Document.created_at.desc())
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_by_user(
        self,
        user_id: str,
        limit: int = 1,
        include_deleted: bool = False,
    ) -> list[Document]:
        """Get most recent documents for a user.

        Args:
            user_id: Hashed LINE user ID
            limit: Maximum number of documents to return
            include_deleted: Include soft-deleted documents

        Returns:
            List of Document instances, ordered by created_at DESC
        """
        stmt = (
            select(Document)
            .where(Document.user_id == user_id)
            .order_by(Document.created_at.desc())
        )

        if not include_deleted:
            stmt = stmt.where(Document.is_deleted.is_(False))

        stmt = stmt.limit(limit
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_parse_status(
        self,
        doc_id: str,
        status: str,
        llm_trace: dict[str, Any] | None = None,
        lang: str | None = None,
        doc_type: str | None = None,
        parser_version: str | None = None,
    ) -> Document | None:
        """Update document parse status and related fields.

        Args:
            doc_id: Document ID
            status: New parse status (parsed/failed)
            llm_trace: Optional LLM call metadata
            lang: Optional updated language detection
            doc_type: Optional updated document type
            parser_version: Optional parser version

        Returns:
            Updated Document if found, None otherwise
        """
        update_values: dict[str, Any] = {"parse_status": status}

        if llm_trace is not None:
            update_values["llm_trace"] = llm_trace
        if lang is not None:
            update_values["lang"] = lang
        if doc_type is not None:
            update_values["doc_type"] = doc_type
        if parser_version is not None:
            update_values["parser_version"] = parser_version

        stmt = (
            update(Document)
            .where(Document.doc_id == doc_id)
            .values(**update_values)
            .returning(Document)
        )

        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one_or_none()

    async def get_by_raw_id(self, raw_id: str) -> Document | None:
        """Get document by raw message ID.

        Args:
            raw_id: Raw message ID

        Returns:
            Document if found, None otherwise
        """
        stmt = select(Document).where(Document.raw_id == raw_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
