"""UserProfile repository — 使用者偏好與每日用量的資料存取層。

提供 get_or_create（含日切重置）、模式切換、原子 token 累加。
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user_profile import UserProfile

logger = logging.getLogger(__name__)

# 舊模式值 → 新模式值映射（相容 migration 前的 DB 資料）
_LEGACY_MODE_MAP: dict[str, str] = {
    "balanced": "free",
}

# Asia/Taipei = UTC+8
_TAIPEI_OFFSET = timezone(timedelta(hours=8))


def _next_reset_at() -> datetime:
    """計算下一個 Asia/Taipei 00:00 (以 UTC 表示)。"""
    now_taipei = datetime.now(_TAIPEI_OFFSET)
    tomorrow_taipei = (now_taipei + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return tomorrow_taipei.astimezone(timezone.utc)


class UserProfileRepository:
    """使用者偏好 Repository。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, user_id: str) -> UserProfile:
        """取得使用者偏好；不存在則建立，並在日切時重置 daily_used_tokens。

        Args:
            user_id: Hashed LINE user ID

        Returns:
            UserProfile（已處理日切重置）
        """
        profile = await self.session.get(UserProfile, user_id)

        if profile is None:
            profile = UserProfile(
                user_id=user_id,
                reset_at=_next_reset_at(),
            )
            self.session.add(profile)
            await self.session.flush()
            return profile

        # 日切重置檢查
        now_utc = datetime.now(timezone.utc)
        if now_utc >= profile.reset_at:
            profile.daily_used_tokens = 0
            profile.reset_at = _next_reset_at()
            await self.session.flush()

        # 舊模式值相容處理
        new_mode = _LEGACY_MODE_MAP.get(profile.mode)
        if new_mode:
            profile.mode = new_mode
            await self.session.flush()

        return profile

    async def set_target_lang(self, user_id: str, target_lang: str) -> UserProfile:
        """切換目標學習語言。

        Args:
            user_id: Hashed LINE user ID
            target_lang: ja / en

        Returns:
            更新後的 UserProfile
        """
        if target_lang not in ("ja", "en"):
            raise ValueError(f"Invalid target_lang: {target_lang}")
        profile = await self.get_or_create(user_id)
        profile.target_lang = target_lang
        await self.session.flush()
        return profile

    async def set_mode(self, user_id: str, mode: str) -> UserProfile:
        """切換 LLM 模式。

        Args:
            user_id: Hashed LINE user ID
            mode: cheap / balanced / rigorous

        Returns:
            更新後的 UserProfile
        """
        profile = await self.get_or_create(user_id)
        profile.mode = mode
        await self.session.flush()
        return profile

    async def add_tokens(self, user_id: str, delta: int) -> UserProfile:
        """原子累加今日已使用 token 數。

        使用 SQL 原子 increment 避免 race condition。

        Args:
            user_id: Hashed LINE user ID
            delta: 要累加的 token 數

        Returns:
            更新後的 UserProfile
        """
        stmt = (
            update(UserProfile)
            .where(UserProfile.user_id == user_id)
            .values(daily_used_tokens=UserProfile.daily_used_tokens + delta)
        )
        await self.session.execute(stmt)
        await self.session.flush()

        # 重新讀取最新值
        profile = await self.session.get(UserProfile, user_id)
        if profile:
            await self.session.refresh(profile)
        return profile  # type: ignore[return-value]
