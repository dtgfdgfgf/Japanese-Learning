"""
Delete service for managing data deletion.

T070: Implement soft delete for last raw/doc/items
T071: Implement "清空資料" with confirmation state
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.document import Document
from src.models.item import Item
from src.models.raw_message import RawMessage
from src.repositories.document_repo import DocumentRepository
from src.repositories.item_repo import ItemRepository
from src.repositories.raw_message_repo import RawMessageRepository
from src.templates.messages import (
    Messages,
    format_delete_clear_success,
    format_delete_last_success,
)

logger = logging.getLogger(__name__)

# Store confirmation states (user_id -> timestamp)
_confirmation_pending: dict[str, datetime] = {}

# Confirmation timeout in seconds
CONFIRMATION_TIMEOUT = 60


def is_confirmation_pending(user_id: str) -> bool:
    """檢查使用者是否有待確認的清空請求。
    
    Args:
        user_id: Hashed user ID
        
    Returns:
        True if confirmation is pending and not expired
    """
    pending_time = _confirmation_pending.get(user_id)

    if not pending_time:
        return False

    elapsed = (datetime.now(UTC) - pending_time).total_seconds()
    if elapsed > CONFIRMATION_TIMEOUT:
        # Expired
        del _confirmation_pending[user_id]
        return False

    return True


def request_clear_all(user_id: str) -> str:
    """請求清空所有資料 - 設置待確認狀態（不需要 DB session）。
    
    Args:
        user_id: Hashed user ID
        
    Returns:
        Confirmation prompt message
    """
    _confirmation_pending[user_id] = datetime.now(UTC)

    return Messages.DELETE_CONFIRM_PROMPT


class DeleteService:
    """Service for managing data deletion operations."""

    def __init__(self, session: AsyncSession):
        """Initialize DeleteService.
        
        Args:
            session: Database session
        """
        self.session = session
        self.raw_repo = RawMessageRepository(session)
        self.doc_repo = DocumentRepository(session)
        self.item_repo = ItemRepository(session)

    async def delete_last(self, user_id: str) -> tuple[int, str]:
        """Delete the most recently created raw message, its document, and associated items.
        
        Args:
            user_id: Hashed user ID
            
        Returns:
            Tuple of (count deleted, message)
        """
        # Get the most recent raw message
        latest_raw = await self._get_latest_raw(user_id)

        if not latest_raw:
            return 0, Messages.DELETE_NOTHING

        deleted_count = 0

        # Delete associated items through document
        if latest_raw.raw_id:
            doc = await self._get_doc_by_raw(str(latest_raw.raw_id))
            if doc:
                items_deleted = await self._delete_items_by_doc(str(doc.doc_id))
                deleted_count += items_deleted

                # Soft delete document
                await self.doc_repo.soft_delete(doc.doc_id)
                deleted_count += 1

        # Soft delete raw message
        await self.raw_repo.soft_delete(latest_raw.raw_id)
        deleted_count += 1

        logger.info(f"User {user_id[:8]} deleted last entry: {deleted_count} records")

        return deleted_count, format_delete_last_success(deleted_count)

    async def _get_latest_raw(self, user_id: str) -> RawMessage | None:
        """Get the most recent raw message for user."""
        stmt = (
            select(RawMessage)
            .where(RawMessage.user_id == user_id)
            .where(RawMessage.is_deleted.is_(False))
            .order_by(RawMessage.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_doc_by_raw(self, raw_id: str) -> Document | None:
        """Get document associated with a raw message."""
        stmt = (
            select(Document)
            .where(Document.raw_id == raw_id)
            .where(Document.is_deleted.is_(False))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _delete_items_by_doc(self, doc_id: str) -> int:
        """Soft delete all items associated with a document."""
        stmt = (
            update(Item)
            .where(Item.doc_id == doc_id)
            .where(Item.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    def check_confirmation_pending(self, user_id: str) -> bool:
        """Check if user has pending clear confirmation.
        
        Args:
            user_id: Hashed user ID
            
        Returns:
            True if confirmation is pending and not expired
        """
        pending_time = _confirmation_pending.get(user_id)

        if not pending_time:
            return False

        elapsed = (datetime.now(UTC) - pending_time).total_seconds()
        if elapsed > CONFIRMATION_TIMEOUT:
            # Expired
            del _confirmation_pending[user_id]
            return False

        return True

    def clear_confirmation(self, user_id: str) -> None:
        """Clear pending confirmation for user."""
        _confirmation_pending.pop(user_id, None)

    async def clear_all_data(self, user_id: str) -> tuple[int, str]:
        """Clear all data for a user (soft delete).
        
        Args:
            user_id: Hashed user ID
            
        Returns:
            Tuple of (count deleted, message)
        """
        # Clear confirmation state
        self.clear_confirmation(user_id)

        deleted_count = 0

        # Count items before deletion
        item_count = await self._count_items(user_id)
        doc_count = await self._count_docs(user_id)
        raw_count = await self._count_raws(user_id)

        # Soft delete all items
        items_deleted = await self._soft_delete_all_items(user_id)
        deleted_count += items_deleted

        # Soft delete all documents
        docs_deleted = await self._soft_delete_all_docs(user_id)
        deleted_count += docs_deleted

        # Soft delete all raw messages
        raws_deleted = await self._soft_delete_all_raws(user_id)
        deleted_count += raws_deleted

        logger.info(f"User {user_id[:8]} cleared all data: {deleted_count} records")

        return deleted_count, format_delete_clear_success(
            raws=raws_deleted,
            docs=docs_deleted,
            items=items_deleted,
        )

    async def _count_items(self, user_id: str) -> int:
        """Count non-deleted items for user."""
        return await self.item_repo.count_by_user(user_id)

    async def _count_docs(self, user_id: str) -> int:
        """Count non-deleted documents for user."""
        stmt = (
            select(func.count())
            .select_from(Document)
            .where(Document.user_id == user_id)
            .where(Document.is_deleted.is_(False))
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def _count_raws(self, user_id: str) -> int:
        """Count non-deleted raw messages for user."""
        stmt = (
            select(func.count())
            .select_from(RawMessage)
            .where(RawMessage.user_id == user_id)
            .where(RawMessage.is_deleted.is_(False))
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def _soft_delete_all_items(self, user_id: str) -> int:
        """Soft delete all items for user."""
        stmt = (
            update(Item)
            .where(Item.user_id == user_id)
            .where(Item.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    async def _soft_delete_all_docs(self, user_id: str) -> int:
        """Soft delete all documents for user."""
        stmt = (
            update(Document)
            .where(Document.user_id == user_id)
            .where(Document.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    async def _soft_delete_all_raws(self, user_id: str) -> int:
        """Soft delete all raw messages for user."""
        stmt = (
            update(RawMessage)
            .where(RawMessage.user_id == user_id)
            .where(RawMessage.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount


def is_confirmation_pending(user_id: str) -> bool:
    """檢查用戶是否有待確認的清空請求（module-level function）。"""
    pending_time = _confirmation_pending.get(user_id)

    if not pending_time:
        return False

    elapsed = (datetime.now(UTC) - pending_time).total_seconds()
    if elapsed > CONFIRMATION_TIMEOUT:
        del _confirmation_pending[user_id]
        return False

    return True
