"""指令邏輯審計 — 每個 handler 的 edge case 測試。

每個指令 5 個 edge case，涵蓋邊界條件、錯誤處理、狀態交互。
共 15 個 handler × 5 = 75 tests。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.webhook import (
    _dispatch_command,
    _handle_confirm_save,
    _handle_cost,
    _handle_delete_all_request,
    _handle_delete_confirm,
    _handle_delete_item,
    _handle_delete_select,
    _handle_exit_practice,
    _handle_practice,
    _handle_practice_answer,
    _handle_save,
    _handle_search,
    _handle_stats,
    _handle_unknown,
    _handle_word_save,
)
from src.schemas.command import CommandType, ParsedCommand
from src.templates.messages import Messages


# ============================================================================
# 通用 Mock Helper
# ============================================================================


def _mock_session_ctx() -> MagicMock:
    """建立 get_session() 返回的 mock async context manager。"""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=MagicMock())
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _mock_user_state_repo(**kwargs: object) -> MagicMock:
    """建立 mock UserStateRepository。"""
    repo = MagicMock()
    repo.get_last_message = AsyncMock(return_value=kwargs.get("last_message"))
    repo.clear_last_message = AsyncMock()
    repo.get_pending_save = AsyncMock(return_value=kwargs.get("pending_save"))
    repo.clear_pending_save = AsyncMock()
    repo.has_pending_save = AsyncMock(return_value=kwargs.get("has_pending_save", False))
    repo.has_pending_delete = AsyncMock(return_value=kwargs.get("has_pending_delete", False))
    repo.get_pending_delete = AsyncMock(return_value=kwargs.get("pending_delete"))
    repo.clear_pending_delete = AsyncMock()
    repo.set_pending_save = AsyncMock()
    repo.set_pending_save_with_item = AsyncMock()
    repo.set_pending_delete = AsyncMock()
    repo.set_delete_confirm_at = AsyncMock()
    repo.is_delete_confirmation_pending = AsyncMock(
        return_value=kwargs.get("is_delete_pending", False)
    )
    repo.clear_delete_confirm = AsyncMock()
    repo.set_last_message = AsyncMock()
    # parse_pending_save_content：使用真實邏輯
    from src.repositories.user_state_repo import UserStateRepository
    repo.parse_pending_save_content = UserStateRepository.parse_pending_save_content.__get__(repo)
    return repo


def _mock_command_service(message: str = "已入庫：test", success: bool = True, doc_id: str | None = "test-doc-id") -> MagicMock:
    """建立 mock CommandService，save_raw 回傳指定訊息。"""
    result = MagicMock()
    result.message = message
    result.success = success
    result.doc_id = doc_id
    service = MagicMock()
    service.save_raw = AsyncMock(return_value=result)
    return service


def _mock_item(
    surface: str = "食べる",
    reading: str = "たべる",
    meaning: str = "吃",
    item_type: str = "vocab",
) -> MagicMock:
    """建立 mock Item。"""
    item = MagicMock()
    item.item_id = uuid.uuid4()
    item.item_type = item_type
    item.key = surface
    if item_type == "vocab":
        item.payload = {"surface": surface, "reading": reading, "glossary_zh": [meaning]}
    else:
        item.payload = {"pattern": surface, "meaning_zh": meaning}
    return item


# ============================================================================
# 1. SAVE（入庫）— 5 edge cases
# ============================================================================


class TestSaveEdgeCases:
    """_handle_save edge cases。"""

    async def test_no_last_message_returns_no_content(self) -> None:
        """last_message 為 None → SAVE_NO_CONTENT。"""
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=_mock_user_state_repo(last_message=None)),
        ):
            result = await _handle_save("Utest")
        assert result == Messages.SAVE_NO_CONTENT

    async def test_pure_emoji_last_message_returns_no_content(self) -> None:
        """last_message 僅含 emoji → _has_meaningful_content=False → SAVE_NO_CONTENT。"""
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=_mock_user_state_repo(last_message="🎉🎉🎉")),
        ):
            result = await _handle_save("Utest")
        assert result == Messages.SAVE_NO_CONTENT

    async def test_pure_punctuation_returns_no_content(self) -> None:
        """last_message 僅含符號 → _has_meaningful_content=False → SAVE_NO_CONTENT。"""
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=_mock_user_state_repo(last_message="!!??...")),
        ):
            result = await _handle_save("Utest")
        assert result == Messages.SAVE_NO_CONTENT

    async def test_successful_save_clears_last_message(self) -> None:
        """成功入庫後 clear_last_message 應被呼叫。"""
        mock_repo = _mock_user_state_repo(last_message="日本語テスト")
        mock_service = _mock_command_service("已入庫：日本語テスト")
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
            patch("src.api.webhook.CommandService", return_value=mock_service),
        ):
            result = await _handle_save("Utest")
        mock_repo.clear_last_message.assert_awaited_once_with("h")
        assert "已入庫" in result

    async def test_mixed_emoji_and_text_saves_successfully(self) -> None:
        """last_message 含 emoji + 文字 → 有意義內容 → 正常入庫。"""
        mock_repo = _mock_user_state_repo(last_message="🎉 おめでとう！")
        mock_service = _mock_command_service("已入庫：🎉 おめでとう！")
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
            patch("src.api.webhook.CommandService", return_value=mock_service),
        ):
            result = await _handle_save("Utest")
        assert "已入庫" in result


# ============================================================================
# 2. WORD_SAVE（<單字> save）— 5 edge cases
# ============================================================================


class TestWordSaveEdgeCases:
    """_handle_word_save edge cases。"""

    async def test_none_keyword_returns_no_content(self) -> None:
        """keyword=None → SAVE_NO_CONTENT。"""
        result = await _handle_word_save("Utest", None)
        assert result == Messages.SAVE_NO_CONTENT

    async def test_empty_string_keyword_returns_no_content(self) -> None:
        """keyword="" → SAVE_NO_CONTENT。"""
        result = await _handle_word_save("Utest", "")
        assert result == Messages.SAVE_NO_CONTENT

    async def test_pure_emoji_keyword_returns_no_content(self) -> None:
        """keyword 僅含 emoji → SAVE_NO_CONTENT。"""
        result = await _handle_word_save("Utest", "🎉🎉")
        assert result == Messages.SAVE_NO_CONTENT

    async def test_cjk_keyword_saves_normally(self) -> None:
        """CJK 單字正常入庫。"""
        mock_service = _mock_command_service("已入庫：食べる")
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.CommandService", return_value=mock_service),
        ):
            result = await _handle_word_save("Utest", "食べる")
        assert "已入庫" in result

    async def test_keyword_with_spaces_saves_as_is(self) -> None:
        """含空白的關鍵字照樣傳遞給 save_raw。"""
        mock_service = _mock_command_service("已入庫：get up")
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.CommandService", return_value=mock_service),
        ):
            result = await _handle_word_save("Utest", "get up")
        mock_service.save_raw.assert_awaited_once()
        call_kwargs = mock_service.save_raw.call_args
        assert call_kwargs[1]["content_text"] == "get up"


# ============================================================================
# 3. CONFIRM_SAVE（「1」確認入庫）— 5 edge cases
# ============================================================================


class TestConfirmSaveEdgeCases:
    """_handle_confirm_save edge cases。"""

    async def test_no_pending_content_returns_expired(self) -> None:
        """pending_save 為 None（競態條件）→ PENDING_EXPIRED（Issue #5 修復驗證）。"""
        mock_repo = _mock_user_state_repo(pending_save=None)
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
        ):
            result = await _handle_confirm_save("hashed_uid", "Utest")
        assert result == Messages.PENDING_EXPIRED

    async def test_empty_string_pending_returns_expired(self) -> None:
        """pending_save 為空字串 → PENDING_EXPIRED。"""
        mock_repo = _mock_user_state_repo(pending_save="")
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
        ):
            result = await _handle_confirm_save("hashed_uid", "Utest")
        assert result == Messages.PENDING_EXPIRED

    async def test_successful_confirm_returns_save_message(self) -> None:
        """正常確認 → 回傳包含「已入庫」的訊息。"""
        mock_repo = _mock_user_state_repo(pending_save="apple")
        mock_service = _mock_command_service("已入庫：apple")
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
            patch("src.api.webhook.CommandService", return_value=mock_service),
            patch("src.api.webhook._auto_extract", new_callable=AsyncMock, return_value="1 個單字"),
        ):
            result = await _handle_confirm_save("hashed_uid", "Utest")
        assert "已入庫" in result

    async def test_confirm_clears_pending_save(self) -> None:
        """成功入庫後 clear_pending_save 應被呼叫。"""
        mock_repo = _mock_user_state_repo(pending_save="apple")
        mock_service = _mock_command_service("已入庫：apple")
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
            patch("src.api.webhook.CommandService", return_value=mock_service),
            patch("src.api.webhook._auto_extract", new_callable=AsyncMock, return_value=None),
        ):
            await _handle_confirm_save("hashed_uid", "Utest")
        mock_repo.clear_pending_save.assert_awaited_once_with("hashed_uid")

    async def test_confirm_passes_line_user_id_to_save_raw(self) -> None:
        """save_raw 接收的是原始 line_user_id（非 hashed）。"""
        mock_repo = _mock_user_state_repo(pending_save="word")
        mock_service = _mock_command_service("ok")
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
            patch("src.api.webhook.CommandService", return_value=mock_service),
            patch("src.api.webhook._auto_extract", new_callable=AsyncMock, return_value=None),
        ):
            await _handle_confirm_save("hashed_uid", "Uoriginal")
        call_kwargs = mock_service.save_raw.call_args[1]
        assert call_kwargs["line_user_id"] == "Uoriginal"


