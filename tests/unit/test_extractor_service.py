"""
Unit tests for ExtractorService.

T043: Write unit tests for ExtractorService
DoD: Mock LLM 回應；驗證 item 建立邏輯；涵蓋 confidence 邊界
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from src.schemas.extractor import ExtractedItem, ExtractorResponse, ExtractionSummary
from src.services.extractor_service import (
    ExtractorService,
    create_extraction_summary,
    LONG_TEXT_THRESHOLD,
)


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "extractor"


@pytest.fixture
def extractor_fixtures() -> dict:
    """Load extractor test fixtures."""
    with open(FIXTURES_DIR / "test_cases.json", "r", encoding="utf-8") as f:
        return json.load(f)


class TestExtractedItem:
    """Tests for ExtractedItem schema."""
    
    def test_vocab_item_to_payload(self):
        """Test vocab item converts to correct payload."""
        item = ExtractedItem(
            item_type="vocab",
            key="vocab:考える",
            surface="考える",
            reading="かんがえる",
            pos="verb",
            glossary_zh=["思考", "考慮"],
            confidence=1.0,
        )
        payload = item.to_payload()
        
        assert payload["surface"] == "考える"
        assert payload["reading"] == "かんがえる"
        assert payload["pos"] == "verb"
        assert payload["glossary_zh"] == ["思考", "考慮"]
    
    def test_grammar_item_to_payload(self):
        """Test grammar item converts to correct payload."""
        item = ExtractedItem(
            item_type="grammar",
            key="grammar:〜てしまう",
            pattern="〜てしまう",
            meaning_zh="表示遺憾",
            form_notes="Vて + しまう",
            confidence=0.9,
        )
        payload = item.to_payload()
        
        assert payload["pattern"] == "〜てしまう"
        assert payload["meaning_zh"] == "表示遺憾"
        assert payload["form_notes"] == "Vて + しまう"
    
    def test_confidence_validation(self):
        """Test confidence must be between 0 and 1."""
        # Valid confidence
        item = ExtractedItem(
            item_type="vocab",
            key="vocab:test",
            confidence=0.5,
        )
        assert item.confidence == 0.5
        
        # Edge cases
        item_low = ExtractedItem(item_type="vocab", key="vocab:test", confidence=0.0)
        assert item_low.confidence == 0.0
        
        item_high = ExtractedItem(item_type="vocab", key="vocab:test", confidence=1.0)
        assert item_high.confidence == 1.0


class TestExtractorResponse:
    """Tests for ExtractorResponse schema."""
    
    def test_from_items(self):
        """Test creating response from items list."""
        items = [
            ExtractedItem(item_type="vocab", key="vocab:a", confidence=1.0),
            ExtractedItem(item_type="vocab", key="vocab:b", confidence=1.0),
            ExtractedItem(item_type="grammar", key="grammar:c", confidence=1.0),
        ]
        
        response = ExtractorResponse.from_items("doc123", items)
        
        assert response.doc_id == "doc123"
        assert len(response.items) == 3
        assert response.vocab_count == 2
        assert response.grammar_count == 1
    
    def test_empty_response(self):
        """Test response with no items."""
        response = ExtractorResponse.from_items("doc123", [])
        
        assert response.vocab_count == 0
        assert response.grammar_count == 0
        assert len(response.items) == 0


class TestExtractionSummary:
    """Tests for ExtractionSummary."""
    
    def test_to_message_with_items(self):
        """Test message formatting with items."""
        summary = ExtractionSummary(
            vocab_count=3,
            grammar_count=2,
            total_count=5,
        )
        
        message = summary.to_message()
        assert "3 個單字" in message
        assert "2 個文法" in message
    
    def test_to_message_vocab_only(self):
        """Test message with vocab only."""
        summary = ExtractionSummary(
            vocab_count=5,
            grammar_count=0,
            total_count=5,
        )
        
        message = summary.to_message()
        assert "5 個單字" in message
        assert "文法" not in message
    
    def test_to_message_grammar_only(self):
        """Test message with grammar only."""
        summary = ExtractionSummary(
            vocab_count=0,
            grammar_count=3,
            total_count=3,
        )
        
        message = summary.to_message()
        assert "3 個文法" in message
        assert "單字" not in message
    
    def test_to_message_no_items(self):
        """Test message with no items."""
        summary = ExtractionSummary(
            vocab_count=0,
            grammar_count=0,
            total_count=0,
        )
        
        message = summary.to_message()
        assert "沒有發現" in message
    
    def test_to_message_truncated(self):
        """Test message indicates truncation."""
        summary = ExtractionSummary(
            vocab_count=15,
            grammar_count=5,
            total_count=20,
            is_truncated=True,
        )
        
        message = summary.to_message()
        assert "限制" in message or "截斷" in message or "較長" in message


class TestExtractorService:
    """Tests for ExtractorService."""
    
    @pytest.mark.asyncio
    async def test_extract_vocab_only(self, async_db_session, extractor_fixtures):
        """Test extracting vocabulary items."""
        fixture = extractor_fixtures["vocab_only"]
        
        # Mock LLM response
        mock_llm = MagicMock()
        mock_trace = MagicMock()
        mock_trace.to_dict = MagicMock(return_value={})
        mock_llm.complete_json_with_mode = AsyncMock(return_value=(
            {
                "items": [
                    {
                        "item_type": "vocab",
                        "key": "vocab:考える",
                        "surface": "考える",
                        "reading": "かんがえる",
                        "pos": "verb",
                        "glossary_zh": ["思考", "考慮"],
                        "confidence": 1.0,
                    },
                    {
                        "item_type": "vocab",
                        "key": "vocab:食べる",
                        "surface": "食べる",
                        "reading": "たべる",
                        "pos": "verb",
                        "glossary_zh": ["吃"],
                        "confidence": 1.0,
                    },
                ]
            },
            mock_trace,
        ))
        
        # Mock repositories
        with patch.object(ExtractorService, "__init__", lambda self, session, llm_client=None: None):
            service = ExtractorService.__new__(ExtractorService)
            service.session = async_db_session
            service.llm_client = mock_llm
            
            # Mock repository methods
            mock_doc = MagicMock()
            mock_doc.doc_id = "doc123"
            mock_doc.raw_id = "raw123"
            mock_doc.parse_status = "deferred"
            
            mock_raw = MagicMock()
            mock_raw.raw_text = fixture["input"]
            
            service.document_repo = MagicMock()
            service.document_repo.get_by_id = AsyncMock(return_value=mock_doc)
            service.document_repo.update = AsyncMock()
            
            service.raw_message_repo = MagicMock()
            service.raw_message_repo.get_by_id = AsyncMock(return_value=mock_raw)
            
            service.item_repo = MagicMock()
            service.item_repo.upsert = AsyncMock(return_value=MagicMock())

            service.usage_repo = MagicMock()
            service.usage_repo.create_log = AsyncMock()
            
            # Execute
            result = await service.extract("doc123", "user123")
            
            # Verify
            assert result.vocab_count == 2
            assert result.grammar_count == 0
            mock_llm.complete_json_with_mode.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_extract_already_parsed(self, async_db_session):
        """Test extraction skips already parsed documents."""
        with patch.object(ExtractorService, "__init__", lambda self, session, llm_client=None: None):
            service = ExtractorService.__new__(ExtractorService)
            service.session = async_db_session
            
            mock_doc = MagicMock()
            mock_doc.doc_id = "doc123"
            mock_doc.parse_status = "parsed"
            
            service.document_repo = MagicMock()
            service.document_repo.get_by_id = AsyncMock(return_value=mock_doc)
            
            result = await service.extract("doc123", "user123")
            
            assert len(result.items) == 0
            assert "already parsed" in result.warnings[0].lower()


class TestCreateExtractionSummary:
    """Tests for create_extraction_summary helper."""
    
    def test_creates_summary_from_response(self):
        """Test creating summary from ExtractorResponse."""
        response = ExtractorResponse(
            doc_id="doc123",
            items=[],
            vocab_count=5,
            grammar_count=3,
        )
        
        summary = create_extraction_summary(response)
        
        assert summary.vocab_count == 5
        assert summary.grammar_count == 3
        assert summary.total_count == 8
    
    def test_detects_truncation_from_warnings(self):
        """Test truncation detection from warnings."""
        response = ExtractorResponse(
            doc_id="doc123",
            items=[],
            vocab_count=20,
            grammar_count=0,
            warnings=["Long text - extraction limited to 20 items"],
        )
        
        summary = create_extraction_summary(response)
        
        assert summary.is_truncated is True
