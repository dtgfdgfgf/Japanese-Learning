"""
Unit tests for PracticeService.

T053: Write unit tests for item selection
DoD: 驗證優先順序邏輯；mock 時間測試 24h/7d 條件
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
import pytest_asyncio

from src.schemas.practice import (
    PracticeAnswer,
    PracticeQuestion,
    PracticeSession,
    PracticeType,
)
from src.schemas.extractor import ExtractionSummary


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "practice"


@pytest.fixture
def practice_fixtures() -> dict:
    """Load practice test fixtures."""
    with open(FIXTURES_DIR / "test_items.json", "r", encoding="utf-8") as f:
        return json.load(f)


class TestPracticeQuestion:
    """Tests for PracticeQuestion schema."""
    
    def test_vocab_recall_format(self):
        """Test vocab recall question formatting."""
        q = PracticeQuestion(
            question_id="q1",
            item_id="item1",
            practice_type=PracticeType.VOCAB_RECALL,
            prompt="思考",
            expected_answer="考える",
            item_key="vocab:考える",
        )
        
        formatted = q.format_for_display(1)
        
        assert "1." in formatted
        assert "思考" in formatted
        assert "日文" in formatted
    
    def test_grammar_cloze_format(self):
        """Test grammar cloze question formatting."""
        q = PracticeQuestion(
            question_id="q1",
            item_id="item1",
            practice_type=PracticeType.GRAMMAR_CLOZE,
            prompt="新しいレストランに行って____\n（提示：嘗試做某事）",
            expected_answer="みる",
            item_key="grammar:〜てみる",
        )
        
        formatted = q.format_for_display(2)
        
        assert "2." in formatted
        assert "____" in formatted or "提示" in formatted


class TestPracticeSession:
    """Tests for PracticeSession schema."""
    
    def test_total_questions(self):
        """Test total_questions property."""
        session = PracticeSession(
            session_id="s1",
            user_id="user1",
            questions=[
                PracticeQuestion(
                    question_id="q1",
                    item_id="i1",
                    practice_type=PracticeType.VOCAB_RECALL,
                    prompt="test",
                    expected_answer="answer",
                    item_key="vocab:test",
                )
                for _ in range(5)
            ],
        )
        
        assert session.total_questions == 5
    
    def test_current_question(self):
        """Test current_question property."""
        questions = [
            PracticeQuestion(
                question_id=f"q{i}",
                item_id=f"i{i}",
                practice_type=PracticeType.VOCAB_RECALL,
                prompt=f"prompt{i}",
                expected_answer=f"answer{i}",
                item_key=f"vocab:test{i}",
            )
            for i in range(3)
        ]
        
        session = PracticeSession(
            session_id="s1",
            user_id="user1",
            questions=questions,
            current_index=0,
        )
        
        assert session.current_question.question_id == "q0"
        
        session.current_index = 1
        assert session.current_question.question_id == "q1"
        
        session.current_index = 3
        assert session.current_question is None
    
    def test_correct_count(self):
        """Test correct_count property."""
        session = PracticeSession(
            session_id="s1",
            user_id="user1",
            questions=[],
            answers=[
                {"is_correct": True},
                {"is_correct": False},
                {"is_correct": True},
                {"is_correct": True},
            ],
        )
        
        assert session.correct_count == 3
    
    def test_format_questions_message(self):
        """Test formatting questions as message."""
        questions = [
            PracticeQuestion(
                question_id="q1",
                item_id="i1",
                practice_type=PracticeType.VOCAB_RECALL,
                prompt="思考",
                expected_answer="考える",
                item_key="vocab:考える",
            ),
            PracticeQuestion(
                question_id="q2",
                item_id="i2",
                practice_type=PracticeType.VOCAB_RECALL,
                prompt="吃",
                expected_answer="食べる",
                item_key="vocab:食べる",
            ),
        ]
        
        session = PracticeSession(
            session_id="s1",
            user_id="user1",
            questions=questions,
        )
        
        message = session.format_questions_message()
        
        assert "練習" in message
        assert "1." in message
        assert "2." in message
    
    def test_format_result_message_perfect(self):
        """Test result message for perfect score."""
        questions = [
            PracticeQuestion(
                question_id=f"q{i}",
                item_id=f"item{i}",
                practice_type=PracticeType.VOCAB_RECALL,
                prompt=f"meaning{i}",
                expected_answer=f"answer{i}",
                item_key=f"key{i}",
            )
            for i in range(5)
        ]
        
        session = PracticeSession(
            session_id="s1",
            user_id="user1",
            questions=questions,
            answers=[{"is_correct": True} for _ in range(5)],
        )
        
        message = session.format_result_message()
        
        assert "5/5" in message
        assert "全部" in message or "🎉" in message


class TestPracticeAnswer:
    """Tests for PracticeAnswer schema."""
    
    def test_correct_feedback(self):
        """Test feedback for correct answer."""
        answer = PracticeAnswer(
            question_id="q1",
            user_answer="考える",
            is_correct=True,
            expected_answer="考える",
        )
        
        feedback = answer.format_feedback_message()
        
        assert "✅" in feedback or "正確" in feedback
    
    def test_incorrect_feedback(self):
        """Test feedback for incorrect answer."""
        answer = PracticeAnswer(
            question_id="q1",
            user_answer="wrong",
            is_correct=False,
            expected_answer="考える",
        )
        
        feedback = answer.format_feedback_message()
        
        assert "❌" in feedback or "答案" in feedback
        assert "考える" in feedback


class TestPracticeServiceSelection:
    """Tests for item selection algorithm in PracticeService."""
    
    @pytest.mark.asyncio
    async def test_insufficient_items(self, async_db_session):
        """Test behavior when user has fewer than 5 items."""
        from src.services.practice_service import PracticeService, MIN_ITEMS_FOR_PRACTICE
        
        with patch.object(PracticeService, "__init__", lambda self, session: None):
            service = PracticeService.__new__(PracticeService)
            service.session = async_db_session
            service.item_repo = MagicMock()
            service.item_repo.count_by_user = AsyncMock(return_value=3)
            service.practice_log_repo = MagicMock()
            
            session, message = await service.create_session("user1")
            
            assert session is None
            assert "不夠" in message or "3" in message
    
    @pytest.mark.asyncio
    async def test_creates_session_with_enough_items(self, async_db_session):
        """Test session creation with sufficient items."""
        from src.services.practice_service import PracticeService
        
        # Create mock items
        mock_items = []
        for i in range(5):
            item = MagicMock()
            item.item_id = str(uuid.uuid4())
            item.item_type = "vocab"
            item.key = f"vocab:word{i}"
            item.payload = {
                "surface": f"word{i}",
                "reading": f"reading{i}",
                "glossary_zh": [f"meaning{i}"],
            }
            mock_items.append(item)
        
        with patch.object(PracticeService, "__init__", lambda self, session: None):
            service = PracticeService.__new__(PracticeService)
            service.session = async_db_session
            service.item_repo = MagicMock()
            service.item_repo.count_by_user = AsyncMock(return_value=10)
            service.item_repo.get_recent_by_user = AsyncMock(return_value=mock_items[:2])
            service.item_repo.get_stale_by_user = AsyncMock(return_value=mock_items[2:4])
            service.item_repo.get_random_by_user = AsyncMock(return_value=[mock_items[4]])
            service.practice_log_repo = MagicMock()
            service.practice_log_repo.get_items_with_high_error_rate = AsyncMock(return_value=[])
            
            session_obj, message = await service.create_session("user1")
            
            assert session_obj is not None
            assert len(session_obj.questions) > 0
            assert "練習" in message


class TestQuestionGeneration:
    """Tests for question generation."""
    
    def test_generate_vocab_question(self):
        """Test generating vocab recall question."""
        from src.services.practice_service import PracticeService
        
        mock_item = MagicMock()
        mock_item.item_id = str(uuid.uuid4())
        mock_item.item_type = "vocab"
        mock_item.key = "vocab:考える"
        mock_item.payload = {
            "surface": "考える",
            "reading": "かんがえる",
            "glossary_zh": ["思考", "考慮"],
        }
        
        with patch.object(PracticeService, "__init__", lambda self, session: None):
            service = PracticeService.__new__(PracticeService)
            
            question = service._generate_question(mock_item)
            
            assert question is not None
            assert question.practice_type == PracticeType.VOCAB_RECALL
            assert question.expected_answer == "考える"
            assert "思考" in question.prompt
    
    def test_generate_grammar_question(self):
        """Test generating grammar cloze question."""
        from src.services.practice_service import PracticeService
        
        mock_item = MagicMock()
        mock_item.item_id = str(uuid.uuid4())
        mock_item.item_type = "grammar"
        mock_item.key = "grammar:〜てみる"
        mock_item.payload = {
            "pattern": "〜てみる",
            "meaning_zh": "嘗試做某事",
            "example": "新しいレストランに行ってみたい",
        }
        
        with patch.object(PracticeService, "__init__", lambda self, session: None):
            service = PracticeService.__new__(PracticeService)
            
            question = service._generate_question(mock_item)
            
            assert question is not None
            assert question.practice_type == PracticeType.GRAMMAR_CLOZE