# ============================================================================
# 4. SEARCH（查詢）— 5 edge cases
# ============================================================================


class TestSearchEdgeCases:
    """_handle_search edge cases。"""

    async def test_no_keyword_returns_hint(self) -> None:
        """keyword=None → SEARCH_HINT。"""
        result = await _handle_search("Utest", None)
        assert result == Messages.SEARCH_HINT

    async def test_no_results_returns_formatted_message(self) -> None:
        """查無結果 → 包含關鍵字的提示。"""
        mock_item_repo = MagicMock()
        mock_item_repo.search_by_keyword = AsyncMock(return_value=[])
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.repositories.item_repo.ItemRepository", return_value=mock_item_repo),
        ):
            result = await _handle_search("Utest", "不存在的字")
        assert "不存在的字" in result

    async def test_exactly_display_limit_no_more_indicator(self) -> None:
        """結果數 = DISPLAY_LIMIT (5) → 無「還有 N 筆」提示。"""
        items = [_mock_item(surface=f"word{i}") for i in range(5)]
        mock_item_repo = MagicMock()
        mock_item_repo.search_by_keyword = AsyncMock(return_value=items)
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.repositories.item_repo.ItemRepository", return_value=mock_item_repo),
        ):
            result = await _handle_search("Utest", "word")
        assert "還有" not in result

    async def test_above_display_limit_shows_more_indicator(self) -> None:
        """結果數 > DISPLAY_LIMIT → 出現「還有 N 筆」。"""
        items = [_mock_item(surface=f"word{i}") for i in range(8)]
        mock_item_repo = MagicMock()
        mock_item_repo.search_by_keyword = AsyncMock(return_value=items)
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.repositories.item_repo.ItemRepository", return_value=mock_item_repo),
        ):
            result = await _handle_search("Utest", "word")
        assert "還有 3 筆" in result

    async def test_search_exception_returns_error(self) -> None:
        """search_by_keyword 拋出例外 → ERROR_SEARCH。"""
        mock_item_repo = MagicMock()
        mock_item_repo.search_by_keyword = AsyncMock(side_effect=Exception("DB error"))
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.repositories.item_repo.ItemRepository", return_value=mock_item_repo),
        ):
            result = await _handle_search("Utest", "test")
        assert result == Messages.ERROR_SEARCH


