"""Base repository class with common CRUD operations.

T015: Create base repository class in src/repositories/base.py
DoD: BaseRepository 提供 get_by_id, create, update, soft_delete 方法
"""

from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Base repository with common CRUD operations.

    Provides generic database operations that can be inherited
    by specific entity repositories.

    Type Parameters:
        ModelT: SQLAlchemy model class
    """

    model: type[ModelT]
    pk_field: str = "id"  # Override in subclass if different

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session.

        Args:
            session: Async SQLAlchemy session
        """
        self.session = session

    async def get_by_id(self, id_value: str | UUID) -> ModelT | None:
        """Get entity by primary key.

        Args:
            id_value: Primary key value

        Returns:
            Entity if found, None otherwise
        """
        pk_column = getattr(self.model, self.pk_field)
        stmt = select(self.model).where(
            pk_column == str(id_value),
            self.model.is_deleted.is_(False),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, **kwargs: Any) -> ModelT:
        """Create new entity.

        Args:
            **kwargs: Entity field values

        Returns:
            Created entity instance
        """
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(self, id_value: str | UUID, **kwargs: Any) -> ModelT | None:
        """Update entity by primary key.

        Args:
            id_value: Primary key value
            **kwargs: Fields to update

        Returns:
            Updated entity if found, None otherwise
        """
        pk_column = getattr(self.model, self.pk_field)
        stmt = (
            update(self.model)
            .where(pk_column == str(id_value))
            .where(self.model.is_deleted.is_(False))
            .values(**kwargs)
            .returning(self.model)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one_or_none()

    async def soft_delete(self, id_value: str | UUID) -> bool:
        """Soft delete entity by setting is_deleted=True.

        Args:
            id_value: Primary key value

        Returns:
            True if entity was found and deleted, False otherwise
        """
        pk_column = getattr(self.model, self.pk_field)
        stmt = (
            update(self.model)
            .where(pk_column == str(id_value))
            .where(self.model.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def exists(self, id_value: str | UUID) -> bool:
        """Check if entity exists by primary key.

        Args:
            id_value: Primary key value

        Returns:
            True if entity exists, False otherwise
        """
        entity = await self.get_by_id(id_value)
        return entity is not None
