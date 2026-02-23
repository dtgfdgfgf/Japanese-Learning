"""Repository for user transient state persistence."""

import json
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

# 待確認刪除逾時（秒）
PENDING_DELETE_TIMEOUT = 300  # 5 分鐘


class UserStateRepository:
    """使用者暫存狀態的 DB 操作。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_active(self, user_id: str) -> UserStateModel | None:
        """取得使用者的 active（未 soft delete）state 記錄。"""
        stmt = select(UserStateModel).where(
            UserStateModel.user_id == user_id,
            UserStateModel.is_deleted.is_(False),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_or_create(self, user_id: str) -> UserStateModel:
        """取得或建立 user state 記錄。

        若記錄曾被 soft delete，則恢復（設 is_deleted=False）。
        """
        stmt = select(UserStateModel).where(UserStateModel.user_id == user_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            if row.is_deleted:
                row.is_deleted = False
                await self.session.flush()
            return row
        row = UserStateModel(user_id=user_id)
        self.session.add(row)
        await self.session.flush()
        return row

    # ---- last_message ----

    async def get_last_message(self, user_id: str) -> str | None:
        """讀取使用者最後一則非指令訊息。"""
        stmt = select(UserStateModel.last_message).where(
            UserStateModel.user_id == user_id,
            UserStateModel.is_deleted.is_(False),
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
        row = await self._get_active(user_id)
        if row:
            row.last_message = None
            row.last_message_at = None
            await self.session.flush()

    # ---- delete_confirm ----

    async def get_delete_confirm_at(self, user_id: str) -> datetime | None:
        """取得清空確認請求時間。"""
        stmt = select(UserStateModel.delete_confirm_at).where(
            UserStateModel.user_id == user_id,
            UserStateModel.is_deleted.is_(False),
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
        row = await self._get_active(user_id)
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
        ).where(
            UserStateModel.user_id == user_id,
            UserStateModel.is_deleted.is_(False),
        )
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

    async def set_pending_save_with_item(
        self,
        user_id: str,
        content: str,
        extracted_item: dict,
    ) -> None:
        """設定待確認入庫的內容，附帶預先抽取的 item 資料。

        將 word + extracted_item 打包為 JSON 存入 pending_save_content，
        確認入庫時可直接建立 item，省去再次呼叫 ExtractorService。

        Args:
            user_id: Hashed LINE user ID
            content: 待確認入庫的單字
            extracted_item: 結構化 item 資料（與 ExtractedItem schema 相容）
        """
        payload = json.dumps(
            {"word": content, "extracted_item": extracted_item},
            ensure_ascii=False,
        )
        row = await self._get_or_create(user_id)
        row.pending_save_content = payload
        row.pending_save_at = datetime.now(UTC)
        await self.session.flush()

    def parse_pending_save_content(self, raw_content: str) -> tuple[str, dict | None]:
        """解析 pending_save_content，相容新舊格式。

        新格式：JSON {"word": "...", "extracted_item": {...}}
        舊格式：純文字（直接回傳）

        Args:
            raw_content: DB 中的 pending_save_content

        Returns:
            (content, extracted_item_dict | None)
        """
        try:
            data = json.loads(raw_content)
            if isinstance(data, dict) and "word" in data:
                return data["word"], data.get("extracted_item")
        except (json.JSONDecodeError, TypeError):
            pass
        return raw_content, None

    async def clear_pending_save(self, user_id: str) -> None:
        """清除待確認入庫狀態。

        Args:
            user_id: Hashed LINE user ID
        """
        row = await self._get_active(user_id)
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

    # ---- pending_delete ----

    async def get_pending_delete(self, user_id: str) -> list[dict[str, str]] | None:
        """取得待確認刪除的項目列表（含過期檢查）。

        Args:
            user_id: Hashed LINE user ID

        Returns:
            待確認刪除項目列表，若不存在或已過期則回傳 None
        """
        stmt = select(
            UserStateModel.pending_delete_items,
            UserStateModel.pending_delete_at,
        ).where(
            UserStateModel.user_id == user_id,
            UserStateModel.is_deleted.is_(False),
        )
        result = await self.session.execute(stmt)
        row = result.one_or_none()

        if not row or not row.pending_delete_items or not row.pending_delete_at:
            return None

        pending_at = row.pending_delete_at
        # 確保 timezone-aware 比較
        if pending_at.tzinfo is None:
            pending_at = pending_at.replace(tzinfo=UTC)

        elapsed = (datetime.now(UTC) - pending_at).total_seconds()
        if elapsed > PENDING_DELETE_TIMEOUT:
            await self.clear_pending_delete(user_id)
            return None

        try:
            return json.loads(row.pending_delete_items)
        except (json.JSONDecodeError, TypeError):
            await self.clear_pending_delete(user_id)
            return None

    async def set_pending_delete(
        self, user_id: str, items: list[dict[str, str]]
    ) -> None:
        """設定待確認刪除的項目列表，同時清除 pending_save（互斥）。

        Args:
            user_id: Hashed LINE user ID
            items: 待確認刪除項目列表 [{item_id, label}]
        """
        row = await self._get_or_create(user_id)
        row.pending_delete_items = json.dumps(items, ensure_ascii=False)
        row.pending_delete_at = datetime.now(UTC)
        # 互斥：清除 pending_save
        row.pending_save_content = None
        row.pending_save_at = None
        await self.session.flush()

    async def clear_pending_delete(self, user_id: str) -> None:
        """清除待確認刪除狀態。

        Args:
            user_id: Hashed LINE user ID
        """
        row = await self._get_active(user_id)
        if row:
            row.pending_delete_items = None
            row.pending_delete_at = None
            await self.session.flush()

    async def has_pending_delete(self, user_id: str) -> bool:
        """檢查是否有未過期的待確認刪除狀態。

        Args:
            user_id: Hashed LINE user ID

        Returns:
            True 若有未過期的待確認狀態
        """
        items = await self.get_pending_delete(user_id)
        return items is not None
