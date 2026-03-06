"""
單字輸入「先查庫再 LLM 解釋」測試。

驗證 _handle_unknown 中 WORD 分類的
DB 優先查詢 + LLM fallback 行為。

注意：已改用結構特徵分類（_classify_input），不再呼叫 router_service.classify()。
"""

from typing import Any
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


def _make_extracted_item(word: str) -> dict[str, Any]:
    """建立模擬的 extracted_item dict。"""
    return {
        "item_type": "vocab",
        "key": f"vocab:{word}",
        "surface": word,
        "pronunciation": "",
        "pos": "noun",
        "glossary_zh": [f"{word}的中文"],
        "example": f"Example for {word}.",
        "example_translation": f"{word}的例句翻譯。",
        "confidence": 1.0,
        "display": f"【{word}】的完整解釋",
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
# WORD 分類：multi-word 路徑 — 統一處理
# ============================================================================


class TestMultiWordInput:
    """多單字輸入 → 所有單字都走完整流程。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_compound_word_treated_as_single(
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

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_multi_word_all_db_hit(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
        mock_session_ctx: MagicMock,
    ) -> None:
        """3 字全在 DB → 合併顯示，無 pending_save。"""
        mock_router = MagicMock()
        mock_get_router.return_value = mock_router

        # 每個 token 都回傳 DB 結果
        mock_search.side_effect = [
            [_mock_item("apple")],
            [_mock_item("banana")],
            [_mock_item("cherry")],
        ]

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = mock_session

        mock_user_state_repo = MagicMock()
        mock_user_state_repo.set_pending_save = AsyncMock()
        mock_user_state_repo.set_pending_save_with_item = AsyncMock()
        mock_user_state_repo.set_pending_save_multi = AsyncMock()

        with patch(
            "src.api.webhook.UserStateRepository",
            return_value=mock_user_state_repo,
        ):
            result = await _handle_unknown(
                "Utest", "apple banana cherry", mode="free", target_lang="en"
            )

        # 不呼叫 LLM
        mock_router.get_word_explanation_structured.assert_not_called()
        mock_router.get_batch_word_explanation_structured.assert_not_called()
        # 不設 pending
        mock_user_state_repo.set_pending_save.assert_not_awaited()
        mock_user_state_repo.set_pending_save_with_item.assert_not_awaited()
        mock_user_state_repo.set_pending_save_multi.assert_not_awaited()
        # 回覆包含已入庫標記
        assert "已入庫" in result
        # 回覆有分隔線
        assert "━━━━━━━━━━" in result

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_multi_word_all_db_miss(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
        mock_session_ctx: MagicMock,
    ) -> None:
        """3 字全不在 DB → batch LLM，全部進 pending_save_multi。"""
        mock_router = MagicMock()

        batch_results = [
            ("apple", "apple 的解釋", _make_extracted_item("apple")),
            ("banana", "banana 的解釋", _make_extracted_item("banana")),
            ("cherry", "cherry 的解釋", _make_extracted_item("cherry")),
        ]
        mock_router.get_batch_word_explanation_structured = AsyncMock(
            return_value=(batch_results, None)
        )
        mock_get_router.return_value = mock_router

        mock_search.return_value = []  # 全部 DB miss

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = mock_session

        mock_user_state_repo = MagicMock()
        mock_user_state_repo.set_pending_save = AsyncMock()
        mock_user_state_repo.set_pending_save_with_item = AsyncMock()
        mock_user_state_repo.set_pending_save_multi = AsyncMock()

        with patch(
            "src.api.webhook.UserStateRepository",
            return_value=mock_user_state_repo,
        ):
            result = await _handle_unknown(
                "Utest", "apple banana cherry", mode="free", target_lang="en"
            )

        # 應呼叫 batch LLM
        mock_router.get_batch_word_explanation_structured.assert_awaited_once()
        # 應設定 multi pending
        mock_user_state_repo.set_pending_save_multi.assert_awaited_once()
        call_args = mock_user_state_repo.set_pending_save_multi.call_args
        assert call_args[0][0] == "hashed_user"
        entries = call_args[0][1]
        assert len(entries) == 3
        assert entries[0]["word"] == "apple"
        # 回覆包含各字解釋
        assert "apple 的解釋" in result
        assert "banana 的解釋" in result
        assert "cherry 的解釋" in result
        # 有 pending 提示
        assert "入庫" in result

    @pytest.mark.asyncio
    @patch("src.api.webhook.get_session")
    @patch("src.api.webhook.hash_user_id", return_value="hashed_user")
    @patch("src.services.router_service.get_router_service")
    @patch("src.api.webhook._search_user_items", new_callable=AsyncMock)
    async def test_multi_word_mixed(
        self,
        mock_search: AsyncMock,
        mock_get_router: MagicMock,
        mock_hash: MagicMock,
        mock_session_ctx: MagicMock,
    ) -> None:
        """A 在 DB、B/C 不在 → A 秒回 + B/C LLM，只 B/C 進 pending。"""
        mock_router = MagicMock()

        batch_results = [
            ("banana", "banana 的解釋", _make_extracted_item("banana")),
            ("cherry", "cherry 的解釋", _make_extracted_item("cherry")),
        ]
        mock_router.get_batch_word_explanation_structured = AsyncMock(
            return_value=(batch_results, None)
        )
        mock_get_router.return_value = mock_router

        # apple 在 DB，banana 和 cherry 不在
        mock_search.side_effect = [
            [_mock_item("apple")],  # apple → DB hit
            [],                      # banana → DB miss
            [],                      # cherry → DB miss
        ]

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = mock_session

        mock_user_state_repo = MagicMock()
        mock_user_state_repo.set_pending_save = AsyncMock()
        mock_user_state_repo.set_pending_save_with_item = AsyncMock()
        mock_user_state_repo.set_pending_save_multi = AsyncMock()

        with patch(
            "src.api.webhook.UserStateRepository",
            return_value=mock_user_state_repo,
        ):
            result = await _handle_unknown(
                "Utest", "apple banana cherry", mode="free", target_lang="en"
            )

        # batch LLM 只查 banana 和 cherry
        mock_router.get_batch_word_explanation_structured.assert_awaited_once()
        call_args = mock_router.get_batch_word_explanation_structured.call_args
        assert call_args[0][0] == ["banana", "cherry"]

        # pending 只有 banana 和 cherry
        mock_user_state_repo.set_pending_save_multi.assert_awaited_once()
        entries = mock_user_state_repo.set_pending_save_multi.call_args[0][1]
        assert len(entries) == 2
        assert entries[0]["word"] == "banana"
        assert entries[1]["word"] == "cherry"

        # 回覆包含已入庫和新解釋
        assert "已入庫" in result
        assert "banana 的解釋" in result


# ============================================================================
# 多字 pending 確認入庫 + 取消
# ============================================================================


class TestMultiWordConfirmSave:
    """「1」確認多字 pending → 全部入庫。"""

    @pytest.mark.asyncio
    @patch("src.api.webhook._schedule_background_extraction")
    @patch("src.api.webhook.get_session")
    async def test_multi_word_confirm_save(
        self,
        mock_session_ctx: MagicMock,
        mock_bg_extract: MagicMock,
    ) -> None:
        """確認 3 字 pending → 全部入庫，回覆 BATCH_SAVE_SUCCESS。"""
        import json

        from src.repositories.user_state_repo import (
            UserStateRepository as RealUserStateRepo,
        )

        multi_pending = json.dumps({
            "words": [
                {"word": "apple", "extracted_item": _make_extracted_item("apple")},
                {"word": "banana", "extracted_item": _make_extracted_item("banana")},
                {"word": "cherry", "extracted_item": _make_extracted_item("cherry")},
            ]
        }, ensure_ascii=False)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = mock_session

        mock_user_state_repo = MagicMock()
        mock_user_state_repo.get_pending_save = AsyncMock(return_value=multi_pending)
        mock_user_state_repo.clear_pending_save = AsyncMock()

        mock_command_service = MagicMock()
        mock_command_service.save_raw = AsyncMock(
            return_value=MagicMock(
                success=True,
                data={"doc_id": "test-doc-id"},
                message="OK",
            )
        )

        mock_item_repo = MagicMock()
        mock_item_repo.upsert = AsyncMock()
        mock_doc_repo = MagicMock()
        mock_doc_repo.update = AsyncMock()

        with (
            patch("src.api.webhook.UserStateRepository") as mock_usr_cls,
            patch("src.api.webhook.CommandService", return_value=mock_command_service),
            patch("src.repositories.item_repo.ItemRepository", return_value=mock_item_repo),
            patch("src.repositories.document_repo.DocumentRepository", return_value=mock_doc_repo),
        ):
            # 保留 parse_pending_save_content 靜態方法
            mock_usr_cls.return_value = mock_user_state_repo
            mock_usr_cls.parse_pending_save_content = RealUserStateRepo.parse_pending_save_content

            from src.api.webhook import _handle_confirm_save

            result = await _handle_confirm_save(
                "hashed_user", "Utest", mode="free", target_lang="en"
            )

        # 應包含批次入庫成功訊息
        assert "已批次入庫" in result or "已入庫" in result
        # save_raw 應呼叫 3 次
        assert mock_command_service.save_raw.await_count == 3


class TestMultiWordPendingCancel:
    """多字 pending 被新輸入取消 → 列出全部。"""

    def test_multi_word_pending_cancel_notice(self) -> None:
        """多字 pending 取消時應列出所有被取消的單字。"""
        import json

        from src.repositories.user_state_repo import UserStateRepository
        from src.templates.messages import Messages

        multi_pending = json.dumps({
            "words": [
                {"word": "apple", "extracted_item": None},
                {"word": "banana", "extracted_item": None},
            ]
        }, ensure_ascii=False)

        entries = UserStateRepository.parse_pending_save_content(multi_pending)
        assert len(entries) == 2
        all_words = "、".join(f"「{w}」" for w, _ in entries)
        notice = Messages.format("PENDING_DISCARDED_MULTI", words=all_words)
        assert "apple" in notice
        assert "banana" in notice


# ============================================================================
# parse_pending_save_content 格式相容性
# ============================================================================


class TestParsePendingSaveContent:
    """parse_pending_save_content 新舊格式相容測試。"""

    def test_parse_multi_format(self) -> None:
        """新多字 JSON 格式解析。"""
        import json

        from src.repositories.user_state_repo import UserStateRepository

        raw = json.dumps({
            "words": [
                {"word": "食べる", "extracted_item": {"key": "vocab:食べる"}},
                {"word": "飲む", "extracted_item": None},
            ]
        }, ensure_ascii=False)

        result = UserStateRepository.parse_pending_save_content(raw)
        assert len(result) == 2
        assert result[0] == ("食べる", {"key": "vocab:食べる"})
        assert result[1] == ("飲む", None)

    def test_parse_single_json_format(self) -> None:
        """舊單字 JSON 格式仍正常。"""
        import json

        from src.repositories.user_state_repo import UserStateRepository

        raw = json.dumps({
            "word": "食べる",
            "extracted_item": {"key": "vocab:食べる"},
        }, ensure_ascii=False)

        result = UserStateRepository.parse_pending_save_content(raw)
        assert len(result) == 1
        assert result[0] == ("食べる", {"key": "vocab:食べる"})

    def test_parse_plain_text_format(self) -> None:
        """純文字 legacy 格式仍正常。"""
        from src.repositories.user_state_repo import UserStateRepository

        result = UserStateRepository.parse_pending_save_content("食べる")
        assert len(result) == 1
        assert result[0] == ("食べる", None)


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
