"""
Pydantic schemas for Practice service.

T045: Create Pydantic schemas for Practice
DoD: PracticeQuestion, PracticeSession schemas 定義完整；支援 vocab_recall/grammar_cloze
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    # 避免循環引用
    pass


def _utc_now() -> datetime:
    """取得當前 UTC 時間（timezone-aware）。"""
    return datetime.now(timezone.utc)


class PracticeType(str, Enum):
    """Types of practice questions."""
    
    VOCAB_RECALL = "vocab_recall"  # Given meaning, recall Japanese
    GRAMMAR_CLOZE = "grammar_cloze"  # Fill in the blank with grammar pattern
    VOCAB_MEANING = "vocab_meaning"  # Given Japanese, recall meaning
    GRAMMAR_USAGE = "grammar_usage"  # Use grammar in context


class PracticeQuestion(BaseModel):
    """Represents a single practice question."""
    
    question_id: str = Field(..., description="Unique ID for this question")
    item_id: str = Field(..., description="Associated item ID")
    practice_type: PracticeType = Field(..., description="Type of practice")
    prompt: str = Field(..., description="Question prompt to show user")
    expected_answer: str = Field(..., description="Expected correct answer")
    hints: list[str] = Field(
        default_factory=list,
        description="Optional hints for the question"
    )
    source_context: Optional[str] = Field(
        None,
        description="Original context where this item appeared"
    )
    item_key: str = Field(..., description="Item key for reference")
    
    def format_for_display(self, index: int) -> str:
        """Format question for LINE message display.
        
        Args:
            index: Question number (1-based)
            
        Returns:
            Formatted string for display
        """
        if self.practice_type == PracticeType.VOCAB_RECALL:
            return f"{index}. 「{self.prompt}」的日文是？"
        elif self.practice_type == PracticeType.GRAMMAR_CLOZE:
            return f"{index}. {self.prompt}"
        elif self.practice_type == PracticeType.VOCAB_MEANING:
            return f"{index}. 「{self.prompt}」是什麼意思？"
        else:
            return f"{index}. {self.prompt}"


class PracticeSession(BaseModel):
    """Represents a practice session with multiple questions."""
    
    session_id: str = Field(..., description="Unique session ID")
    user_id: str = Field(..., description="User ID (hashed)")
    questions: list[PracticeQuestion] = Field(
        default_factory=list,
        description="Questions in this session"
    )
    current_index: int = Field(
        default=0,
        description="Index of current question (0-based)"
    )
    answers: list[dict] = Field(
        default_factory=list,
        description="User's answers with results"
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="When session was created"
    )
    is_complete: bool = Field(default=False, description="Whether all questions answered")
    
    @property
    def total_questions(self) -> int:
        """Get total number of questions."""
        return len(self.questions)
    
    @property
    def current_question(self) -> Optional[PracticeQuestion]:
        """Get current question."""
        if self.current_index < len(self.questions):
            return self.questions[self.current_index]
        return None
    
    @property
    def correct_count(self) -> int:
        """Get number of correct answers."""
        return sum(1 for a in self.answers if a.get("is_correct", False))
    
    @property
    def answered_count(self) -> int:
        """Get number of answered questions."""
        return len(self.answers)
    
    def format_questions_message(self) -> str:
        """Format all questions as LINE message.
        
        Returns:
            Formatted string with all questions
        """
        # 延遲引入以避免循環引用
        from src.templates.messages import Messages
        
        lines = [Messages.PRACTICE_HEADER]
        for i, q in enumerate(self.questions, 1):
            lines.append(q.format_for_display(i))
        lines.append(Messages.PRACTICE_FOOTER)
        return "".join(lines)
    
    def format_result_message(self) -> str:
        """Format practice results as LINE message.
        
        Returns:
            Formatted string with results
        """
        # 延遲引入以避免循環引用
        from src.templates.messages import format_practice_result
        
        return format_practice_result(self.correct_count, self.total_questions)


class PracticeAnswer(BaseModel):
    """Represents a user's answer to a practice question."""
    
    question_id: str = Field(..., description="Question being answered")
    user_answer: str = Field(..., description="User's answer")
    is_correct: bool = Field(..., description="Whether answer is correct")
    expected_answer: str = Field(..., description="Expected answer")
    feedback: Optional[str] = Field(None, description="Feedback message")
    
    def format_feedback_message(self) -> str:
        """Format feedback for LINE message.
        
        Returns:
            Formatted feedback string
        """
        # 延遲引入以避免循環引用
        from src.templates.messages import Messages, format_practice_answer_wrong
        
        if self.is_correct:
            return Messages.PRACTICE_ANSWER_CORRECT
        else:
            return format_practice_answer_wrong(self.expected_answer)


class ItemSelectionCriteria(BaseModel):
    """Criteria for selecting items for practice."""
    
    recent_hours: int = Field(
        default=24,
        description="Include items added within this many hours"
    )
    error_rate_days: int = Field(
        default=7,
        description="Check error rate within this many days"
    )
    min_error_rate: float = Field(
        default=0.3,
        description="Minimum error rate to prioritize"
    )
    stale_days: int = Field(
        default=7,
        description="Consider stale if not practiced within this many days"
    )