# ============================================================================
# 5. PRACTICE（練習）— 5 edge cases
# ============================================================================


class TestPracticeEdgeCases:
    """_handle_practice edge cases。"""

    async def test_create_session_success(self) -> None:
        """建立 session 成功 → 回傳 service 訊息。"""
        mock_service = MagicMock()
        mock_service.create_session = AsyncMock(return_value=(MagicMock(), "📝 今日練習題"))
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.practice_service.PracticeService", return_value=mock_service),
        ):
            result = await _handle_practice("Utest")
        assert "練習" in result

    async def test_create_session_exception_returns_error(self) -> None:
        """create_session 拋出例外 → ERROR_PRACTICE。"""
        mock_service = MagicMock()
        mock_service.create_session = AsyncMock(side_effect=Exception("DB error"))
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.practice_service.PracticeService", return_value=mock_service),
        ):
            result = await _handle_practice("Utest")
        assert result == Messages.ERROR_PRACTICE

    async def test_mode_passed_to_practice_service(self) -> None:
        """mode 正確傳遞給 PracticeService 建構子。"""
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.practice_service.PracticeService") as MockPS,
        ):
            mock_service = MagicMock()
            mock_service.create_session = AsyncMock(return_value=(MagicMock(), "ok"))
            MockPS.return_value = mock_service
            await _handle_practice("Utest", mode="rigorous")
        assert MockPS.call_args[1]["mode"] == "rigorous"

    async def test_target_lang_passed_to_practice_service(self) -> None:
        """target_lang 正確傳遞給 PracticeService 建構子。"""
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.practice_service.PracticeService") as MockPS,
        ):
            mock_service = MagicMock()
            mock_service.create_session = AsyncMock(return_value=(MagicMock(), "ok"))
            MockPS.return_value = mock_service
            await _handle_practice("Utest", target_lang="en")
        assert MockPS.call_args[1]["target_lang"] == "en"

    async def test_question_count_always_five(self) -> None:
        """create_session 固定使用 question_count=5。"""
        mock_service = MagicMock()
        mock_service.create_session = AsyncMock(return_value=(MagicMock(), "ok"))
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.practice_service.PracticeService", return_value=mock_service),
        ):
            await _handle_practice("Utest")
        assert mock_service.create_session.call_args[1]["question_count"] == 5


# ============================================================================
# 7. EXIT_PRACTICE（結束練習）— 5 edge cases
# ============================================================================


