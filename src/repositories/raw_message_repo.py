"""RawMessage repository for database operations.

T016: Implement RawMessageRepository in src/repositories/raw_message_repo.py
DoD: 可 create/get raw_message；get_latest_by_user 方法可用
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.raw_message import RawMessage
from src.repositories.base import BaseRepository


class RawMessageRepository(BaseRepository[RawMessage]):
    """Repository for RawMessage entity operations."""

    model = RawMessage
    pk_field = "raw_id"

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session."""
        super().__init__(session)

    async def create_raw_message(
        self,
        user_id: str,
        raw_text: str,
        channel: str = "line",
        raw_meta: dict[str, Any] | None = None,
    ) -> RawMessage:
        """Create a new raw message.

        Args:
            user_id: Hashed LINE user ID
            raw_text: Original message content
            channel: Source channel (default: "line")
            raw_meta: Optional metadata

        Returns:
            Created RawMessage instance
        """
        return await self.create(
            user_id=user_id,
            raw_text=raw_text,
            channel=channel,
            raw_meta=raw_meta,
        )

    async def get_latest_by_user(
        self,
        user_id: str,
        limit: int = 1,
        include_deleted: bool = False,
    ) -> list[RawMessage]:
        """Get most recent raw messages for a user.

        Args:
            user_id: Hashed LINE user ID
            limit: Maximum number of messages to return
            include_deleted: Include soft-deleted messages

        Returns:
            List of RawMessage instances, ordered by created_at DESC
        """
        stmt = (
            select(RawMessage)
            .where(RawMessage.user_id == user_id)
            .order_by(RawMessage.created_at.desc())
            .limit(limit)
        )

        if not include_deleted:
            stmt = stmt.where(RawMessage.is_deleted.is_(False))

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_previous_message(
        self,
        user_id: str,
        exclude_raw_id: str | None = None,
    ) -> RawMessage | None:
        """Get the previous message for a user (for "入庫" command context).

        Args:
            user_id: Hashed LINE user ID
            exclude_raw_id: Optional raw_id to exclude from search

        Returns:
            Previous RawMessage if exists, None otherwise
        """
        stmt = (
            select(RawMessage)
            .where(RawMessage.user_id == user_id)
            .where(RawMessage.is_deleted.is_(False))
            .order_by(RawMessage.created_at.desc())
            .limit(2)  # Get last 2 to skip current if needed
        )

        result = await self.session.execute(stmt)
        messages = list(result.scalars().all())

        if not messages:
            return None

        # If exclude_raw_id specified, skip it
        if exclude_raw_id and messages[0].raw_id == exclude_raw_id:
            return messages[1] if len(messages) > 1 else None

        return messages[0]

    async def count_by_user(
        self,
        user_id: str,
        include_deleted: bool = False,
    ) -> int:
        """Count raw messages for a user.

        Args:
            user_id: Hashed LINE user ID
            include_deleted: Include soft-deleted messages

        Returns:
            Count of raw messages
        """
        from sqlalchemy import func

        stmt = select(func.count()).select_from(RawMessage).where(
            RawMessage.user_id == user_id
        )

        if not include_deleted:
            stmt = stmt.where(RawMessage.is_deleted.is_(False))

        result = await self.session.execute(stmt)
        return result.scalar() or 0
