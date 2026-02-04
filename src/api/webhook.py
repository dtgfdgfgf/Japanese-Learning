"""LINE webhook handler.

T028: Create LINE webhook handler in src/api/webhook.py
T029: Wire up "入庫" command to save raw and create deferred doc
T030: Add validation for empty/missing previous message
T031: Format LINE reply message for save confirmation
T038: Wire up "分析" command to ExtractorService
T049: Wire up "練習" command to PracticeService
"""

import asyncio
import logging
import os
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
from src.repositories.user_state_repo import UserStateRepository
from src.schemas.command import CommandType, ParsedCommand
from src.services.command_service import LANG_NAME_MAP, MODE_NAME_MAP, CommandService, parse_command
from src.services.practice_service import has_active_session
from src.templates.messages import (
    Messages,
    format_lang_switch_confirm,
    format_mode_switch_confirm,
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
        raise HTTPException(status_code=400, detail="Invalid signature") from None

    # Production：背景處理，立即回 200 避免 LINE webhook timeout（冷啟動防護）
    # 測試：同步等待，確保 mock assert 正確
    background = os.environ.get("RENDER_EXTERNAL_HOSTNAME") is not None

    for event in events:
        if isinstance(event, MessageEvent):
            if background:
                asyncio.create_task(_safe_handle_message(event))
            else:
                await handle_message_event(event)
        elif isinstance(event, PostbackEvent):
            if background:
                asyncio.create_task(_safe_handle_postback(event))
            else:
                await handle_postback_event(event)

    return {"status": "ok"}


async def _safe_handle_message(event: MessageEvent) -> None:
    """背景安全處理 message event，確保例外不會遺失。"""
    try:
        await handle_message_event(event)
    except Exception as e:
        logger.exception(f"Background message handler failed: {e}")


async def _safe_handle_postback(event: PostbackEvent) -> None:
    """背景安全處理 postback event，確保例外不會遺失。"""
    try:
        await handle_postback_event(event)
    except Exception as e:
        logger.exception(f"Background postback handler failed: {e}")


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

    hashed_uid = hash_user_id(user_id)

    logger.info(
        f"Received message from {hashed_uid[:8]}...: {text[:LOG_TRUNCATE_LENGTH]}..."
    )

    # 建立 UsageContext 追蹤本次 token 使用量
    usage_ctx = UsageContext()
    token = usage_context_var.set(usage_ctx)

    try:
        # === Pre-dispatch session：讀取 profile + 檢查 session + pending_save + 模式/語言切換 ===
        current_mode = "free"
        target_lang = "ja"
        daily_used = 0
        daily_cap = 50000
        parsed = parse_command(text)
        has_session = False
        has_pending_save = False
        try:
            async with get_session() as session:
                # 讀取 profile（失敗不影響後續操作）
                try:
                    profile_repo = UserProfileRepository(session)
                    profile = await profile_repo.get_or_create(hashed_uid)
                    current_mode = profile.mode or "free"
                    target_lang = profile.target_lang or "ja"
                    daily_used = profile.daily_used_tokens or 0
                    daily_cap = profile.daily_cap_tokens_free or 50000
                except Exception as e:
                    logger.warning(f"Failed to load user profile, using defaults: {e}")

                # 檢查 pending_save 狀態
                user_state_repo = UserStateRepository(session)
                has_pending_save = await user_state_repo.has_pending_save(hashed_uid)

                # 練習 session 中的答案處理（需查 DB）
                if parsed.command_type == CommandType.UNKNOWN and not has_pending_save:
                    has_session = await has_active_session(session, hashed_uid)

                # 模式切換需在 reply 前完成
                if parsed.command_type == CommandType.MODE_SWITCH:
                    mode_key = _resolve_mode_key(parsed)
                    if mode_key:
                        try:
                            profile_repo = UserProfileRepository(session)
                            profile = await profile_repo.set_mode(hashed_uid, mode_key)
                            current_mode = profile.mode
                        except Exception as e:
                            logger.warning(f"Failed to set mode: {e}")

                # 語言切換需在 reply 前完成
                if parsed.command_type == CommandType.SET_LANG:
                    lang_key = _resolve_lang_key(parsed)
                    if lang_key:
                        try:
                            profile_repo = UserProfileRepository(session)
                            profile = await profile_repo.set_target_lang(hashed_uid, lang_key)
                            target_lang = profile.target_lang
                        except Exception as e:
                            logger.warning(f"Failed to set target_lang: {e}")
                    else:
                        logger.warning(f"Could not resolve lang_key from: {parsed.keyword}")
        except Exception as e:
            logger.warning(f"Failed to open pre-dispatch session: {e}")

        # === Dispatch ===
        # 優先處理 pending_save 狀態
        if parsed.command_type == CommandType.CONFIRM_SAVE and has_pending_save:
            # 用戶輸入「1」確認入庫
            response = await _handle_confirm_save(hashed_uid, user_id)
        elif has_pending_save and parsed.command_type != CommandType.CONFIRM_SAVE:
            # 有 pending_save 但輸入非「1」→ 清除狀態，處理新輸入
            async with get_session() as session:
                user_state_repo = UserStateRepository(session)
                await user_state_repo.clear_pending_save(hashed_uid)
            # 繼續處理當前輸入
            response = await _dispatch_command(
                command=parsed,
                line_user_id=user_id,
                raw_text=text,
                mode=current_mode,
                target_lang=target_lang,
            )
        elif parsed.command_type == CommandType.CONFIRM_SAVE and not has_pending_save:
            # 輸入「1」但無 pending_save → 視為普通輸入交給 Router
            response = await _handle_unknown(user_id, text, current_mode, target_lang)
        elif parsed.command_type == CommandType.UNKNOWN and has_session:
            response = await _handle_practice_answer(hashed_uid, text, current_mode, target_lang)
        elif parsed.command_type == CommandType.MODE_SWITCH:
            mode_key = _resolve_mode_key(parsed)
            if mode_key:
                response = format_mode_switch_confirm(mode_key)
            else:
                response = Messages.FALLBACK_UNKNOWN
        elif parsed.command_type == CommandType.SET_LANG:
            lang_key = _resolve_lang_key(parsed)
            if lang_key:
                response = format_lang_switch_confirm(lang_key)
            else:
                response = Messages.format("LANG_SWITCH_INVALID")
        else:
            response = await _dispatch_command(
                command=parsed,
                line_user_id=user_id,
                raw_text=text,
                mode=current_mode,
                target_lang=target_lang,
            )

        # === Post-dispatch session：累加 token + 儲存 last_message ===
        total_tokens = usage_ctx.total_tokens
        need_save_last_msg = parsed.command_type == CommandType.UNKNOWN and not has_session
        if total_tokens > 0 or need_save_last_msg:
            try:
                async with get_session() as session:
                    if total_tokens > 0:
                        repo = UserProfileRepository(session)
                        profile = await repo.add_tokens(hashed_uid, total_tokens)
                        daily_used = profile.daily_used_tokens
                    if need_save_last_msg:
                        user_state_repo = UserStateRepository(session)
                        # 截斷過長訊息，避免 DB 儲存巨大 payload
                        truncated_text = text[:5000] if len(text) > 5000 else text
                        await user_state_repo.set_last_message(hashed_uid, truncated_text)
            except Exception as e:
                logger.warning(f"Failed in post-dispatch session: {e}")

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

        # 使用 Quick Reply 發送（reply 失敗時 fallback 至 Push API）
        quick_reply = build_mode_quick_replies(current_mode)
        replied = await line_client.reply_with_quick_reply(
            reply_token, full_response, quick_reply
        )
        if not replied:
            logger.warning("Reply failed, falling back to Push API")
            await line_client.push_message_with_quick_reply(
                user_id, full_response, quick_reply
            )

    except Exception as e:
        # 最後防線：確保使用者至少收到回覆
        logger.exception(f"Unhandled error in message handler: {e}")
        try:
            replied = await line_client.reply_message(
                reply_token, Messages.ERROR_GENERIC
            )
            if not replied:
                await line_client.push_message(user_id, Messages.ERROR_GENERIC)
        except Exception:
            logger.exception("Failed to send fallback error reply")
    finally:
        usage_context_var.reset(token)


async def handle_postback_event(event: PostbackEvent) -> None:
    """處理 PostbackEvent（Quick Reply 模式切換）。"""
    line_client = get_line_client()
    user_id = event.source.user_id if event.source else None
    reply_token = event.reply_token

    if not user_id or not reply_token:
        return

    try:
        hashed_uid = hash_user_id(user_id)
        data = parse_qs(event.postback.data) if event.postback else {}
        action = data.get("action", [None])[0]
        mode = data.get("mode", [None])[0]

        if action == "switch_mode" and mode in ("free", "cheap", "rigorous"):
            daily_used = 0
            daily_cap = 50000
            try:
                async with get_session() as session:
                    repo = UserProfileRepository(session)
                    profile = await repo.set_mode(hashed_uid, mode)
                    daily_used = profile.daily_used_tokens or 0
                    daily_cap = profile.daily_cap_tokens_free or 50000
            except Exception as e:
                logger.warning(f"Failed to set mode via postback: {e}")

            confirm_msg = format_mode_switch_confirm(mode)

            # 附加簡易 footer
            footer = format_usage_footer(
                daily_used=daily_used,
                daily_cap=daily_cap,
                in_tokens=0,
                out_tokens=0,
                mode=mode,
            )
            full_response = f"{confirm_msg}\n\n{footer}"
            quick_reply = build_mode_quick_replies(mode)
            replied = await line_client.reply_with_quick_reply(
                reply_token, full_response, quick_reply
            )
            if not replied:
                logger.warning("Postback reply failed, falling back to Push API")
                await line_client.push_message_with_quick_reply(
                    user_id, full_response, quick_reply
                )
        else:
            logger.warning(f"Unknown postback: {event.postback.data if event.postback else 'None'}")
    except Exception as e:
        logger.exception(f"Unhandled error in postback handler: {e}")
        try:
            replied = await line_client.reply_message(
                reply_token, Messages.ERROR_GENERIC
            )
            if not replied:
                await line_client.push_message(user_id, Messages.ERROR_GENERIC)
        except Exception:
            logger.exception("Failed to send fallback error reply for postback")


# ============================================================================
# Command Handlers
# ============================================================================


def _resolve_mode_key(command: ParsedCommand) -> str | None:
    """從 ParsedCommand 解析模式 key。"""
    if command.keyword:
        return MODE_NAME_MAP.get(command.keyword)
    # 嘗試從 raw_text 解析
    return MODE_NAME_MAP.get(command.raw_text.strip())


def _resolve_lang_key(command: ParsedCommand) -> str | None:
    """從 ParsedCommand 解析語言 key（僅允許 ja/en）。"""
    if command.keyword:
        return LANG_NAME_MAP.get(command.keyword)
    return None


async def _dispatch_command(
    command: ParsedCommand,
    line_user_id: str,
    raw_text: str,
    mode: str = "free",
    target_lang: str = "ja",
) -> str:
    """Dispatch command to appropriate handler."""
    command_type = command.command_type

    if command_type == CommandType.HELP:
        from src.templates.messages import MODE_LABELS
        mode_label = MODE_LABELS.get(mode, mode)
        lang_label = {"ja": "日文", "en": "英文"}.get(target_lang, target_lang)
        return f"{Messages.HELP}\n\n⚙️ 目前模式：{mode_label}｜學習語言：{lang_label}"

    if command_type == CommandType.PRIVACY:
        return Messages.PRIVACY

    if command_type == CommandType.SAVE:
        return await _handle_save(line_user_id)

    if command_type == CommandType.SEARCH:
        return await _handle_search(line_user_id, command.keyword)

    if command_type == CommandType.ANALYZE:
        return await _handle_analyze(line_user_id, mode, target_lang)

    if command_type == CommandType.PRACTICE:
        return await _handle_practice(line_user_id, mode, target_lang)

    if command_type == CommandType.DELETE_LAST:
        return await _handle_delete_last(line_user_id)

    if command_type == CommandType.DELETE_ALL:
        return await _handle_delete_all_request(line_user_id)

    if command_type == CommandType.COST:
        return await _handle_cost(line_user_id)

    if command_type == CommandType.STATS:
        return await _handle_stats(line_user_id)

    if command_type == CommandType.DELETE_CONFIRM:
        return await _handle_delete_confirm(line_user_id)

    return await _handle_unknown(line_user_id, raw_text, mode, target_lang)


async def _handle_save(line_user_id: str) -> str:
    """處理入庫指令。"""
    hashed_uid = hash_user_id(line_user_id)

    async with get_session() as session:
        user_state_repo = UserStateRepository(session)
        previous_content = await user_state_repo.get_last_message(hashed_uid)

        if not previous_content:
            return Messages.SAVE_NO_CONTENT

        service = CommandService(session)
        result = await service.save_raw(
            line_user_id=line_user_id,
            content_text=previous_content,
        )

        await user_state_repo.clear_last_message(hashed_uid)

    return result.message


async def _handle_confirm_save(hashed_uid: str, line_user_id: str) -> str:
    """處理確認入庫（用戶輸入「1」）。"""
    async with get_session() as session:
        user_state_repo = UserStateRepository(session)
        pending_content = await user_state_repo.get_pending_save(hashed_uid)

        if not pending_content:
            return Messages.FALLBACK_UNKNOWN

        service = CommandService(session)
        result = await service.save_raw(
            line_user_id=line_user_id,
            content_text=pending_content,
        )

        await user_state_repo.clear_pending_save(hashed_uid)

        # save_raw() 已回傳格式化訊息，直接使用
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


async def _handle_analyze(line_user_id: str, mode: str = "free", target_lang: str = "ja") -> str:
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
                target_lang=target_lang,
            )

            summary = create_extraction_summary(result)
            return summary.to_message()
        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            return Messages.ERROR_ANALYZE


