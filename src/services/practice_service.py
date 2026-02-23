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
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.lib.llm_client import get_llm_client
from src.lib.normalizer import is_correct_answer, kanji_to_reading_variants, normalize_for_compare
from src.models.item import Item
from src.prompts.grader import GRADER_SYSTEM_PROMPT, format_grader_request
from src.repositories.item_repo import ItemRepository
from src.repositories.practice_log_repo import PracticeLogRepository
from src.schemas.practice import (
    ItemSelectionCriteria,
    PracticeAnswer,
    PracticeQuestion,
    PracticeSession,
    PracticeType,
)
from src.services.session_service import SessionService
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

    def __init__(self, session: AsyncSession, mode: str = "free", target_lang: str = "ja"):
        """
        Initialize PracticeService.

        Args:
            session: Database session
            mode: LLM mode（預留供未來 LLM 題目生成使用）
            target_lang: 目標學習語言 (ja/en)
        """
        self.session = session
        self.mode = mode
        self.target_lang = target_lang
        self.item_repo = ItemRepository(session)
        self.practice_log_repo = PracticeLogRepository(session)
        self.session_service = SessionService(session)
        self.llm_client = get_llm_client()

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
        await self.session_service.set_session(user_id, practice_session)

        return practice_session, practice_session.format_questions_message()

    async def _select_items_for_practice(
        self,
        user_id: str,
        count: int,
        criteria: ItemSelectionCriteria | None = None,
    ) -> list[Item]:
        """
        Select items for practice based on priority algorithm.

        Priority order:
        1. Items added within 24 hours (new learning)
        2. Items with high error rate (>30%) in last 7 days
        3. Items not practiced in 7+ days (stale)
        4. Random selection from remaining
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
    ) -> list[Item]:
        """Get items with high error rate."""
        items_with_errors = await self.practice_log_repo.get_items_with_high_error_rate(
            user_id=user_id,
            days=days,
            threshold=min_rate,
            limit=limit,
        )

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
    ) -> list[Item]:
        """Get items not practiced recently."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        return await self.item_repo.get_stale_by_user(
            user_id,
            not_practiced_since=cutoff,
            limit=limit,
        )

    def _generate_question(self, item: Item) -> PracticeQuestion | None:
        """Generate a practice question for an item.

        vocab 隨機選 VOCAB_RECALL 或 VOCAB_MEANING；
        grammar 隨機選 GRAMMAR_CLOZE 或 GRAMMAR_USAGE。
        若選中的 generator 回傳 None 則 fallback 到另一個。
        """
        question_id = str(uuid.uuid4())
        item_type = item.item_type
        payload = item.payload or {}

        if item_type == "vocab":
            generators = [self._generate_vocab_question, self._generate_vocab_meaning_question]
            random.shuffle(generators)
            for gen in generators:
                q = gen(question_id, item, payload)
                if q:
                    return q
            return None
        elif item_type == "grammar":
            generators = [self._generate_grammar_question, self._generate_grammar_usage_question]
            random.shuffle(generators)
            for gen in generators:
                q = gen(question_id, item, payload)
                if q:
                    return q
            return None
        else:
            logger.warning(f"Unknown item type: {item_type}")
            return None

    def _generate_vocab_question(
        self,
        question_id: str,
        item: Item,
        payload: dict[str, Any],
    ) -> PracticeQuestion | None:
        """
        Generate vocabulary recall question.

        Format: 「{meaning}」的日文/英文是？
        """
        surface = payload.get("surface", "")
        glossary = payload.get("glossary_zh", [])
        reading = payload.get("reading", "")
        pronunciation = payload.get("pronunciation", "")

        if not surface or not glossary:
            return None

        meaning = glossary[0] if isinstance(glossary, list) else str(glossary)
        expected = surface

        hints = []
        if self.target_lang == "ja" and reading and reading != surface:
            hints.append(f"讀音：{reading}")
        elif self.target_lang == "en" and pronunciation:
            hints.append(f"發音：{pronunciation}")

        # 建構可接受答案：漢字 + 讀音變體（日文）或僅 surface（英文）
        if self.target_lang == "ja" and reading:
            accepted = kanji_to_reading_variants(surface, reading)
        else:
            accepted = [surface]

        return PracticeQuestion(
            question_id=question_id,
            item_id=str(item.item_id),
            practice_type=PracticeType.VOCAB_RECALL,
            prompt=meaning,
            expected_answer=expected,
            accepted_answers=accepted,
            hints=hints,
            item_key=item.key,
            target_lang=self.target_lang,
        )

    def _generate_grammar_question(
        self,
        question_id: str,
        item: Item,
        payload: dict[str, Any],
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

        if example and pattern in example:
            cloze = example.replace(pattern, "____")
            prompt = f"{cloze}\n（提示：{meaning}）"
            expected = pattern
        else:
            prompt = f"表示「{meaning}」的文法是？"
            expected = pattern

        return PracticeQuestion(
            question_id=question_id,
            item_id=str(item.item_id),
            practice_type=PracticeType.GRAMMAR_CLOZE,
            prompt=prompt,
            expected_answer=expected,
            item_key=item.key,
            target_lang=self.target_lang,
        )

    def _generate_vocab_meaning_question(
        self,
        question_id: str,
        item: Item,
        payload: dict[str, Any],
    ) -> PracticeQuestion | None:
        """生成目標語→中文詞義題。

        日文 Format: 「考える（かんがえる）」是什麼意思？
        英文 Format: 「consider (/kənˈsɪdər/)」是什麼意思？
        """
        surface = payload.get("surface", "")
        reading = payload.get("reading", "")
        pronunciation = payload.get("pronunciation", "")
        glossary = payload.get("glossary_zh", [])

        if not surface or not glossary:
            return None

        meaning = glossary[0] if isinstance(glossary, list) else str(glossary)

        # 提示文字：surface + reading/pronunciation（若有）
        prompt = surface
        if self.target_lang == "ja" and reading and reading != surface:
            prompt = f"{surface}（{reading}）"
        elif self.target_lang == "en" and pronunciation:
            prompt = f"{surface} ({pronunciation})"

        # 建構可接受答案：整個 glossary_zh 陣列
        accepted = list(glossary) if isinstance(glossary, list) else [str(glossary)]

        return PracticeQuestion(
            question_id=question_id,
            item_id=str(item.item_id),
            practice_type=PracticeType.VOCAB_MEANING,
            prompt=prompt,
            expected_answer=meaning,
            accepted_answers=accepted,
            item_key=item.key,
            target_lang=self.target_lang,
        )

    def _generate_grammar_usage_question(
        self,
        question_id: str,
        item: Item,
        payload: dict[str, Any],
    ) -> PracticeQuestion | None:
        """生成文法造句題。

        Format: 請用「〜てみる」（嘗試做某事）造一個句子
        """
        pattern = payload.get("pattern", "")
        meaning = payload.get("meaning_zh", "")

        if not pattern or not meaning:
            return None

        prompt = f"請用「{pattern}」（{meaning}）造一個句子"

        return PracticeQuestion(
            question_id=question_id,
            item_id=str(item.item_id),
            practice_type=PracticeType.GRAMMAR_USAGE,
            prompt=prompt,
            expected_answer=pattern,
            item_key=item.key,
            target_lang=self.target_lang,
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
        practice_session = await self.session_service.get_session(user_id)

        if not practice_session:
            return None, Messages.PRACTICE_NO_ACTIVE_SESSION

        current_question = practice_session.current_question
        if not current_question:
            practice_session.is_complete = True
            await self.session_service.clear_session(user_id)
            return None, practice_session.format_result_message()

        # Grade answer — GRAMMAR_USAGE 使用模糊判定（答案需包含 pattern）
        if current_question.practice_type == PracticeType.GRAMMAR_USAGE:
            is_correct = (
                normalize_for_compare(current_question.expected_answer)
                in normalize_for_compare(answer_text)
            )
        else:
            # Phase 1：嚴格匹配（含 accepted_answers）
            grading_answers = (
                current_question.accepted_answers
                if current_question.accepted_answers
                else [current_question.expected_answer]
            )
            is_correct = is_correct_answer(answer_text, grading_answers)

            # Phase 2：LLM 語義 fallback
            if not is_correct:
                is_correct = await self._llm_grade_answer(
                    user_answer=answer_text,
                    expected_answer=current_question.expected_answer,
                    accepted_answers=grading_answers,
                    question_context=current_question.prompt,
                )

        # Create answer record
        practice_answer = PracticeAnswer(
            question_id=current_question.question_id,
            user_answer=answer_text,
            is_correct=is_correct,
            expected_answer=current_question.expected_answer,
        )

        # Record to session
        practice_session.answers.append({
            "question_id": current_question.question_id,
            "item_id": current_question.item_id,
            "user_answer": answer_text,
            "is_correct": is_correct,
        })

        # Record to database
        await self.practice_log_repo.create_log(
            user_id=user_id,
            item_id=current_question.item_id,
            practice_type=current_question.practice_type.value,
            prompt_snapshot=current_question.prompt,
            user_answer=answer_text,
            is_correct=is_correct,
        )

        # Move to next question
        practice_session.current_index += 1

        # Build response message
        feedback = practice_answer.format_feedback_message()

        if practice_session.current_index >= practice_session.total_questions:
            practice_session.is_complete = True
            feedback += "\n\n" + practice_session.format_result_message()
            await self.session_service.clear_session(user_id)
        else:
            # 更新 session state 到 DB
            await self.session_service.update_session(user_id, practice_session)
            next_q = practice_session.current_question
            if next_q:
                q_num = practice_session.current_index + 1
                total = practice_session.total_questions
                feedback += f"\n\n第 {q_num}/{total} 題：\n{next_q.format_for_display(q_num)}"

        return practice_answer, feedback


    async def _llm_grade_answer(
        self,
        user_answer: str,
        expected_answer: str,
        accepted_answers: list[str],
        question_context: str,
    ) -> bool:
        """Phase 2：LLM 語義判定 fallback。

        嚴格匹配失敗時，用 LLM 判斷語義等價性。
        LLM 失敗時 fail-safe 回傳 False。
        """
        try:
            user_message = format_grader_request(
                user_answer=user_answer,
                expected_answer=expected_answer,
                accepted_answers=accepted_answers,
                question_context=question_context,
            )
            parsed, _trace = await self.llm_client.complete_json_with_mode(
                mode=self.mode,
                system_prompt=GRADER_SYSTEM_PROMPT,
                user_message=user_message,
                temperature=0.0,
            )
            result = parsed.get("is_correct", False)
            reason = parsed.get("reason", "")
            logger.info(
                "LLM grading: answer=%r expected=%r is_correct=%s reason=%s",
                user_answer, expected_answer, result, reason,
            )
            return bool(result)
        except Exception:
            logger.warning(
                "LLM grading failed, falling back to strict: answer=%r expected=%r",
                user_answer, expected_answer,
                exc_info=True,
            )
            return False


async def has_active_session(db_session: AsyncSession, user_id: str) -> bool:
    """檢查用戶是否有進行中的練習 session（需要 DB session）。"""
    svc = SessionService(db_session)
    return await svc.has_active_session(user_id)
