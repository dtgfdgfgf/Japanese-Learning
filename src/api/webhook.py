"""LINE webhook handler.

T028: Create LINE webhook handler in src/api/webhook.py
T029: Wire up "入庫" command to save raw and create deferred doc
T030: Add validation for empty/missing previous message
T031: Format LINE reply message for save confirmation
T049: Wire up "練習" command to PracticeService
"""

import asyncio
import logging
import os
import time
import unicodedata
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
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
from src.services.command_service import (
    LANG_NAME_MAP,
    MODE_NAME_MAP,
    CommandService,
    parse_command,
)
from src.services.practice_service import has_active_session
from src.templates.messages import (
    Messages,
    format_help_with_status,
    format_lang_switch_confirm,
    format_mode_switch_confirm,
    format_search_no_result,
    format_search_result_header,
    format_search_result_more,
    format_usage_footer,
    format_word_multi_detected,
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

# 不會中斷 pending_save 的安全指令（這些指令執行後 pending 仍保留）
PENDING_SAFE_COMMANDS = {
    CommandType.HELP,
    CommandType.MODE_SWITCH,
    CommandType.SET_LANG,
    CommandType.COST,
    CommandType.STATS,
    CommandType.PRIVACY,
    CommandType.EXIT_PRACTICE,
    CommandType.WORD_SAVE,
    CommandType.LIST_ITEMS,
}


# LINE 訊息長度上限（預留 footer 空間）
LINE_MESSAGE_MAX_LENGTH = 5000
FOOTER_RESERVE = 300

# Edge Case 26: 超長文本直接入庫閾值（超過此長度跳過 Router）
LONG_TEXT_THRESHOLD = 2000


# ============================================================================
# 輸入文字處理工具
# ============================================================================

# Edge Case 12: 移除隱形 Unicode 字元（ZWS、ZWNJ、BOM、Soft Hyphen、Word Joiner）
_INVISIBLE_CHAR_TABLE = str.maketrans("", "", "\u200b\u200c\ufeff\u00ad\u2060")


def _sanitize_text(text: str) -> str:
    """移除隱形 Unicode 字元，並將全形英數字轉為半形。"""
    # Edge Case 21: NFKC 正規化（全形→半形：ａ→a, １→1, ﾎﾟ→ポ）
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_INVISIBLE_CHAR_TABLE)
    # Edge Case 25: 剝除首尾成對引號/括號
    text = _strip_outer_quotes(text)
    return text


# Edge Case 25: 引號/括號配對表
_QUOTE_PAIRS = [
    ("「", "」"), ("『", "』"),
    ("\u201c", "\u201d"),  # ""
    ("\u2018", "\u2019"),  # ''
    ("\"", "\""), ("'", "'"),
    ("【", "】"), ("（", "）"), ("〈", "〉"),
]


def _strip_outer_quotes(text: str) -> str:
    """移除首尾成對的引號/括號（只剝除一層）。"""
    stripped = text.strip()
    for open_q, close_q in _QUOTE_PAIRS:
        if (
            stripped.startswith(open_q)
            and stripped.endswith(close_q)
            and len(stripped) > len(open_q) + len(close_q)
        ):
            stripped = stripped[len(open_q):-len(close_q)].strip()
            break  # 只剝除一層
    return stripped


def _has_meaningful_content(text: str) -> bool:
    """檢查文字是否包含有意義的字元（字母、CJK、假名等）。

    純空白、純符號、純 emoji 回傳 False。
    """
    return any(c.isalpha() for c in text)


def _is_supported_char(c: str) -> bool:
    """檢查字元是否屬於系統支援的語言範圍。

    支援：ASCII 字母、CJK 漢字、平假名、全形/半形片假名。
    """
    return (
        (c.isascii() and c.isalpha())
        or "\u4e00" <= c <= "\u9fff"   # CJK 漢字
        or "\u3040" <= c <= "\u309f"   # 平假名
        or "\u30a0" <= c <= "\u30ff"   # 全形片假名
        or "\uff65" <= c <= "\uff9f"   # 半形片假名（NFKC 後通常已轉全形，防禦性保留）
    )


def _has_supported_language_content(text: str) -> bool:
    """檢查文字是否包含系統支援語言的字元（ASCII + CJK + 假名）。

    已通過 _has_meaningful_content() 的文字若全是非支援語言（韓文、泰文等），
    此函式回傳 False。
    """
    return any(_is_supported_char(c) for c in text)


# Edge Case 13: 近似指令偵測（開頭匹配但有多餘字元，最多容忍 5 字元差距）
_COMMAND_HINTS: dict[str, str] = {
    "入庫": "入庫",
    "練習": "練習",
    "查詢": "查詢 <關鍵字>",
    "說明": "說明",
    "幫助": "說明",
    "統計": "統計",
    "進度": "統計",
    "用量": "用量",
    "隱私": "隱私",
    "刪除": "刪除 <關鍵字>",
    "清空": "清空資料",
    "結束": "結束練習",
    "停止": "結束練習",
}


