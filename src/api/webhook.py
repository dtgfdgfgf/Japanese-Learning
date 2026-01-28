"""LINE webhook handler.

T028: Create LINE webhook handler in src/api/webhook.py
T029: Wire up "入庫" command to save raw and create deferred doc
T030: Add validation for empty/missing previous message
T031: Format LINE reply message for save confirmation
T038: Wire up "分析" command to ExtractorService
T049: Wire up "練習" command to PracticeService
"""

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from src.database import get_session
from src.lib.line_client import get_line_client
from src.lib.security import hash_user_id
from src.schemas.command import CommandType
from src.services.command_service import (
    CommandService,
    get_help_message,
    get_no_content_message,
    get_privacy_message,
    get_search_hint_message,
    parse_command,
)
from src.services.practice_service import has_active_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhook"])

# Store last message per user for "入庫" context (in-memory for MVP)
# In production, use Redis or database
_user_last_message: dict[str, str] = {}


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

    logger.info(f"Received message from {user_id[:8]}...: {text[:50]}...")

    # Parse command
    parsed = parse_command(text)

    # Check if user has active practice session and message isn't a command
    hashed_user_id = hash_user_id(user_id)
    if parsed.command_type == CommandType.UNKNOWN and has_active_session(hashed_user_id):
        # Treat as practice answer
        response = await handle_practice_answer(hashed_user_id, text)
    else:
        # Handle command
        response = await execute_command(
            command=parsed,
            line_user_id=user_id,
            raw_text=text,
        )

    # Send reply
    await line_client.reply_message(reply_token, response)

    # Store message for potential "入庫" context (if not a command and no active session)
    if parsed.command_type == CommandType.UNKNOWN and not has_active_session(hashed_user_id):
        _user_last_message[user_id] = text


