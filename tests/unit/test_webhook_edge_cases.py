"""
Edge case 測試：驗證 pending_save 與 dispatch 的交互行為。

覆蓋 Case 5-9, 21-30。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.webhook import (
    _has_supported_language_content,
    _is_duplicate_event,
    _is_likely_romaji,
    _processed_events,
    _sanitize_text,
    handle_message_event,
)
from src.templates.messages import Messages


def _make_message_event(
    text: str,
    user_id: str = "Utest_user",
    reply_token: str = "test_reply_token",
) -> MagicMock:
    """建立模擬的 MessageEvent。"""
    from linebot.v3.webhooks import TextMessageContent

    event = MagicMock()
    event.source = MagicMock()
    event.source.user_id = user_id
    event.reply_token = reply_token
    event.message = MagicMock(spec=TextMessageContent)
    event.message.text = text
    return event


def _setup_common_mocks(
    mock_get_line: MagicMock,
    mock_session_ctx: MagicMock,
    has_pending_save: bool = False,
    has_active_session: bool = False,
    mode: str = "free",
    target_lang: str = "ja",
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """設定 handle_message_event 所需的通用 mock。

    Returns:
        (mock_line, mock_user_state_repo, mock_profile_repo)
    """
    # LINE client
    mock_line = MagicMock()
    mock_line.reply_with_quick_reply = AsyncMock(return_value=True)
    mock_line.verify_signature = MagicMock(return_value=True)
    mock_get_line.return_value = mock_line

    # DB session（contextmanager mock）
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session_ctx.return_value = mock_session

    # Profile repo
    mock_profile = MagicMock()
    mock_profile.mode = mode
    mock_profile.target_lang = target_lang
    mock_profile.daily_used_tokens = 0
    mock_profile.daily_cap_tokens_free = 50000

    mock_profile_repo = MagicMock()
    mock_profile_repo.get_or_create = AsyncMock(return_value=mock_profile)
    mock_profile_repo.set_mode = AsyncMock(return_value=mock_profile)
    mock_profile_repo.add_tokens = AsyncMock(return_value=mock_profile)

    # User state repo
    mock_user_state_repo = MagicMock()
    mock_user_state_repo.has_pending_delete = AsyncMock(return_value=False)
    mock_user_state_repo.has_pending_save = AsyncMock(return_value=has_pending_save)
    mock_user_state_repo.clear_pending_save = AsyncMock()
    mock_user_state_repo.clear_pending_delete = AsyncMock()
    mock_user_state_repo.set_last_message = AsyncMock()
    mock_user_state_repo.get_pending_save = AsyncMock(
        return_value="apple" if has_pending_save else None
    )
    mock_user_state_repo.get_article_mode = AsyncMock(return_value=None)

    return mock_line, mock_user_state_repo, mock_profile_repo


def _get_reply_text(mock_line: MagicMock) -> str:
    """從 mock LINE client 的 reply 呼叫中提取回覆文字。"""
    call_args = mock_line.reply_with_quick_reply.call_args
    if call_args:
        return call_args[0][1] if len(call_args[0]) > 1 else ""
    return ""


class TestCase5ConfirmSaveNoPending:
    """Case 5: 輸入「1」但 pending_save 已過期 → 應顯示明確提示。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_confirm_save_no_pending_shows_expired_message(
        self, mock_has_session, mock_hash, mock_session_ctx, mock_get_line
    ):
        """「1」+ 無 pending → 回覆 PENDING_EXPIRED，不走 Router。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx, has_pending_save=False
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
        ):
            event = _make_message_event("1")
            await handle_message_event(event)

        reply_text = _get_reply_text(mock_line)
        assert "沒有待入庫的內容" in reply_text
        assert "入庫" in reply_text


class TestCase6SafeCommandPreservesPending:
    """Case 6: pending_save 存在 + 安全指令（說明）→ 不清 pending。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    async def test_help_does_not_clear_pending_save(
        self, mock_hash, mock_session_ctx, mock_get_line
    ):
        """pending 存在時輸入「說明」→ pending 不應被清除。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx, has_pending_save=True
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
        ):
            event = _make_message_event("說明")
            await handle_message_event(event)

        # 關鍵斷言：clear_pending_save 不應被呼叫
        mock_user_state_repo.clear_pending_save.assert_not_awaited()

        # 回覆應包含說明內容
        reply_text = _get_reply_text(mock_line)
        assert "可用指令" in reply_text

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    async def test_cost_does_not_clear_pending_save(
        self, mock_hash, mock_session_ctx, mock_get_line
    ):
        """pending 存在時輸入「用量」→ pending 不應被清除。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx, has_pending_save=True
        )

        mock_cost_result = MagicMock()
        mock_cost_result.message = "📊 用量摘要..."

        mock_cost_service = MagicMock()
        mock_cost_service.get_usage_summary = AsyncMock(return_value=mock_cost_result)

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
            patch("src.services.cost_service.CostService", return_value=mock_cost_service),
        ):
            event = _make_message_event("用量")
            await handle_message_event(event)

        # 關鍵斷言：clear_pending_save 不應被呼叫
        mock_user_state_repo.clear_pending_save.assert_not_awaited()