class TestExitPracticeEdgeCases:
    """_handle_exit_practice edge cases。"""

    async def test_no_active_session_returns_no_session(self) -> None:
        """無進行中 session → PRACTICE_EXIT_NO_SESSION。"""
        mock_session_service = MagicMock()
        mock_session_service.has_active_session = AsyncMock(return_value=False)
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.session_service.SessionService", return_value=mock_session_service),
        ):
            result = await _handle_exit_practice("hashed_uid")
        assert "沒有進行中的練習" in result

    async def test_active_session_cleared_and_confirmed(self) -> None:
        """有進行中 session → 清除 + 確認訊息。"""
        mock_session_service = MagicMock()
        mock_session_service.has_active_session = AsyncMock(return_value=True)
        mock_session_service.clear_session = AsyncMock()
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.session_service.SessionService", return_value=mock_session_service),
        ):
            result = await _handle_exit_practice("hashed_uid")
        assert "已結束練習" in result

    async def test_clear_session_is_awaited(self) -> None:
        """clear_session 應被正確 await。"""
        mock_session_service = MagicMock()
        mock_session_service.has_active_session = AsyncMock(return_value=True)
        mock_session_service.clear_session = AsyncMock()
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.session_service.SessionService", return_value=mock_session_service),
        ):
            await _handle_exit_practice("hashed_uid")
        mock_session_service.clear_session.assert_awaited_once()

    async def test_has_active_session_called_with_correct_uid(self) -> None:
        """has_active_session 接收正確的 hashed user ID。"""
        mock_session_service = MagicMock()
        mock_session_service.has_active_session = AsyncMock(return_value=False)
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.session_service.SessionService", return_value=mock_session_service),
        ):
            await _handle_exit_practice("specific_hash_123")
        mock_session_service.has_active_session.assert_awaited_once_with("specific_hash_123")

    async def test_clear_session_called_with_correct_uid(self) -> None:
        """clear_session 接收正確的 hashed user ID。"""
        mock_session_service = MagicMock()
        mock_session_service.has_active_session = AsyncMock(return_value=True)
        mock_session_service.clear_session = AsyncMock()
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.session_service.SessionService", return_value=mock_session_service),
        ):
            await _handle_exit_practice("specific_hash_456")
        mock_session_service.clear_session.assert_awaited_once_with("specific_hash_456")


# ============================================================================
# 8. PRACTICE_ANSWER（練習答案）— 5 edge cases
# ============================================================================


class TestPracticeAnswerEdgeCases:
    """_handle_practice_answer edge cases。"""

    async def test_submit_success_returns_message(self) -> None:
        """submit_answer 成功 → 回傳 service 訊息。"""
        mock_service = MagicMock()
        mock_service.submit_answer = AsyncMock(return_value=(MagicMock(), "✅ 正確！"))
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.practice_service.PracticeService", return_value=mock_service),
        ):
            result = await _handle_practice_answer("h", "食べる")
        assert "正確" in result

    async def test_submit_exception_returns_error(self) -> None:
        """submit_answer 拋出例外 → ERROR_PRACTICE_ANSWER。"""
        mock_service = MagicMock()
        mock_service.submit_answer = AsyncMock(side_effect=Exception("grading failed"))
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.practice_service.PracticeService", return_value=mock_service),
        ):
            result = await _handle_practice_answer("h", "answer")
        assert result == Messages.ERROR_PRACTICE_ANSWER

    async def test_mode_passed_to_service(self) -> None:
        """mode 正確傳遞。"""
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.practice_service.PracticeService") as MockPS,
        ):
            mock_service = MagicMock()
            mock_service.submit_answer = AsyncMock(return_value=(MagicMock(), "ok"))
            MockPS.return_value = mock_service
            await _handle_practice_answer("h", "ans", mode="cheap")
        assert MockPS.call_args[1]["mode"] == "cheap"

    async def test_target_lang_passed_to_service(self) -> None:
        """target_lang 正確傳遞。"""
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.practice_service.PracticeService") as MockPS,
        ):
            mock_service = MagicMock()
            mock_service.submit_answer = AsyncMock(return_value=(MagicMock(), "ok"))
            MockPS.return_value = mock_service
            await _handle_practice_answer("h", "ans", target_lang="en")
        assert MockPS.call_args[1]["target_lang"] == "en"

    async def test_empty_answer_still_submitted(self) -> None:
        """空白答案不做前置驗證，直接提交（由 service 判斷）。"""
        mock_service = MagicMock()
        mock_service.submit_answer = AsyncMock(return_value=(MagicMock(), "❌ 答案是：x"))
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.practice_service.PracticeService", return_value=mock_service),
        ):
            result = await _handle_practice_answer("h", "   ")
        mock_service.submit_answer.assert_awaited_once()
        assert "答案" in result


# ============================================================================
# 9. COST（用量）— 5 edge cases
# ============================================================================


