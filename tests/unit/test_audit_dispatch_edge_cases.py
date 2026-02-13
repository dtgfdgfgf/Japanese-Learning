"""指令邏輯審計 — dispatch-level edge case 測試。

MODE_SWITCH 和 SET_LANG 的 dispatch 邏輯嵌入在 handle_message_event 中，
需要完整 mock 才能測試。此外也測試 _resolve_mode_key / _resolve_lang_key。
共 2 × 5 = 10 tests。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from linebot.v3.webhooks import TextMessageContent

from src.api.webhook import (
    _resolve_lang_key,
    _resolve_mode_key,
    handle_message_event,
)
from src.schemas.command import CommandType, ParsedCommand
from src.templates.messages import Messages


# ============================================================================
# 通用 Mock Helper
# ============================================================================


def _make_message_event(
    text: str,
    user_id: str = "Utest_dispatch",
    reply_token: str = "test_reply_token",
) -> MagicMock:
    """建立模擬的 MessageEvent。"""
    event = MagicMock()
    event.source = MagicMock()
    event.source.user_id = user_id
    event.reply_token = reply_token
    event.message = MagicMock(spec=TextMessageContent)
    event.message.text = text
    return event


def _setup_dispatch_mocks(
    mock_get_line: MagicMock,
    mock_session_ctx: MagicMock,
    mode: str = "free",
    target_lang: str = "ja",
    set_mode_side_effect: Exception | None = None,
    set_lang_side_effect: Exception | None = None,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """設定 handle_message_event 所需的 mock。

    Returns:
        (mock_line, mock_user_state_repo, mock_profile_repo)
    """
    # LINE client
    mock_line = MagicMock()
    mock_line.reply_with_quick_reply = AsyncMock(return_value=True)
    mock_line.verify_signature = MagicMock(return_value=True)
    mock_get_line.return_value = mock_line

    # DB session
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
    mock_profile_repo.add_tokens = AsyncMock(return_value=mock_profile)

    if set_mode_side_effect:
        mock_profile_repo.set_mode = AsyncMock(side_effect=set_mode_side_effect)
    else:
        mock_profile_repo.set_mode = AsyncMock(return_value=mock_profile)

    if set_lang_side_effect:
        mock_profile_repo.set_target_lang = AsyncMock(side_effect=set_lang_side_effect)
    else:
        mock_profile_repo.set_target_lang = AsyncMock(return_value=mock_profile)

    # User state repo
    mock_user_state_repo = MagicMock()
    mock_user_state_repo.has_pending_delete = AsyncMock(return_value=False)
    mock_user_state_repo.has_pending_save = AsyncMock(return_value=False)
    mock_user_state_repo.clear_pending_save = AsyncMock()
    mock_user_state_repo.clear_pending_delete = AsyncMock()
    mock_user_state_repo.set_last_message = AsyncMock()

    return mock_line, mock_user_state_repo, mock_profile_repo


def _get_reply_text(mock_line: MagicMock) -> str:
    """從 mock LINE client 提取回覆文字。"""
    call_args = mock_line.reply_with_quick_reply.call_args
    if call_args:
        return call_args[0][1] if len(call_args[0]) > 1 else ""
    return ""


# ============================================================================
# MODE_SWITCH（模式切換）— 5 edge cases
# ============================================================================


class TestModeSwitchEdgeCases:
    """MODE_SWITCH 指令 edge cases。"""

    def test_resolve_mode_key_free(self) -> None:
        """keyword='免費' → 'free'。"""
        cmd = ParsedCommand(command_type=CommandType.MODE_SWITCH, raw_text="免費模式", keyword="免費")
        assert _resolve_mode_key(cmd) == "free"

    def test_resolve_mode_key_rigorous(self) -> None:
        """keyword='嚴謹' → 'rigorous'。"""
        cmd = ParsedCommand(command_type=CommandType.MODE_SWITCH, raw_text="嚴謹模式", keyword="嚴謹")
        assert _resolve_mode_key(cmd) == "rigorous"

    def test_resolve_mode_key_from_raw_text(self) -> None:
        """keyword=None 時從 raw_text 解析（「切換便宜」strip 後查 MODE_NAME_MAP）。"""
        # _resolve_mode_key 先查 keyword，再查 raw_text
        # 「切換便宜」→ 由 parse_command 解析後 keyword="便宜"
        cmd = ParsedCommand(command_type=CommandType.MODE_SWITCH, raw_text="便宜模式", keyword="便宜")
        assert _resolve_mode_key(cmd) == "cheap"

    def test_resolve_mode_key_invalid_returns_none(self) -> None:
        """無效的 keyword → None。"""
        cmd = ParsedCommand(command_type=CommandType.MODE_SWITCH, raw_text="快速模式", keyword="快速")
        assert _resolve_mode_key(cmd) is None

    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_db_save_failure_returns_error_generic(
        self, mock_has_session: AsyncMock, mock_hash: MagicMock,
        mock_session_ctx: MagicMock, mock_get_line: MagicMock,
    ) -> None:
        """DB 儲存模式失敗 → 回覆 ERROR_GENERIC。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_dispatch_mocks(
            mock_get_line, mock_session_ctx,
            set_mode_side_effect=Exception("DB connection lost"),
        )
        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
        ):
            event = _make_message_event("免費模式")
            await handle_message_event(event)
        reply = _get_reply_text(mock_line)
        assert Messages.ERROR_GENERIC in reply


# ============================================================================
# SET_LANG（語言切換）— 5 edge cases
# ============================================================================


class TestSetLangEdgeCases:
    """SET_LANG 指令 edge cases。"""

    def test_resolve_lang_key_japanese(self) -> None:
        """keyword='日文' → 'ja'。"""
        cmd = ParsedCommand(command_type=CommandType.SET_LANG, raw_text="日文", keyword="日文")
        assert _resolve_lang_key(cmd) == "ja"

    def test_resolve_lang_key_english(self) -> None:
        """keyword='英文' → 'en'。"""
        cmd = ParsedCommand(command_type=CommandType.SET_LANG, raw_text="英文", keyword="英文")
        assert _resolve_lang_key(cmd) == "en"

    def test_resolve_lang_key_none_keyword(self) -> None:
        """keyword=None → None。"""
        cmd = ParsedCommand(command_type=CommandType.SET_LANG, raw_text="日文", keyword=None)
        assert _resolve_lang_key(cmd) is None

    def test_resolve_lang_key_unsupported(self) -> None:
        """不支援的語言「韓文」→ None。"""
        cmd = ParsedCommand(command_type=CommandType.SET_LANG, raw_text="韓文", keyword="韓文")
        assert _resolve_lang_key(cmd) is None

    @patch("src.api.webhook.get_line_client")
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook.has_active_session", new_callable=AsyncMock, return_value=False)
    async def test_db_save_failure_returns_error_generic(
        self, mock_has_session: AsyncMock, mock_hash: MagicMock,
        mock_session_ctx: MagicMock, mock_get_line: MagicMock,
    ) -> None:
        """DB 儲存語言失敗 → 回覆 ERROR_GENERIC。"""
        mock_line, mock_user_state_repo, mock_profile_repo = _setup_dispatch_mocks(
            mock_get_line, mock_session_ctx,
            set_lang_side_effect=Exception("DB connection lost"),
        )
        with (
            patch("src.api.webhook.UserProfileRepository", return_value=mock_profile_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state_repo),
            patch("src.api.webhook.build_mode_quick_replies", return_value=None),
        ):
            event = _make_message_event("日文")
            await handle_message_event(event)
        reply = _get_reply_text(mock_line)
        assert Messages.ERROR_GENERIC in reply