class TestCase9ModeSwitchPreservesPending:
    """Case 9: pending_save 存在 + 模式切換 → 不清 pending，且顯示切換確認。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    async def test_mode_switch_preserves_pending_and_confirms(
        self, mock_hash, mock_session_ctx, mock_get_line
    ):
        """pending 存在時輸入「免費模式」→ pending 保留 + 回覆模式切換確認。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx, has_pending_save=True
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
        ):
            event = _make_message_event("免費模式")
            await handle_message_event(event)

        # 關鍵斷言：clear_pending_save 不應被呼叫
        mock_user_state_repo.clear_pending_save.assert_not_awaited()

        # 回覆應包含模式切換確認
        reply_text = _get_reply_text(mock_line)
        assert "已切換為" in reply_text
        assert "免費" in reply_text

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    async def test_lang_switch_preserves_pending(
        self, mock_hash, mock_session_ctx, mock_get_line
    ):
        """pending 存在時輸入「英文」→ pending 保留 + 回覆語言切換確認。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx, has_pending_save=True
        )

        mock_profile_repo.set_target_lang = AsyncMock(
            return_value=MagicMock(target_lang="en")
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
        ):
            event = _make_message_event("英文")
            await handle_message_event(event)

        # 關鍵斷言：clear_pending_save 不應被呼叫
        mock_user_state_repo.clear_pending_save.assert_not_awaited()

        # 回覆應包含語言切換確認
        reply_text = _get_reply_text(mock_line)
        assert "已切換為" in reply_text


class TestNonSafeCommandClearsPending:
    """驗證非安全指令仍然正確清除 pending_save。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook._handle_unknown", new_callable=AsyncMock, return_value="處理結果")
    async def test_unknown_input_clears_pending(
        self, mock_handle_unknown, mock_hash, mock_session_ctx, mock_get_line
    ):
        """pending 存在時輸入一般文字 → 應清除 pending。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx, has_pending_save=True
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
        ):
            event = _make_message_event("banana")
            await handle_message_event(event)

        # 關鍵斷言：clear_pending_save 應被呼叫
        mock_user_state_repo.clear_pending_save.assert_awaited_once()


class TestCase2PendingDiscardNotification:
    """Case 2: 新輸入清除 pending 時，回覆應包含取消通知。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook._dispatch_command", new_callable=AsyncMock, return_value="banana 的處理結果")
    async def test_discard_notification_in_response(
        self, mock_dispatch, mock_hash, mock_session_ctx, mock_get_line
    ):
        """pending 存在時輸入新文字 → 回覆應包含舊 pending 的取消通知。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx, has_pending_save=True
        )
        # get_pending_save 回傳 "apple"（被丟棄的舊 pending）
        mock_user_state_repo.get_pending_save = AsyncMock(return_value="apple")

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
        ):
            event = _make_message_event("banana")
            await handle_message_event(event)

        reply_text = _get_reply_text(mock_line)
        # 回覆應包含舊 pending 取消通知
        assert "apple" in reply_text
        assert "已取消" in reply_text


class TestCase8SaveWithPendingConfirms:
    """Case 8: pending 存在時輸入「入庫」→ 視同確認，直接儲存 pending 內容。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook._handle_confirm_save", new_callable=AsyncMock, return_value="已入庫：apple")
    async def test_save_with_pending_triggers_confirm(
        self, mock_confirm, mock_hash, mock_session_ctx, mock_get_line
    ):
        """pending 存在 + 輸入「入庫」→ 應走 _handle_confirm_save。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx, has_pending_save=True
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
        ):
            event = _make_message_event("入庫")
            await handle_message_event(event)

        # 關鍵斷言：走 confirm_save 而非 clear + dispatch
        mock_confirm.assert_awaited_once()
        # pending 不應被額外清除（confirm_save 內部會清）
        mock_user_state_repo.clear_pending_save.assert_not_awaited()


class TestCase7ExitPractice:
    """Case 7: 練習中可輸入「結束練習」退出。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    async def test_exit_practice_clears_session(
        self, mock_hash, mock_session_ctx, mock_get_line
    ):
        """輸入「結束練習」→ 清除 session + 回覆確認。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx
        )

        mock_session_service = MagicMock()
        mock_session_service.has_active_session = AsyncMock(return_value=True)
        mock_session_service.clear_session = AsyncMock()

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
            patch("src.services.session_service.SessionService", return_value=mock_session_service),
        ):
            event = _make_message_event("結束練習")
            await handle_message_event(event)

        reply_text = _get_reply_text(mock_line)
        assert "已結束練習" in reply_text
        mock_session_service.clear_session.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    async def test_exit_practice_no_session(
        self, mock_hash, mock_session_ctx, mock_get_line
    ):
        """無練習中輸入「結束練習」→ 回覆無進行中練習。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx
        )

        mock_session_service = MagicMock()
        mock_session_service.has_active_session = AsyncMock(return_value=False)

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
            patch("src.services.session_service.SessionService", return_value=mock_session_service),
        ):
            event = _make_message_event("結束練習")
            await handle_message_event(event)

        reply_text = _get_reply_text(mock_line)
        assert "沒有進行中的練習" in reply_text