class TestCostEdgeCases:
    """_handle_cost edge cases。"""

    async def test_service_returns_message(self) -> None:
        """正常情況回傳 service 訊息。"""
        mock_result = MagicMock()
        mock_result.message = "📊 API 用量統計"
        mock_service = MagicMock()
        mock_service.get_usage_summary = AsyncMock(return_value=mock_result)
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.cost_service.CostService", return_value=mock_service),
        ):
            result = await _handle_cost("Utest")
        assert "用量" in result

    async def test_service_exception_returns_error(self) -> None:
        """service 拋出例外 → ERROR_COST。"""
        mock_service = MagicMock()
        mock_service.get_usage_summary = AsyncMock(side_effect=Exception("DB timeout"))
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.cost_service.CostService", return_value=mock_service),
        ):
            result = await _handle_cost("Utest")
        assert result == Messages.ERROR_COST

    async def test_line_user_id_passed_correctly(self) -> None:
        """webhook 先 hash 再傳給 service（service 接收 hashed ID）。"""
        mock_service = MagicMock()
        mock_service.get_usage_summary = AsyncMock(return_value=MagicMock(message="ok"))
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.cost_service.CostService", return_value=mock_service),
            patch("src.api.webhook.hash_user_id", return_value="hashed_uid"),
        ):
            await _handle_cost("Uoriginal_line_id")
        mock_service.get_usage_summary.assert_awaited_once_with("hashed_uid")

    async def test_empty_result_message(self) -> None:
        """無用量紀錄 → service 回傳的空結果訊息仍正常顯示。"""
        mock_result = MagicMock()
        mock_result.message = Messages.COST_NO_DATA
        mock_service = MagicMock()
        mock_service.get_usage_summary = AsyncMock(return_value=mock_result)
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.cost_service.CostService", return_value=mock_service),
        ):
            result = await _handle_cost("Utest")
        assert "尚無" in result

    async def test_result_message_returned_directly(self) -> None:
        """回傳值即 result.message，不做額外包裝。"""
        mock_result = MagicMock()
        mock_result.message = "EXACT_MESSAGE"
        mock_service = MagicMock()
        mock_service.get_usage_summary = AsyncMock(return_value=mock_result)
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.cost_service.CostService", return_value=mock_service),
        ):
            result = await _handle_cost("Utest")
        assert result == "EXACT_MESSAGE"


# ============================================================================
# 10. STATS（統計）— 5 edge cases
# ============================================================================


class TestStatsEdgeCases:
    """_handle_stats edge cases。"""

    async def test_service_returns_message(self) -> None:
        """正常情況回傳 service 訊息。"""
        mock_result = MagicMock()
        mock_result.message = "📊 學習進度"
        mock_service = MagicMock()
        mock_service.get_stats_summary = AsyncMock(return_value=mock_result)
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.stats_service.StatsService", return_value=mock_service),
        ):
            result = await _handle_stats("Utest")
        assert "學習" in result or "進度" in result

    async def test_service_exception_returns_error(self) -> None:
        """service 拋出例外 → ERROR_STATS。"""
        mock_service = MagicMock()
        mock_service.get_stats_summary = AsyncMock(side_effect=Exception("timeout"))
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.stats_service.StatsService", return_value=mock_service),
        ):
            result = await _handle_stats("Utest")
        assert result == Messages.ERROR_STATS

    async def test_line_user_id_passed_correctly(self) -> None:
        """webhook 先 hash 再傳給 service（service 接收 hashed ID）。"""
        mock_service = MagicMock()
        mock_service.get_stats_summary = AsyncMock(return_value=MagicMock(message="ok"))
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.stats_service.StatsService", return_value=mock_service),
            patch("src.api.webhook.hash_user_id", return_value="hashed_uid"),
        ):
            await _handle_stats("Uline_456")
        mock_service.get_stats_summary.assert_awaited_once_with("hashed_uid")

    async def test_empty_stats_message(self) -> None:
        """新使用者無資料 → 回傳空結果訊息。"""
        mock_result = MagicMock()
        mock_result.message = "📊 尚無學習紀錄"
        mock_service = MagicMock()
        mock_service.get_stats_summary = AsyncMock(return_value=mock_result)
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.stats_service.StatsService", return_value=mock_service),
        ):
            result = await _handle_stats("Utest")
        assert "尚無" in result

    async def test_result_message_returned_directly(self) -> None:
        """回傳值即 result.message，不做額外包裝。"""
        mock_result = MagicMock()
        mock_result.message = "EXACT_STATS"
        mock_service = MagicMock()
        mock_service.get_stats_summary = AsyncMock(return_value=mock_result)
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.services.stats_service.StatsService", return_value=mock_service),
        ):
            result = await _handle_stats("Utest")
        assert result == "EXACT_STATS"


# ============================================================================
# 11. DELETE_ITEM（刪除 <關鍵字>）— 5 edge cases
# ============================================================================


