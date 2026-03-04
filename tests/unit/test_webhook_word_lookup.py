"""
單字輸入「先查庫再 LLM 解釋」測試。

驗證 _handle_unknown 中 WORD 分類的
DB 優先查詢 + LLM fallback 行為。

注意：已改用結構特徵分類（_classify_input），不再呼叫 router_service.classify()。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.webhook import _handle_unknown


# ============================================================================
# _handle_unknown 整合測試：WORD 分類 + 單字
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
_SAMPLE_DISPLAY = "【FIT】/fɪt/\n詞性：adjective\n中文：適合的、健康的\n例句：This shirt fits well.\n翻譯：這件襯衫很合身。"

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
    "display": _SAMPLE_DISPLAY,
}


class TestWordClassificationDbHit:
    """WORD 分類 + DB 有紀錄 → 回傳 DB 結果，不呼叫 LLM。"""

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
        mock_router = MagicMock()
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
        mock_router = MagicMock()
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


class TestWordClassificationDbMiss:
    """WORD 分類 + DB 無紀錄 → 呼叫 LLM 解釋，設 pending_save_with_item。"""

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
        mock_router = MagicMock()
        mock_router.get_word_explanation_structured = AsyncMock(
            return_value=("FIT 的意思是...", _SAMPLE_EXTRACTED_ITEM, None)
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
        mock_router = MagicMock()
        # item 為 None（JSON parse 失敗的 fallback 情境）
        mock_router.get_word_explanation_structured = AsyncMock(
            return_value=("FIT 的意思是...", None, None)
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
# WORD 分類：日文單字 DB 搜尋
# ============================================================================


class TestJapaneseWordDbHit:
    """日文單字 + DB 有結果 → 回傳 DB 結果。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_japanese_word_db_hit_returns_results(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
    ) -> None:
        """「食べる」DB 有結果 → 直接回傳搜尋結果。"""
        mock_router = MagicMock()
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
# WORD 分類：multi-word 路徑
# ============================================================================


class TestMultiWordInput:
    """多單字輸入（"red apple"）→ 解釋第一個 + 提示其餘。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_multi_word_explains_first(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
        mock_session_ctx: MagicMock,
    ) -> None:
        """「red apple」→ compound word（2 token ≤15 字元），整體作為單字解釋。"""
        mock_router = MagicMock()
        mock_router.get_word_explanation_structured = AsyncMock(
            return_value=("red apple 表示紅蘋果", _SAMPLE_EXTRACTED_ITEM, None)
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
            result = await _handle_unknown("Utest", "red apple", mode="free", target_lang="en")

        # 2 token ≤15 字元 → compound word，整體查詢而非拆分
        mock_router.get_word_explanation_structured.assert_awaited_once_with(
            "red apple", mode="free", target_lang="en"
        )
        assert "red apple" in result


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
    async def test_word_api_failure(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
        mock_session_ctx: MagicMock,
    ) -> None:
        """WORD 分類 LLM 失敗 → 回傳錯誤訊息，不設 pending_save。"""
        mock_router = MagicMock()
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

        assert "系統繁忙" in result
        mock_user_state_repo.set_pending_save.assert_not_awaited()
        mock_user_state_repo.set_pending_save_with_item.assert_not_awaited()


# ============================================================================
# DB hit 單筆有 display → 回傳 header + display 全文
# ============================================================================


class TestDbHitWithDisplay:
    """DB 單筆結果有 display 時，回傳完整 LLM 分析而非摘要。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_single_result_with_display_returns_full_text(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
    ) -> None:
        """單筆 DB 結果且 payload 有 display → 回傳 header + display 全文。"""
        mock_router = MagicMock()
        mock_get_router.return_value = mock_router

        mock_item = MagicMock()
        mock_item.item_type = "vocab"
        mock_item.payload = {
            "surface": "FIT",
            "pronunciation": "fɪt",
            "glossary_zh": ["適合"],
            "display": _SAMPLE_DISPLAY,
        }
        mock_search.return_value = [mock_item]

        result = await _handle_unknown("Utest", "FIT", mode="free", target_lang="en")

        # 應包含完整 display 文字
        assert _SAMPLE_DISPLAY in result
        # 應包含搜尋 header
        assert "找到" in result
        # 不應呼叫 LLM
        mock_router.get_word_explanation_structured.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_multiple_results_use_summary_format(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
    ) -> None:
        """多筆 DB 結果 → 仍走摘要格式，不顯示 display 全文。"""
        mock_router = MagicMock()
        mock_get_router.return_value = mock_router

        items = []
        for surface in ["FIT", "FITness"]:
            item = MagicMock()
            item.item_type = "vocab"
            item.payload = {
                "surface": surface,
                "pronunciation": "fɪt",
                "glossary_zh": ["適合"],
                "display": f"完整分析：{surface}",
            }
            items.append(item)
        mock_search.return_value = items

        result = await _handle_unknown("Utest", "FIT", mode="free", target_lang="en")

        # 多筆結果不應包含 display 全文
        assert "完整分析：FIT" not in result
        # 應走摘要格式（有編號列表）
        assert "1." in result
        assert "2." in result

    @pytest.mark.asyncio
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_single_result_without_display_uses_summary(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
    ) -> None:
        """單筆 DB 結果但無 display（舊資料）→ 走摘要格式。"""
        mock_router = MagicMock()
        mock_get_router.return_value = mock_router

        mock_item = MagicMock()
        mock_item.item_type = "vocab"
        mock_item.payload = {
            "surface": "FIT",
            "pronunciation": "fɪt",
            "glossary_zh": ["適合"],
        }
        mock_search.return_value = [mock_item]

        result = await _handle_unknown("Utest", "FIT", mode="free", target_lang="en")

        # 無 display → 走摘要格式（有編號列表）
        assert "1." in result
        assert "FIT" in result


# ============================================================================
# _format_search_results: show_display 參數行為
# ============================================================================


class TestFormatSearchResultsShowDisplay:
    """搜尋指令（show_display=False）vs 單字查詢（show_display=True）。"""

    def _make_item(self, surface: str = "FIT", display: str | None = None) -> MagicMock:
        item = MagicMock()
        item.item_type = "vocab"
        item.payload = {
            "surface": surface,
            "pronunciation": "fɪt",
            "glossary_zh": ["適合"],
        }
        if display is not None:
            item.payload["display"] = display
        return item

    def test_search_command_single_with_display_uses_summary(self) -> None:
        """搜尋指令單筆有 display → 仍走摘要格式（預設 show_display=False）。"""
        from src.api.webhook import _format_search_results

        item = self._make_item(display="完整 LLM 分析文字")
        result = _format_search_results([item])

        assert "完整 LLM 分析文字" not in result
        assert "1." in result

    def test_word_lookup_single_with_display_shows_full(self) -> None:
        """單字查詢單筆有 display → show_display=True 顯示全文。"""
        from src.api.webhook import _format_search_results

        display_text = "【FIT】/fɪt/\n詞性：adjective"
        item = self._make_item(display=display_text)
        result = _format_search_results([item], show_display=True)

        assert display_text in result