def _suggest_command(text: str) -> str | None:
    """若輸入近似某個指令（開頭匹配但有多餘字元），回傳建議指令。"""
    stripped = text.strip()
    for cmd_prefix, full_cmd in _COMMAND_HINTS.items():
        prefix_len = len(cmd_prefix)
        if (
            prefix_len < len(stripped) <= prefix_len + 5
            and stripped.startswith(cmd_prefix)
        ):
            return full_cmd
    return None


def _is_url(text: str) -> bool:
    """檢查文字是否為 URL。"""
    lower = text.strip().lower()
    return lower.startswith(("http://", "https://"))


# Edge Case 23: Romaji 偵測用常見日語 token
_ROMAJI_MARKERS = frozenset({
    # 助詞
    "wa", "ga", "wo", "ni", "de", "to", "mo", "he", "no",
    # 語尾
    "desu", "masu", "mashita", "masen", "nai", "tai", "da", "datta",
    # 常見詞
    "watashi", "boku", "anata", "kore", "sore", "are",
    "nani", "doko", "dare", "itsu", "hai", "iie",
    "san", "kun", "chan", "sensei",
})


def _is_likely_romaji(text: str, target_lang: str) -> bool:
    """偵測是否為日語羅馬字拼音（IME 未開啟）。"""
    if target_lang != "ja":
        return False
    stripped = text.strip()
    if not all(c.isascii() for c in stripped):
        return False
    tokens = stripped.lower().split()
    if len(tokens) < 2:
        return False
    hits = sum(1 for t in tokens if t in _ROMAJI_MARKERS)
    return hits >= 2


# Edge Case 19: per-user lock，確保同一用戶的背景訊息依序處理
# 使用 OrderedDict 實作 LRU，限制最大數量避免記憶體洩漏
# ⚠️ 假設單 worker 部署：in-memory lock 不跨 process 共享
_MAX_USER_LOCKS = 1000
_user_locks: dict[str, asyncio.Lock] = {}

# 背景 task 集合：防止 asyncio.create_task 結果被 GC 回收
_background_tasks: set[asyncio.Task[None]] = set()

# Edge Case 28: Webhook 去重（in-memory TTL set）
# ⚠️ 假設單 worker 部署：in-memory dedup 不跨 process 共享
_processed_events: dict[str, float] = {}  # {webhook_event_id: timestamp}
_EVENT_DEDUP_TTL = 60  # 60 秒內的重複事件視為 retry
_MAX_DEDUP_EVENTS = 10000  # dedup dict 最大條目數