class TestDeleteItemEdgeCases:
    """_handle_delete_item edge cases。"""

    async def test_no_keyword_returns_hint(self) -> None:
        """keyword=None → DELETE_ITEM_HINT。"""
        result = await _handle_delete_item("Utest", None)
        assert result == Messages.DELETE_ITEM_HINT

    async def test_no_results_returns_not_found(self) -> None:
        """查無結果 → 包含關鍵字的 NOT_FOUND 訊息。"""
        mock_item_repo = MagicMock()
        mock_item_repo.search_by_keyword = AsyncMock(return_value=[])
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.repositories.item_repo.ItemRepository", return_value=mock_item_repo),
        ):
            result = await _handle_delete_item("Utest", "xyz")
        assert "xyz" in result

    async def test_single_result_direct_delete(self) -> None:
        """單筆結果 → 直接刪除，不設 pending_delete。"""
        mock_item_repo = MagicMock()
        mock_item_repo.search_by_keyword = AsyncMock(return_value=[_mock_item()])
        mock_delete_service = MagicMock()
        mock_delete_service.delete_item = AsyncMock(return_value=(True, "已刪除「食べる」🗑️"))
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.repositories.item_repo.ItemRepository", return_value=mock_item_repo),
            patch("src.services.delete_service.DeleteService", return_value=mock_delete_service),
        ):
            result = await _handle_delete_item("Utest", "食べる")
        assert "已刪除" in result

    async def test_three_results_sets_pending_delete(self) -> None:
        """3 筆結果 → 設定 pending_delete + 顯示編號列表。"""
        items = [_mock_item(surface=f"word{i}") for i in range(3)]
        mock_item_repo = MagicMock()
        mock_item_repo.search_by_keyword = AsyncMock(return_value=items)
        mock_user_state = _mock_user_state_repo()
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.repositories.item_repo.ItemRepository", return_value=mock_item_repo),
            patch("src.api.webhook.UserStateRepository", return_value=mock_user_state),
        ):
            result = await _handle_delete_item("Utest", "word")
        assert "3 筆" in result
        assert "1." in result
        mock_user_state.set_pending_delete.assert_awaited_once()

    async def test_six_results_too_many(self) -> None:
        """6 筆結果 → 不設 pending，提示更精確。"""
        items = [_mock_item(surface=f"w{i}") for i in range(6)]
        mock_item_repo = MagicMock()
        mock_item_repo.search_by_keyword = AsyncMock(return_value=items)
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.repositories.item_repo.ItemRepository", return_value=mock_item_repo),
        ):
            result = await _handle_delete_item("Utest", "w")
        assert "6 筆" in result
        assert "更精確" in result


# ============================================================================
# 12. DELETE_ALL_REQUEST（清空資料）— 5 edge cases
# ============================================================================


class TestDeleteAllRequestEdgeCases:
    """_handle_delete_all_request edge cases。"""

    async def test_sets_confirm_and_returns_prompt(self) -> None:
        """設定 confirm flag + 回傳確認提示。"""
        mock_repo = _mock_user_state_repo()
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
        ):
            result = await _handle_delete_all_request("Utest")
        assert result == Messages.DELETE_CONFIRM_PROMPT
        mock_repo.set_delete_confirm_at.assert_awaited_once()

    async def test_hashed_uid_used_for_confirm(self) -> None:
        """set_delete_confirm_at 接收 hashed user ID。"""
        mock_repo = _mock_user_state_repo()
        with (
            patch("src.api.webhook.hash_user_id", return_value="hashed_abc"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
        ):
            await _handle_delete_all_request("Utest")
        mock_repo.set_delete_confirm_at.assert_awaited_once_with("hashed_abc")

    async def test_prompt_contains_confirmation_instruction(self) -> None:
        """確認提示包含「確定清空資料」指示。"""
        mock_repo = _mock_user_state_repo()
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
        ):
            result = await _handle_delete_all_request("Utest")
        assert "確定清空資料" in result

    async def test_prompt_mentions_timeout(self) -> None:
        """確認提示包含 60 秒限時。"""
        mock_repo = _mock_user_state_repo()
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
        ):
            result = await _handle_delete_all_request("Utest")
        assert "60 秒" in result

    async def test_prompt_lists_deletion_scope(self) -> None:
        """確認提示列出清除範圍（素材、單字/文法、練習紀錄）。"""
        mock_repo = _mock_user_state_repo()
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
        ):
            result = await _handle_delete_all_request("Utest")
        assert "素材" in result
        assert "單字" in result


# ============================================================================
# 13. DELETE_CONFIRM（確定清空資料）— 5 edge cases
# ============================================================================