# ============================================================================
# Edge Case 21: NFKC 正規化
# ============================================================================


class TestCase21NfkcNormalization:
    """Case 21: 全形英數字 → NFKC 正規化為半形。"""

    def test_sanitize_fullwidth_to_halfwidth(self):
        """全形英文 ａｐｐｌｅ → 半形 apple。"""
        result = _sanitize_text("ａｐｐｌｅ")
        assert result == "apple"

    def test_sanitize_fullwidth_number(self):
        """全形數字 １ → 半形 1（可匹配 CONFIRM_SAVE）。"""
        result = _sanitize_text("１")
        assert result == "1"

    def test_sanitize_halfwidth_katakana(self):
        """半形片假名 ﾎﾟｹｯﾄ → 全形 ポケット（NFKC 副作用）。"""
        result = _sanitize_text("ﾎﾟｹｯﾄ")
        assert result == "ポケット"

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_fullwidth_1_triggers_confirm_save(
        self, mock_has_session, mock_hash, mock_session_ctx, mock_get_line
    ):
        """全形「１」經 NFKC 正規化後應觸發 CONFIRM_SAVE 流程。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx, has_pending_save=False
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
        ):
            event = _make_message_event("１")
            await handle_message_event(event)

        # 「１」→「1」→ CONFIRM_SAVE + 無 pending → PENDING_EXPIRED
        reply_text = _get_reply_text(mock_line)
        assert "沒有待入庫的內容" in reply_text


# ============================================================================
# Edge Case 25: 引號剝除
# ============================================================================


class TestCase25QuoteStripping:
    """Case 25: 首尾成對引號/括號剝除。"""

    def test_sanitize_strip_cjk_quotes(self):
        """「食べる」→ 食べる。"""
        result = _sanitize_text("「食べる」")
        assert result == "食べる"

    def test_sanitize_strip_english_quotes(self):
        """\"apple\" → apple（雙引號）。"""
        result = _sanitize_text('"apple"')
        assert result == "apple"

    def test_sanitize_strip_single_quotes(self):
        """'test' → test（單引號）。"""
        result = _sanitize_text("'test'")
        assert result == "test"

    def test_sanitize_strip_brackets(self):
        """【apple】→ apple。"""
        result = _sanitize_text("【apple】")
        assert result == "apple"

    def test_sanitize_no_strip_mismatched(self):
        """不成對的引號不剝除。"""
        result = _sanitize_text("「apple』")
        assert result == "「apple』"

    def test_sanitize_no_strip_empty_quotes(self):
        """只有引號沒有內容不剝除。"""
        result = _sanitize_text("「」")
        assert result == "「」"


