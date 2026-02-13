"""
Delete service for managing data deletion.

T071: Implement "清空資料" with confirmation state
"""

import logging

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.document import Document
from src.models.item import Item
from src.models.raw_message import RawMessage
from src.repositories.item_repo import ItemRepository
from src.templates.messages import (
    Messages,
    format_delete_clear_success,
    format_delete_item_success,
)

logger = logging.getLogger(__name__)


class DeleteService:
    """Service for managing data deletion operations."""

    def __init__(self, session: AsyncSession):
        """Initialize DeleteService.

        Args:
            session: Database session
        """
        self.session = session
        self.item_repo = ItemRepository(session)

    async def delete_item(self, user_id: str, item_id: str) -> tuple[bool, str]:
        """刪除指定的 item（軟刪除，驗證所有權）。

        Args:
            user_id: Hashed user ID
            item_id: 要刪除的 item ID

        Returns:
            Tuple of (success, message)
        """
        item = await self.item_repo.get_by_id(item_id)

        if not item or item.user_id != user_id:
            return False, Messages.DELETE_NOTHING

        # 軟刪除
        await self.item_repo.soft_delete(item_id)

        # 格式化 label
        label = self._format_item_label(item)
        return True, format_delete_item_success(label)

    @staticmethod
    def _format_item_label(item: Item) -> str:
        """格式化 item 的顯示標籤。"""
        payload = item.payload or {}
        if item.item_type == "vocab":
            surface = payload.get("surface", "")
            reading = payload.get("reading", "")
            glossary = payload.get("glossary_zh", [])
            meaning = glossary[0] if glossary else ""
            if reading and reading != surface:
                return f"{surface}【{reading}】- {meaning}"
            return f"{surface} - {meaning}"
        elif item.item_type == "grammar":
            pattern = payload.get("pattern", "")
            meaning = payload.get("meaning_zh", "")
            return f"{pattern} - {meaning}"
        return item.key

    async def clear_all_data(self, user_id: str) -> tuple[int, str]:
        """Clear all data for a user (soft delete).

        Args:
            user_id: Hashed user ID

        Returns:
            Tuple of (count deleted, message)
        """
        deleted_count = 0

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
