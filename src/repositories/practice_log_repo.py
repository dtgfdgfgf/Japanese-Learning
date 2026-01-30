"""PracticeLog repository for database operations.

T019: Implement PracticeLogRepository in src/repositories/practice_log_repo.py
DoD: 可 create/get practice_log；get_by_item 回傳該 item 的練習紀錄
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.practice_log import PracticeLog
from src.repositories.base import BaseRepository


class PracticeLogRepository(BaseRepository[PracticeLog]):
    """Repository for PracticeLog entity operations."""

    model = PracticeLog
    pk_field = "log_id"

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session."""
        super().__init__(session)

    async def create_log(
        self,
        user_id: str,
        item_id: str,
        practice_type: str,
        user_answer: str,
        is_correct: bool,
        prompt_snapshot: str | None = None,
        score: float | None = None,
        feedback: str | None = None,
    ) -> PracticeLog:
        """Create a new practice log entry.

        Args:
            user_id: Hashed LINE user ID
            item_id: Reference to practiced item
            practice_type: Type of practice (vocab_recall/grammar_cloze)
            user_answer: User's response
            is_correct: Whether answer was correct
            prompt_snapshot: Question text shown
            score: Optional numeric score
            feedback: Optional feedback text

        Returns:
            Created PracticeLog instance
        """
        return await self.create(
            user_id=user_id,
            item_id=item_id,
            practice_type=practice_type,
            user_answer=user_answer,
            is_correct=is_correct,
            prompt_snapshot=prompt_snapshot,
            score=score,
            feedback=feedback,
        )

    async def get_by_item(
        self,
        item_id: str,
        limit: int = 10,
    ) -> list[PracticeLog]:
        """Get practice logs for a specific item.

        Args:
            item_id: Item ID
            limit: Maximum number of logs to return

        Returns:
            List of PracticeLog instances, ordered by created_at DESC
        """
        stmt = (
            select(PracticeLog)
            .where(PracticeLog.item_id == item_id)
            .where(PracticeLog.is_deleted.is_(False))
            .order_by(PracticeLog.created_at.desc())
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_user(
        self,
        user_id: str,
        limit: int = 50,
        practice_type: str | None = None,
    ) -> list[PracticeLog]:
        """Get practice logs for a user.

        Args:
            user_id: Hashed LINE user ID
            limit: Maximum number of logs to return
            practice_type: Optional filter by practice type

        Returns:
            List of PracticeLog instances, ordered by created_at DESC
        """
        stmt = (
            select(PracticeLog)
            .where(PracticeLog.user_id == user_id)
            .where(PracticeLog.is_deleted.is_(False))
        )

        if practice_type:
            stmt = stmt.where(PracticeLog.practice_type == practice_type)

        stmt = stmt.order_by(PracticeLog.created_at.desc()).limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_error_rate_by_item(
        self,
        item_id: str,
        days: int = 7,
    ) -> float:
        """Calculate error rate for an item in the last N days.

        Args:
            item_id: Item ID
            days: Number of days to look back

        Returns:
            Error rate as float (0.0-1.0), or 0.0 if no logs
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Count total and incorrect
        total_stmt = (
            select(func.count())
            .select_from(PracticeLog)
            .where(PracticeLog.item_id == item_id)
            .where(PracticeLog.is_deleted.is_(False))
            .where(PracticeLog.created_at >= cutoff)
        )

        incorrect_stmt = (
            select(func.count())
            .select_from(PracticeLog)
            .where(PracticeLog.item_id == item_id)
            .where(PracticeLog.is_deleted.is_(False))
            .where(PracticeLog.created_at >= cutoff)
            .where(PracticeLog.is_correct.is_(False))
        )

        total_result = await self.session.execute(total_stmt)
        incorrect_result = await self.session.execute(incorrect_stmt)

        total = total_result.scalar() or 0
        incorrect = incorrect_result.scalar() or 0

        if total == 0:
            return 0.0

        return incorrect / total

    async def get_items_with_high_error_rate(
        self,
        user_id: str,
        days: int = 7,
        threshold: float = 0.5,
        limit: int = 10,
    ) -> list[str]:
        """Get item IDs with high error rate for a user.

        Args:
            user_id: Hashed LINE user ID
            days: Number of days to look back
            threshold: Minimum error rate to include
            limit: Maximum number of item IDs to return

        Returns:
            List of item IDs with high error rate
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Subquery to calculate error rate per item
        stmt = (
            select(
                PracticeLog.item_id,
                (
                    func.sum(func.cast(~PracticeLog.is_correct, func.Integer))
                    / func.count()
                ).label("error_rate"),
            )
            .where(PracticeLog.user_id == user_id)
            .where(PracticeLog.is_deleted.is_(False))
            .where(PracticeLog.created_at >= cutoff)
            .group_by(PracticeLog.item_id)
            .having(
                func.sum(func.cast(~PracticeLog.is_correct, func.Integer))
                / func.count()
                >= threshold
            )
            .order_by(
                (
                    func.sum(func.cast(~PracticeLog.is_correct, func.Integer))
                    / func.count()
                ).desc()
            )
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]

    async def count_by_user_since(
        self,
        user_id: str,
        since: datetime,
        correct_only: bool | None = None,
    ) -> int:
        """Count practice logs for a user since a given time.

        Args:
            user_id: Hashed LINE user ID
            since: 起算時間點
            correct_only: If True, count only correct; if False, only incorrect; if None, all

        Returns:
            Count of practice logs
        """
        stmt = (
            select(func.count())
            .select_from(PracticeLog)
            .where(PracticeLog.user_id == user_id)
            .where(PracticeLog.is_deleted.is_(False))
            .where(PracticeLog.created_at >= since)
        )

        if correct_only is True:
            stmt = stmt.where(PracticeLog.is_correct.is_(True))
        elif correct_only is False:
            stmt = stmt.where(PracticeLog.is_correct.is_(False))

        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_by_user(
        self,
        user_id: str,
        correct_only: bool | None = None,
    ) -> int:
        """Count practice logs for a user.

        Args:
            user_id: Hashed LINE user ID
            correct_only: If True, count only correct answers;
                         if False, count only incorrect; if None, count all

        Returns:
            Count of practice logs
        """
        stmt = (
            select(func.count())
            .select_from(PracticeLog)
            .where(PracticeLog.user_id == user_id)
            .where(PracticeLog.is_deleted.is_(False))
        )

        if correct_only is True:
            stmt = stmt.where(PracticeLog.is_correct.is_(True))
        elif correct_only is False:
            stmt = stmt.where(PracticeLog.is_correct.is_(False))

        result = await self.session.execute(stmt)
        return result.scalar() or 0
