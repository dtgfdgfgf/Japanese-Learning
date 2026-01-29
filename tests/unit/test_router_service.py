"""
Unit tests for RouterService.

T087: Write unit tests for RouterService in tests/unit/test_router_service.py
DoD: Mock LLM 回應；驗證各 intent 分類；測試 fallback 觸發
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from src.schemas.router import IntentType, RouterResponse
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
        
        router_service.llm_client.complete = AsyncMock(
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
        
        router_service.llm_client.complete = AsyncMock(
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
        
        router_service.llm_client.complete = AsyncMock(
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
        
        router_service.llm_client.complete = AsyncMock(
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
        
        router_service.llm_client.complete = AsyncMock(
            return_value=_create_llm_response_mock(mock_content)
        )
        
        result = await router_service.classify("ok")
        
        assert result.needs_fallback is True
    
    @pytest.mark.asyncio
    async def test_llm_error_returns_unknown(self, router_service):
        """Test that LLM errors return unknown intent."""
        router_service.llm_client.complete = AsyncMock(
            side_effect=Exception("LLM Error")
        )
        
        result = await router_service.classify("test message")
        
        assert result.intent == IntentType.UNKNOWN
        assert result.confidence == 0.0
    
    @pytest.mark.asyncio
    async def test_invalid_json_uses_heuristic(self, router_service):
        """Test that invalid JSON response uses heuristic fallback."""
        router_service.llm_client.complete = AsyncMock(
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
        service.llm_client.complete = AsyncMock(
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
        service.llm_client.complete = AsyncMock(side_effect=Exception("Error"))
        
        response = await service.get_chat_response("test")
        
        assert "抱歉" in response or "無法" in response
