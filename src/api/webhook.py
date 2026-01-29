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
from urllib.parse import parse_qs

from fastapi import APIRouter, Header, HTTPException, Request
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
)

from src.database import get_session
from src.lib.line_client import build_mode_quick_replies, get_line_client
from src.lib.llm_client import UsageContext, usage_context_var
from src.lib.security import hash_user_id
from src.models.item import Item
from src.repositories.user_profile_repo import UserProfileRepository
from src.schemas.command import CommandType, ParsedCommand
from src.services.command_service import MODE_NAME_MAP, CommandService, parse_command
from src.services.practice_service import has_active_session
from src.templates.messages import (
    Messages,
    format_mode_switch_confirm,
    format_save_success,
    format_search_no_result,
    format_search_result_header,
    format_search_result_more,
    format_usage_footer,
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

# LINE 訊息長度上限（預留 footer 空間）
LINE_MESSAGE_MAX_LENGTH = 5000
FOOTER_RESERVE = 300

# Store last message per user for "入庫" context (in-memory for MVP)
_user_last_message: dict[str, str] = {}


# ============================================================================
# Main Webhook Handler
# ============================================================================


@router.post("/webhook")
async def handle_webhook(
    request: Request,
    x_line_signature: str = Header(..., alias="X-Line-Signature"),
) -> dict[str, str]:
    """Handle LINE webhook events."""
    line_client = get_line_client()

    body = await request.body()
    body_str = body.decode("utf-8")

    if not line_client.verify_signature(body_str, x_line_signature):
        logger.warning("Invalid LINE signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        events = line_client.parse_events(body_str, x_line_signature)
    except InvalidSignatureError:
        logger.warning("Failed to parse LINE events")
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if isinstance(event, MessageEvent):
            await handle_message_event(event)
        elif isinstance(event, PostbackEvent):
            await handle_postback_event(event)

    return {"status": "ok"}


async def handle_message_event(event: MessageEvent) -> None:
    """Handle a single message event."""
    line_client = get_line_client()

    if not isinstance(event.message, TextMessageContent):
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

    hashed_uid = hash_user_id(user_id)

    # 建立 UsageContext 追蹤本次 token 使用量
    usage_ctx = UsageContext()
    token = usage_context_var.set(usage_ctx)

    try:
        # 取得 user profile（含日切重置）
        async with get_session() as profile_session:
            profile_repo = UserProfileRepository(profile_session)
            profile = await profile_repo.get_or_create(hashed_uid)
            current_mode = profile.mode
            daily_used = profile.daily_used_tokens
            daily_cap = profile.daily_cap_tokens_free

        # 解析指令
        parsed = parse_command(text)

        # 練習 session 中的答案處理
        if parsed.command_type == CommandType.UNKNOWN and has_active_session(hashed_uid):
            response = await _handle_practice_answer(hashed_uid, text)
        elif parsed.command_type == CommandType.MODE_SWITCH:
            # 模式切換
            mode_key = _resolve_mode_key(parsed)
            if mode_key:
                async with get_session() as session:
                    repo = UserProfileRepository(session)
                    profile = await repo.set_mode(hashed_uid, mode_key)
                    current_mode = profile.mode
                response = format_mode_switch_confirm(mode_key)
            else:
                response = Messages.FALLBACK_UNKNOWN
        else:
            response = await _dispatch_command(
                command=parsed,
                line_user_id=user_id,
                raw_text=text,
                mode=current_mode,
            )

        # 累加本次 token 使用量到 user profile
        total_tokens = usage_ctx.total_tokens
        if total_tokens > 0:
            async with get_session() as session:
                repo = UserProfileRepository(session)
                profile = await repo.add_tokens(hashed_uid, total_tokens)
                daily_used = profile.daily_used_tokens

        # 組裝 footer
        footer = format_usage_footer(
            daily_used=daily_used,
            daily_cap=daily_cap,
            in_tokens=usage_ctx.input_tokens,
            out_tokens=usage_ctx.output_tokens,
            mode=current_mode,
        )

        # 確保不超過 LINE 訊息長度上限
        max_body = LINE_MESSAGE_MAX_LENGTH - len(footer) - 4  # 預留 \n\n
        if len(response) > max_body:
            response = response[:max_body - 3] + "..."

        full_response = f"{response}\n\n{footer}"

        # 使用 Quick Reply 發送
        quick_reply = build_mode_quick_replies(current_mode)
        await line_client.reply_with_quick_reply(reply_token, full_response, quick_reply)

        # 儲存訊息供「入庫」使用
        if parsed.command_type == CommandType.UNKNOWN and not has_active_session(hashed_uid):
            _user_last_message[user_id] = text

    finally:
        usage_context_var.reset(token)


async def handle_postback_event(event: PostbackEvent) -> None:
    """處理 PostbackEvent（Quick Reply 模式切換）。"""
    line_client = get_line_client()
    user_id = event.source.user_id if event.source else None
    reply_token = event.reply_token

    if not user_id or not reply_token:
        return

    hashed_uid = hash_user_id(user_id)
    data = parse_qs(event.postback.data) if event.postback else {}
    action = data.get("action", [None])[0]
    mode = data.get("mode", [None])[0]

    if action == "switch_mode" and mode in ("cheap", "balanced", "rigorous"):
        async with get_session() as session:
            repo = UserProfileRepository(session)
            profile = await repo.set_mode(hashed_uid, mode)

        confirm_msg = format_mode_switch_confirm(mode)

        # 附加簡易 footer
        footer = format_usage_footer(
            daily_used=profile.daily_used_tokens,
            daily_cap=profile.daily_cap_tokens_free,
            in_tokens=0,
            out_tokens=0,
            mode=mode,
        )
        full_response = f"{confirm_msg}\n\n{footer}"
        quick_reply = build_mode_quick_replies(mode)
        await line_client.reply_with_quick_reply(reply_token, full_response, quick_reply)
    else:
        logger.warning(f"Unknown postback: {event.postback.data if event.postback else 'None'}")


# ============================================================================
# Command Handlers
# ============================================================================


def _resolve_mode_key(command: ParsedCommand) -> str | None:
    """從 ParsedCommand 解析模式 key。"""
    if command.keyword:
        return MODE_NAME_MAP.get(command.keyword)
    # 嘗試從 raw_text 解析
    return MODE_NAME_MAP.get(command.raw_text.strip())


async def _dispatch_command(
    command: ParsedCommand,
    line_user_id: str,
    raw_text: str,
    mode: str = "balanced",
) -> str:
    """Dispatch command to appropriate handler."""
    command_type = command.command_type

    if command_type == CommandType.HELP:
        return Messages.HELP

    if command_type == CommandType.PRIVACY:
        return Messages.PRIVACY

    if command_type == CommandType.SAVE:
        return await _handle_save(line_user_id)

    if command_type == CommandType.SEARCH:
        return await _handle_search(line_user_id, command.keyword)

    if command_type == CommandType.ANALYZE:
        return await _handle_analyze(line_user_id, mode)

    if command_type == CommandType.PRACTICE:
        return await _handle_practice(line_user_id, mode)

    if command_type == CommandType.DELETE_LAST:
        return await _handle_delete_last(line_user_id)

    if command_type == CommandType.DELETE_ALL:
        return _handle_delete_all_request(line_user_id)

    if command_type == CommandType.COST:
        return await _handle_cost(line_user_id)

    if command_type == CommandType.DELETE_CONFIRM:
        return await _handle_delete_confirm(line_user_id)

    return await _handle_unknown(line_user_id, raw_text, mode)


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


async def _handle_analyze(line_user_id: str, mode: str = "balanced") -> str:
    """處理分析指令。"""
    hashed_user_id = hash_user_id(line_user_id)

    async with get_session() as session:
        from src.services.extractor_service import (
            ExtractorService,
            create_extraction_summary,
        )

        extractor = ExtractorService(session)

        deferred_docs = await extractor.get_deferred_documents(hashed_user_id, limit=1)

        if not deferred_docs:
            return Messages.ANALYZE_NO_DEFERRED

        doc = deferred_docs[0]
        try:
            result = await extractor.extract(
                doc_id=str(doc.doc_id),
                user_id=hashed_user_id,
                mode=mode,
            )

            summary = create_extraction_summary(result)
            return summary.to_message()
        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            return Messages.ERROR_ANALYZE


async def _handle_practice(line_user_id: str, mode: str = "balanced") -> str:
    """處理練習指令。"""
    hashed_user_id = hash_user_id(line_user_id)

    async with get_session() as session:
        from src.services.practice_service import PracticeService

        practice_service = PracticeService(session, mode=mode)

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
    """處理練習答案提交。"""
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


async def _handle_unknown(
    line_user_id: str,
    raw_text: str,
    mode: str = "balanced",
) -> str:
    """使用 Router LLM 處理未知指令。"""
    from src.schemas.router import IntentType
    from src.services.router_service import get_router_service

    hashed_user_id = hash_user_id(line_user_id)
    router_service = get_router_service()

    try:
        classification = await router_service.classify(raw_text, mode=mode)

        if classification.intent == IntentType.SAVE and classification.confidence >= 0.8:
            async with get_session() as session:
                service = CommandService(session)
                result = await service.save_raw(
                    line_user_id=line_user_id,
                    content_text=raw_text,
                )
            return f"{result.message}\n\n💡 輸入「分析」來抽取單字和文法"

        if classification.intent == IntentType.CHAT:
            response = await router_service.get_chat_response(raw_text, mode=mode)
            return response

        if classification.intent == IntentType.HELP:
            return Messages.HELP

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

        return Messages.FALLBACK_UNKNOWN

    except Exception as e:
        logger.error(f"Router failed: {e}")
        return Messages.FALLBACK_UNKNOWN


# ============================================================================
# Helper Functions
# ============================================================================


def _format_search_results(items: "Sequence[Item]") -> str:
    """格式化搜尋結果為使用者友善的訊息。"""
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