# ============================================================================
# Edge Case 23: Romaji 偵測
# ============================================================================


class TestCase23RomajiDetection:
    """Case 23: 偵測日語羅馬字拼音。"""

    def test_romaji_detection(self):
        """watashi wa gakusei desu → 偵測到 Romaji。"""
        assert _is_likely_romaji("watashi wa gakusei desu", "ja") is True

    def test_romaji_not_triggered_for_english(self):
        """I like sushi → 不偵測為 Romaji。"""
        assert _is_likely_romaji("I like sushi", "ja") is False

    def test_romaji_not_triggered_for_en_mode(self):
        """日文 Romaji 但 target_lang=en → 不偵測。"""
        assert _is_likely_romaji("watashi wa gakusei desu", "en") is False

    def test_romaji_single_word_not_triggered(self):
        """單一 Romaji 單字不偵測（避免誤判）。"""
        assert _is_likely_romaji("watashi", "ja") is False

    def test_romaji_with_non_ascii_not_triggered(self):
        """含非 ASCII 字元不偵測。"""
        assert _is_likely_romaji("watashi は gakusei", "ja") is False

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_romaji_input_shows_hint(
        self, mock_has_session, mock_hash, mock_session_ctx, mock_get_line
    ):
        """Romaji 輸入應顯示 IME 提示。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
        ):
            event = _make_message_event("watashi wa gakusei desu")
            await handle_message_event(event)

        reply_text = _get_reply_text(mock_line)
        assert "羅馬字" in reply_text
        assert "日文輸入法" in reply_text


# ============================================================================
# Edge Case 24: 非「1」數字 — pending 狀態下特殊處理
# ============================================================================


class TestCase24PendingWrongNumber:
    """Case 24: pending 狀態下輸入數字 2-9 → 提示，不清除 pending。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    async def test_pending_wrong_number_shows_hint(
        self, mock_hash, mock_session_ctx, mock_get_line
    ):
        """pending 存在時輸入 '2' → 提示只有 1 可入庫，pending 不清除。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx, has_pending_save=True
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
        ):
            event = _make_message_event("2")
            await handle_message_event(event)

        # 關鍵斷言：pending 不應被清除
        mock_user_state_repo.clear_pending_save.assert_not_awaited()

        reply_text = _get_reply_text(mock_line)
        assert "1" in reply_text
        assert "入庫" in reply_text

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    async def test_pending_zero_shows_hint(
        self, mock_hash, mock_session_ctx, mock_get_line
    ):
        """pending 存在時輸入 '0' → 同樣提示。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx, has_pending_save=True
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
        ):
            event = _make_message_event("0")
            await handle_message_event(event)

        mock_user_state_repo.clear_pending_save.assert_not_awaited()
        reply_text = _get_reply_text(mock_line)
        assert "1" in reply_text


# ============================================================================
# Edge Case 26: 超長文本直接入庫
# ============================================================================


