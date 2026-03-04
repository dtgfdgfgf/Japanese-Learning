"""
Session service for managing practice session state.

DB-backed 版本：透過 PracticeSessionRepository 持久化 session，
解決重啟遺失、多 worker 並發不安全問題。
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.practice_session_repo import PracticeSessionRepository
from src.schemas.practice import PracticeSession

logger = logging.getLogger(__name__)


class SessionService:
    """Service for managing user session state（DB-backed）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.repo = PracticeSessionRepository(session)

    async def get_session(self, user_id: str) -> PracticeSession | None:
        """取得使用者的有效 session。"""
        return await self.repo.get_active(user_id)

    async def set_session(self, user_id: str, practice_session: PracticeSession) -> None:
        """儲存 session（會 soft delete 舊的）。"""
        await self.repo.upsert(user_id, practice_session)
        logger.debug("Stored session %s for user %s", practice_session.session_id, user_id[:8])

    async def update_session(self, user_id: str, practice_session: PracticeSession) -> None:
        """更新現有 session 的 state（不建新記錄）。"""
        await self.repo.update_state(user_id, practice_session)

    async def clear_session(self, user_id: str) -> bool:
        """清除使用者的 session。"""
        await self.repo.delete(user_id)
        logger.debug("Cleared session for user %s", user_id[:8])
        return True

    async def has_active_session(self, user_id: str) -> bool:
        """檢查使用者是否有進行中的 session。"""
        session = await self.repo.get_active(user_id)
        return session is not None

    async def cleanup_expired_sessions(self) -> int:
        """清除所有過期 sessions。"""
        count = await self.repo.cleanup_expired()
        if count:
            logger.info("Cleaned up %d expired sessions", count)
        return count
