"""Repository for practice session persistence."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.practice_session import PracticeSessionModel
from src.schemas.practice import PracticeSession

logger = logging.getLogger(__name__)

# Session 預設過期時間（分鐘）
SESSION_EXPIRATION_MINUTES = 30


class PracticeSessionRepository:
    """練習 session 的 DB 持久化操作。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active(self, user_id: str) -> PracticeSession | None:
        """取得使用者的有效 session。"""
        now = datetime.now(UTC)
        stmt = (
            select(PracticeSessionModel)
            .where(PracticeSessionModel.user_id == user_id)
            .where(PracticeSessionModel.is_deleted.is_(False))
            .where(PracticeSessionModel.expires_at > now)
            .order_by(PracticeSessionModel.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None

        try:
            ps = PracticeSession.model_validate(row.state)
            # 若 session 已完成，不回傳
            if ps.is_complete:
                return None
            return ps
        except Exception:
            logger.exception("反序列化 PracticeSession 失敗")
            return None

    async def upsert(self, user_id: str, practice_session: PracticeSession) -> None:
        """儲存或更新 session（soft delete 舊的，插入新的）。"""
        # Soft delete 該使用者現有的 active sessions
        await self._soft_delete_user_sessions(user_id)

        expires_at = datetime.now(UTC) + timedelta(minutes=SESSION_EXPIRATION_MINUTES)
        model = PracticeSessionModel(
            session_id=practice_session.session_id,
            user_id=user_id,
            state=practice_session.model_dump(mode="json"),
            expires_at=expires_at,
        )
        self.session.add(model)
        await self.session.flush()

    async def update_state(self, user_id: str, practice_session: PracticeSession) -> None:
        """僅更新現有 session 的 state（用於 submit_answer 後）。"""
        now = datetime.now(UTC)
        stmt = (
            update(PracticeSessionModel)
            .where(PracticeSessionModel.user_id == user_id)
            .where(PracticeSessionModel.is_deleted.is_(False))
            .where(PracticeSessionModel.expires_at > now)
            .values(state=practice_session.model_dump(mode="json"))
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def delete(self, user_id: str) -> None:
        """Soft delete 使用者的所有 active sessions。"""
        await self._soft_delete_user_sessions(user_id)

    async def cleanup_expired(self) -> int:
        """批次 soft delete 所有過期 sessions。"""
        now = datetime.now(UTC)
        stmt = (
            update(PracticeSessionModel)
            .where(PracticeSessionModel.is_deleted.is_(False))
            .where(PracticeSessionModel.expires_at <= now)
            .values(is_deleted=True)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    async def _soft_delete_user_sessions(self, user_id: str) -> None:
        """Soft delete 該使用者所有未刪除的 sessions。"""
        stmt = (
            update(PracticeSessionModel)
            .where(PracticeSessionModel.user_id == user_id)
            .where(PracticeSessionModel.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        await self.session.execute(stmt)
        await self.session.flush()
