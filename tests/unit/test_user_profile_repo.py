"""
UserProfileRepository 的單元測試。

測試 get_or_create（含日切重置）、set_mode、add_tokens。
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.user_profile import UserProfile
from src.repositories.user_profile_repo import UserProfileRepository, _next_reset_at


# ============================================================================
# Helpers
# ============================================================================

_TAIPEI_OFFSET = timezone(timedelta(hours=8))


def _make_profile(
    user_id: str = "hashed_user",
    mode: str = "free",
    daily_used: int = 0,
    reset_at: datetime | None = None,
) -> MagicMock:
    """建立測試用 UserProfile mock 物件。"""
    p = MagicMock(spec=UserProfile)
    p.user_id = user_id
    p.mode = mode
    p.daily_cap_tokens_free = 50000
    p.daily_used_tokens = daily_used
    p.reset_at = reset_at or (_next_reset_at())
    p.created_at = datetime.now(timezone.utc)
    p.updated_at = datetime.now(timezone.utc)
    return p


# ============================================================================
# _next_reset_at
# ============================================================================


class TestNextResetAt:
    """測試 _next_reset_at 工具函數。"""

    def test_returns_future_utc(self):
        """回傳的時間應在未來且為 UTC。"""
        result = _next_reset_at()
        now_utc = datetime.now(timezone.utc)
        assert result > now_utc

    def test_result_is_midnight_taipei(self):
        """回傳的時間轉換為台北時區後應為 00:00。"""
        result = _next_reset_at()
        taipei_time = result.astimezone(_TAIPEI_OFFSET)
        assert taipei_time.hour == 0
        assert taipei_time.minute == 0
        assert taipei_time.second == 0


# ============================================================================
# get_or_create
# ============================================================================


class TestGetOrCreate:
    """測試 get_or_create 方法。"""

    @pytest.mark.asyncio
    async def test_creates_new_profile(self):
        """使用者不存在時應建立新 profile。"""
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        session.add = MagicMock()
        session.flush = AsyncMock()

        repo = UserProfileRepository(session)
        profile = await repo.get_or_create("new_user")

        assert profile.user_id == "new_user"
        # mode/daily_used 的 Python default 由 SQLAlchemy mapped_column default 控制
        # 新建的 profile 應有 reset_at
        assert profile.reset_at is not None
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_existing_profile(self):
        """使用者已存在且未過日切時應直接回傳。"""
        existing = _make_profile(
            reset_at=datetime.now(timezone.utc) + timedelta(hours=12),
            daily_used=1000,
        )
        session = AsyncMock()
        session.get = AsyncMock(return_value=existing)
        session.flush = AsyncMock()

        repo = UserProfileRepository(session)
        profile = await repo.get_or_create("hashed_user")

        assert profile.daily_used_tokens == 1000

    @pytest.mark.asyncio
    async def test_daily_reset_triggers(self):
        """過了 reset_at 應重置 daily_used_tokens 為 0。"""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        existing = _make_profile(reset_at=past, daily_used=30000)

        session = AsyncMock()
        session.get = AsyncMock(return_value=existing)
        session.flush = AsyncMock()

        repo = UserProfileRepository(session)
        profile = await repo.get_or_create("hashed_user")

        assert profile.daily_used_tokens == 0
        # reset_at 應被更新到未來
        assert profile.reset_at > datetime.now(timezone.utc)
        session.flush.assert_awaited_once()


# ============================================================================
# set_mode
# ============================================================================


class TestSetMode:
    """測試 set_mode 方法。"""

    @pytest.mark.asyncio
    async def test_set_mode_updates_profile(self):
        """set_mode 應更新 profile 的 mode 欄位。"""
        existing = _make_profile(
            mode="balanced",
            reset_at=datetime.now(timezone.utc) + timedelta(hours=12),
        )
        session = AsyncMock()
        session.get = AsyncMock(return_value=existing)
        session.flush = AsyncMock()

        repo = UserProfileRepository(session)
        profile = await repo.set_mode("hashed_user", "cheap")

        assert profile.mode == "cheap"

    @pytest.mark.asyncio
    async def test_set_mode_rigorous(self):
        """切換至嚴謹模式。"""
        existing = _make_profile(
            mode="balanced",
            reset_at=datetime.now(timezone.utc) + timedelta(hours=12),
        )
        session = AsyncMock()
        session.get = AsyncMock(return_value=existing)
        session.flush = AsyncMock()

        repo = UserProfileRepository(session)
        profile = await repo.set_mode("hashed_user", "rigorous")

        assert profile.mode == "rigorous"


# ============================================================================
# add_tokens
# ============================================================================


class TestAddTokens:
    """測試 add_tokens 方法。"""

    @pytest.mark.asyncio
    async def test_add_tokens_returns_updated(self):
        """add_tokens 應執行 SQL 原子更新並回傳更新後的 profile。"""
        updated_profile = _make_profile(daily_used=500)

        session = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        session.get = AsyncMock(return_value=updated_profile)
        session.refresh = AsyncMock()

        repo = UserProfileRepository(session)
        result = await repo.add_tokens("hashed_user", 500)

        assert result.daily_used_tokens == 500
        session.execute.assert_awaited_once()
        session.refresh.assert_awaited_once()
