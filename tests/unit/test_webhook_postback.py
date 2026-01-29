"""
PostbackEvent 處理的單元測試。

測試 handle_postback_event 的模式切換邏輯。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.webhook import handle_postback_event


def _make_postback_event(
    data: str,
    user_id: str = "Utest_user",
    reply_token: str = "test_reply_token",
) -> MagicMock:
    """建立模擬的 PostbackEvent。"""
    event = MagicMock()
    event.source = MagicMock()
    event.source.user_id = user_id
    event.reply_token = reply_token
    event.postback = MagicMock()
    event.postback.data = data
    return event


class TestHandlePostbackEvent:
    """測試 PostbackEvent 處理。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    async def test_switch_mode_cheap(self, mock_hash, mock_session_ctx, mock_get_line):
        """Postback 切換省錢模式應呼叫 set_mode 並回覆。"""
        # 設定 mock
        mock_line = MagicMock()
        mock_line.reply_with_quick_reply = AsyncMock(return_value=True)
        mock_get_line.return_value = mock_line

        mock_profile = MagicMock()
        mock_profile.daily_used_tokens = 1000
        mock_profile.daily_cap_tokens_free = 50000

        mock_repo = MagicMock()
        mock_repo.set_mode = AsyncMock(return_value=mock_profile)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = mock_session

        with patch("src.api.webhook.UserProfileRepository", return_value=mock_repo):
            event = _make_postback_event("action=switch_mode&mode=cheap")
            await handle_postback_event(event)

        mock_repo.set_mode.assert_awaited_once_with("hashed_user", "cheap")
        mock_line.reply_with_quick_reply.assert_awaited_once()

        # 確認回覆包含省錢
        call_args = mock_line.reply_with_quick_reply.call_args
        reply_text = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("text", "")
        assert "便宜" in reply_text

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    async def test_unknown_postback_logs_warning(self, mock_get_line):
        """未知 postback action 應記錄 warning 不回覆。"""
        mock_line = MagicMock()
        mock_line.reply_with_quick_reply = AsyncMock()
        mock_get_line.return_value = mock_line

        event = _make_postback_event("action=unknown_action&foo=bar")
        await handle_postback_event(event)

        mock_line.reply_with_quick_reply.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    async def test_missing_user_id_returns_early(self, mock_get_line):
        """缺少 user_id 時應提前返回。"""
        mock_line = MagicMock()
        mock_get_line.return_value = mock_line

        event = MagicMock()
        event.source = MagicMock()
        event.source.user_id = None
        event.reply_token = "token"

        await handle_postback_event(event)

        # 不應有任何 LINE API 呼叫
        mock_line.reply_with_quick_reply.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    async def test_switch_mode_rigorous(self, mock_hash, mock_session_ctx, mock_get_line):
        """Postback 切換嚴謹模式。"""
        mock_line = MagicMock()
        mock_line.reply_with_quick_reply = AsyncMock(return_value=True)
        mock_get_line.return_value = mock_line

        mock_profile = MagicMock()
        mock_profile.daily_used_tokens = 2000
        mock_profile.daily_cap_tokens_free = 50000

        mock_repo = MagicMock()
        mock_repo.set_mode = AsyncMock(return_value=mock_profile)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = mock_session

        with patch("src.api.webhook.UserProfileRepository", return_value=mock_repo):
            event = _make_postback_event("action=switch_mode&mode=rigorous")
            await handle_postback_event(event)

        mock_repo.set_mode.assert_awaited_once_with("hashed_user", "rigorous")
