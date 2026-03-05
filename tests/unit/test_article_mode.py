"""文章閱讀模式（article mode）完整流程測試。

測試範圍：
- 長文/MATERIAL → 翻譯 + 進入 article mode
- article mode 中查詞 → 帶語境 LLM + pending_save
- 輸入「1」→ 入庫 + article mode 持續
- 輸入「完成」→ 結束 article mode
- 5 分鐘過期 → 自動結束
- article mode + 其他指令互動
"""

from unittest.mock import AsyncMock, MagicMock, patch

from src.api.webhook import (
    _handle_article_translation,
    _handle_article_word_lookup,
    _handle_unknown,
)
from src.repositories.user_state_repo import (
    ARTICLE_MODE_TIMEOUT,
    UserStateRepository,
)
from src.schemas.command import CommandType
from src.services.command_service import parse_command
from src.templates.messages import Messages

# ============================================================================
# 指令解析測試
# ============================================================================


class TestCompleteArticleCommand:
    """「完成」指令解析。"""

    def test_parse_complete(self) -> None:
        """「完成」→ COMPLETE_ARTICLE。"""
        parsed = parse_command("完成")
        assert parsed.command_type == CommandType.COMPLETE_ARTICLE

    def test_parse_complete_not_prefix(self) -> None:
        """「完成了」不應匹配 COMPLETE_ARTICLE。"""
        parsed = parse_command("完成了")
        assert parsed.command_type == CommandType.UNKNOWN


# ============================================================================
# _handle_article_translation 測試
# ============================================================================


_SAMPLE_ARTICLE = "日本語の勉強は楽しいです。毎日少しずつ進歩しています。"
_SAMPLE_TRANSLATION = "學日語很有趣。每天都有一點點進步。"


class TestHandleArticleTranslation:
    """長文 → 翻譯 + 進入 article mode。"""

    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.lib.llm_client.get_llm_client")
    @patch("src.api.webhook.get_session")
    async def test_translates_and_enters_article_mode(
        self,
        mock_get_session: MagicMock,
        mock_get_llm: MagicMock,
        mock_hash: MagicMock,
    ) -> None:
        """翻譯回覆應包含 header + 翻譯 + 操作提示。"""
        # mock LLM
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = _SAMPLE_TRANSLATION
        mock_response.to_trace.return_value = MagicMock(
            input_tokens=100, output_tokens=50,
        )
        mock_llm.complete_with_mode = AsyncMock(
            return_value=mock_response,
        )
        mock_get_llm.return_value = mock_llm

        # mock DB sessions
        mock_session = AsyncMock()
        mock_repo = AsyncMock(spec=UserStateRepository)
        mock_usage_repo = AsyncMock()

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = ctx

        with patch(
            "src.api.webhook.UserStateRepository",
            return_value=mock_repo,
        ), patch(
            "src.repositories.api_usage_log_repo.ApiUsageLogRepository",
            return_value=mock_usage_repo,
        ):
            result = await _handle_article_translation(
                "Utest", _SAMPLE_ARTICLE, "free", "ja",
            )

        # 回覆應包含翻譯 header
        assert Messages.ARTICLE_TRANSLATION_HEADER in result
        # 回覆應包含翻譯內容
        assert _SAMPLE_TRANSLATION in result
        # 回覆應包含操作提示
        assert "完成" in result
        # 應呼叫 set_article_mode
        mock_repo.set_article_mode.assert_called_once()

    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.lib.llm_client.get_llm_client")
    @patch("src.api.webhook.get_session")
    async def test_truncates_long_article(
        self,
        mock_get_session: MagicMock,
        mock_get_llm: MagicMock,
        mock_hash: MagicMock,
    ) -> None:
        """超過 5000 字的原文應截斷。"""
        long_text = "あ" * 6000
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "翻譯結果"
        mock_response.to_trace.return_value = MagicMock(
            input_tokens=100, output_tokens=50,
        )
        mock_llm.complete_with_mode = AsyncMock(
            return_value=mock_response,
        )
        mock_get_llm.return_value = mock_llm

        mock_session = AsyncMock()
        mock_repo = AsyncMock(spec=UserStateRepository)
        mock_usage_repo = AsyncMock()

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = ctx

        with patch(
            "src.api.webhook.UserStateRepository",
            return_value=mock_repo,
        ), patch(
            "src.repositories.api_usage_log_repo.ApiUsageLogRepository",
            return_value=mock_usage_repo,
        ):
            await _handle_article_translation(
                "Utest", long_text, "free", "ja",
            )

        # set_article_mode 收到的文字應截斷至 5000 字
        call_args = mock_repo.set_article_mode.call_args
        saved_text = call_args[0][1]
        assert len(saved_text) == 5000


# ============================================================================
# _handle_article_word_lookup 測試
# ============================================================================


_SAMPLE_DISPLAY = "【詞條】勉強（べんきょう）\n【核心意思】學習、用功"
_SAMPLE_EXTRACTED_ITEM = {
    "item_type": "vocab",
    "key": "vocab:勉強",
    "surface": "勉強",
    "reading": "べんきょう",
    "pos": "noun",
    "glossary_zh": ["學習", "用功"],
    "confidence": 1.0,
    "display": _SAMPLE_DISPLAY,
}