async def _handle_practice(line_user_id: str, mode: str = "free", target_lang: str = "ja") -> str:
    """處理練習指令。"""
    hashed_user_id = hash_user_id(line_user_id)

    async with get_session() as session:
        from src.services.practice_service import PracticeService

        practice_service = PracticeService(session, mode=mode, target_lang=target_lang)

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


async def _handle_stats(line_user_id: str) -> str:
    """處理統計指令。"""
    async with get_session() as session:
        from src.services.stats_service import StatsService

        stats_service = StatsService(session)

        try:
            result = await stats_service.get_stats_summary(hash_user_id(line_user_id))
            return result.message
        except Exception as e:
            logger.error(f"Stats query failed: {e}")
            return Messages.ERROR_GENERIC


async def _handle_practice_answer(hashed_user_id: str, answer_text: str, mode: str = "free", target_lang: str = "ja") -> str:
    """處理練習答案提交。"""
    async with get_session() as session:
        from src.services.practice_service import PracticeService

        practice_service = PracticeService(session, mode=mode, target_lang=target_lang)

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
            return message
        except Exception as e:
            logger.error(f"Delete last failed: {e}")
            return Messages.ERROR_DELETE


async def _handle_delete_all_request(line_user_id: str) -> str:
    """處理清空資料請求（設置確認狀態）。"""
    hashed_user_id = hash_user_id(line_user_id)

    async with get_session() as session:
        user_state_repo = UserStateRepository(session)
        await user_state_repo.set_delete_confirm_at(hashed_user_id)

    return Messages.DELETE_CONFIRM_PROMPT