class TestDeleteConfirmEdgeCases:
    """_handle_delete_confirm edge cases。"""

    async def test_no_pending_confirmation(self) -> None:
        """無待確認的清空請求 → DELETE_CONFIRM_NOT_PENDING。"""
        mock_repo = _mock_user_state_repo(is_delete_pending=False)
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
        ):
            result = await _handle_delete_confirm("Utest")
        assert result == Messages.DELETE_CONFIRM_NOT_PENDING

    async def test_pending_confirmation_clears_and_deletes(self) -> None:
        """有待確認 → 清除 confirm flag + 刪除所有資料。"""
        mock_repo = _mock_user_state_repo(is_delete_pending=True)
        mock_delete_service = MagicMock()
        mock_delete_service.clear_all_data = AsyncMock(
            return_value=(True, "已清空所有資料 🗑️")
        )
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
            patch("src.services.delete_service.DeleteService", return_value=mock_delete_service),
        ):
            result = await _handle_delete_confirm("Utest")
        assert "已清空" in result
        mock_repo.clear_delete_confirm.assert_awaited_once()

    async def test_clear_all_exception_returns_error(self) -> None:
        """clear_all_data 拋出例外 → ERROR_CLEAR。"""
        mock_repo = _mock_user_state_repo(is_delete_pending=True)
        mock_delete_service = MagicMock()
        mock_delete_service.clear_all_data = AsyncMock(side_effect=Exception("DB error"))
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
            patch("src.services.delete_service.DeleteService", return_value=mock_delete_service),
        ):
            result = await _handle_delete_confirm("Utest")
        assert result == Messages.ERROR_CLEAR

    async def test_clear_confirm_called_before_delete(self) -> None:
        """clear_delete_confirm 在 clear_all_data 之前呼叫。"""
        call_order: list[str] = []

        async def _track_clear_confirm(*a: object) -> None:
            call_order.append("clear_confirm")

        async def _track_clear_all(*a: object) -> tuple[bool, str]:
            call_order.append("clear_all")
            return (True, "ok")

        mock_repo = _mock_user_state_repo(is_delete_pending=True)
        mock_repo.clear_delete_confirm = AsyncMock(side_effect=_track_clear_confirm)
        mock_delete_service = MagicMock()
        mock_delete_service.clear_all_data = AsyncMock(side_effect=_track_clear_all)
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
            patch("src.services.delete_service.DeleteService", return_value=mock_delete_service),
        ):
            await _handle_delete_confirm("Utest")
        assert call_order == ["clear_confirm", "clear_all"]

    async def test_success_returns_service_message(self) -> None:
        """成功清空 → 回傳 delete service 的訊息。"""
        mock_repo = _mock_user_state_repo(is_delete_pending=True)
        mock_delete_service = MagicMock()
        mock_delete_service.clear_all_data = AsyncMock(
            return_value=(True, "已清空所有資料 🗑️\n\n刪除了：\n• 5 筆原始訊息")
        )
        with (
            patch("src.api.webhook.hash_user_id", return_value="h"),
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
            patch("src.services.delete_service.DeleteService", return_value=mock_delete_service),
        ):
            result = await _handle_delete_confirm("Utest")
        assert "5 筆" in result


# ============================================================================
# 14. DELETE_SELECT（pending_delete 選擇）— 5 edge cases
# ============================================================================


class TestDeleteSelectEdgeCases:
    """_handle_delete_select edge cases。"""

    async def test_expired_pending_returns_new_message(self) -> None:
        """pending_delete 為 None（過期）→ DELETE_SELECT_EXPIRED（Issue #3 修復驗證）。"""
        mock_repo = _mock_user_state_repo(pending_delete=None)
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
        ):
            result = await _handle_delete_select("h", 1)
        assert "刪除選項已過期" in result
        assert "入庫" not in result  # 不應包含入庫相關提示

    async def test_number_zero_returns_invalid(self) -> None:
        """編號 0 → INVALID_NUMBER。"""
        candidates = [{"item_id": "id1", "label": "食べる"}]
        mock_repo = _mock_user_state_repo(pending_delete=candidates)
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
        ):
            result = await _handle_delete_select("h", 0)
        assert "有效的編號" in result

    async def test_number_exceeds_max_returns_invalid(self) -> None:
        """編號超過最大值 → INVALID_NUMBER。"""
        candidates = [
            {"item_id": "id1", "label": "word1"},
            {"item_id": "id2", "label": "word2"},
        ]
        mock_repo = _mock_user_state_repo(pending_delete=candidates)
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
        ):
            result = await _handle_delete_select("h", 5)
        assert "1-2" in result

    async def test_valid_number_deletes_selected(self) -> None:
        """有效編號 → 刪除對應項目。"""
        candidates = [
            {"item_id": "id1", "label": "word1"},
            {"item_id": "id2", "label": "word2"},
        ]
        mock_repo = _mock_user_state_repo(pending_delete=candidates)
        mock_delete_service = MagicMock()
        mock_delete_service.delete_item = AsyncMock(return_value=(True, "已刪除「word2」🗑️"))
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
            patch("src.services.delete_service.DeleteService", return_value=mock_delete_service),
        ):
            result = await _handle_delete_select("h", 2)
        mock_delete_service.delete_item.assert_awaited_once_with("h", "id2")
        assert "已刪除" in result

    async def test_after_delete_clears_pending(self) -> None:
        """刪除成功後 clear_pending_delete 應被呼叫。"""
        candidates = [{"item_id": "id1", "label": "w"}]
        mock_repo = _mock_user_state_repo(pending_delete=candidates)
        mock_delete_service = MagicMock()
        mock_delete_service.delete_item = AsyncMock(return_value=(True, "ok"))
        with (
            patch("src.api.webhook.get_session", return_value=_mock_session_ctx()),
            patch("src.api.webhook.UserStateRepository", return_value=mock_repo),
            patch("src.services.delete_service.DeleteService", return_value=mock_delete_service),
        ):
            await _handle_delete_select("h", 1)
        mock_repo.clear_pending_delete.assert_awaited_once()


# ============================================================================
# 15. UNKNOWN / Router fallback — 5 edge cases
# ============================================================================


