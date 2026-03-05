"""
Integration tests for input classification flow.

驗證非指令訊息透過 handle_message_event 正確路由到 WORD/MATERIAL/CHAT 分類處理。
已從 LLM Router 遷移至結構特徵分類（_classify_input）。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.webhook import handle_message_event


def _make_message_event(
    text: str,
    user_id: str = "Utest",
) -> MagicMock:
    """建立模擬的 MessageEvent。"""
    from linebot.v3.webhooks import TextMessageContent

    event = MagicMock()
    event.source = MagicMock()
    event.source.user_id = user_id
    event.reply_token = "test_reply_token"
    event.message = MagicMock(spec=TextMessageContent)
    event.message.text = text
    event.webhook_event_id = None
    return event


def _setup_common_mocks(
    mock_get_line: MagicMock,
    mock_session_ctx: MagicMock,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """設定 handle_message_event 所需的通用 mock。"""
    mock_line = MagicMock()
    mock_line.reply_with_quick_reply = AsyncMock(return_value=True)
    mock_get_line.return_value = mock_line

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session_ctx.return_value = mock_session

    mock_profile = MagicMock()
    mock_profile.mode = "free"
    mock_profile.target_lang = "ja"
    mock_profile.daily_used_tokens = 0
    mock_profile.daily_cap_tokens_free = 50000

    mock_profile_repo = MagicMock()
    mock_profile_repo.get_or_create = AsyncMock(return_value=mock_profile)
    mock_profile_repo.add_tokens = AsyncMock(return_value=mock_profile)

    mock_user_state_repo = MagicMock()
    mock_user_state_repo.has_pending_delete = AsyncMock(return_value=False)
    mock_user_state_repo.has_pending_save = AsyncMock(return_value=False)
    mock_user_state_repo.set_last_message = AsyncMock()
    mock_user_state_repo.set_pending_save = AsyncMock()
    mock_user_state_repo.set_pending_save_with_item = AsyncMock()
    mock_user_state_repo.get_article_mode = AsyncMock(return_value=None)

    return mock_line, mock_user_state_repo, mock_profile_repo


def _get_reply_text(mock_line: MagicMock) -> str:
    call_args = mock_line.reply_with_quick_reply.call_args
    if call_args:
        return call_args[0][1] if len(call_args[0]) > 1 else ""
    return ""


class TestInputClassificationIntegration:
    """Integration tests for structure-based input classification."""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_material_classification_article_translation(
        self, mock_has_session, mock_hash, mock_session_ctx, mock_get_line
    ):
        """日文段落（有句讀）→ MATERIAL → 文章翻譯模式。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
            patch(
                "src.api.webhook._handle_article_translation",
                new_callable=AsyncMock,
                return_value="📖 全文翻譯：\n翻譯結果",
            ) as mock_article,
        ):
            event = _make_message_event("今日は天気がいいですね。散歩に行きましょう。")
            await handle_message_event(event)

        mock_article.assert_awaited_once()
        reply_text = _get_reply_text(mock_line)
        assert "全文翻譯" in reply_text

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_chat_classification_for_questions(
        self, mock_has_session, mock_hash, mock_session_ctx, mock_get_line
    ):
        """中文問句 → CHAT → LLM chat 回覆。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx
        )

        mock_chat_resp = MagicMock()
        mock_chat_resp.content = "this grammar means..."
        mock_chat_resp.to_trace.return_value = MagicMock()

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
            patch(
                "src.services.router_service.RouterService.get_chat_response",
                new_callable=AsyncMock,
                return_value=mock_chat_resp,
            ),
        ):
            # NFKC: ？→?
            event = _make_message_event("這個文法怎麼用？")
            await handle_message_event(event)

        reply_text = _get_reply_text(mock_line)
        assert "this grammar means" in reply_text

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_word_classification_for_short_input(
        self, mock_has_session, mock_hash, mock_session_ctx, mock_get_line
    ):
        """短日文單字 → WORD → 查詞解釋。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
            patch("src.api.webhook._search_user_items", new_callable=AsyncMock, return_value=[]),
            patch(
                "src.services.router_service.RouterService.get_word_explanation_structured",
                new_callable=AsyncMock,
                return_value=("means thinking", None, None),
            ),
        ):
            event = _make_message_event("考える")
            await handle_message_event(event)

        reply_text = _get_reply_text(mock_line)
        assert "means thinking" in reply_text

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_word_classification_for_english_ok(
        self, mock_has_session, mock_hash, mock_session_ctx, mock_get_line
    ):
        """英文 'ok' → WORD → 查詞解釋（不再是 UNKNOWN fallback）。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
            patch("src.api.webhook._search_user_items", new_callable=AsyncMock, return_value=[]),
            patch(
                "src.services.router_service.RouterService.get_word_explanation_structured",
                new_callable=AsyncMock,
                return_value=("ok means alright", None, None),
            ),
        ):
            event = _make_message_event("ok")
            await handle_message_event(event)

        reply_text = _get_reply_text(mock_line)
        assert "ok means alright" in reply_text

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_word_handler_error_graceful_fallback(
        self, mock_has_session, mock_hash, mock_session_ctx, mock_get_line
    ):
        """WORD handler 內部錯誤時仍應回覆錯誤訊息（不 crash）。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
            patch(
                "src.api.webhook._search_user_items",
                new_callable=AsyncMock,
                side_effect=Exception("DB connection error"),
            ),
        ):
            event = _make_message_event("test")
            await handle_message_event(event)

        # 應有回覆（不 crash），回覆內容為錯誤訊息
        mock_line.reply_with_quick_reply.assert_awaited_once()