async def _handle_delete_confirm(line_user_id: str) -> str:
    """處理確認清空資料指令。"""
    from src.services.delete_service import DeleteService

    hashed_user_id = hash_user_id(line_user_id)

    async with get_session() as session:
        user_state_repo = UserStateRepository(session)
        is_pending = await user_state_repo.is_delete_confirmation_pending(hashed_user_id)

        if not is_pending:
            return Messages.DELETE_CONFIRM_NOT_PENDING

        delete_service = DeleteService(session)

        try:
            await user_state_repo.clear_delete_confirm(hashed_user_id)
            _, message = await delete_service.clear_all_data(hashed_user_id)
            return message
        except Exception as e:
            logger.error(f"Clear all failed: {e}")
            return Messages.ERROR_CLEAR


async def _handle_unknown(
    line_user_id: str,
    raw_text: str,
    mode: str = "free",
    target_lang: str = "ja",
) -> str:
    """使用 Router LLM 處理未知指令。"""
    from src.schemas.router import IntentType
    from src.services.router_service import get_router_service

    hashed_user_id = hash_user_id(line_user_id)
    router_service = get_router_service()

    try:
        classification = await router_service.classify(raw_text, mode=mode, target_lang=target_lang)

        if classification.intent == IntentType.SAVE and classification.confidence >= 0.8:
            # 判斷是否為短單字（根據語言調整閾值）
            stripped_text = raw_text.strip()
            if target_lang == "ja":
                # 日文：通常 1-10 字元，設 15 為上限
                is_short_word = len(stripped_text) <= 15
            else:
                # 英文：單字通常無空格且較短
                is_short_word = len(stripped_text) <= 30 and ' ' not in stripped_text

            if is_short_word:
                # 短單字流程：解釋意思 + 詢問入庫
                explanation = await router_service.get_word_explanation(
                    raw_text.strip(), mode=mode, target_lang=target_lang
                )
                # 設定 pending_save 狀態
                async with get_session() as session:
                    user_state_repo = UserStateRepository(session)
                    await user_state_repo.set_pending_save(hashed_user_id, raw_text.strip())
                return Messages.format("WORD_EXPLANATION", explanation=explanation)
            else:
                # 長文本：直接入庫
                async with get_session() as session:
                    service = CommandService(session)
                    result = await service.save_raw(
                        line_user_id=line_user_id,
                        content_text=raw_text,
                    )
                return f"{result.message}\n\n💡 輸入「分析」來抽取單字和文法"

        if classification.intent == IntentType.CHAT:
            response = await router_service.get_chat_response(raw_text, mode=mode, target_lang=target_lang)
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
            pronunciation = payload.get("pronunciation", "")
            glossary = payload.get("glossary_zh", [])
            meaning = glossary[0] if glossary else ""

            # 日文用【reading】，英文用 (pronunciation)
            if reading and reading != surface:
                lines.append(f"{i}. {surface}【{reading}】- {meaning}")
            elif pronunciation:
                lines.append(f"{i}. {surface} ({pronunciation}) - {meaning}")
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