class TestCase26LongTextDirectSave:
    """Case 26: 超長文本（> 2000 字）跳過 Router 直接入庫。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_long_text_saved_directly(
        self, mock_has_session, mock_hash, mock_session_ctx, mock_get_line
    ):
        """2001+ 字文本跳過 Router，進入文章翻譯模式。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
            patch("src.api.webhook._handle_article_translation", new_callable=AsyncMock, return_value="📖 全文翻譯：\n翻譯結果") as mock_article,
        ):
            long_text = "あ" * 2001
            event = _make_message_event(long_text)
            await handle_message_event(event)

        reply_text = _get_reply_text(mock_line)
        assert "全文翻譯" in reply_text
        mock_article.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_long_text_translation_failure_returns_error(
        self, mock_has_session, mock_hash, mock_session_ctx, mock_get_line
    ):
        """長文本翻譯失敗時，回傳錯誤訊息。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
            patch("src.api.webhook._handle_article_translation", new_callable=AsyncMock, return_value=Messages.ERROR_SAVE),
        ):
            long_text = "あ" * 2001
            event = _make_message_event(long_text)
            await handle_message_event(event)

        reply_text = _get_reply_text(mock_line)
        assert Messages.ERROR_SAVE in reply_text

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_short_text_classified_as_material(
        self, mock_has_session, mock_hash, mock_session_ctx, mock_get_line
    ):
        """2000 字以下的假名長文 → MATERIAL 分類 → 文章翻譯模式。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
            patch("src.api.webhook._handle_article_translation", new_callable=AsyncMock, return_value="📖 全文翻譯：\n翻譯結果") as mock_article,
        ):
            # "あ"×100 → 有假名 + len>20 → MATERIAL → _handle_article_translation
            normal_text = "あ" * 100
            event = _make_message_event(normal_text)
            await handle_message_event(event)

        # 應走 MATERIAL → _handle_article_translation
        mock_article.assert_awaited_once()


# ============================================================================
# Edge Case 27: 非文字訊息回覆提示
# ============================================================================


class TestCase27NonTextMessage:
    """Case 27: 非文字訊息應回覆提示而非靜默。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    async def test_non_text_message_replies_hint(self, mock_get_line):
        """圖片/貼圖等非文字訊息 → 回覆提示。"""
        mock_line = MagicMock()
        mock_line.reply_message = AsyncMock(return_value=True)
        mock_get_line.return_value = mock_line

        event = MagicMock()
        event.source = MagicMock()
        event.source.user_id = "Utest_user"
        event.reply_token = "test_reply_token"
        # 非 TextMessageContent
        event.message = MagicMock()
        event.message.__class__ = MagicMock  # 不是 TextMessageContent

        await handle_message_event(event)

        mock_line.reply_message.assert_awaited_once()
        reply_text = mock_line.reply_message.call_args[0][1]
        assert "文字" in reply_text


# ============================================================================
# Edge Case 28: Webhook 去重
# ============================================================================


class TestCase28WebhookDedup:
    """Case 28: 重複 webhook event 應被跳過。"""

    @pytest.fixture(autouse=True)
    def _clean_dedup_state(self):
        """每個測試前後清理全域 dedup 狀態，避免測試間污染。"""
        _processed_events.clear()
        yield
        _processed_events.clear()

    def test_first_event_not_duplicate(self):
        """首次出現的 event ID 不重複。"""
        assert _is_duplicate_event("test_event_001") is False

    def test_second_event_is_duplicate(self):
        """相同 event ID 第二次出現為重複。"""
        _is_duplicate_event("test_event_002")
        assert _is_duplicate_event("test_event_002") is True

    def test_none_event_id_not_duplicate(self):
        """event_id 為 None 時不視為重複。"""
        assert _is_duplicate_event(None) is False

    def test_different_events_not_duplicate(self):
        """不同 event ID 不重複。"""
        _is_duplicate_event("test_event_003")
        assert _is_duplicate_event("test_event_004") is False

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_duplicate_event_skipped(
        self, mock_has_session, mock_hash, mock_session_ctx, mock_get_line
    ):
        """重複的 webhook event 應被跳過，不回覆。"""
        _processed_events.clear()

        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx, has_pending_save=False
        )

        from linebot.v3.webhooks import TextMessageContent

        event = MagicMock()
        event.source = MagicMock()
        event.source.user_id = "Utest_user"
        event.reply_token = "test_reply_token"
        event.message = MagicMock(spec=TextMessageContent)
        event.message.text = "說明"
        event.webhook_event_id = "dedup_test_event_123"

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
        ):
            # 第一次：正常處理
            await handle_message_event(event)
            assert mock_line.reply_with_quick_reply.await_count == 1

            # 第二次：重複，跳過
            event.reply_token = "test_reply_token_2"
            await handle_message_event(event)
            # reply 仍然只被呼叫 1 次
            assert mock_line.reply_with_quick_reply.await_count == 1


# ============================================================================
# Edge Case 29: 非支援語言偵測
# ============================================================================


class TestCase29UnsupportedLanguage:
    """Case 29: 韓文等非支援語言應引導用戶。"""

    def test_korean_not_supported(self):
        """韓文 한국어 不被視為支援語言。"""
        assert _has_supported_language_content("한국어") is False

    def test_thai_not_supported(self):
        """泰文不被視為支援語言。"""
        assert _has_supported_language_content("สวัสดี") is False

    def test_japanese_supported(self):
        """日文假名是支援語言。"""
        assert _has_supported_language_content("こんにちは") is True

    def test_english_supported(self):
        """英文是支援語言。"""
        assert _has_supported_language_content("hello") is True

    def test_cjk_supported(self):
        """CJK 漢字是支援語言。"""
        assert _has_supported_language_content("食べる") is True

    def test_mixed_korean_english_supported(self):
        """韓英混合（含英文）仍視為支援。"""
        assert _has_supported_language_content("hello 한국어") is True

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_korean_input_shows_unsupported_hint(
        self, mock_has_session, mock_hash, mock_session_ctx, mock_get_line
    ):
        """純韓文輸入應顯示不支援語言提示。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx
        )

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
        ):
            event = _make_message_event("한국어")
            await handle_message_event(event)

        reply_text = _get_reply_text(mock_line)
        assert "日文" in reply_text
        assert "英文" in reply_text