def _is_duplicate_event(event_id: str | None) -> bool:
    """檢查 webhook event 是否為重複（LINE retry）。"""
    if not event_id:
        return False
    now = time.monotonic()
    # 清理過期條目（懶惰清理，每次檢查時順便清）
    expired = [k for k, v in _processed_events.items() if now - v > _EVENT_DEDUP_TTL]
    for k in expired:
        del _processed_events[k]
    # 超過上限時清除最舊的一半
    if len(_processed_events) >= _MAX_DEDUP_EVENTS:
        oldest = sorted(_processed_events, key=lambda eid: _processed_events[eid])[:_MAX_DEDUP_EVENTS // 2]
        for k in oldest:
            del _processed_events[k]
    if event_id in _processed_events:
        logger.info(f"Duplicate webhook event detected: {event_id[:16]}...")
        return True
    _processed_events[event_id] = now
    return False


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
                task = asyncio.create_task(_with_user_lock(event, handle_message_event))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            else:
                await handle_message_event(event)
        elif isinstance(event, PostbackEvent):
            if background:
                task = asyncio.create_task(_with_user_lock(event, handle_postback_event))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            else:
                await handle_postback_event(event)

    return {"status": "ok"}


async def _with_user_lock(event: MessageEvent | PostbackEvent, handler: Callable[..., Any]) -> None:
    """以 per-user lock 執行 handler，確保同一用戶的事件依序處理（Edge Case 19）。

    背景安全處理，確保例外不會遺失。
    """
    try:
        user_id = event.source.user_id if event.source else None
        if user_id:
            if user_id not in _user_locks:
                # 超過上限時清除最舊的一半條目
                if len(_user_locks) >= _MAX_USER_LOCKS:
                    keys_to_remove = list(_user_locks.keys())[: _MAX_USER_LOCKS // 2]
                    for k in keys_to_remove:
                        # 只清除未被佔用的 lock
                        if not _user_locks[k].locked():
                            del _user_locks[k]
                _user_locks[user_id] = asyncio.Lock()
            lock = _user_locks[user_id]
            async with lock:
                await handler(event)
        else:
            await handler(event)
    except Exception as e:
        logger.exception(f"Background event handler failed: {e}")


async def handle_message_event(event: MessageEvent) -> None:
    """Handle a single message event."""
    line_client = get_line_client()

    # Edge Case 27: 非文字訊息回覆提示（貼圖、圖片、語音等）
    if not isinstance(event.message, TextMessageContent):
        reply_token = event.reply_token
        if reply_token:
            try:
                await line_client.reply_message(
                    reply_token, Messages.format("INPUT_NON_TEXT")
                )
            except Exception:
                logger.warning("Failed to reply to non-text message")
        return

    # Edge Case 28: Webhook 去重（LINE retry 機制可能重送同一 event）
    event_id = getattr(event, "webhook_event_id", None)
    if _is_duplicate_event(event_id):
        return

    text = _sanitize_text(event.message.text)
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
        has_pending_delete = False
        mode_saved = parsed.command_type != CommandType.MODE_SWITCH
        lang_saved = parsed.command_type != CommandType.SET_LANG
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
                    logger.debug(
                        "Profile loaded: mode=%s, target_lang=%s, user=%s",
                        profile.mode, profile.target_lang, hashed_uid[:8],
                    )
                except Exception as e:
                    logger.warning(f"Failed to load user profile, using defaults: {e}")

                # 檢查 pending_delete / pending_save 狀態
                user_state_repo = UserStateRepository(session)
                has_pending_delete = await user_state_repo.has_pending_delete(hashed_uid)
                has_pending_save = await user_state_repo.has_pending_save(hashed_uid)

                # 練習 session 中的答案處理（需查 DB）
                if parsed.command_type == CommandType.UNKNOWN and not has_pending_delete and not has_pending_save:
                    has_session = await has_active_session(session, hashed_uid)

                # 模式切換需在 reply 前完成
                if parsed.command_type == CommandType.MODE_SWITCH:
                    mode_key = _resolve_mode_key(parsed)
                    if mode_key:
                        try:
                            profile_repo = UserProfileRepository(session)
                            profile = await profile_repo.set_mode(hashed_uid, mode_key)
                            current_mode = profile.mode
                            mode_saved = True
                            logger.info("Mode switched to %s for user %s", mode_key, hashed_uid[:8])
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
                            lang_saved = True
                            logger.info("Target lang switched to %s for user %s", lang_key, hashed_uid[:8])
                        except Exception as e:
                            logger.warning(f"Failed to set target_lang: {e}")
                    else:
                        logger.warning(f"Could not resolve lang_key from: {parsed.keyword}")
        except Exception as e:
            logger.warning(f"Failed to open pre-dispatch session: {e}")

        # === Dispatch ===
        # 優先處理 pending_delete 狀態（必須在 pending_save 之前，否則 "1" 會被誤判）
        if has_pending_delete and text.strip().isdigit():
            # 數字輸入 → 選擇刪除項目
            response = await _handle_delete_select(hashed_uid, int(text.strip()))
        elif has_pending_delete and parsed.command_type in PENDING_SAFE_COMMANDS:
            # 安全指令不影響 pending_delete
            response = await _dispatch_command(
                command=parsed,
                line_user_id=user_id,
                raw_text=text,
                mode=current_mode,
                target_lang=target_lang,
            )
        elif has_pending_delete:
            # 非數字、非安全指令 → 清除 pending_delete + 正常分派
            async with get_session() as session:
                user_state_repo = UserStateRepository(session)
                await user_state_repo.clear_pending_delete(hashed_uid)
            response = await _dispatch_command(
                command=parsed,
                line_user_id=user_id,
                raw_text=text,
                mode=current_mode,
                target_lang=target_lang,
            )
        # 處理 pending_save 狀態
        elif parsed.command_type == CommandType.CONFIRM_SAVE and has_pending_save:
            # 用戶輸入「1」確認入庫
            response = await _handle_confirm_save(hashed_uid, user_id, current_mode, target_lang)
        elif has_pending_save and parsed.command_type == CommandType.SAVE:
            # 用戶輸入「入庫」→ 視同確認，直接儲存 pending 內容
            response = await _handle_confirm_save(hashed_uid, user_id, current_mode, target_lang)
        elif has_pending_save and parsed.command_type not in PENDING_SAFE_COMMANDS:
            # Edge Case 24: 單一數字 0-9 但非「1」→ 提示，不清除 pending
            stripped_input = text.strip()
            if len(stripped_input) == 1 and stripped_input in "023456789":
                response = Messages.format("PENDING_WRONG_NUMBER")
            else:
                # 非安全指令（新的 UNKNOWN 輸入等）→ 取得舊 pending + 清除 + 處理新輸入
                discarded_word = None
                async with get_session() as session:
                    user_state_repo = UserStateRepository(session)
                    discarded_word = await user_state_repo.get_pending_save(hashed_uid)
                    await user_state_repo.clear_pending_save(hashed_uid)
                response = await _dispatch_command(
                    command=parsed,
                    line_user_id=user_id,
                    raw_text=text,
                    mode=current_mode,
                    target_lang=target_lang,
                )
                # 在回覆前加上取消通知
                if discarded_word:
                    notice = Messages.format("PENDING_DISCARDED", word=discarded_word)
                    response = f"{notice}\n\n{response}"
        elif parsed.command_type == CommandType.CONFIRM_SAVE and not has_pending_save:
            # 輸入「1」但無 pending_save → 明確告知可能已過期
            response = Messages.PENDING_EXPIRED
        elif parsed.command_type == CommandType.EXIT_PRACTICE:
            response = await _handle_exit_practice(hashed_uid)
        elif parsed.command_type == CommandType.UNKNOWN and has_session:
            response = await _handle_practice_answer(hashed_uid, text, current_mode, target_lang)
        elif parsed.command_type == CommandType.MODE_SWITCH:
            mode_key = _resolve_mode_key(parsed)
            if mode_key:
                if mode_saved:
                    response = format_mode_switch_confirm(mode_key)
                else:
                    response = Messages.ERROR_GENERIC
            else:
                response = Messages.FALLBACK_UNKNOWN
        elif parsed.command_type == CommandType.SET_LANG:
            lang_key = _resolve_lang_key(parsed)
            if lang_key:
                if lang_saved:
                    response = format_lang_switch_confirm(lang_key)
                else:
                    response = Messages.ERROR_GENERIC
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
        need_save_last_msg = (
            parsed.command_type == CommandType.UNKNOWN
            and not has_session
            and _has_meaningful_content(text)
        )
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
        return format_help_with_status(mode, target_lang)

    if command_type == CommandType.PRIVACY:
        return Messages.PRIVACY

    if command_type == CommandType.SAVE:
        return await _handle_save(line_user_id, mode, target_lang)

    if command_type == CommandType.WORD_SAVE:
        return await _handle_word_save(line_user_id, command.keyword, mode, target_lang)

    if command_type == CommandType.SEARCH:
        return await _handle_search(line_user_id, command.keyword)

    if command_type == CommandType.PRACTICE:
        return await _handle_practice(line_user_id, mode, target_lang)

    if command_type == CommandType.DELETE_ITEM:
        return await _handle_delete_item(line_user_id, command.keyword)

    if command_type == CommandType.DELETE_ALL:
        return await _handle_delete_all_request(line_user_id)

    if command_type == CommandType.COST:
        return await _handle_cost(line_user_id)

    if command_type == CommandType.STATS:
        return await _handle_stats(line_user_id)

    if command_type == CommandType.LIST_ITEMS:
        return await _handle_list_items(line_user_id, command.keyword)

    if command_type == CommandType.DELETE_CONFIRM:
        return await _handle_delete_confirm(line_user_id)

    return await _handle_unknown(line_user_id, raw_text, mode, target_lang)


async def _auto_extract(
    hashed_uid: str,
    doc_id: str,
    mode: str,
    target_lang: str,
) -> str | None:
    """自動抽取已入庫文件的單字/文法。

    Args:
        hashed_uid: Hashed LINE user ID
        doc_id: 剛建立的 document ID
        mode: LLM mode
        target_lang: 目標語言

    Returns:
        抽取摘要字串（如「1 個單字 和 2 個文法」），失敗時回傳 None
    """
    try:
        async with get_session() as session:
            from src.services.extractor_service import (
                ExtractorService,
                create_extraction_summary,
            )

            extractor = ExtractorService(session)
            result = await extractor.extract(
                doc_id=doc_id,
                user_id=hashed_uid,
                mode=mode,
                target_lang=target_lang,
            )

            summary = create_extraction_summary(result)
            if summary.total_count == 0:
                return None
            # 組裝摘要文字（如「1 個單字 和 2 個文法」）
            parts = []
            if summary.vocab_count > 0:
                parts.append(f"{summary.vocab_count} 個單字")
            if summary.grammar_count > 0:
                parts.append(f"{summary.grammar_count} 個文法")
            return " 和 ".join(parts)
    except Exception as e:
        logger.error(f"Auto-extract failed for doc {doc_id}: {e}")
        return None


async def _handle_save(line_user_id: str, mode: str = "free", target_lang: str = "ja") -> str:
    """處理入庫指令。"""
    hashed_uid = hash_user_id(line_user_id)

    async with get_session() as session:
        user_state_repo = UserStateRepository(session)
        previous_content = await user_state_repo.get_last_message(hashed_uid)

        if not previous_content or not _has_meaningful_content(previous_content):
            return Messages.SAVE_NO_CONTENT

        service = CommandService(session)
        result = await service.save_raw(
            line_user_id=line_user_id,
            content_text=previous_content,
        )

        await user_state_repo.clear_last_message(hashed_uid)

    if not result.success:
        return result.message

    # 自動抽取
    doc_id = str(result.data["doc_id"]) if result.data.get("doc_id") else None
    if doc_id:
        summary = await _auto_extract(hashed_uid, doc_id, mode, target_lang)
        if summary:
            return Messages.format("SAVE_AND_EXTRACT_SUCCESS", summary=summary)
        return Messages.format("SAVE_EXTRACT_FAILED_HINT")
    return result.message


async def _handle_word_save(
    line_user_id: str,
    word: str | None,
    mode: str = "free",
    target_lang: str = "ja",
) -> str:
    """處理「單字 入庫」直接入庫指令。"""
    if not word or not _has_meaningful_content(word):
        return Messages.SAVE_NO_CONTENT

    hashed_uid = hash_user_id(line_user_id)

    async with get_session() as session:
        service = CommandService(session)
        result = await service.save_raw(
            line_user_id=line_user_id,
            content_text=word,
        )

    if not result.success:
        return result.message

    # 自動抽取
    doc_id = str(result.data["doc_id"]) if result.data.get("doc_id") else None
    if doc_id:
        summary = await _auto_extract(hashed_uid, doc_id, mode, target_lang)
        if summary:
            return Messages.format("WORD_SAVE_AND_EXTRACT", word=word)
    return result.message


async def _handle_confirm_save(
    hashed_uid: str,
    line_user_id: str,
    mode: str = "free",
    target_lang: str = "ja",
) -> str:
    """處理確認入庫（用戶輸入「1」）。"""
    async with get_session() as session:
        user_state_repo = UserStateRepository(session)
        raw_content = await user_state_repo.get_pending_save(hashed_uid)

        if not raw_content:
            return Messages.PENDING_EXPIRED

        # 解析新舊格式
        pending_word, extracted_item = user_state_repo.parse_pending_save_content(raw_content)

        service = CommandService(session)
        result = await service.save_raw(
            line_user_id=line_user_id,
            content_text=pending_word,
        )

        await user_state_repo.clear_pending_save(hashed_uid)

    if not result.success:
        return result.message

    doc_id = str(result.data["doc_id"]) if result.data.get("doc_id") else None

    # 有預先抽取的 item → 直接建立 item（跳過 ExtractorService）
    if extracted_item and doc_id:
        try:
            async with get_session() as session:
                from src.repositories.item_repo import ItemRepository
                from src.schemas.extractor import ExtractedItem

                item_repo = ItemRepository(session)
                item = ExtractedItem(**extracted_item)
                await item_repo.upsert(
                    user_id=hashed_uid,
                    doc_id=doc_id,
                    item_type=item.item_type,
                    key=item.key,
                    payload=item.to_payload(),
                    source_quote=item.source_quote,
                    confidence=item.confidence,
                )
                # 更新 document 狀態為 parsed
                from src.repositories.document_repo import DocumentRepository

                doc_repo = DocumentRepository(session)
                await doc_repo.update(
                    doc_id, parse_status="parsed", parser_version="v1.0.0"
                )

            return Messages.format("WORD_SAVE_AND_EXTRACT", word=pending_word)
        except Exception as e:
            logger.warning(f"Direct item creation failed, falling back to auto-extract: {e}")

    # 無 item 或直接建立失敗 → auto-extract
    if doc_id:
        summary = await _auto_extract(hashed_uid, doc_id, mode, target_lang)
        if summary:
            return Messages.format("WORD_SAVE_AND_EXTRACT", word=pending_word)

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
    hashed_uid = hash_user_id(line_user_id)
    async with get_session() as session:
        from src.services.cost_service import CostService

        cost_service = CostService(session)

        try:
            result = await cost_service.get_usage_summary(hashed_uid)
            return result.message
        except Exception as e:
            logger.error(f"Cost query failed: {e}")
            return Messages.ERROR_COST


async def _handle_stats(line_user_id: str) -> str:
    """處理統計指令。"""
    hashed_uid = hash_user_id(line_user_id)
    async with get_session() as session:
        from src.services.stats_service import StatsService

        stats_service = StatsService(session)

        try:
            result = await stats_service.get_stats_summary(hashed_uid)
            return result.message
        except Exception as e:
            logger.error(f"Stats query failed: {e}")
            return Messages.ERROR_STATS


async def _handle_list_items(line_user_id: str, keyword: str | None) -> str:
    """處理清單指令，列出使用者所有項目。"""
    hashed_user_id = hash_user_id(line_user_id)

    # 判斷篩選類型
    type_filter: str | None = None
    if keyword == "單字":
        type_filter = "vocab"
    elif keyword == "文法":
        type_filter = "grammar"

    async with get_session() as session:
        from src.repositories.item_repo import ItemRepository

        item_repo = ItemRepository(session)

        try:
            items = await item_repo.get_by_user(
                user_id=hashed_user_id,
                item_type=type_filter,
                limit=200,
            )

            if not items:
                return Messages.LIST_ITEMS_EMPTY

            return _format_list_items(items, type_filter)

        except Exception as e:
            logger.error(f"List items failed: {e}")
            return Messages.ERROR_LIST_ITEMS


def _format_list_items(items: "Sequence[Item]", type_filter: str | None) -> str:
    """格式化項目清單為使用者友善的訊息。"""
    vocab_items = [i for i in items if i.item_type == "vocab"]
    grammar_items = [i for i in items if i.item_type == "grammar"]
    total = len(items)

    lines = [Messages.format("LIST_ITEMS_HEADER", total=total)]

    # 單字區塊
    if vocab_items and type_filter != "grammar":
        lines.append(Messages.format("LIST_ITEMS_VOCAB_HEADER", count=len(vocab_items)))
        for i, item in enumerate(vocab_items, 1):
            payload = item.payload or {}
            surface = payload.get("surface", "")
            reading = payload.get("reading", "")
            pronunciation = payload.get("pronunciation", "")
            glossary = payload.get("glossary_zh", [])
            meaning = glossary[0] if glossary else ""

            if reading and reading != surface:
                lines.append(f"{i}. {surface}【{reading}】- {meaning}")
            elif pronunciation:
                lines.append(f"{i}. {surface} ({pronunciation}) - {meaning}")
            else:
                lines.append(f"{i}. {surface} - {meaning}")

    # 文法區塊
    if grammar_items and type_filter != "vocab":
        lines.append(Messages.format("LIST_ITEMS_GRAMMAR_HEADER", count=len(grammar_items)))
        for i, item in enumerate(grammar_items, 1):
            payload = item.payload or {}
            pattern = payload.get("pattern", "")
            meaning = payload.get("meaning_zh", "")
            lines.append(f"{i}. {pattern} - {meaning}")

    return "\n".join(lines)


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


async def _handle_exit_practice(hashed_user_id: str) -> str:
    """處理結束練習指令。"""
    async with get_session() as session:
        from src.services.session_service import SessionService

        session_service = SessionService(session)
        has_session = await session_service.has_active_session(hashed_user_id)

        if not has_session:
            return Messages.format("PRACTICE_EXIT_NO_SESSION")

        await session_service.clear_session(hashed_user_id)
        return Messages.format("PRACTICE_EXIT")


async def _handle_delete_item(line_user_id: str, keyword: str | None) -> str:
    """處理「刪除 <關鍵字>」指令。"""
    if not keyword:
        return Messages.DELETE_ITEM_HINT

    hashed_user_id = hash_user_id(line_user_id)

    async with get_session() as session:
        from src.repositories.item_repo import ItemRepository
        from src.services.delete_service import DeleteService

        item_repo = ItemRepository(session)

        try:
            items = await item_repo.search_by_keyword(
                user_id=hashed_user_id,
                keyword=keyword,
                limit=MAX_SEARCH_RESULTS,
            )

            if not items:
                return Messages.format("DELETE_ITEM_NOT_FOUND", keyword=keyword)

            if len(items) == 1:
                # 單筆直接刪除
                delete_service = DeleteService(session)
                _, message = await delete_service.delete_item(
                    hashed_user_id, str(items[0].item_id)
                )
                return message

            if len(items) <= 5:
                # 2-5 筆：顯示列表 + 存 pending_delete
                candidates = _build_delete_candidates(items)
                list_text = _format_delete_candidates(candidates)
                user_state_repo = UserStateRepository(session)
                await user_state_repo.set_pending_delete(hashed_user_id, candidates)
                return Messages.format(
                    "DELETE_ITEM_SELECT",
                    count=len(items),
                    keyword=keyword,
                    list=list_text,
                )

            # >5 筆：顯示前 5 筆 + 請更精確
            candidates = _build_delete_candidates(items[:5])
            list_text = _format_delete_candidates(candidates)
            return Messages.format(
                "DELETE_ITEM_TOO_MANY",
                count=len(items),
                keyword=keyword,
                list=list_text,
            )

        except Exception as e:
            logger.error(f"Delete item failed: {e}")
            return Messages.ERROR_DELETE


async def _handle_delete_select(hashed_uid: str, number: int) -> str:
    """處理 pending_delete 狀態下的編號選擇。"""
    async with get_session() as session:
        from src.services.delete_service import DeleteService

        user_state_repo = UserStateRepository(session)
        candidates = await user_state_repo.get_pending_delete(hashed_uid)

        if not candidates:
            return Messages.format("DELETE_SELECT_EXPIRED")

        if number < 1 or number > len(candidates):
            return Messages.format("DELETE_ITEM_INVALID_NUMBER", max=len(candidates))

        selected = candidates[number - 1]
        delete_service = DeleteService(session)
        success, message = await delete_service.delete_item(
            hashed_uid, selected["item_id"]
        )

        await user_state_repo.clear_pending_delete(hashed_uid)
        return message


def _build_delete_candidates(items: "Sequence[Item]") -> list[dict[str, str]]:
    """將 Item 列表轉為 pending_delete 候選項格式。"""
    from src.services.delete_service import DeleteService

    candidates: list[dict[str, str]] = []
    for item in items:
        label = DeleteService._format_item_label(item)
        candidates.append({"item_id": str(item.item_id), "label": label})
    return candidates


def _format_delete_candidates(candidates: list[dict[str, str]]) -> str:
    """格式化刪除候選項為編號列表。"""
    lines: list[str] = []
    for i, c in enumerate(candidates, 1):
        lines.append(f"{i}. {c['label']}")
    return "\n".join(lines)


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
    # Edge Case 13: 近似指令偵測（如「入庫了」→ 建議「入庫」）
    suggestion = _suggest_command(raw_text)
    if suggestion:
        return Messages.format("COMMAND_SUGGESTION", command=suggestion)

    # Edge Case 11/14: 無意義內容（純 emoji、純符號、純空白）
    if not _has_meaningful_content(raw_text):
        return Messages.format("INPUT_NO_MEANINGFUL_CONTENT")

    # Edge Case 18: URL 偵測
    if _is_url(raw_text):
        return Messages.format("INPUT_URL_DETECTED")

    # Edge Case 23: Romaji 偵測（IME 未開啟）
    if _is_likely_romaji(raw_text, target_lang):
        return Messages.format("INPUT_LIKELY_ROMAJI")

    # Edge Case 29: 非支援語言偵測（韓文、泰文等）
    # 必須在 TSV / 長文本自動入庫之前檢查，避免非支援語言被存入 DB
    if not _has_supported_language_content(raw_text):
        return Messages.format("INPUT_UNSUPPORTED_LANG")

    # Edge Case 20: TSV 格式偵測（試算表複製貼上）→ 直接入庫 + 自動抽取
    if '\t' in raw_text:
        return await _save_and_extract(line_user_id, raw_text, mode, target_lang)

    # Edge Case 26: 超長文本直接入庫 + 自動抽取（跳過 Router 節省 LLM tokens）
    if len(raw_text) > LONG_TEXT_THRESHOLD:
        return await _save_and_extract(line_user_id, raw_text, mode, target_lang)

    from src.lib.llm_client import LLMResponse, LLMTrace
    from src.schemas.router import IntentType
    from src.services.router_service import get_router_service

    hashed_user_id = hash_user_id(line_user_id)
    router_service = get_router_service()

    # 收集 LLM traces，在 finally 區塊批次寫入 DB
    llm_traces: list[tuple[LLMTrace, str]] = []

    def _collect_trace(resp: LLMResponse | None, operation: str) -> None:
        if resp is not None:
            llm_traces.append((resp.to_trace(), operation))

    try:
        # 短單字直接翻譯（跳過 Router LLM 節省一次 API 呼叫）
        if _is_short_word_input(raw_text, target_lang):
            word = raw_text.strip()
            db_items = await _search_user_items(hashed_user_id, word)
            if db_items:
                return _format_search_results(db_items)
            try:
                display, extracted_item, word_trace = await router_service.get_word_explanation_structured(
                    word, mode=mode, target_lang=target_lang
                )
                if word_trace:
                    llm_traces.append((word_trace, "word_explanation"))
            except Exception:
                return Messages.ERROR_API_CALL
            async with get_session() as session:
                user_state_repo = UserStateRepository(session)
                if extracted_item:
                    await user_state_repo.set_pending_save_with_item(hashed_user_id, word, extracted_item)
                else:
                    await user_state_repo.set_pending_save(hashed_user_id, word)
            return Messages.format("WORD_EXPLANATION", explanation=display)

        classification, classify_resp = await router_service.classify(
            raw_text, mode=mode, target_lang=target_lang,
        )
        _collect_trace(classify_resp, "router_classify")

        if classification.intent == IntentType.SAVE and classification.confidence >= 0.8:
            # 判斷是否為短單字（根據語言調整閾值）
            stripped_text = raw_text.strip()
            if target_lang == "ja":
                # 日文：通常 1-10 字元，設 15 為上限；需為單一 token
                is_short_word = len(stripped_text) <= 15 and len(stripped_text.split()) == 1
            else:
                # 英文：單字通常無空白且較短（split 涵蓋空格、換行、Tab）
                is_short_word = len(stripped_text) <= 30 and len(stripped_text.split()) == 1

            if is_short_word:
                # 短單字流程：先查 DB，已入庫則直接顯示
                word = raw_text.strip()
                db_items = await _search_user_items(hashed_user_id, word)
                if db_items:
                    return _format_search_results(db_items)
                # DB 無紀錄：LLM 解釋 + 詢問入庫
                try:
                    display, extracted_item, word_trace = await router_service.get_word_explanation_structured(
                        word, mode=mode, target_lang=target_lang
                    )
                    if word_trace:
                        llm_traces.append((word_trace, "word_explanation"))
                except Exception:
                    return Messages.ERROR_API_CALL
                async with get_session() as session:
                    user_state_repo = UserStateRepository(session)
                    if extracted_item:
                        await user_state_repo.set_pending_save_with_item(hashed_user_id, word, extracted_item)
                    else:
                        await user_state_repo.set_pending_save(hashed_user_id, word)
                return Messages.format("WORD_EXPLANATION", explanation=display)
            else:
                # 偵測多個空格分隔的短單字（例如 "apple banana cherry"）
                tokens = stripped_text.split()
                is_multi_word = (
                    2 <= len(tokens) <= 5
                    and all(len(t) <= 30 for t in tokens)
                    and all(t.isalpha() or all(c.isalpha() or c == '-' for c in t) for t in tokens)
                )
                if is_multi_word:
                    # 處理第一個單字，提示其餘逐一輸入
                    first_word = tokens[0]
                    try:
                        display, extracted_item, word_trace = await router_service.get_word_explanation_structured(
                            first_word, mode=mode, target_lang=target_lang
                        )
                        if word_trace:
                            llm_traces.append((word_trace, "word_explanation"))
                    except Exception:
                        return Messages.ERROR_API_CALL
                    async with get_session() as session:
                        user_state_repo = UserStateRepository(session)
                        if extracted_item:
                            await user_state_repo.set_pending_save_with_item(hashed_user_id, first_word, extracted_item)
                        else:
                            await user_state_repo.set_pending_save(hashed_user_id, first_word)
                    remaining = "、".join(f"「{t}」" for t in tokens[1:])
                    base = Messages.format("WORD_EXPLANATION", explanation=display)
                    return f"{base}\n\n{format_word_multi_detected(first_word, remaining)}"
                else:
                    # 長文本：直接入庫 + 自動抽取
                    return await _save_and_extract(line_user_id, raw_text, mode, target_lang)

        if classification.intent == IntentType.CHAT:
            chat_resp = await router_service.get_chat_response(
                raw_text, mode=mode, target_lang=target_lang,
            )
            _collect_trace(chat_resp, "chat")
            return chat_resp.content

        if classification.intent == IntentType.HELP:
            return format_help_with_status(mode, target_lang)

        if classification.intent == IntentType.PRACTICE:
            return await _handle_practice(line_user_id, mode, target_lang)

        if classification.intent == IntentType.DELETE:
            return Messages.format("DELETE_HINT_USAGE")

        if classification.intent == IntentType.SEARCH and classification.keyword:
            items = await _search_user_items(hashed_user_id, classification.keyword)
            if items:
                return _format_search_results(items)

            # DB 無結果 + 單字 → LLM 解釋 + 詢問入庫
            keyword = classification.keyword
            if _is_single_word(keyword, target_lang):
                try:
                    display, extracted_item, word_trace = await router_service.get_word_explanation_structured(
                        keyword, mode=mode, target_lang=target_lang
                    )
                    if word_trace:
                        llm_traces.append((word_trace, "word_explanation"))
                except Exception:
                    return Messages.ERROR_API_CALL
                async with get_session() as session:
                    user_state_repo = UserStateRepository(session)
                    if extracted_item:
                        await user_state_repo.set_pending_save_with_item(hashed_user_id, keyword, extracted_item)
                    else:
                        await user_state_repo.set_pending_save(hashed_user_id, keyword)
                return Messages.format("WORD_EXPLANATION", explanation=display)

            return format_search_no_result(keyword)

        return Messages.FALLBACK_UNKNOWN

    except Exception as e:
        logger.error(f"Router failed: {e}")
        return Messages.ERROR_GENERIC

    finally:
        # 批次寫入 LLM traces — 失敗不影響使用者回覆
        if llm_traces:
            try:
                from src.repositories.api_usage_log_repo import ApiUsageLogRepository

                async with get_session() as session:
                    repo = ApiUsageLogRepository(session)
                    for trace, operation in llm_traces:
                        await repo.create_log(
                            user_id=hashed_user_id,
                            trace=trace,
                            operation=operation,
                        )
            except Exception:
                logger.warning("Failed to write LLM traces to DB", exc_info=True)



async def _save_and_extract(
    line_user_id: str,
    content: str,
    mode: str = "free",
    target_lang: str = "ja",
) -> str:
    """入庫原始內容並自動抽取單字/文法。"""
    hashed_uid = hash_user_id(line_user_id)

    async with get_session() as session:
        service = CommandService(session)
        result = await service.save_raw(line_user_id=line_user_id, content_text=content)
    if not result.success:
        return result.message

    doc_id = str(result.data["doc_id"]) if result.data.get("doc_id") else None

    if doc_id:
        summary = await _auto_extract(hashed_uid, doc_id, mode, target_lang)
        if summary:
            return Messages.format("SAVE_AND_EXTRACT_SUCCESS", summary=summary)
        return Messages.format("SAVE_EXTRACT_FAILED_HINT")
    return result.message


# ============================================================================
# Helper Functions
# ============================================================================


def _is_single_word(text: str, target_lang: str) -> bool:
    """判斷文字是否為可用 LLM 解釋的單一短字詞。"""
    stripped = text.strip()
    if len(stripped.split()) != 1:
        return False
    return len(stripped) <= 15 if target_lang == "ja" else len(stripped) <= 30


def _is_short_word_input(text: str, target_lang: str) -> bool:
    """判斷輸入是否為可直接翻譯的單一詞彙（跳過 Router LLM）。

    條件：
    - 單一 token（無空格）
    - 非問句
    - 語言符合 target_lang 且長度在合理範圍內
    """
    stripped = text.strip()

    # 必須是單一 token
    if len(stripped.split()) != 1:
        return False

    # 問句不攔截，交給 Router 判斷 CHAT
    if any(q in stripped for q in ("?", "？", "嗎", "什麼", "怎麼", "如何")):
        return False

    if target_lang == "en":
        # 英文模式：主要由 ASCII 字母組成（允許連字符，如 "well-known"）
        alpha_chars = sum(1 for c in stripped if c.isalpha() and c.isascii())
        total = max(len(stripped), 1)
        return alpha_chars / total > 0.8 and 1 <= len(stripped) <= 30

    else:  # ja
        # 日文模式：必須含假名或漢字
        has_kana = any('\u3040' <= c <= '\u30ff' or '\uff65' <= c <= '\uff9f' for c in stripped)
        has_cjk = any('\u4e00' <= c <= '\u9fff' for c in stripped)
        return (has_kana or has_cjk) and 1 <= len(stripped) <= 15


async def _search_user_items(hashed_user_id: str, keyword: str, limit: int = MAX_SEARCH_RESULTS) -> list[Item]:
    """在使用者 items 中搜尋關鍵字。"""
    from src.repositories.item_repo import ItemRepository

    async with get_session() as session:
        item_repo = ItemRepository(session)
        return await item_repo.search_by_keyword(
            user_id=hashed_user_id, keyword=keyword, limit=limit,
        )


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

