"""
單字輸入「先查庫再 LLM 解釋」測試。

驗證 _handle_unknown 中 SAVE intent 短單字路徑和 SEARCH intent 路徑的
DB 優先查詢 + LLM fallback 行為。

注意：已改用 get_word_explanation_structured()，回傳 (display, extracted_item)。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.webhook import _handle_unknown, _is_single_word

# ============================================================================
# _is_single_word 單元測試
# ============================================================================


class TestIsSingleWord:
    """_is_single_word 邊界測試。"""

    def test_single_japanese_word(self) -> None:
        assert _is_single_word("食べる", "ja") is True

    def test_single_english_word(self) -> None:
        assert _is_single_word("apple", "en") is True

    def test_multi_word_returns_false(self) -> None:
        assert _is_single_word("red apple", "en") is False

    def test_japanese_word_over_15_chars(self) -> None:
        assert _is_single_word("あ" * 16, "ja") is False

    def test_english_word_over_30_chars(self) -> None:
        assert _is_single_word("a" * 31, "en") is False

    def test_whitespace_stripped(self) -> None:
        assert _is_single_word("  FIT  ", "en") is True

    def test_empty_string(self) -> None:
        assert _is_single_word("  ", "en") is False


# ============================================================================
# _handle_unknown 整合測試：SAVE intent + 短單字
# ============================================================================


def _mock_item(surface: str = "FIT", item_type: str = "vocab") -> MagicMock:
    """建立模擬的 Item 物件。"""
    item = MagicMock()
    item.item_type = item_type
    item.payload = {
        "surface": surface,
        "reading": "",
        "pronunciation": "fɪt",
        "glossary_zh": ["適合"],
    }
    return item


# 預設的 structured 回傳用 extracted_item
_SAMPLE_EXTRACTED_ITEM = {
    "item_type": "vocab",
    "key": "vocab:FIT",
    "surface": "FIT",
    "pronunciation": "/fɪt/",
    "pos": "adjective",
    "glossary_zh": ["適合的", "健康的"],
    "example": "This shirt fits well.",
    "example_translation": "這件襯衫很合身。",
    "confidence": 1.0,
}


class TestSaveIntentShortWordDbHit:
    """SAVE intent + 短單字 + DB 有紀錄 → 回傳 DB 結果，不呼叫 LLM。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_returns_db_results_without_llm(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
    ) -> None:
        """DB 有結果時直接回傳搜尋結果，不呼叫 get_word_explanation_structured。"""
        from src.schemas.router import IntentType, RouterResponse

        mock_router = MagicMock()
        mock_router.classify = AsyncMock(
            return_value=(
                RouterResponse(intent=IntentType.SAVE, confidence=0.9, reason="single word"),
                None,
            )
        )
        mock_get_router.return_value = mock_router

        # DB 回傳已入庫的 item
        mock_search.return_value = [_mock_item("FIT")]

        result = await _handle_unknown("Utest", "FIT", mode="free", target_lang="en")

        # 應包含搜尋結果
        assert "FIT" in result
        # 不應呼叫 LLM 解釋
        mock_router.get_word_explanation_structured.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_no_pending_save_set_when_db_hit(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
    ) -> None:
        """DB 有結果時不應設定 pending_save。"""
        from src.schemas.router import IntentType, RouterResponse

        mock_router = MagicMock()
        mock_router.classify = AsyncMock(
            return_value=(
                RouterResponse(intent=IntentType.SAVE, confidence=0.9, reason="single word"),
                None,
            )
        )
        mock_get_router.return_value = mock_router
        mock_search.return_value = [_mock_item("FIT")]

        with patch("src.api.webhook.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_ctx.return_value = mock_session

            mock_user_state_repo = MagicMock()
            mock_user_state_repo.set_pending_save = AsyncMock()
            mock_user_state_repo.set_pending_save_with_item = AsyncMock()

            with patch(
                "src.api.webhook.UserStateRepository",
                return_value=mock_user_state_repo,
            ):
                await _handle_unknown("Utest", "FIT", mode="free", target_lang="en")

            # pending_save 不應被設定
            mock_user_state_repo.set_pending_save.assert_not_awaited()
            mock_user_state_repo.set_pending_save_with_item.assert_not_awaited()


class TestSaveIntentShortWordDbMiss:
    """SAVE intent + 短單字 + DB 無紀錄 → 呼叫 LLM 解釋，設 pending_save_with_item。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_calls_llm_and_sets_pending(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
        mock_session_ctx: MagicMock,
    ) -> None:
        """DB 無結果時呼叫 structured LLM 解釋並設定 pending_save_with_item。"""
        from src.schemas.router import IntentType, RouterResponse

        mock_router = MagicMock()
        mock_router.classify = AsyncMock(
            return_value=(
                RouterResponse(intent=IntentType.SAVE, confidence=0.9, reason="single word"),
                None,
            )
        )
        mock_router.get_word_explanation_structured = AsyncMock(
            return_value=("FIT 的意思是...", _SAMPLE_EXTRACTED_ITEM)
        )
        mock_get_router.return_value = mock_router

        # DB 無結果
        mock_search.return_value = []

        # mock session for pending_save
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = mock_session

        mock_user_state_repo = MagicMock()
        mock_user_state_repo.set_pending_save = AsyncMock()
        mock_user_state_repo.set_pending_save_with_item = AsyncMock()

        with patch(
            "src.api.webhook.UserStateRepository",
            return_value=mock_user_state_repo,
        ):
            result = await _handle_unknown("Utest", "FIT", mode="free", target_lang="en")

        # 應呼叫 structured LLM 解釋
        mock_router.get_word_explanation_structured.assert_awaited_once_with(
            "FIT", mode="free", target_lang="en"
        )
        # 應設定 pending_save_with_item（因為有 extracted_item）
        mock_user_state_repo.set_pending_save_with_item.assert_awaited_once_with(
            "hashed_user", "FIT", _SAMPLE_EXTRACTED_ITEM
        )
        # 回覆應包含解釋
        assert "FIT 的意思是" in result

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_fallback_to_plain_pending_when_no_item(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
        mock_session_ctx: MagicMock,
    ) -> None:
        """structured 回傳 item=None → fallback 到 set_pending_save（純文字）。"""
        from src.schemas.router import IntentType, RouterResponse

        mock_router = MagicMock()
        mock_router.classify = AsyncMock(
            return_value=(
                RouterResponse(intent=IntentType.SAVE, confidence=0.9, reason="single word"),
                None,
            )
        )
        # item 為 None（JSON parse 失敗的 fallback 情境）
        mock_router.get_word_explanation_structured = AsyncMock(
            return_value=("FIT 的意思是...", None)
        )
        mock_get_router.return_value = mock_router

        mock_search.return_value = []

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = mock_session

        mock_user_state_repo = MagicMock()
        mock_user_state_repo.set_pending_save = AsyncMock()
        mock_user_state_repo.set_pending_save_with_item = AsyncMock()

        with patch(
            "src.api.webhook.UserStateRepository",
            return_value=mock_user_state_repo,
        ):
            result = await _handle_unknown("Utest", "FIT", mode="free", target_lang="en")

        # item=None → 應使用舊的 set_pending_save
        mock_user_state_repo.set_pending_save.assert_awaited_once_with("hashed_user", "FIT")
        mock_user_state_repo.set_pending_save_with_item.assert_not_awaited()
        assert "FIT 的意思是" in result


# ============================================================================
# _handle_unknown 整合測試：SEARCH intent
# ============================================================================


class TestSearchIntentSingleWordDbMiss:
    """SEARCH intent + 單字 + DB 無結果 → fallback LLM 解釋 + pending_save。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_search_single_word_fallback_to_llm(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
        mock_session_ctx: MagicMock,
    ) -> None:
        """SEARCH intent DB 無結果且 keyword 為單字 → structured LLM 解釋。"""
        from src.schemas.router import IntentType, RouterResponse

        mock_router = MagicMock()
        mock_router.classify = AsyncMock(
            return_value=(
                RouterResponse(
                    intent=IntentType.SEARCH,
                    confidence=0.85,
                    keyword="FIT",
                    reason="search intent",
                ),
                None,
            )
        )
        mock_router.get_word_explanation_structured = AsyncMock(
            return_value=("FIT 表示適合", _SAMPLE_EXTRACTED_ITEM)
        )
        mock_get_router.return_value = mock_router

        # DB 無結果
        mock_search.return_value = []

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = mock_session

        mock_user_state_repo = MagicMock()
        mock_user_state_repo.set_pending_save = AsyncMock()
        mock_user_state_repo.set_pending_save_with_item = AsyncMock()

        with patch(
            "src.api.webhook.UserStateRepository",
            return_value=mock_user_state_repo,
        ):
            result = await _handle_unknown("Utest", "FIT", mode="free", target_lang="en")

        # 應呼叫 structured LLM 解釋
        mock_router.get_word_explanation_structured.assert_awaited_once()
        # 應設定 pending_save_with_item
        mock_user_state_repo.set_pending_save_with_item.assert_awaited_once_with(
            "hashed_user", "FIT", _SAMPLE_EXTRACTED_ITEM
        )
        # 回覆應包含解釋
        assert "FIT" in result


class TestSearchIntentMultiWordDbMiss:
    """SEARCH intent + 多字 + DB 無結果 → 回傳「找不到」（不變）。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_search_multi_word_no_fallback(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
    ) -> None:
        """SEARCH intent 多字無 DB 結果 → 回傳找不到，不走 LLM。"""
        from src.schemas.router import IntentType, RouterResponse

        mock_router = MagicMock()
        mock_router.classify = AsyncMock(
            return_value=(
                RouterResponse(
                    intent=IntentType.SEARCH,
                    confidence=0.8,
                    keyword="red apple",
                    reason="search intent",
                ),
                None,
            )
        )
        mock_get_router.return_value = mock_router

        # DB 無結果
        mock_search.return_value = []

        result = await _handle_unknown("Utest", "red apple", mode="free", target_lang="en")

        # 不應呼叫 LLM 解釋
        mock_router.get_word_explanation_structured.assert_not_called()
        # 應回傳找不到
        assert "找不到" in result


class TestSearchIntentDbHit:
    """SEARCH intent + DB 有結果 → 回傳 DB 結果（regression）。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_search_db_hit_returns_results(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
    ) -> None:
        """SEARCH intent DB 有結果 → 直接回傳搜尋結果。"""
        from src.schemas.router import IntentType, RouterResponse

        mock_router = MagicMock()
        mock_router.classify = AsyncMock(
            return_value=(
                RouterResponse(
                    intent=IntentType.SEARCH,
                    confidence=0.85,
                    keyword="食べる",
                    reason="search intent",
                ),
                None,
            )
        )
        mock_get_router.return_value = mock_router

        mock_item = MagicMock()
        mock_item.item_type = "vocab"
        mock_item.payload = {
            "surface": "食べる",
            "reading": "たべる",
            "pronunciation": "",
            "glossary_zh": ["吃"],
        }
        mock_search.return_value = [mock_item]

        result = await _handle_unknown("Utest", "食べる", mode="free", target_lang="ja")

        # 回覆應包含搜尋結果
        assert "食べる" in result
        # 不應呼叫 LLM 解釋
        mock_router.get_word_explanation_structured.assert_not_called()


# ============================================================================
# LLM API 失敗時的錯誤處理
# ============================================================================


class TestWordExplanationApiFailure:
    """LLM API 呼叫失敗時，回傳錯誤訊息且不設 pending_save。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_save_intent_api_failure(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
        mock_session_ctx: MagicMock,
    ) -> None:
        """SAVE intent 短單字 LLM 失敗 → 回傳錯誤訊息，不設 pending_save。"""
        from src.schemas.router import IntentType, RouterResponse

        mock_router = MagicMock()
        mock_router.classify = AsyncMock(
            return_value=(
                RouterResponse(intent=IntentType.SAVE, confidence=0.9, reason="single word"),
                None,
            )
        )
        mock_router.get_word_explanation_structured = AsyncMock(
            side_effect=Exception("Gemini API error")
        )
        mock_get_router.return_value = mock_router
        mock_search.return_value = []

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = mock_session

        mock_user_state_repo = MagicMock()
        mock_user_state_repo.set_pending_save = AsyncMock()
        mock_user_state_repo.set_pending_save_with_item = AsyncMock()

        with patch(
            "src.api.webhook.UserStateRepository",
            return_value=mock_user_state_repo,
        ):
            result = await _handle_unknown("Utest", "spell", mode="free", target_lang="en")

        assert "API呼叫失敗" in result
        mock_user_state_repo.set_pending_save.assert_not_awaited()
        mock_user_state_repo.set_pending_save_with_item.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_search_intent_api_failure(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
        mock_session_ctx: MagicMock,
    ) -> None:
        """SEARCH intent 單字 LLM 失敗 → 回傳錯誤訊息。"""
        from src.schemas.router import IntentType, RouterResponse

        mock_router = MagicMock()
        mock_router.classify = AsyncMock(
            return_value=(
                RouterResponse(
                    intent=IntentType.SEARCH,
                    confidence=0.85,
                    keyword="spell",
                    reason="search intent",
                ),
                None,
            )
        )
        mock_router.get_word_explanation_structured = AsyncMock(
            side_effect=Exception("API timeout")
        )
        mock_get_router.return_value = mock_router
        mock_search.return_value = []

        result = await _handle_unknown("Utest", "spell", mode="free", target_lang="en")

        assert "API呼叫失敗" in result
