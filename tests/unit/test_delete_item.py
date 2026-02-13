"""
Unit tests for「刪除 <關鍵字>」完整流程。

測試涵蓋：
- 單筆直刪
- 多筆列表 + 選號碼
- 太多筆 → 提示更精確
- 無結果
- pending_delete 狀態互動
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.schemas.command import CommandType
from src.services.command_service import parse_command


# ============================================================================
# 測試用 mock item 工廠
# ============================================================================

def _make_mock_item(
    item_type: str = "vocab",
    surface: str = "食べる",
    reading: str = "たべる",
    meaning: str = "吃",
    user_id: str = "test_hash",
) -> MagicMock:
    """建立 mock Item 物件。"""
    item = MagicMock()
    item.item_id = str(uuid.uuid4())
    item.user_id = user_id
    item.item_type = item_type
    item.key = surface

    if item_type == "vocab":
        item.payload = {
            "surface": surface,
            "reading": reading,
            "glossary_zh": [meaning],
        }
    else:
        item.payload = {
            "pattern": surface,
            "meaning_zh": meaning,
        }
    return item


# ============================================================================
# 指令解析測試
# ============================================================================

class TestDeleteItemParsing:
    """測試 parse_command 對刪除指令的解析。"""

    def test_delete_with_keyword(self):
        result = parse_command("刪除 食べる")
        assert result.command_type == CommandType.DELETE_ITEM
        assert result.keyword == "食べる"

    def test_delete_without_keyword(self):
        result = parse_command("刪除")
        assert result.command_type == CommandType.DELETE_ITEM
        assert result.keyword is None

    def test_delete_with_whitespace_keyword(self):
        result = parse_command("刪除   apple  ")
        assert result.command_type == CommandType.DELETE_ITEM
        assert result.keyword == "apple"

    def test_delete_with_multi_word_keyword(self):
        result = parse_command("刪除 te form")
        assert result.command_type == CommandType.DELETE_ITEM
        assert result.keyword == "te form"


# ============================================================================
# Webhook handler 測試
# ============================================================================

class TestHandleDeleteItem:
    """測試 _handle_delete_item handler。"""

    @pytest.mark.asyncio
    async def test_no_keyword_returns_hint(self):
        """無關鍵字 → 提示訊息。"""
        from src.api.webhook import _handle_delete_item

        result = await _handle_delete_item("test_line_id", None)
        assert "請輸入要刪除的關鍵字" in result

    @pytest.mark.asyncio
    async def test_no_results(self):
        """搜尋無結果 → 找不到訊息。"""
        from src.api.webhook import _handle_delete_item

        mock_item_repo = MagicMock()
        mock_item_repo.search_by_keyword = AsyncMock(return_value=[])

        with patch("src.api.webhook.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("src.api.webhook.hash_user_id", return_value="hashed_123"):
                with patch("src.repositories.item_repo.ItemRepository", return_value=mock_item_repo):
                    result = await _handle_delete_item("test_line_id", "不存在的字")

        assert "找不到" in result
        assert "不存在的字" in result

    @pytest.mark.asyncio
    async def test_single_result_direct_delete(self):
        """單筆結果 → 直接刪除。"""
        from src.api.webhook import _handle_delete_item

        mock_item = _make_mock_item(user_id="hashed_123")
        mock_item_repo = MagicMock()
        mock_item_repo.search_by_keyword = AsyncMock(return_value=[mock_item])

        mock_delete_service = MagicMock()
        mock_delete_service.delete_item = AsyncMock(
            return_value=(True, "已刪除「食べる【たべる】- 吃」🗑️")
        )

        with patch("src.api.webhook.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("src.api.webhook.hash_user_id", return_value="hashed_123"):
                with patch("src.repositories.item_repo.ItemRepository", return_value=mock_item_repo):
                    with patch("src.services.delete_service.DeleteService", return_value=mock_delete_service):
                        result = await _handle_delete_item("test_line_id", "食べる")

        assert "已刪除" in result

    @pytest.mark.asyncio
    async def test_multiple_results_show_list(self):
        """2-5 筆結果 → 顯示列表。"""
        from src.api.webhook import _handle_delete_item

        items = [
            _make_mock_item(surface="食べる", reading="たべる", meaning="吃", user_id="hashed_123"),
            _make_mock_item(surface="食べ物", reading="たべもの", meaning="食物", user_id="hashed_123"),
        ]

        mock_item_repo = MagicMock()
        mock_item_repo.search_by_keyword = AsyncMock(return_value=items)

        mock_user_state_repo = MagicMock()
        mock_user_state_repo.set_pending_delete = AsyncMock()

        with patch("src.api.webhook.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("src.api.webhook.hash_user_id", return_value="hashed_123"):
                with patch("src.repositories.item_repo.ItemRepository", return_value=mock_item_repo):
                    with patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo):
                        result = await _handle_delete_item("test_line_id", "食べ")

        assert "2 筆" in result
        assert "食べる" in result
        assert "食べ物" in result
        assert "編號" in result
        mock_user_state_repo.set_pending_delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_too_many_results(self):
        """超過 5 筆 → 提示更精確。"""
        from src.api.webhook import _handle_delete_item

        items = [
            _make_mock_item(surface=f"word{i}", reading=f"reading{i}", meaning=f"意思{i}", user_id="hashed_123")
            for i in range(8)
        ]

        mock_item_repo = MagicMock()
        mock_item_repo.search_by_keyword = AsyncMock(return_value=items)

        with patch("src.api.webhook.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("src.api.webhook.hash_user_id", return_value="hashed_123"):
                with patch("src.repositories.item_repo.ItemRepository", return_value=mock_item_repo):
                    result = await _handle_delete_item("test_line_id", "word")

        assert "8 筆" in result
        assert "更精確" in result


# ============================================================================
# pending_delete 選號測試
# ============================================================================

class TestHandleDeleteSelect:
    """測試 _handle_delete_select handler。"""

    @pytest.mark.asyncio
    async def test_valid_selection(self):
        """有效編號 → 刪除成功。"""
        from src.api.webhook import _handle_delete_select

        candidates = [
            {"item_id": str(uuid.uuid4()), "label": "食べる【たべる】- 吃"},
            {"item_id": str(uuid.uuid4()), "label": "食べ物【たべもの】- 食物"},
        ]

        mock_user_state_repo = MagicMock()
        mock_user_state_repo.get_pending_delete = AsyncMock(return_value=candidates)
        mock_user_state_repo.clear_pending_delete = AsyncMock()

        mock_delete_service = MagicMock()
        mock_delete_service.delete_item = AsyncMock(
            return_value=(True, "已刪除「食べる【たべる】- 吃」🗑️")
        )

        with patch("src.api.webhook.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo):
                with patch("src.services.delete_service.DeleteService", return_value=mock_delete_service):
                    result = await _handle_delete_select("hashed_123", 1)

        assert "已刪除" in result
        mock_user_state_repo.clear_pending_delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_number_too_high(self):
        """編號超出範圍 → 提示。"""
        from src.api.webhook import _handle_delete_select

        candidates = [
            {"item_id": str(uuid.uuid4()), "label": "食べる【たべる】- 吃"},
        ]

        mock_user_state_repo = MagicMock()
        mock_user_state_repo.get_pending_delete = AsyncMock(return_value=candidates)

        with patch("src.api.webhook.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo):
                result = await _handle_delete_select("hashed_123", 5)

        assert "有效的編號" in result

    @pytest.mark.asyncio
    async def test_invalid_number_zero(self):
        """編號 0 → 提示。"""
        from src.api.webhook import _handle_delete_select

        candidates = [
            {"item_id": str(uuid.uuid4()), "label": "食べる【たべる】- 吃"},
        ]

        mock_user_state_repo = MagicMock()
        mock_user_state_repo.get_pending_delete = AsyncMock(return_value=candidates)

        with patch("src.api.webhook.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo):
                result = await _handle_delete_select("hashed_123", 0)

        assert "有效的編號" in result

    @pytest.mark.asyncio
    async def test_expired_pending(self):
        """pending_delete 已過期 → 過期提示。"""
        from src.api.webhook import _handle_delete_select

        mock_user_state_repo = MagicMock()
        mock_user_state_repo.get_pending_delete = AsyncMock(return_value=None)

        with patch("src.api.webhook.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo):
                result = await _handle_delete_select("hashed_123", 1)

        assert "刪除選項已過期" in result


# ============================================================================
# Helper 函數測試
# ============================================================================

class TestDeleteHelpers:
    """測試刪除相關 helper 函數。"""

    def test_build_delete_candidates(self):
        """測試 _build_delete_candidates 格式化。"""
        from src.api.webhook import _build_delete_candidates

        items = [
            _make_mock_item(surface="食べる", reading="たべる", meaning="吃"),
            _make_mock_item(
                item_type="grammar",
                surface="〜てしまう",
                reading="",
                meaning="不小心做了",
            ),
        ]

        candidates = _build_delete_candidates(items)

        assert len(candidates) == 2
        assert "item_id" in candidates[0]
        assert "label" in candidates[0]
        assert "食べる" in candidates[0]["label"]
        assert "〜てしまう" in candidates[1]["label"]

    def test_format_delete_candidates(self):
        """測試 _format_delete_candidates 編號列表。"""
        from src.api.webhook import _format_delete_candidates

        candidates = [
            {"item_id": "id1", "label": "食べる【たべる】- 吃"},
            {"item_id": "id2", "label": "食べ物【たべもの】- 食物"},
        ]

        result = _format_delete_candidates(candidates)

        assert "1. 食べる【たべる】- 吃" in result
        assert "2. 食べ物【たべもの】- 食物" in result


# ============================================================================
# 狀態互斥測試
# ============================================================================

class TestPendingDeleteMutualExclusion:
    """測試 pending_delete 與 pending_save 的互斥。"""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_set_pending_delete_clears_pending_save(self, mock_session):
        """設定 pending_delete 時清除 pending_save。"""
        from src.repositories.user_state_repo import UserStateRepository

        mock_row = MagicMock()
        mock_row.pending_save_content = "舊的 pending 內容"
        mock_row.pending_save_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row
        mock_session.execute.return_value = mock_result

        repo = UserStateRepository(mock_session)
        items = [{"item_id": "id1", "label": "test"}]
        await repo.set_pending_delete("test_user", items)

        # 確認 pending_save 被清除
        assert mock_row.pending_save_content is None
        assert mock_row.pending_save_at is None
        # 確認 pending_delete 被設定
        assert mock_row.pending_delete_items is not None
        assert mock_row.pending_delete_at is not None
