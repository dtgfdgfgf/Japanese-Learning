"""
Unit tests for RouterService.

T087: Write unit tests for RouterService in tests/unit/test_router_service.py
DoD: Mock LLM 回應；驗證各 intent 分類；測試 fallback 觸發
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.schemas.router import IntentType
from src.services.router_service import RouterService


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "router"


@pytest.fixture
def router_fixtures() -> dict:
    """Load router test fixtures."""
    with open(FIXTURES_DIR / "test_cases.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def router_service():
    """Create RouterService with mocked LLM client."""
    service = RouterService()
    service.llm_client = MagicMock()
    return service


def _create_llm_response_mock(content: str):
    """建立模擬 LLMResponse 的 mock 對象。"""
    mock_response = MagicMock()
    mock_response.content = content
    return mock_response


class TestRouterService:
    """Tests for RouterService."""
    
    @pytest.mark.asyncio
    async def test_classify_save_intent(self, router_service):
        """Test classification of save intent."""
        mock_content = json.dumps({
            "intent": "save",
            "confidence": 0.85,
            "reason": "Contains Japanese learning content"
        })
        
        router_service.llm_client.complete_with_mode = AsyncMock(
            return_value=_create_llm_response_mock(mock_content)
        )
        
        result = await router_service.classify("今日は天気がいいですね。")
        
        assert result.intent == IntentType.SAVE
        assert result.confidence >= 0.8
    
    @pytest.mark.asyncio
    async def test_classify_practice_intent(self, router_service):
        """Test classification of practice intent."""
        mock_content = json.dumps({
            "intent": "practice",
            "confidence": 0.9,
            "reason": "User wants to practice"
        })
        
        router_service.llm_client.complete_with_mode = AsyncMock(
            return_value=_create_llm_response_mock(mock_content)
        )
        
        result = await router_service.classify("我要練習")
        
        assert result.intent == IntentType.PRACTICE
        assert result.confidence >= 0.7
    
    @pytest.mark.asyncio
    async def test_classify_search_with_keyword(self, router_service):
        """Test classification of search intent with keyword extraction."""
        mock_content = json.dumps({
            "intent": "search",
            "confidence": 0.8,
            "keyword": "考える",
            "reason": "User searching for a word"
        })
        
        router_service.llm_client.complete_with_mode = AsyncMock(
            return_value=_create_llm_response_mock(mock_content)
        )
        
        result = await router_service.classify("找一下「考える」")
        
        assert result.intent == IntentType.SEARCH
        assert result.keyword == "考える"
    
    @pytest.mark.asyncio
    async def test_classify_chat_intent(self, router_service):
        """Test classification of chat intent."""
        mock_content = json.dumps({
            "intent": "chat",
            "confidence": 0.7,
            "reason": "User asking a learning question"
        })
        
        router_service.llm_client.complete_with_mode = AsyncMock(
            return_value=_create_llm_response_mock(mock_content)
        )
        
        result = await router_service.classify("這個文法怎麼用？")
        
        assert result.intent == IntentType.CHAT
    
    @pytest.mark.asyncio
    async def test_low_confidence_triggers_fallback(self, router_service):
        """Test that low confidence triggers fallback."""
        mock_content = json.dumps({
            "intent": "unknown",
            "confidence": 0.3,
            "reason": "Cannot determine intent"
        })
        
        router_service.llm_client.complete_with_mode = AsyncMock(
            return_value=_create_llm_response_mock(mock_content)
        )
        
        result = await router_service.classify("ok")
        
        assert result.needs_fallback is True
    
    @pytest.mark.asyncio
    async def test_llm_error_falls_back_to_heuristic(self, router_service):
        """Test that LLM errors fall back to heuristic classification."""
        router_service.llm_client.complete_with_mode = AsyncMock(
            side_effect=Exception("LLM Error")
        )

        result = await router_service.classify("test message")

        # heuristic 對短文本回傳 UNKNOWN，但 confidence > 0（非硬 0.0）
        assert result.intent == IntentType.UNKNOWN
        assert result.confidence > 0.0
    
    @pytest.mark.asyncio
    async def test_invalid_json_uses_heuristic(self, router_service):
        """Test that invalid JSON response uses heuristic fallback."""
        router_service.llm_client.complete_with_mode = AsyncMock(
            return_value=_create_llm_response_mock("This is not JSON")
        )
        
        result = await router_service.classify("今日は天気がいい")
        
        # Heuristic should detect Japanese content
        assert result.intent in [IntentType.SAVE, IntentType.UNKNOWN]


class TestHeuristicClassification:
    """Tests for heuristic classification fallback."""
    
    def test_japanese_content_detected_as_save(self):
        """Test that Japanese-heavy content is classified as save."""
        service = RouterService()
        
        result = service._heuristic_classify(
            "今日は天気がいいですね。散歩に行きましょう。"
        )
        
        assert result.intent == IntentType.SAVE
    
    def test_question_detected_as_chat(self):
        """Test that questions are classified as chat."""
        service = RouterService()
        
        result = service._heuristic_classify("這是什麼意思？")
        
        assert result.intent == IntentType.CHAT
    
    def test_short_message_low_confidence(self):
        """Test that short messages have low confidence."""
        service = RouterService()

        result = service._heuristic_classify("ok")

        assert result.confidence < 0.5

    def test_english_content_detected_as_save_in_en_mode(self):
        """英文模式下，長英文內容應判為 save。"""
        service = RouterService()

        result = service._heuristic_classify(
            "The committee has decided to postpone the meeting until further notice.",
            target_lang="en",
        )

        assert result.intent == IntentType.SAVE

    def test_english_content_not_save_in_ja_mode(self):
        """日文模式下，英文內容不應判為 save。"""
        service = RouterService()

        result = service._heuristic_classify(
            "The committee has decided to postpone the meeting.",
            target_lang="ja",
        )

        assert result.intent != IntentType.SAVE

    def test_english_word_save_in_ja_mode(self):
        """日文模式下，英文短單字應透過跨語言規則判為 SAVE（Case 4 修復）。"""
        service = RouterService()

        result = service._heuristic_classify("sunshine", target_lang="ja")

        assert result.intent == IntentType.SAVE
        assert result.confidence >= 0.8

    def test_english_word_save_in_ja_mode_3chars(self):
        """日文模式下，3字元英文單字應判為 SAVE。"""
        service = RouterService()

        result = service._heuristic_classify("cat", target_lang="ja")

        assert result.intent == IntentType.SAVE

    def test_english_sentence_not_save_in_ja_mode_crosslang(self):
        """日文模式下，含空格的英文句子不應被跨語言短單字規則匹配。"""
        service = RouterService()

        result = service._heuristic_classify(
            "I love sushi",
            target_lang="ja",
        )

        # 含空格 → 不匹配跨語言短單字規則 → 不會是 SAVE
        assert result.intent != IntentType.SAVE

    def test_japanese_word_save_in_en_mode(self):
        """英文模式下，日文短詞應透過跨語言規則判為 SAVE。"""
        service = RouterService()

        result = service._heuristic_classify("食べる", target_lang="en")

        assert result.intent == IntentType.SAVE
        assert result.confidence >= 0.8

    def test_english_question_not_save_in_ja_mode(self):
        """日文模式下，英文問句不應判為 SAVE。"""
        service = RouterService()

        result = service._heuristic_classify("What does this mean?", target_lang="ja")

        assert result.intent != IntentType.SAVE

    def test_single_char_english_word_in_en_mode(self):
        """英文模式下，單字元「I」應判為 SAVE（Case 10 修復）。"""
        service = RouterService()

        result = service._heuristic_classify("I", target_lang="en")

        assert result.intent == IntentType.SAVE
        assert result.confidence >= 0.8

    def test_single_char_english_a_in_en_mode(self):
        """英文模式下，單字元「a」應判為 SAVE。"""
        service = RouterService()

        result = service._heuristic_classify("a", target_lang="en")

        assert result.intent == IntentType.SAVE

    def test_single_kanji_in_ja_mode(self):
        """日文模式下，單一漢字應判為 SAVE。"""
        service = RouterService()

        result = service._heuristic_classify("雨", target_lang="ja")

        assert result.intent == IntentType.SAVE

    def test_router_prompt_uses_target_lang(self):
        """Router system prompt 依語言切換。"""
        from src.prompts.router import get_system_prompt

        ja_prompt = get_system_prompt(lang="ja")
        en_prompt = get_system_prompt(lang="en")

        assert "日文" in ja_prompt
        assert "英文" in en_prompt

    def test_mixed_language_boundary(self):
        """Edge Case 22: 日英混合句 japanese_ratio=0.5 應判為 SAVE（>= 閾值）。"""
        service = RouterService()

        result = service._heuristic_classify("appleは美味しい", target_lang="ja")

        assert result.intent == IntentType.SAVE
        assert result.confidence >= 0.7


class TestJsonExtraction:
    """Tests for JSON extraction from LLM responses."""
    
    def test_extract_json_block(self):
        """Test extraction of JSON from code block."""
        service = RouterService()
        
        response = '''Here's my analysis:
```json
{"intent": "save", "confidence": 0.8}
```
'''
        
        json_str = service._extract_json(response)
        data = json.loads(json_str)
        
        assert data["intent"] == "save"
    
    def test_extract_raw_json(self):
        """Test extraction of raw JSON."""
        service = RouterService()
        
        response = 'The intent is {"intent": "practice", "confidence": 0.9}'
        
        json_str = service._extract_json(response)
        data = json.loads(json_str)
        
        assert data["intent"] == "practice"
    
    def test_extract_json_no_block(self):
        """Test error when no JSON found."""
        service = RouterService()
        
        with pytest.raises(ValueError):
            service._extract_json("No JSON here")


class TestChatResponse:
    """Tests for chat response generation."""
    
    @pytest.mark.asyncio
    async def test_chat_response_generated(self):
        """Test that chat responses are generated."""
        service = RouterService()
        service.llm_client = MagicMock()
        service.llm_client.complete_with_mode = AsyncMock(
            return_value=_create_llm_response_mock("這個文法表示完成或遺憾的語氣。")
        )
        
        response = await service.get_chat_response("這個文法怎麼用？")
        
        assert response
        assert len(response) > 0
    
    @pytest.mark.asyncio
    async def test_chat_response_error_handling(self):
        """Test chat response error handling."""
        service = RouterService()
        service.llm_client = MagicMock()
        service.llm_client.complete_with_mode = AsyncMock(side_effect=Exception("Error"))

        response = await service.get_chat_response("test")

        assert "抱歉" in response or "無法" in response


class TestWordExplanation:
    """Tests for word explanation generation."""

    @pytest.mark.asyncio
    async def test_japanese_word_explanation(self):
        """日文單字解釋正常回傳。"""
        service = RouterService()
        service.llm_client = MagicMock()
        service.llm_client.complete_with_mode = AsyncMock(
            return_value=_create_llm_response_mock(
                "【たべる】\n吃的意思。例：ご飯を食べる（吃飯）"
            )
        )

        response = await service.get_word_explanation("食べる", target_lang="ja")

        assert response
        assert len(response) > 0
        # 確認 LLM 被呼叫且有設定 max_tokens
        call_kwargs = service.llm_client.complete_with_mode.call_args.kwargs
        assert call_kwargs.get("max_tokens") == 300

    @pytest.mark.asyncio
    async def test_english_word_explanation(self):
        """英文單字解釋正常回傳。"""
        service = RouterService()
        service.llm_client = MagicMock()
        service.llm_client.complete_with_mode = AsyncMock(
            return_value=_create_llm_response_mock(
                "/træn'sɛndənt/\n超越的、卓越的。常用於形容超凡脫俗的事物。"
            )
        )

        response = await service.get_word_explanation("transcendent", target_lang="en")

        assert response
        assert len(response) > 0

    @pytest.mark.asyncio
    async def test_word_explanation_error_fallback(self):
        """LLM 錯誤時回傳 fallback 訊息。"""
        service = RouterService()
        service.llm_client = MagicMock()
        service.llm_client.complete_with_mode = AsyncMock(
            side_effect=Exception("LLM Error")
        )

        response = await service.get_word_explanation("test")

        # 應回傳包含原單字的 fallback
        assert "test" in response

    @pytest.mark.asyncio
    async def test_word_explanation_uses_correct_mode(self):
        """確認使用指定的 mode 呼叫 LLM。"""
        service = RouterService()
        service.llm_client = MagicMock()
        service.llm_client.complete_with_mode = AsyncMock(
            return_value=_create_llm_response_mock("解釋內容")
        )

        await service.get_word_explanation("word", mode="rigorous", target_lang="ja")

        call_kwargs = service.llm_client.complete_with_mode.call_args.kwargs
        assert call_kwargs.get("mode") == "rigorous"
