"""Repository for user transient state persistence."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user_state import UserStateModel

logger = logging.getLogger(__name__)

# 清空確認逾時（秒）
CONFIRMATION_TIMEOUT = 60

# 待確認入庫逾時（秒）
PENDING_SAVE_TIMEOUT = 300  # 5 分鐘


class UserStateRepository:
    """使用者暫存狀態的 DB 操作。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_or_create(self, user_id: str) -> UserStateModel:
        """取得或建立 user state 記錄。"""
        stmt = select(UserStateModel).where(UserStateModel.user_id == user_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            return row
        row = UserStateModel(user_id=user_id)
        self.session.add(row)
        await self.session.flush()
        return row

    # ---- last_message ----

    async def get_last_message(self, user_id: str) -> str | None:
        """讀取使用者最後一則非指令訊息。"""
        stmt = select(UserStateModel.last_message).where(
            UserStateModel.user_id == user_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_last_message(self, user_id: str, message: str) -> None:
        """儲存使用者最後一則非指令訊息。"""
        row = await self._get_or_create(user_id)
        row.last_message = message
        row.last_message_at = datetime.now(UTC)
        await self.session.flush()

    async def clear_last_message(self, user_id: str) -> None:
        """清除使用者最後一則非指令訊息。"""
        stmt = select(UserStateModel).where(UserStateModel.user_id == user_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            row.last_message = None
            row.last_message_at = None
            await self.session.flush()

    # ---- delete_confirm ----

    async def get_delete_confirm_at(self, user_id: str) -> datetime | None:
        """取得清空確認請求時間。"""
        stmt = select(UserStateModel.delete_confirm_at).where(
            UserStateModel.user_id == user_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_delete_confirm_at(self, user_id: str) -> None:
        """設定清空確認請求時間為現在。"""
        row = await self._get_or_create(user_id)
        row.delete_confirm_at = datetime.now(UTC)
        await self.session.flush()

    async def clear_delete_confirm(self, user_id: str) -> None:
        """清除清空確認狀態。"""
        stmt = select(UserStateModel).where(UserStateModel.user_id == user_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            row.delete_confirm_at = None
            await self.session.flush()

    async def is_delete_confirmation_pending(self, user_id: str) -> bool:
        """檢查是否有未過期的清空確認請求。"""
        confirm_at = await self.get_delete_confirm_at(user_id)
        if not confirm_at:
            return False
        # 確保 timezone-aware 比較（防止 DB driver 回傳 naive datetime）
        if confirm_at.tzinfo is None:
            confirm_at = confirm_at.replace(tzinfo=UTC)
        elapsed = (datetime.now(UTC) - confirm_at).total_seconds()
        if elapsed > CONFIRMATION_TIMEOUT:
            await self.clear_delete_confirm(user_id)
            return False
        return True

    # ---- pending_save ----

    async def get_pending_save(self, user_id: str) -> str | None:
        """取得待確認入庫的內容（含過期檢查）。

        Args:
            user_id: Hashed LINE user ID

        Returns:
            待確認內容，若不存在或已過期則回傳 None
        """
        stmt = select(
            UserStateModel.pending_save_content,
            UserStateModel.pending_save_at,
        ).where(UserStateModel.user_id == user_id)
        result = await self.session.execute(stmt)
        row = result.one_or_none()

        if not row or not row.pending_save_content or not row.pending_save_at:
            return None

        pending_at = row.pending_save_at
        # 確保 timezone-aware 比較
        if pending_at.tzinfo is None:
            pending_at = pending_at.replace(tzinfo=UTC)

        elapsed = (datetime.now(UTC) - pending_at).total_seconds()
        if elapsed > PENDING_SAVE_TIMEOUT:
            await self.clear_pending_save(user_id)
            return None

        return row.pending_save_content

    async def set_pending_save(self, user_id: str, content: str) -> None:
        """設定待確認入庫的內容。

        Args:
            user_id: Hashed LINE user ID
            content: 待確認入庫的內容
        """
        row = await self._get_or_create(user_id)
        row.pending_save_content = content
        row.pending_save_at = datetime.now(UTC)
        await self.session.flush()

    async def clear_pending_save(self, user_id: str) -> None:
        """清除待確認入庫狀態。

        Args:
            user_id: Hashed LINE user ID
        """
        stmt = select(UserStateModel).where(UserStateModel.user_id == user_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            row.pending_save_content = None
            row.pending_save_at = None
            await self.session.flush()

    async def has_pending_save(self, user_id: str) -> bool:
        """檢查是否有未過期的待確認入庫狀態。

        Args:
            user_id: Hashed LINE user ID

        Returns:
            True 若有未過期的待確認狀態
        """
        content = await self.get_pending_save(user_id)
        return content is not None
