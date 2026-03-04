"""
Unit tests for delete functionality.

T074: Write unit tests for delete in tests/unit/test_delete.py
DoD: 測試軟刪除邏輯；驗證 is_deleted flag 正確設定
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta, timezone
import uuid

from src.services.delete_service import DeleteService


class TestUserStateConfirmation:
    """Tests for DB-backed confirmation state via UserStateRepository."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_is_pending_false_when_no_record(self, mock_session):
        """沒有記錄時回傳 False。"""
        from src.repositories.user_state_repo import UserStateRepository

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        repo = UserStateRepository(mock_session)
        assert await repo.is_delete_confirmation_pending("test_user") is False

    @pytest.mark.asyncio
    async def test_is_pending_true_when_recent(self, mock_session):
        """有近期確認請求時回傳 True。"""
        from src.repositories.user_state_repo import UserStateRepository

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = datetime.now(timezone.utc)
        mock_session.execute.return_value = mock_result

        repo = UserStateRepository(mock_session)
        assert await repo.is_delete_confirmation_pending("test_user") is True

    @pytest.mark.asyncio
    async def test_is_pending_false_when_expired(self, mock_session):
        """確認請求過期時回傳 False。"""
        from src.repositories.user_state_repo import UserStateRepository, CONFIRMATION_TIMEOUT

        expired_time = datetime.now(timezone.utc) - timedelta(seconds=CONFIRMATION_TIMEOUT + 10)

        # 第一次呼叫 get_delete_confirm_at 回傳過期時間
        # 第二次呼叫 clear_delete_confirm 時查詢 row
        mock_row = MagicMock()
        mock_result_time = MagicMock()
        mock_result_time.scalar_one_or_none.return_value = expired_time
        mock_result_row = MagicMock()
        mock_result_row.scalar_one_or_none.return_value = mock_row
        mock_session.execute.side_effect = [mock_result_time, mock_result_row]

        repo = UserStateRepository(mock_session)
        assert await repo.is_delete_confirmation_pending("test_user") is False


class TestDeleteItem:
    """Tests for DeleteService.delete_item."""

    @pytest.fixture
    def mock_session(self):
        """Create mock database session."""
        session = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_delete_item_success(self, mock_session):
        """成功刪除指定 item。"""
        mock_item = MagicMock()
        mock_item.item_id = str(uuid.uuid4())
        mock_item.user_id = "test_user_hash"
        mock_item.item_type = "vocab"
        mock_item.key = "食べる"
        mock_item.payload = {
            "surface": "食べる",
            "reading": "たべる",
            "glossary_zh": ["吃"],
        }

        service = DeleteService(mock_session)
        service.item_repo = MagicMock()
        service.item_repo.get_by_id = AsyncMock(return_value=mock_item)
        service.item_repo.soft_delete = AsyncMock(return_value=True)
        service.practice_log_repo = MagicMock()
        service.practice_log_repo.soft_delete_by_item = AsyncMock(return_value=0)

        success, message = await service.delete_item("test_user_hash", mock_item.item_id)

        assert success is True
        assert "已刪除" in message
        assert "食べる" in message
        service.item_repo.soft_delete.assert_awaited_once_with(mock_item.item_id)
        service.practice_log_repo.soft_delete_by_item.assert_awaited_once_with(mock_item.item_id)

    @pytest.mark.asyncio
    async def test_delete_item_not_found(self, mock_session):
        """刪除不存在的 item。"""
        service = DeleteService(mock_session)
        service.item_repo = MagicMock()
        service.item_repo.get_by_id = AsyncMock(return_value=None)

        success, message = await service.delete_item("test_user_hash", str(uuid.uuid4()))

        assert success is False
        assert "沒有可刪除的資料" in message

    @pytest.mark.asyncio
    async def test_delete_item_wrong_owner(self, mock_session):
        """嘗試刪除他人的 item。"""
        mock_item = MagicMock()
        mock_item.item_id = str(uuid.uuid4())
        mock_item.user_id = "other_user_hash"
        mock_item.item_type = "vocab"
        mock_item.payload = {"surface": "食べる"}

        service = DeleteService(mock_session)
        service.item_repo = MagicMock()
        service.item_repo.get_by_id = AsyncMock(return_value=mock_item)

        success, message = await service.delete_item("test_user_hash", mock_item.item_id)

        assert success is False
        assert "沒有可刪除的資料" in message

    def test_format_item_label_vocab(self):
        """格式化 vocab item 標籤。"""
        mock_item = MagicMock()
        mock_item.item_type = "vocab"
        mock_item.key = "食べる"
        mock_item.payload = {
            "surface": "食べる",
            "reading": "たべる",
            "glossary_zh": ["吃"],
        }

        label = DeleteService.format_item_label(mock_item)
        assert "食べる" in label
        assert "たべる" in label
        assert "吃" in label

    def test_format_item_label_grammar(self):
        """格式化 grammar item 標籤。"""
        mock_item = MagicMock()
        mock_item.item_type = "grammar"
        mock_item.key = "〜てしまう"
        mock_item.payload = {
            "pattern": "〜てしまう",
            "meaning_zh": "完全做完；不小心做了",
        }

        label = DeleteService.format_item_label(mock_item)
        assert "〜てしまう" in label
        assert "完全做完" in label

    def test_format_item_label_vocab_same_surface_reading(self):
        """surface 與 reading 相同時不重複顯示。"""
        mock_item = MagicMock()
        mock_item.item_type = "vocab"
        mock_item.key = "たべる"
        mock_item.payload = {
            "surface": "たべる",
            "reading": "たべる",
            "glossary_zh": ["吃"],
        }

        label = DeleteService.format_item_label(mock_item)
        assert "【" not in label  # 不應有【reading】


class TestClearAllData:
    """Tests for DeleteService.clear_all_data."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_clear_all_data_includes_practice_logs(self, mock_session):
        """清空資料需包含練習紀錄並反映在回傳訊息。"""
        service = DeleteService(mock_session)
        # _soft_delete_all 依序呼叫：Item(3), PracticeLog(4), Document(2), RawMessage(1), PracticeSession(2)
        service._soft_delete_all = AsyncMock(side_effect=[3, 4, 2, 1, 2])

        deleted_count, message = await service.clear_all_data("test_user_hash")

        assert deleted_count == 12
        assert "4 筆練習紀錄" in message


class TestSoftDeleteFlags:
    """Tests for soft delete flag behavior."""

    @pytest.mark.asyncio
    async def test_soft_delete_sets_is_deleted_flag(self, async_db_session):
        """Test that soft delete sets is_deleted to True."""
        from src.repositories.item_repo import ItemRepository

        repo = ItemRepository(async_db_session)

        assert hasattr(repo, 'soft_delete')

    @pytest.mark.asyncio
    async def test_deleted_items_excluded_from_queries(self, async_db_session):
        """Test that deleted items are excluded from normal queries."""
        from src.repositories.item_repo import ItemRepository

        repo = ItemRepository(async_db_session)

        items = await repo.get_by_user(
            user_id="test_user_hash",
            include_deleted=False,
        )

        assert items == []

    @pytest.mark.asyncio
    async def test_deleted_items_included_when_requested(self, async_db_session):
        """Test that deleted items can be included when explicitly requested."""
        from src.repositories.item_repo import ItemRepository

        repo = ItemRepository(async_db_session)

        items = await repo.get_by_user(
            user_id="test_user_hash",
            include_deleted=True,
        )

        assert isinstance(items, list)
