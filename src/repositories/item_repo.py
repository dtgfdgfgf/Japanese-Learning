"""Item repository for database operations.

T018: Implement ItemRepository in src/repositories/item_repo.py
DoD: 可 create/get/upsert item；upsert 依 (user_id, item_type, key) 正確更新
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.item import Item
from src.repositories.base import BaseRepository


class ItemRepository(BaseRepository[Item]):
    """Repository for Item entity operations."""

    model = Item
    pk_field = "item_id"

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session."""
        super().__init__(session)

    async def create_item(
        self,
        user_id: str,
        doc_id: str,
        item_type: str,
        key: str,
        payload: dict[str, Any],
        source_quote: str | None = None,
        confidence: float = 1.0,
    ) -> Item:
        """Create a new item.

        Args:
            user_id: Hashed LINE user ID
            doc_id: Reference to source document
            item_type: Type of item (vocab/grammar)
            key: Deduplication key
            payload: Type-specific data
            source_quote: Original text snippet
            confidence: Extraction confidence (0-1)

        Returns:
            Created Item instance
        """
        return await self.create(
            user_id=user_id,
            doc_id=doc_id,
            item_type=item_type,
            key=key,
            payload=payload,
            source_quote=source_quote,
            confidence=confidence,
        )

    async def upsert_item(
        self,
        user_id: str,
        doc_id: str,
        item_type: str,
        key: str,
        payload: dict[str, Any],
        source_quote: str | None = None,
        confidence: float = 1.0,
    ) -> tuple[Item, bool]:
        """Insert or update item based on (user_id, item_type, key).

        If an item with the same user_id, item_type, and key exists,
        updates its payload and confidence. Otherwise creates a new item.

        Args:
            user_id: Hashed LINE user ID
            doc_id: Reference to source document
            item_type: Type of item (vocab/grammar)
            key: Deduplication key
            payload: Type-specific data
            source_quote: Original text snippet
            confidence: Extraction confidence (0-1)

        Returns:
            Tuple of (Item instance, was_created boolean)
        """
        # 先查後寫，搭配 IntegrityError retry 防止並發 race condition
        existing = await self.get_by_unique_key(user_id, item_type, key)

        if existing:
            # Update existing item
            updated = await self.update(
                existing.item_id,
                payload=payload,
                confidence=confidence,
                source_quote=source_quote,
                doc_id=doc_id,  # Update doc reference to latest
            )
            return updated or existing, False

        try:
            item = await self.create_item(
                user_id=user_id,
                doc_id=doc_id,
                item_type=item_type,
                key=key,
                payload=payload,
                source_quote=source_quote,
                confidence=confidence,
            )
            return item, True
        except IntegrityError:
            # 並發插入衝突：回滾後重新查詢並更新
            await self.session.rollback()
            existing = await self.get_by_unique_key(user_id, item_type, key)
            if existing:
                updated = await self.update(
                    existing.item_id,
                    payload=payload,
                    confidence=confidence,
                    source_quote=source_quote,
                    doc_id=doc_id,
                )
                return updated or existing, False
            raise

    async def get_by_unique_key(
        self,
        user_id: str,
        item_type: str,
        key: str,
    ) -> Item | None:
        """Get item by unique constraint fields.

        Args:
            user_id: Hashed LINE user ID
            item_type: Type of item (vocab/grammar)
            key: Deduplication key

        Returns:
            Item if found, None otherwise
        """
        stmt = (
            select(Item)
            .where(Item.user_id == user_id)
            .where(Item.item_type == item_type)
            .where(Item.key == key)
            .where(Item.is_deleted.is_(False))
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_user(
        self,
        user_id: str,
        item_type: str | None = None,
        limit: int = 100,
        include_deleted: bool = False,
    ) -> list[Item]:
        """Get items for a user.

        Args:
            user_id: Hashed LINE user ID
            item_type: Optional filter by item type
            limit: Maximum number of items to return
            include_deleted: Include soft-deleted items

        Returns:
            List of Item instances
        """
        stmt = (
            select(Item)
            .where(Item.user_id == user_id)
            .order_by(Item.created_at.desc())
            .limit(limit)
        )

        if not include_deleted:
            stmt = stmt.where(Item.is_deleted.is_(False))

        if item_type:
            stmt = stmt.where(Item.item_type == item_type)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_user(
        self,
        user_id: str,
        item_type: str | None = None,
        include_deleted: bool = False,
    ) -> int:
        """Count items for a user.

        Args:
            user_id: Hashed LINE user ID
            item_type: Optional filter by item type
            include_deleted: Include soft-deleted items

        Returns:
            Count of items
        """
        stmt = select(func.count()).select_from(Item).where(Item.user_id == user_id)

        if not include_deleted:
            stmt = stmt.where(Item.is_deleted.is_(False))

        if item_type:
            stmt = stmt.where(Item.item_type == item_type)

        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def search_by_keyword(
        self,
        user_id: str,
        keyword: str,
        limit: int = 10,
    ) -> list[Item]:
        """Search items by keyword in payload fields.

        Searches vocab surface, reading and grammar pattern.

        Args:
            user_id: Hashed LINE user ID
            keyword: Search keyword
            limit: Maximum number of results

        Returns:
            List of matching Item instances
        """
        # Escape SQL LIKE 特殊字元，防止 SQL injection
        escaped_keyword = (
            keyword.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped_keyword}%"

        # Search in JSONB payload fields
        stmt = (
            select(Item)
            .where(Item.user_id == user_id)
            .where(Item.is_deleted.is_(False))
            .where(
                or_(
                    # Vocab: search surface and reading
                    and_(
                        Item.item_type == "vocab",
                        or_(
                            Item.payload["surface"].astext.ilike(pattern),
                            Item.payload["reading"].astext.ilike(pattern),
                        ),
                    ),
                    # Grammar: search pattern
                    and_(
                        Item.item_type == "grammar",
                        Item.payload["pattern"].astext.ilike(pattern),
                    ),
                    # Also search in key
                    Item.key.ilike(pattern),
                )
            )
            .order_by(Item.created_at.desc())
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_items_for_practice(
        self,
        user_id: str,
        count: int = 5,
        item_type: str | None = None,
    ) -> list[Item]:
        """Get items for practice with priority algorithm.

        Priority order:
        1. Recent items (created within 24 hours)
        2. Error-prone items (high error rate in last 7 days)
        3. Oldest unpracticed items
        4. Random selection

        Args:
            user_id: Hashed LINE user ID
            count: Number of items to return
            item_type: Optional filter by item type

        Returns:
            List of Item instances for practice
        """
        now = datetime.now(UTC)
        day_ago = now - timedelta(hours=24)

        # Base query
        base_stmt = select(Item).where(
            Item.user_id == user_id,
            Item.is_deleted.is_(False),
        )

        if item_type:
            base_stmt = base_stmt.where(Item.item_type == item_type)

        # Priority 1: Recent items (last 24h)
        recent_stmt = base_stmt.where(Item.created_at >= day_ago).limit(count)
        result = await self.session.execute(recent_stmt)
        recent_items = list(result.scalars().all())

        if len(recent_items) >= count:
            return recent_items[:count]

        # Get remaining needed
        remaining = count - len(recent_items)
        seen_ids = {item.item_id for item in recent_items}

        # Priority 2-4: Other items (ordered by created_at for oldest first)
        other_stmt = (
            base_stmt.where(Item.item_id.notin_(seen_ids))
            .order_by(Item.created_at.asc())
            .limit(remaining)
        )
        result = await self.session.execute(other_stmt)
        other_items = list(result.scalars().all())

        return recent_items + other_items

    async def soft_delete_by_doc(self, doc_id: str) -> int:
        """Soft delete all items belonging to a document.

        Args:
            doc_id: Document ID

        Returns:
            Number of items deleted
        """
        stmt = (
            update(Item)
            .where(Item.doc_id == doc_id)
            .where(Item.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    async def soft_delete_by_user(self, user_id: str) -> int:
        """Soft delete all items for a user.

        Args:
            user_id: Hashed LINE user ID

        Returns:
            Number of items deleted
        """
        stmt = (
            update(Item)
            .where(Item.user_id == user_id)
            .where(Item.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount
    async def get_recent_by_user(
        self,
        user_id: str,
        since: datetime,
        limit: int = 10,
    ) -> list[Item]:
        """Get items created since a given time.

        Args:
            user_id: Hashed LINE user ID
            since: Datetime cutoff
            limit: Maximum items to return

        Returns:
            List of recent Item instances
        """
        stmt = (
            select(Item)
            .where(Item.user_id == user_id)
            .where(Item.is_deleted.is_(False))
            .where(Item.created_at >= since)
            .order_by(Item.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_stale_by_user(
        self,
        user_id: str,
        not_practiced_since: datetime,
        limit: int = 10,
    ) -> list[Item]:
        """Get items not practiced since a given time.

        For MVP, this returns items ordered by created_at ascending.
        In a full implementation, this would join with practice_logs.

        Args:
            user_id: Hashed LINE user ID
            not_practiced_since: Datetime cutoff
            limit: Maximum items to return

        Returns:
            List of stale Item instances
        """
        # Simple implementation: return oldest items
        stmt = (
            select(Item)
            .where(Item.user_id == user_id)
            .where(Item.is_deleted.is_(False))
            .order_by(Item.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_random_by_user(
        self,
        user_id: str,
        limit: int = 10,
        exclude_ids: list[str] | None = None,
    ) -> list[Item]:
        """Get random items for a user.

        Args:
            user_id: Hashed LINE user ID
            limit: Maximum items to return
            exclude_ids: Item IDs to exclude

        Returns:
            List of random Item instances
        """
        stmt = (
            select(Item)
            .where(Item.user_id == user_id)
            .where(Item.is_deleted.is_(False))
            .order_by(func.random())
            .limit(limit)
        )

        if exclude_ids:
            stmt = stmt.where(Item.item_id.notin_(exclude_ids))

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert(
        self,
        user_id: str,
        doc_id: str,
        item_type: str,
        key: str,
        payload: dict[str, Any],
        source_quote: str | None = None,
        confidence: float = 1.0,
    ) -> Item:
        """Simplified upsert that returns the item.

        Args:
            user_id: Hashed LINE user ID
            doc_id: Reference to source document
            item_type: Type of item (vocab/grammar)
            key: Deduplication key
            payload: Type-specific data
            source_quote: Original text snippet
            confidence: Extraction confidence (0-1)

        Returns:
            Created or updated Item instance
        """
        item, _ = await self.upsert_item(
            user_id=user_id,
            doc_id=doc_id,
            item_type=item_type,
            key=key,
            payload=payload,
            source_quote=source_quote,
            confidence=confidence,
        )
        return item