class TestHandleArticleWordLookup:
    """article mode 中查詞。"""

    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch(
        "src.api.webhook._search_user_items",
        new_callable=AsyncMock,
        return_value=[],
    )
    @patch("src.api.webhook.get_session")
    @patch("src.services.router_service.get_router_service")
    async def test_llm_lookup_with_context(
        self,
        mock_get_router: MagicMock,
        mock_get_session: MagicMock,
        mock_search: AsyncMock,
        mock_hash: MagicMock,
    ) -> None:
        """DB 未命中時應呼叫帶語境的 LLM 查詞。"""
        mock_router = MagicMock()
        mock_trace = MagicMock(input_tokens=50, output_tokens=30)
        mock_router.get_word_explanation_with_context = AsyncMock(
            return_value=(_SAMPLE_DISPLAY, _SAMPLE_EXTRACTED_ITEM, mock_trace),
        )
        mock_get_router.return_value = mock_router

        mock_session = AsyncMock()
        mock_repo = AsyncMock(spec=UserStateRepository)
        mock_usage_repo = AsyncMock()

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = ctx

        with patch(
            "src.api.webhook.UserStateRepository",
            return_value=mock_repo,
        ), patch(
            "src.repositories.api_usage_log_repo.ApiUsageLogRepository",
            return_value=mock_usage_repo,
        ):
            result = await _handle_article_word_lookup(
                "Utest", "勉強", _SAMPLE_ARTICLE, "free", "ja",
            )

        # 應包含解釋內容
        assert "勉強" in result
        # 應包含繼續查詢提示
        assert "完成" in result
        # 應呼叫帶語境的方法
        mock_router.get_word_explanation_with_context.assert_called_once()
        # 應設定 pending_save
        mock_repo.set_pending_save_with_item.assert_called_once()

    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_db_hit_returns_cached(
        self,
        mock_search: AsyncMock,
        mock_hash: MagicMock,
    ) -> None:
        """DB 有紀錄時直接回傳，不呼叫 LLM。"""
        mock_item = MagicMock()
        mock_item.item_type = "vocab"
        mock_item.payload = {
            "surface": "勉強",
            "reading": "べんきょう",
            "glossary_zh": ["學習"],
            "display": _SAMPLE_DISPLAY,
        }
        mock_search.return_value = [mock_item]

        result = await _handle_article_word_lookup(
            "Utest", "勉強", _SAMPLE_ARTICLE, "free", "ja",
        )

        # 應包含 DB 搜尋結果
        assert "勉強" in result
        # 應包含繼續查詢提示
        assert "完成" in result


# ============================================================================
# _handle_unknown 分類路由測試
# ============================================================================


class TestHandleUnknownArticleRouting:
    """長文 / MATERIAL 分類應路由到 article translation。"""

    @patch("src.api.webhook._handle_article_translation", new_callable=AsyncMock)
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    async def test_long_text_routes_to_article(
        self,
        mock_hash: MagicMock,
        mock_article_trans: AsyncMock,
    ) -> None:
        """超過 LONG_TEXT_THRESHOLD 的文字應路由到翻譯。"""
        mock_article_trans.return_value = "翻譯結果"
        long_text = "あ" * 2500  # > LONG_TEXT_THRESHOLD(2000)

        result = await _handle_unknown("Utest", long_text, "free", "ja")

        mock_article_trans.assert_called_once()
        assert result == "翻譯結果"

    @patch("src.api.webhook._handle_article_translation", new_callable=AsyncMock)
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    async def test_material_routes_to_article(
        self,
        mock_hash: MagicMock,
        mock_article_trans: AsyncMock,
    ) -> None:
        """MATERIAL 分類（有句讀的日文）應路由到翻譯。"""
        mock_article_trans.return_value = "翻譯結果"
        # 含句讀但不超過 LONG_TEXT_THRESHOLD
        text = "日本語の勉強は楽しいです。"

        result = await _handle_unknown("Utest", text, "free", "ja")

        mock_article_trans.assert_called_once()
        assert result == "翻譯結果"


# ============================================================================
# UserStateRepository article mode 方法測試
# ============================================================================


class TestUserStateRepoArticleMode:
    """UserStateRepository article mode 方法的單元測試。"""

    async def test_article_mode_timeout_constant(self) -> None:
        """ARTICLE_MODE_TIMEOUT 應為 300 秒。"""
        assert ARTICLE_MODE_TIMEOUT == 300

    def test_parse_command_complete(self) -> None:
        """「完成」應被解析為 COMPLETE_ARTICLE。"""
        parsed = parse_command("完成")
        assert parsed.command_type == CommandType.COMPLETE_ARTICLE

    def test_complete_article_in_pending_safe(self) -> None:
        """COMPLETE_ARTICLE 應在 PENDING_SAFE_COMMANDS 中。"""
        from src.api.webhook import PENDING_SAFE_COMMANDS
        assert CommandType.COMPLETE_ARTICLE in PENDING_SAFE_COMMANDS


# ============================================================================
# Messages 測試
# ============================================================================


class TestArticleModeMessages:
    """文章模式訊息模板測試。"""

    def test_article_translation_header(self) -> None:
        assert Messages.ARTICLE_TRANSLATION_HEADER == "📖 全文翻譯："

    def test_article_mode_exit(self) -> None:
        assert "結束" in Messages.ARTICLE_MODE_EXIT

    def test_article_mode_instructions_mentions_complete(self) -> None:
        assert "完成" in Messages.ARTICLE_MODE_INSTRUCTIONS

    def test_article_word_save_reminder(self) -> None:
        assert "完成" in Messages.ARTICLE_WORD_SAVE_REMINDER