class TestUnknownRouterEdgeCases:
    """_handle_unknown edge cases（含 Issue #4 修復驗證）。"""

    async def test_near_command_returns_suggestion(self) -> None:
        """近似指令「入庫了」→ COMMAND_SUGGESTION。"""
        result = await _handle_unknown("Utest", "入庫了", mode="free", target_lang="ja")
        assert "入庫" in result
        assert "可能想輸入" in result

    async def test_pure_emoji_returns_no_meaningful_content(self) -> None:
        """純 emoji → INPUT_NO_MEANINGFUL_CONTENT。"""
        result = await _handle_unknown("Utest", "🎉🎉🎉", mode="free", target_lang="ja")
        assert "純符號" in result or "文字內容" in result

    async def test_korean_with_tab_rejected_before_tsv(self) -> None:
        """韓文 + Tab（Issue #4 修復驗證）→ INPUT_UNSUPPORTED_LANG，不自動入庫。"""
        result = await _handle_unknown("Utest", "한국어\t의미", mode="free", target_lang="ja")
        assert "目前支援日文和英文" in result

    async def test_korean_long_text_rejected_before_auto_save(self) -> None:
        """韓文長文本 >2000（Issue #4 修復驗證）→ INPUT_UNSUPPORTED_LANG，不自動入庫。"""
        result = await _handle_unknown("Utest", "한" * 3000, mode="free", target_lang="ja")
        assert "目前支援日文和英文" in result

    async def test_supported_long_text_auto_saves(self) -> None:
        """支援語言的長文本 >2000 → 自動入庫 + 自動抽取。"""
        with patch("src.api.webhook._save_and_extract", new_callable=AsyncMock, return_value="已入庫：aaa...") as mock_save:
            result = await _handle_unknown("Utest", "a" * 3000, mode="free", target_lang="ja")
        mock_save.assert_awaited_once()


# ============================================================================
# 16. HELP（說明）via _dispatch_command — 5 edge cases
# ============================================================================


class TestHelpEdgeCases:
    """_dispatch_command HELP edge cases。"""

    async def test_shows_free_mode(self) -> None:
        """mode=free → 顯示「免費」。"""
        cmd = ParsedCommand(command_type=CommandType.HELP, raw_text="說明")
        result = await _dispatch_command(cmd, "Utest", "說明", mode="free", target_lang="ja")
        assert "免費" in result

    async def test_shows_rigorous_mode(self) -> None:
        """mode=rigorous → 顯示「嚴謹」。"""
        cmd = ParsedCommand(command_type=CommandType.HELP, raw_text="說明")
        result = await _dispatch_command(cmd, "Utest", "說明", mode="rigorous", target_lang="ja")
        assert "嚴謹" in result

    async def test_shows_english_lang(self) -> None:
        """target_lang=en → 顯示「英文」。"""
        cmd = ParsedCommand(command_type=CommandType.HELP, raw_text="說明")
        result = await _dispatch_command(cmd, "Utest", "說明", mode="free", target_lang="en")
        assert "英文" in result

    async def test_shows_japanese_lang(self) -> None:
        """target_lang=ja → 顯示「日文」。"""
        cmd = ParsedCommand(command_type=CommandType.HELP, raw_text="說明")
        result = await _dispatch_command(cmd, "Utest", "說明", mode="free", target_lang="ja")
        assert "日文" in result

    async def test_contains_key_commands(self) -> None:
        """HELP 訊息包含所有重要指令說明。"""
        cmd = ParsedCommand(command_type=CommandType.HELP, raw_text="說明")
        result = await _dispatch_command(cmd, "Utest", "說明", mode="free", target_lang="ja")
        assert "入庫" in result
        assert "練習" in result
        assert "查詢" in result
        assert "刪除" in result
        assert "save" in result


# ============================================================================
# 17. PRIVACY（隱私）via _dispatch_command — 5 edge cases
# ============================================================================


class TestPrivacyEdgeCases:
    """_dispatch_command PRIVACY edge cases。"""

    async def test_returns_privacy_message(self) -> None:
        """回傳 PRIVACY 靜態訊息。"""
        cmd = ParsedCommand(command_type=CommandType.PRIVACY, raw_text="隱私")
        result = await _dispatch_command(cmd, "Utest", "隱私")
        assert result == Messages.PRIVACY

    async def test_contains_hashing_info(self) -> None:
        """包含使用者 ID 雜湊說明。"""
        cmd = ParsedCommand(command_type=CommandType.PRIVACY, raw_text="隱私")
        result = await _dispatch_command(cmd, "Utest", "隱私")
        assert "雜湊" in result

    async def test_contains_deletion_instructions(self) -> None:
        """包含刪除資料的指示。"""
        cmd = ParsedCommand(command_type=CommandType.PRIVACY, raw_text="隱私")
        result = await _dispatch_command(cmd, "Utest", "隱私")
        assert "刪除" in result
        assert "清空資料" in result

    async def test_length_within_line_limit(self) -> None:
        """訊息長度 < 5000（LINE 限制）。"""
        cmd = ParsedCommand(command_type=CommandType.PRIVACY, raw_text="隱私")
        result = await _dispatch_command(cmd, "Utest", "隱私")
        assert len(result) < 5000

    async def test_contains_ai_section(self) -> None:
        """包含 AI 使用說明區段。"""
        cmd = ParsedCommand(command_type=CommandType.PRIVACY, raw_text="隱私")
        result = await _dispatch_command(cmd, "Utest", "隱私")
        assert "AI" in result
        assert "分析" in result or "生成" in result