async def handle_practice_answer(hashed_user_id: str, answer_text: str) -> str:
    """Handle a practice answer submission.
    
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
            return "處理答案時發生錯誤，請重新開始練習"


async def execute_command(
    command: "ParsedCommand",
    line_user_id: str,
    raw_text: str,
) -> str:
    """Execute parsed command and return response message.

    Args:
        command: Parsed command
        line_user_id: Original LINE user ID
        raw_text: Original message text

    Returns:
        Response message to send to user
    """
    from src.schemas.command import ParsedCommand

    command_type = command.command_type

    # Help command
    if command_type == CommandType.HELP:
        return get_help_message()

    # Privacy command
    if command_type == CommandType.PRIVACY:
        return get_privacy_message()

    # Save command (入庫)
    if command_type == CommandType.SAVE:
        # Get previous message content
        previous_content = _user_last_message.get(line_user_id)

        if not previous_content:
            return get_no_content_message()

        # Save to database
        async with get_session() as session:
            service = CommandService(session)
            result = await service.save_raw(
                line_user_id=line_user_id,
                content_text=previous_content,
            )

        # Clear stored message after saving
        _user_last_message.pop(line_user_id, None)

        return result.message

    # Search command (查詢)
    if command_type == CommandType.SEARCH:
        if not command.keyword:
            return get_search_hint_message()

        # Hash user ID for database
        hashed_user_id = hash_user_id(line_user_id)
        
        async with get_session() as session:
            from src.repositories.item_repo import ItemRepository
            
            item_repo = ItemRepository(session)
            
            try:
                items = await item_repo.search_by_keyword(
                    user_id=hashed_user_id,
                    keyword=command.keyword,
                    limit=10,
                )
                
                if not items:
                    return f"找不到「{command.keyword}」相關的項目 🔍"
                
                # Format results (max 5 displayed)
                lines = [f"🔍 找到 {len(items)} 筆："]
                
                for i, item in enumerate(items[:5], 1):
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
                
                if len(items) > 5:
                    lines.append(f"...還有 {len(items) - 5} 筆")
                
                return "\n".join(lines)
                
            except Exception as e:
                logger.error(f"Search failed: {e}")
                return "搜尋時發生錯誤，請稍後再試"

    # Analyze command (分析)
    if command_type == CommandType.ANALYZE:
        # Hash user ID for database
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
                return "沒有待分析的素材 📭\n請先「入庫」一些日文內容"
            
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
                return "分析時發生錯誤 😢\n請稍後再試一次"

    # Practice command (練習)
    if command_type == CommandType.PRACTICE:
        # Hash user ID for database
        hashed_user_id = hash_user_id(line_user_id)
        
        async with get_session() as session:
            from src.services.practice_service import PracticeService
            
            practice_service = PracticeService(session)
            
            try:
                session_obj, message = await practice_service.create_session(
                    user_id=hashed_user_id,
                    question_count=5,
                )
                return message
            except Exception as e:
                logger.error(f"Practice session creation failed: {e}")
                return "練習功能暫時無法使用，請稍後再試 🙇"

    # Delete commands
    if command_type == CommandType.DELETE_LAST:
        # Hash user ID for database
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
                return "刪除時發生錯誤，請稍後再試"

    if command_type == CommandType.DELETE_ALL:
        # Hash user ID for database
        hashed_user_id = hash_user_id(line_user_id)
        
        from src.services.delete_service import DeleteService
        
        # Request confirmation (no DB needed for this)
        delete_service_temp = DeleteService.__new__(DeleteService)
        return delete_service_temp.request_clear_all(hashed_user_id)

    if command_type == CommandType.DELETE_CONFIRM:
        # Hash user ID for database
        hashed_user_id = hash_user_id(line_user_id)
        
        from src.services.delete_service import DeleteService, is_confirmation_pending
        
        # Check if confirmation is pending
        if not is_confirmation_pending(hashed_user_id):
            return "沒有待確認的清空請求 🤔\n如需清空資料，請先輸入「清空資料」"
        
        async with get_session() as session:
            delete_service = DeleteService(session)
            
            try:
                _, message = await delete_service.clear_all_data(hashed_user_id)
                await session.commit()
                return message
            except Exception as e:
                logger.error(f"Clear all failed: {e}")
                return "清空資料時發生錯誤，請稍後再試"

    # Unknown command - use Router LLM for intent classification
    hashed_user_id = hash_user_id(line_user_id)
    
    from src.services.router_service import get_router_service
    from src.schemas.router import IntentType
    
    router = get_router_service()
    
    try:
        classification = await router.classify(raw_text)
        
        # High confidence save intent - auto-save
        if classification.intent == IntentType.SAVE and classification.confidence >= 0.8:
            # Auto-save the content
            async with get_session() as session:
                service = CommandService(session)
                result = await service.save_raw(
                    line_user_id=line_user_id,
                    content_text=raw_text,
                )
            return f"{result.message}\n\n💡 輸入「分析」來抽取單字和文法"
        
        # Chat intent - generate response
        if classification.intent == IntentType.CHAT:
            response = await router.get_chat_response(raw_text)
            return response
        
        # Help intent
        if classification.intent == IntentType.HELP:
            return get_help_message()
        
        # Search intent with keyword
        if classification.intent == IntentType.SEARCH and classification.keyword:
            async with get_session() as session:
                from src.repositories.item_repo import ItemRepository
                
                item_repo = ItemRepository(session)
                items = await item_repo.search_by_keyword(
                    user_id=hashed_user_id,
                    keyword=classification.keyword,
                    limit=10,
                )
                
                if not items:
                    return f"找不到「{classification.keyword}」相關的項目 🔍"
                
                lines = [f"🔍 找到 {len(items)} 筆："]
                for i, item in enumerate(items[:5], 1):
                    payload = item.payload or {}
                    if item.item_type == "vocab":
                        surface = payload.get("surface", "")
                        meaning = (payload.get("glossary_zh", []) or [""])[0]
                        lines.append(f"{i}. {surface} - {meaning}")
                    else:
                        pattern = payload.get("pattern", "")
                        meaning = payload.get("meaning_zh", "")
                        lines.append(f"{i}. {pattern} - {meaning}")
                
                if len(items) > 5:
                    lines.append(f"...還有 {len(items) - 5} 筆")
                
                return "\n".join(lines)
        
        # Low confidence or unknown - prompt user
        if classification.needs_fallback:
            return (
                "我不太確定你想做什麼 🤔\n\n"
                "如果你想保存這段內容，請輸入「入庫」\n"
                "輸入「說明」查看所有指令"
            )
        
        # Default fallback
        return (
            "我不太確定你想做什麼 🤔\n\n"
            "如果你想保存剛才的內容，請輸入「入庫」\n"
            "輸入「說明」查看所有指令"
        )
        
    except Exception as e:
        logger.error(f"Router failed: {e}")
        return (
            "我不太確定你想做什麼 🤔\n\n"
            "如果你想保存剛才的內容，請輸入「入庫」\n"
            "輸入「說明」查看所有指令"
        )
