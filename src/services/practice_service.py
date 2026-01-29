"""
Practice service for generating and managing practice questions.

T046: Implement item selection algorithm
T047: Implement vocab_recall question generator
T048: Implement grammar_cloze question generator
T049: Wire up "練習" command to PracticeService
T050: Handle insufficient items case (< 5 items)
T051: Format LINE reply with practice questions
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.lib.normalizer import is_correct_answer
from src.repositories.item_repo import ItemRepository
from src.repositories.practice_log_repo import PracticeLogRepository
from src.schemas.practice import (
    ItemSelectionCriteria,
    PracticeAnswer,
    PracticeQuestion,
    PracticeSession,
    PracticeType,
)
from src.services.session_service import (
    SessionService,
    clear_session,
    get_active_session,
)
from src.templates.messages import (
    Messages,
    format_practice_answer_wrong,
    format_practice_insufficient,
    format_practice_result,
)

logger = logging.getLogger(__name__)

# Constants
DEFAULT_QUESTION_COUNT = 5
MIN_ITEMS_FOR_PRACTICE = 5


class PracticeService:
    """Service for managing practice sessions and questions."""

    def __init__(self, session: AsyncSession, mode: str = "balanced"):
        """
        Initialize PracticeService.

        Args:
            session: Database session
            mode: LLM mode（預留供未來 LLM 題目生成使用）
        """
        self.session = session
        self.mode = mode
        self.item_repo = ItemRepository(session)
        self.practice_log_repo = PracticeLogRepository(session)

    async def create_session(
        self,
        user_id: str,
        question_count: int = DEFAULT_QUESTION_COUNT,
    ) -> tuple[PracticeSession | None, str]:
        """
        Create a new practice session for a user.
        
        Args:
            user_id: User ID (hashed)
            question_count: Number of questions to generate
            
        Returns:
            Tuple of (session, message) where session may be None if insufficient items
        """
        # Get item count
        total_items = await self.item_repo.count_by_user(user_id)

        if total_items < MIN_ITEMS_FOR_PRACTICE:
            return None, format_practice_insufficient(
                current=total_items,
                required=MIN_ITEMS_FOR_PRACTICE,
            )

        # Select items for practice
        items = await self._select_items_for_practice(user_id, question_count)

        if len(items) < question_count:
            logger.warning(f"Only got {len(items)} items for user {user_id[:8]}")

        # Generate questions
        questions = []
        for item in items:
            question = self._generate_question(item)
            if question:
                questions.append(question)

        if not questions:
            return None, Messages.PRACTICE_GENERATE_FAILED

        # Create session
        session_id = str(uuid.uuid4())
        practice_session = PracticeSession(
            session_id=session_id,
            user_id=user_id,
            questions=questions,
        )

        # Store session (使用 SessionService 統一管理)
        SessionService.set_session(user_id, practice_session)

        return practice_session, practice_session.format_questions_message()

    async def _select_items_for_practice(
        self,
        user_id: str,
        count: int,
        criteria: ItemSelectionCriteria | None = None,
    ) -> list:
        """
        Select items for practice based on priority algorithm.
        
        Priority order:
        1. Items added within 24 hours (new learning)
        2. Items with high error rate (>30%) in last 7 days
        3. Items not practiced in 7+ days (stale)
        4. Random selection from remaining
        
        Args:
            user_id: User ID (hashed)
            count: Number of items to select
            criteria: Optional selection criteria
            
        Returns:
            List of selected items
        """
        criteria = criteria or ItemSelectionCriteria()
        selected = []
        selected_ids = set()

        # 1. Recent items (last 24 hours)
        recent_cutoff = datetime.now(UTC) - timedelta(hours=criteria.recent_hours)
        recent_items = await self.item_repo.get_recent_by_user(
            user_id,
            since=recent_cutoff,
            limit=count
        )
        for item in recent_items:
            if len(selected) >= count:
                break
            if item.item_id not in selected_ids:
                selected.append(item)
                selected_ids.add(item.item_id)

        if len(selected) >= count:
            return selected

        # 2. High error rate items
        error_items = await self._get_high_error_items(
            user_id,
            count - len(selected),
            criteria.error_rate_days,
            criteria.min_error_rate,
        )
        for item in error_items:
            if len(selected) >= count:
                break
            if item.item_id not in selected_ids:
                selected.append(item)
                selected_ids.add(item.item_id)

        if len(selected) >= count:
            return selected

        # 3. Stale items (not practiced recently)
        stale_items = await self._get_stale_items(
            user_id,
            count - len(selected),
            criteria.stale_days,
        )
        for item in stale_items:
            if len(selected) >= count:
                break
            if item.item_id not in selected_ids:
                selected.append(item)
                selected_ids.add(item.item_id)

        if len(selected) >= count:
            return selected

        # 4. Random from remaining
        remaining = count - len(selected)
        if remaining > 0:
            random_items = await self.item_repo.get_random_by_user(
                user_id,
                limit=remaining,
                exclude_ids=list(selected_ids),
            )
            selected.extend(random_items)

        return selected

    async def _get_high_error_items(
        self,
        user_id: str,
        limit: int,
        days: int,
        min_rate: float,
    ) -> list:
        """Get items with high error rate."""
        # Get items with error stats
        items_with_errors = await self.practice_log_repo.get_items_with_high_error_rate(
            user_id=user_id,
            days=days,
            min_error_rate=min_rate,
            limit=limit,
        )

        # Fetch full item records
        items = []
        for item_id in items_with_errors:
            item = await self.item_repo.get_by_id(item_id)
            if item:
                items.append(item)

        return items

    async def _get_stale_items(
        self,
        user_id: str,
        limit: int,
        days: int,
    ) -> list:
        """Get items not practiced recently."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        return await self.item_repo.get_stale_by_user(
            user_id,
            not_practiced_since=cutoff,
            limit=limit,
        )

    def _generate_question(self, item) -> PracticeQuestion | None:
        """
        Generate a practice question for an item.
        
        Args:
            item: Item model instance
            
        Returns:
            PracticeQuestion or None if generation fails
        """
        question_id = str(uuid.uuid4())
        item_type = item.item_type
        payload = item.payload or {}

        if item_type == "vocab":
            return self._generate_vocab_question(question_id, item, payload)
        elif item_type == "grammar":
            return self._generate_grammar_question(question_id, item, payload)
        else:
            logger.warning(f"Unknown item type: {item_type}")
            return None

    def _generate_vocab_question(
        self,
        question_id: str,
        item,
        payload: dict,
    ) -> PracticeQuestion | None:
        """
        Generate vocabulary recall question.
        
        Format: 「{meaning}」的日文是？
        """
        surface = payload.get("surface", "")
        glossary = payload.get("glossary_zh", [])
        reading = payload.get("reading", "")

        if not surface or not glossary:
            return None

        # Use first meaning for prompt
        meaning = glossary[0] if isinstance(glossary, list) else str(glossary)

        # Expected answer is surface form (or reading)
        expected = surface

        hints = []
        if reading and reading != surface:
            hints.append(f"讀音：{reading}")

        return PracticeQuestion(
            question_id=question_id,
            item_id=str(item.item_id),
            practice_type=PracticeType.VOCAB_RECALL,
            prompt=meaning,
            expected_answer=expected,
            hints=hints,
            item_key=item.key,
        )

    def _generate_grammar_question(
        self,
        question_id: str,
        item,
        payload: dict,
    ) -> PracticeQuestion | None:
        """
        Generate grammar cloze question.
        
        Format: Fill in the blank with grammar pattern
        """
        pattern = payload.get("pattern", "")
        meaning = payload.get("meaning_zh", "")
        example = payload.get("example", "")

        if not pattern or not meaning:
            return None

        # Create cloze question
        if example and pattern in example:
            # Create cloze by blanking out the pattern
            cloze = example.replace(pattern, "____")
            prompt = f"{cloze}\n（提示：{meaning}）"
            expected = pattern
        else:
            # Fall back to direct question
            prompt = f"表示「{meaning}」的文法是？"
            expected = pattern

        return PracticeQuestion(
            question_id=question_id,
            item_id=str(item.item_id),
            practice_type=PracticeType.GRAMMAR_CLOZE,
            prompt=prompt,
            expected_answer=expected,
            item_key=item.key,
        )

    async def submit_answer(
        self,
        user_id: str,
        answer_text: str,
    ) -> tuple[PracticeAnswer | None, str]:
        """
        Submit an answer for the current practice question.
        
        Args:
            user_id: User ID (hashed)
            answer_text: User's answer
            
        Returns:
            Tuple of (answer, message) where answer may be None if no active session
        """
        session = get_active_session(user_id)

        if not session:
            return None, Messages.PRACTICE_NO_ACTIVE_SESSION

        current_question = session.current_question
        if not current_question:
            # Session complete
            session.is_complete = True
            return None, session.format_result_message()

        # Grade answer
        is_correct = is_correct_answer(
            answer_text,
            current_question.expected_answer
        )

        # Create answer record
        practice_answer = PracticeAnswer(
            question_id=current_question.question_id,
            user_answer=answer_text,
            is_correct=is_correct,
            expected_answer=current_question.expected_answer,
        )

        # Record to session
        session.answers.append({
            "question_id": current_question.question_id,
            "item_id": current_question.item_id,
            "user_answer": answer_text,
            "is_correct": is_correct,
        })

        # Record to database
        await self.practice_log_repo.create(
            user_id=user_id,
            item_id=current_question.item_id,
            practice_type=current_question.practice_type.value,
            prompt_snapshot=current_question.prompt,
            user_answer=answer_text,
            is_correct=is_correct,
        )

        # Move to next question
        session.current_index += 1

        # Build response message
        feedback = practice_answer.format_feedback_message()

        if session.current_index >= session.total_questions:
            session.is_complete = True
            feedback += "\n\n" + session.format_result_message()
            clear_session(user_id)
        else:
            next_q = session.current_question
            if next_q:
                feedback += f"\n\n下一題：\n{next_q.format_for_display(session.current_index + 1)}"

        return practice_answer, feedback


# 快速檢查函數（經由 session_service 實作）
def has_active_session(user_id: str) -> bool:
    """檢查用戶是否有進行中的練習 session。"""
    return get_active_session(user_id) is not None