# ============================================================================
# Edge Case 30: 手機自動修正 — 模板提示驗證
# ============================================================================


class TestCase30AutocorrectHint:
    """Case 30: WORD_EXPLANATION 模板包含「非目標字」提示。"""

    def test_word_explanation_includes_retype_hint(self):
        """單字解釋模板應包含重新輸入提示。"""
        msg = Messages.format("WORD_EXPLANATION", explanation="test explanation")
        assert "重新輸入" in msg
        assert "拼寫" in msg


# ============================================================================
# WORD_SAVE：「單字 入庫」直接入庫指令
# ============================================================================


class TestWordSaveDispatch:
    """「單字 入庫」指令觸發 _handle_word_save 並呼叫 save_raw。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_word_save_dispatch(
        self, mock_has_session, mock_hash, mock_session_ctx, mock_get_line
    ):
        """「するどい save」→ 觸發 _handle_word_save，呼叫 save_raw。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx, has_pending_save=False
        )

        mock_save_result = MagicMock()
        mock_save_result.message = "已入庫：するどい"

        mock_cmd_service = MagicMock()
        mock_cmd_service.save_raw = AsyncMock(return_value=mock_save_result)

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
            patch("src.api.webhook.CommandService", return_value=mock_cmd_service),
        ):
            event = _make_message_event("するどい save")
            await handle_message_event(event)

        # save_raw 應被呼叫，content_text 為「するどい」
        mock_cmd_service.save_raw.assert_awaited_once()
        call_kwargs = mock_cmd_service.save_raw.call_args
        assert call_kwargs[1]["content_text"] == "するどい"

        reply_text = _get_reply_text(mock_line)
        assert "已入庫" in reply_text

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    async def test_word_save_with_pending_does_not_clear_pending(
        self, mock_hash, mock_session_ctx, mock_get_line
    ):
        """有 pending_save 時使用「にぶい save」→ pending 不被取消。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_common_mocks(
            mock_get_line, mock_session_ctx, has_pending_save=True
        )

        mock_save_result = MagicMock()
        mock_save_result.message = "已入庫：にぶい"

        mock_cmd_service = MagicMock()
        mock_cmd_service.save_raw = AsyncMock(return_value=mock_save_result)

        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
            patch("src.api.webhook.CommandService", return_value=mock_cmd_service),
        ):
            event = _make_message_event("にぶい save")
            await handle_message_event(event)

        # 關鍵斷言：pending_save 不應被清除（WORD_SAVE 在 PENDING_SAFE_COMMANDS）
        mock_user_state_repo.clear_pending_save.assert_not_awaited()

        # save_raw 應被呼叫
        mock_cmd_service.save_raw.assert_awaited_once()

        reply_text = _get_reply_text(mock_line)
        assert "已入庫" in reply_text
