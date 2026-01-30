"""Unit tests for StatsService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestStatsService:
    """Tests for StatsService.get_stats_summary."""

    @pytest.mark.asyncio
    async def test_stats_summary_with_data(self):
        """有練習紀錄時，回傳格式化的統計訊息。"""
        from src.services.stats_service import StatsService

        with patch.object(StatsService, "__init__", lambda self, session: None):
            service = StatsService.__new__(StatsService)
            service.item_repo = MagicMock()
            service.item_repo.count_by_user = AsyncMock(side_effect=[30, 12])
            service.practice_log_repo = MagicMock()
            service.practice_log_repo.count_by_user = AsyncMock(side_effect=[85, 61])
            service.practice_log_repo.count_by_user_since = AsyncMock(side_effect=[20, 16])

            result = await service.get_stats_summary("hashed_user")

            assert result.success is True
            assert "42" in result.message  # total items
            assert "30" in result.message  # vocab
            assert "12" in result.message  # grammar
            assert "85" in result.message  # total practice
            assert "71%" in result.message  # correct rate (61/85 = 71%, truncated)
            assert "20" in result.message  # recent practice
            assert "80%" in result.message  # recent rate (16/20 = 80%)

    @pytest.mark.asyncio
    async def test_stats_summary_empty(self):
        """無任何素材與練習紀錄時，顯示空白訊息。"""
        from src.services.stats_service import StatsService

        with patch.object(StatsService, "__init__", lambda self, session: None):
            service = StatsService.__new__(StatsService)
            service.item_repo = MagicMock()
            service.item_repo.count_by_user = AsyncMock(return_value=0)
            service.practice_log_repo = MagicMock()
            service.practice_log_repo.count_by_user = AsyncMock(return_value=0)
            service.practice_log_repo.count_by_user_since = AsyncMock(return_value=0)

            result = await service.get_stats_summary("hashed_user")

            assert result.success is True
            assert "尚無" in result.message

    @pytest.mark.asyncio
    async def test_stats_zero_practice_no_division_error(self):
        """有素材但無練習紀錄時，正確率顯示 0%。"""
        from src.services.stats_service import StatsService

        with patch.object(StatsService, "__init__", lambda self, session: None):
            service = StatsService.__new__(StatsService)
            service.item_repo = MagicMock()
            service.item_repo.count_by_user = AsyncMock(side_effect=[5, 2])
            service.practice_log_repo = MagicMock()
            service.practice_log_repo.count_by_user = AsyncMock(side_effect=[0, 0])
            service.practice_log_repo.count_by_user_since = AsyncMock(side_effect=[0, 0])

            result = await service.get_stats_summary("hashed_user")

            assert result.success is True
            assert "0%" in result.message
            assert "7" in result.message  # total items
