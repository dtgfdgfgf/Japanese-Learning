"""LINE webhook handler.

T028: Create LINE webhook handler in src/api/webhook.py
T029: Wire up "入庫" command to save raw and create deferred doc
T030: Add validation for empty/missing previous message
T031: Format LINE reply message for save confirmation
T038: Wire up "分析" command to ExtractorService
T049: Wire up "練習" command to PracticeService
"""

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Header, HTTPException, Request
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from src.database import get_session
from src.lib.line_client import get_line_client
from src.lib.security import hash_user_id
from src.models.item import Item
from src.schemas.command import CommandType, ParsedCommand
from src.services.command_service import CommandService, parse_command
from src.services.practice_service import has_active_session
from src.templates.messages import (
    Messages,
    format_save_success,
    format_search_no_result,
    format_search_result_header,
    format_search_result_more,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhook"])

# ============================================================================
# 常數定義
# ============================================================================

# 搜尋結果限制
MAX_SEARCH_RESULTS = 10
DISPLAY_LIMIT = 5

# 日誌截斷長度
LOG_TRUNCATE_LENGTH = 50

# Store last message per user for "入庫" context (in-memory for MVP)
# In production, use Redis or database
_user_last_message: dict[str, str] = {}


# ============================================================================
# Main Webhook Handler
# ============================================================================


@router.post("/webhook")
async def handle_webhook(
    request: Request,
    x_line_signature: str = Header(..., alias="X-Line-Signature"),
) -> dict[str, str]:
    """Handle LINE webhook events.

    Args:
        request: FastAPI request object
        x_line_signature: LINE signature header for verification

    Returns:
        Success message

    Raises:
        HTTPException: If signature verification fails
    """
    line_client = get_line_client()

    # Get raw body
    body = await request.body()
    body_str = body.decode("utf-8")

    # Verify signature
    if not line_client.verify_signature(body_str, x_line_signature):
        logger.warning("Invalid LINE signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Parse events
    try:
        events = line_client.parse_events(body_str, x_line_signature)
    except InvalidSignatureError:
        logger.warning("Failed to parse LINE events")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Process events
    for event in events:
        if isinstance(event, MessageEvent):
            await handle_message_event(event)

    return {"status": "ok"}


async def handle_message_event(event: MessageEvent) -> None:
    """Handle a single message event.

    Args:
        event: LINE message event
    """
    line_client = get_line_client()

    # Extract message content
    if not isinstance(event.message, TextMessageContent):
        # Non-text messages not supported yet
        return

    text = event.message.text
    user_id = event.source.user_id if event.source else None
    reply_token = event.reply_token

    if not user_id or not reply_token:
        logger.warning("Missing user_id or reply_token")
        return

    logger.info(
        f"Received message from {user_id[:8]}...: {text[:LOG_TRUNCATE_LENGTH]}..."
    )

    # Parse command
    parsed = parse_command(text)

    # Check if user has active practice session and message isn't a command
    hashed_user_id = hash_user_id(user_id)
    if parsed.command_type == CommandType.UNKNOWN and has_active_session(hashed_user_id):
        # Treat as practice answer
        response = await _handle_practice_answer(hashed_user_id, text)
    else:
        # Handle command
        response = await _dispatch_command(
            command=parsed,
            line_user_id=user_id,
            raw_text=text,
        )

    # Send reply
    await line_client.reply_message(reply_token, response)

    # Store message for potential "入庫" context (if not a command and no active session)
    if parsed.command_type == CommandType.UNKNOWN and not has_active_session(hashed_user_id):
        _user_last_message[user_id] = text


# ============================================================================
# Command Handlers
# ============================================================================


async def _dispatch_command(
    command: ParsedCommand,
    line_user_id: str,
    raw_text: str,
) -> str:
    """Dispatch command to appropriate handler.

    Args:
        command: Parsed command
        line_user_id: Original LINE user ID
        raw_text: Original message text

    Returns:
        Response message to send to user
    """
    command_type = command.command_type

    # 快速指令（不需要 DB）
    if command_type == CommandType.HELP:
        return Messages.HELP

    if command_type == CommandType.PRIVACY:
        return Messages.PRIVACY

    # 需要 DB 的指令
    if command_type == CommandType.SAVE:
        return await _handle_save(line_user_id)

    if command_type == CommandType.SEARCH:
        return await _handle_search(line_user_id, command.keyword)

    if command_type == CommandType.ANALYZE:
        return await _handle_analyze(line_user_id)

    if command_type == CommandType.PRACTICE:
        return await _handle_practice(line_user_id)

    if command_type == CommandType.DELETE_LAST:
        return await _handle_delete_last(line_user_id)

    if command_type == CommandType.DELETE_ALL:
        return _handle_delete_all_request(line_user_id)

    if command_type == CommandType.COST:
        return await _handle_cost(line_user_id)

    if command_type == CommandType.DELETE_CONFIRM:
        return await _handle_delete_confirm(line_user_id)

    # Unknown command - use Router LLM
    return await _handle_unknown(line_user_id, raw_text)


async def _handle_save(line_user_id: str) -> str:
    """處理入庫指令。"""
    previous_content = _user_last_message.get(line_user_id)

    if not previous_content:
        return Messages.SAVE_NO_CONTENT

    async with get_session() as session:
        service = CommandService(session)
        result = await service.save_raw(
            line_user_id=line_user_id,
            content_text=previous_content,
        )

    # Clear stored message after saving
    _user_last_message.pop(line_user_id, None)

    return result.message


async def _handle_search(line_user_id: str, keyword: str | None) -> str:
    """處理查詢指令。"""
    if not keyword:
        return Messages.SEARCH_HINT

    hashed_user_id = hash_user_id(line_user_id)

    async with get_session() as session:
        from src.repositories.item_repo import ItemRepository

        item_repo = ItemRepository(session)

        try:
            items = await item_repo.search_by_keyword(
                user_id=hashed_user_id,
                keyword=keyword,
                limit=MAX_SEARCH_RESULTS,
            )

            if not items:
                return format_search_no_result(keyword)

            return _format_search_results(items)

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return Messages.ERROR_SEARCH


async def _handle_analyze(line_user_id: str) -> str:
    """處理分析指令。"""
    hashed_user_id = hash_user_id(line_user_id)

    async with get_session() as session:
        from src.services.extractor_service import (
            ExtractorService,
            create_extraction_summary,
        )

        extractor = ExtractorService(session)

        # Get deferred documents
        deferred_docs = await extractor.get_deferred_documents(hashed_user_id, limit=1)

        if not deferred_docs:
            return Messages.ANALYZE_NO_DEFERRED

        # Extract from the most recent deferred document
        doc = deferred_docs[0]
        try:
            result = await extractor.extract(
                doc_id=str(doc.doc_id),
                user_id=hashed_user_id,
            )

            summary = create_extraction_summary(result)
            return summary.to_message()
        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            return Messages.ERROR_ANALYZE


async def _handle_practice(line_user_id: str) -> str:
    """處理練習指令。"""
    hashed_user_id = hash_user_id(line_user_id)

    async with get_session() as session:
        from src.services.practice_service import PracticeService

        practice_service = PracticeService(session)

        try:
            _, message = await practice_service.create_session(
                user_id=hashed_user_id,
                question_count=5,
            )
            return message
        except Exception as e:
            logger.error(f"Practice session creation failed: {e}")
            return Messages.ERROR_PRACTICE


async def _handle_cost(line_user_id: str) -> str:
    """處理用量查詢指令。"""
    async with get_session() as session:
        from src.services.cost_service import CostService

        cost_service = CostService(session)

        try:
            result = await cost_service.get_usage_summary(line_user_id)
            return result.message
        except Exception as e:
            logger.error(f"Cost query failed: {e}")
            return Messages.ERROR_GENERIC


async def _handle_practice_answer(hashed_user_id: str, answer_text: str) -> str:
    """處理練習答案提交。

    Args:
        hashed_user_id: Hashed user ID
        answer_text: User's answer text

    Returns:
        Response message with feedback
    """
    async with get_session() as session:
        from src.services.practice_service import PracticeService

        practice_service = PracticeService(session)

        try:
            _, message = await practice_service.submit_answer(
                user_id=hashed_user_id,
                answer_text=answer_text,
            )
            return message
        except Exception as e:
            logger.error(f"Practice answer submission failed: {e}")
            return Messages.ERROR_PRACTICE_ANSWER


async def _handle_delete_last(line_user_id: str) -> str:
    """處理刪除最後一筆指令。"""
    hashed_user_id = hash_user_id(line_user_id)

    async with get_session() as session:
        from src.services.delete_service import DeleteService

        delete_service = DeleteService(session)

        try:
            _, message = await delete_service.delete_last(hashed_user_id)
            await session.commit()
            return message
        except Exception as e:
            logger.error(f"Delete last failed: {e}")
            return Messages.ERROR_DELETE


def _handle_delete_all_request(line_user_id: str) -> str:
    """處理清空資料請求（設置確認狀態）。"""
    from src.services.delete_service import request_clear_all

    hashed_user_id = hash_user_id(line_user_id)
    return request_clear_all(hashed_user_id)


async def _handle_delete_confirm(line_user_id: str) -> str:
    """處理確認清空資料指令。"""
    from src.services.delete_service import DeleteService, is_confirmation_pending

    hashed_user_id = hash_user_id(line_user_id)

    # Check if confirmation is pending
    if not is_confirmation_pending(hashed_user_id):
        return Messages.DELETE_CONFIRM_NOT_PENDING

    async with get_session() as session:
        delete_service = DeleteService(session)

        try:
            _, message = await delete_service.clear_all_data(hashed_user_id)
            await session.commit()
            return message
        except Exception as e:
            logger.error(f"Clear all failed: {e}")
            return Messages.ERROR_CLEAR


async def _handle_unknown(line_user_id: str, raw_text: str) -> str:
    """使用 Router LLM 處理未知指令。"""
    from src.schemas.router import IntentType
    from src.services.router_service import get_router_service

    hashed_user_id = hash_user_id(line_user_id)
    router_service = get_router_service()

    try:
        classification = await router_service.classify(raw_text)

        # High confidence save intent - auto-save
        if classification.intent == IntentType.SAVE and classification.confidence >= 0.8:
            async with get_session() as session:
                service = CommandService(session)
                result = await service.save_raw(
                    line_user_id=line_user_id,
                    content_text=raw_text,
                )
            return f"{result.message}\n\n💡 輸入「分析」來抽取單字和文法"

        # Chat intent - generate response
        if classification.intent == IntentType.CHAT:
            response = await router_service.get_chat_response(raw_text)
            return response

        # Help intent
        if classification.intent == IntentType.HELP:
            return Messages.HELP

        # Search intent with keyword
        if classification.intent == IntentType.SEARCH and classification.keyword:
            async with get_session() as session:
                from src.repositories.item_repo import ItemRepository

                item_repo = ItemRepository(session)
                items = await item_repo.search_by_keyword(
                    user_id=hashed_user_id,
                    keyword=classification.keyword,
                    limit=MAX_SEARCH_RESULTS,
                )

                if not items:
                    return format_search_no_result(classification.keyword)

                return _format_search_results(items)

        # Low confidence or unknown - prompt user
        return Messages.FALLBACK_UNKNOWN

    except Exception as e:
        logger.error(f"Router failed: {e}")
        return Messages.FALLBACK_UNKNOWN


# ============================================================================
# Helper Functions
# ============================================================================


def _format_search_results(items: "Sequence[Item]") -> str:
    """格式化搜尋結果為使用者友善的訊息。

    Args:
        items: 搜尋到的 Item 列表

    Returns:
        格式化的搜尋結果訊息
    """
    lines = [format_search_result_header(len(items))]

    for i, item in enumerate(items[:DISPLAY_LIMIT], 1):
        payload = item.payload or {}

        if item.item_type == "vocab":
            surface = payload.get("surface", "")
            reading = payload.get("reading", "")
            glossary = payload.get("glossary_zh", [])
            meaning = glossary[0] if glossary else ""

            if reading and reading != surface:
                lines.append(f"{i}. {surface}【{reading}】- {meaning}")
            else:
                lines.append(f"{i}. {surface} - {meaning}")

        elif item.item_type == "grammar":
            pattern = payload.get("pattern", "")
            meaning = payload.get("meaning_zh", "")
            lines.append(f"{i}. {pattern} - {meaning}")

    if len(items) > DISPLAY_LIMIT:
        lines.append(format_search_result_more(len(items) - DISPLAY_LIMIT))

    return "\n".join(lines)


def _get_fallback_message() -> str:
    """取得預設的 fallback 回應訊息。"""
    return Messages.FALLBACK_UNKNOWN
