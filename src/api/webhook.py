"""LINE webhook handler.

T028: Create LINE webhook handler in src/api/webhook.py
T029: Wire up "入庫" command to save raw and create deferred doc
T030: Add validation for empty/missing previous message
T031: Format LINE reply message for save confirmation
T049: Wire up "練習" command to PracticeService
"""

import asyncio
import enum
import json
import logging
import re
import time
import unicodedata
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import parse_qs

from fastapi import APIRouter, Header, HTTPException, Request
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
)

from src.config import settings
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
    CommandType.COMPLETE_ARTICLE,
}


# LINE 訊息長度上限（預留 footer 空間）
LINE_MESSAGE_MAX_LENGTH = 5000
FOOTER_RESERVE = 300

# Edge Case 26: 超長文本直接入庫閾值（超過此長度跳過 Router）
LONG_TEXT_THRESHOLD = 2000

# 英文複合詞偵測閾值：2 token 且去空格後總字元 ≤ 此值視為單一複合詞（如 "ice cream", "to be"），
# 不切分為多單字。15 字元涵蓋常見 2 詞複合詞（平均英文單字 ~5 字元 × 2 + 餘裕）。
_COMPOUND_WORD_MAX_CHARS = 15
_COMPOUND_WORD_MAX_TOKENS = 2

# 多單字偵測：每個 token 的最大字元數（日文單字一般 1-8 字元）
_MULTI_WORD_TOKEN_MAX_CHARS = 10


# ============================================================================
# 輸入分類（取代 LLM Router）
# ============================================================================


class InputCategory(enum.Enum):
    """使用者輸入的結構性分類。

    以假名/CJK/標點/長度等結構特徵做確定性分類，
    不需要 LLM 呼叫。
    """

    WORD = "word"          # 單字或短詞 → 查詞解釋 + pending save
    MATERIAL = "material"  # 素材（句子/段落）→ 直接入庫 + 自動抽取
    CHAT = "chat"          # 中文問答 → LLM chat
    UNKNOWN = "unknown"    # 無法判斷 → fallback


# 素材判定長度閾值（字元數）
_MATERIAL_LENGTH_THRESHOLD = 20

# 中文問句標記（_sanitize_text 做 NFKC 正規化後，？→?）
_QUESTION_MARKERS = ("?", "嗎", "什麼", "怎麼", "如何")

# 句讀標點（表示輸入為句子而非單字）
# NFKC 正規化後 ！→!、？→?，所以只用半形
_SENTENCE_PUNCTUATION_JA = ("。", "!", "?", "、", ",")
_SENTENCE_PUNCTUATION_EN = (".", "!", "?")


def _classify_input(text: str, target_lang: str = "ja") -> InputCategory:
    """根據結構特徵分類使用者輸入。

    分類邏輯：
    1. 含假名 → 日文內容（有句讀/換行/長度>20 → MATERIAL，否則 → WORD）
    2. 無假名、有 CJK → 歧義（中文問句 → CHAT，≤20字 → WORD，>20字 → MATERIAL）
    3. 英文為主 → （有句讀/換行 → MATERIAL，單字 → WORD，2-5短token → WORD，其他 → MATERIAL）
    4. 有中文問句標記 → CHAT
    5. 其他 → UNKNOWN

    注意：此函式假設輸入已經過 _sanitize_text() 處理（NFKC 正規化）。
    """
    stripped = text.strip()
    if not stripped:
        return InputCategory.UNKNOWN

    # 字元統計
    has_kana = False
    has_cjk = False
    ascii_alpha_count = 0
    total_non_space = 0

    for c in stripped:
        if c.isspace():
            continue
        total_non_space += 1
        if "\u3040" <= c <= "\u309f" or "\u30a0" <= c <= "\u30ff" or "\uff65" <= c <= "\uff9f":
            has_kana = True
        elif "\u4e00" <= c <= "\u9fff":
            has_cjk = True
        elif c.isascii() and c.isalpha():
            ascii_alpha_count += 1

    if total_non_space == 0:
        return InputCategory.UNKNOWN

    has_newline = "\n" in stripped
    has_question_marker = any(q in stripped for q in _QUESTION_MARKERS)

    # --- 1. 含假名 → 日文內容 ---
    if has_kana:
        has_ja_punct = any(p in stripped for p in _SENTENCE_PUNCTUATION_JA)
        if has_ja_punct:
            return InputCategory.MATERIAL
        # 空格/換行分隔的多個短 token → 多單字輸入，不是文章
        tokens = stripped.split()
        if all(len(t) <= _MULTI_WORD_TOKEN_MAX_CHARS for t in tokens):
            return InputCategory.WORD
        if has_newline or len(stripped) > _MATERIAL_LENGTH_THRESHOLD:
            return InputCategory.MATERIAL
        return InputCategory.WORD

    # --- 2. 無假名、有 CJK → 歧義（中/日漢字） ---
    if has_cjk:
        if has_question_marker:
            return InputCategory.CHAT
        if len(stripped) <= _MATERIAL_LENGTH_THRESHOLD:
            return InputCategory.WORD
        return InputCategory.MATERIAL

    # --- 3. 英文為主 ---
    english_ratio = ascii_alpha_count / total_non_space
    if english_ratio > 0.5:
        has_en_punct = any(p in stripped for p in _SENTENCE_PUNCTUATION_EN)
        if has_en_punct:
            return InputCategory.MATERIAL

        tokens = stripped.split()
        if len(tokens) == 1:
            return InputCategory.WORD

        # 多個短 alpha token → 多單字輸入，視為 WORD（移到 newline 檢查之前）
        if len(tokens) >= 2 and all(
            len(t) <= 30 and all(ch.isalpha() or ch == "-" for ch in t)
            for t in tokens
        ):
            return InputCategory.WORD

        if has_newline:
            return InputCategory.MATERIAL
        return InputCategory.MATERIAL

    # --- 4. 有中文問句標記 → CHAT ---
    if has_question_marker:
        return InputCategory.CHAT

    # --- 5. 無法判斷 ---
    return InputCategory.UNKNOWN


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
_processed_events: dict[str, float] = {}  # {webhook_event_id: timestamp}（Python 3.7+ 維持插入順序）
_EVENT_DEDUP_TTL = 60  # 60 秒內的重複事件視為 retry
_MAX_DEDUP_EVENTS = 10000  # dedup dict 最大條目數


def _is_duplicate_event(event_id: str | None) -> bool:
    """檢查 webhook event 是否為重複（LINE retry）。"""
    if not event_id:
        return False
    now = time.monotonic()

    if event_id in _processed_events:
        logger.info("Duplicate webhook event detected: %s...", event_id[:16])
        return True

    _processed_events[event_id] = now

    # 惰性清理：僅在超過上限時批次清除（利用 dict 插入順序）
    if len(_processed_events) >= _MAX_DEDUP_EVENTS:
        cutoff = now - _EVENT_DEDUP_TTL
        stale_keys = [k for k, v in _processed_events.items() if v < cutoff]
        for k in stale_keys:
            del _processed_events[k]
        # 若清完過期仍超限，移除最舊的一半
        if len(_processed_events) >= _MAX_DEDUP_EVENTS:
            to_remove = list(_processed_events.keys())[: len(_processed_events) // 2]
            for k in to_remove:
                del _processed_events[k]

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
    background = settings.is_production

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
        raw_user_id = event.source.user_id if event.source else None
        if raw_user_id:
            # 使用 hashed user ID 作為 key，避免在記憶體中保留原始 LINE user ID
            lock_key = hash_user_id(raw_user_id)
            if lock_key not in _user_locks:
                # 超過上限時清除最舊的一半條目
                if len(_user_locks) >= _MAX_USER_LOCKS:
                    keys_to_remove = list(_user_locks.keys())[: _MAX_USER_LOCKS // 2]
                    for k in keys_to_remove:
                        # 只清除未被佔用的 lock
                        if not _user_locks[k].locked():
                            del _user_locks[k]
                _user_locks[lock_key] = asyncio.Lock()
            lock = _user_locks[lock_key]
            async with lock:
                await handler(event)
        else:
            await handler(event)
    except Exception as e:
        logger.exception("Background event handler failed: %s", e)


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
        has_article_mode = False
        article_text: str | None = None
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
                    logger.warning("Failed to load user profile, using defaults: %s", e)

                # 檢查 pending_delete / pending_save / article_mode 狀態
                user_state_repo = UserStateRepository(session)
                has_pending_delete = await user_state_repo.has_pending_delete(hashed_uid)
                has_pending_save = await user_state_repo.has_pending_save(hashed_uid)
                article_text = await user_state_repo.get_article_mode(hashed_uid)
                has_article_mode = article_text is not None

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
                            logger.warning("Failed to set mode: %s", e)

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
                            logger.warning("Failed to set target_lang: %s", e)
                    else:
                        logger.warning("Could not resolve lang_key from: %s", parsed.keyword)
        except Exception as e:
            logger.warning("Failed to open pre-dispatch session: %s", e)

        # === Dispatch ===
        # 優先處理 pending_delete 狀態（必須在 pending_save 之前，否則 "1" 會被誤判）
        if has_pending_delete and text.strip().isdigit():
            # 數字輸入 → 選擇刪除項目
            response = await _handle_delete_select(hashed_uid, int(text.strip()))
        elif has_pending_delete and parsed.command_type in PENDING_SAFE_COMMANDS:
            # 安全指令不影響 pending_delete
            response = await _with_thinking_indicator(
                user_id,
                _dispatch_command(
                    command=parsed,
                    line_user_id=user_id,
                    raw_text=text,
                    mode=current_mode,
                    target_lang=target_lang,
                ),
            )
        elif has_pending_delete:
            # 非數字、非安全指令 → 清除 pending_delete + 正常分派
            async with get_session() as session:
                user_state_repo = UserStateRepository(session)
                await user_state_repo.clear_pending_delete(hashed_uid)
            response = await _with_thinking_indicator(
                user_id,
                _dispatch_command(
                    command=parsed,
                    line_user_id=user_id,
                    raw_text=text,
                    mode=current_mode,
                    target_lang=target_lang,
                ),
            )
        # 處理 pending_save 狀態
        elif parsed.command_type == CommandType.CONFIRM_SAVE and has_pending_save:
            # 用戶輸入「1」確認入庫
            response = await _handle_confirm_save(hashed_uid, user_id, current_mode, target_lang)
            if has_article_mode:
                response += Messages.ARTICLE_WORD_SAVE_REMINDER
        elif has_pending_save and parsed.command_type == CommandType.SAVE:
            # 用戶輸入「入庫」→ 視同確認，直接儲存 pending 內容
            response = await _handle_confirm_save(hashed_uid, user_id, current_mode, target_lang)
            if has_article_mode:
                response += Messages.ARTICLE_WORD_SAVE_REMINDER
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
                response = await _with_thinking_indicator(
                    user_id,
                    _dispatch_command(
                        command=parsed,
                        line_user_id=user_id,
                        raw_text=text,
                        mode=current_mode,
                        target_lang=target_lang,
                    ),
                )
                # 在回覆前加上取消通知
                if discarded_word:
                    entries = UserStateRepository.parse_pending_save_content(discarded_word)
                    if len(entries) == 1:
                        notice = Messages.format("PENDING_DISCARDED", word=entries[0][0])
                    else:
                        all_words = "、".join(f"「{w}」" for w, _ in entries)
                        notice = Messages.format("PENDING_DISCARDED_MULTI", words=all_words)
                    response = f"{notice}\n\n{response}"
        elif parsed.command_type == CommandType.CONFIRM_SAVE and not has_pending_save:
            # 輸入「1」但無 pending_save → 明確告知可能已過期
            response = Messages.PENDING_EXPIRED
        # ── COMPLETE_ARTICLE 指令 ──
        elif parsed.command_type == CommandType.COMPLETE_ARTICLE:
            if has_article_mode:
                async with get_session() as session:
                    repo = UserStateRepository(session)
                    await repo.clear_article_mode(hashed_uid)
                    if has_pending_save:
                        await repo.clear_pending_save(hashed_uid)
                response = Messages.ARTICLE_MODE_EXIT
            else:
                # 不在 article mode，「完成」無意義 → 友善提示
                response = "目前不在文章閱讀模式中。\n輸入日文長文可進入閱讀模式 📖"
        # ── Article mode 中的單字查詢 ──
        elif (
            has_article_mode
            and parsed.command_type == CommandType.UNKNOWN
            and not has_session
        ):
            response = await _with_thinking_indicator(
                user_id,
                _handle_article_word_lookup(
                    line_user_id=user_id,
                    word_text=text,
                    article_text=article_text,  # type: ignore[arg-type]
                    mode=current_mode,
                    target_lang=target_lang,
                ),
            )
        elif parsed.command_type == CommandType.EXIT_PRACTICE:
            response = await _handle_exit_practice(hashed_uid)
        elif parsed.command_type == CommandType.UNKNOWN and has_session:
            response = await _with_thinking_indicator(
                user_id,
                _handle_practice_answer(hashed_uid, text, current_mode, target_lang),
            )
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
        elif (
            parsed.command_type == CommandType.UNKNOWN
            and text.strip().isdigit()
            and not has_pending_delete
            and not has_pending_save
            and not has_session
        ):
            # 無 pending 狀態下輸入純數字 → 可能是過期的刪除選項
            response = Messages.format("DELETE_SELECT_EXPIRED")
        else:
            response = await _with_thinking_indicator(
                user_id,
                _dispatch_command(
                    command=parsed,
                    line_user_id=user_id,
                    raw_text=text,
                    mode=current_mode,
                    target_lang=target_lang,
                ),
            )

        # === Post-dispatch session：累加 token + 儲存 last_message ===
        total_tokens = usage_ctx.total_tokens
        need_save_last_msg = (
            parsed.command_type == CommandType.UNKNOWN
            and not has_session
            and not has_article_mode
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
                logger.warning("Failed in post-dispatch session: %s", e)

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

    except TimeoutError as e:
        # 處理超時：通知使用者稍後重試
        logger.warning("Processing timeout in message handler: %s", e)
        timeout_msg = "處理時間過長，請稍後再試一次 🙏"
        try:
            replied = await line_client.reply_message(reply_token, timeout_msg)
            if not replied:
                await line_client.push_message(user_id, timeout_msg)
        except Exception:
            logger.exception("Failed to send timeout error reply")
    except Exception as e:
        # 最後防線：確保使用者至少收到回覆
        logger.exception("Unhandled error in message handler: %s", e)
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
            mode_set_ok = False
            try:
                async with get_session() as session:
                    repo = UserProfileRepository(session)
                    profile = await repo.set_mode(hashed_uid, mode)
                    daily_used = profile.daily_used_tokens or 0
                    daily_cap = profile.daily_cap_tokens_free or 50000
                    mode_set_ok = True
            except Exception as e:
                logger.warning("Failed to set mode via postback: %s", e, exc_info=True)

            if not mode_set_ok:
                await line_client.reply_message(reply_token, Messages.ERROR_GENERIC)
                return

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
            logger.warning("Unknown postback: %s", event.postback.data if event.postback else "None")
    except Exception as e:
        logger.exception("Unhandled error in postback handler: %s", e)
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
        logger.error("Auto-extract failed for doc %s: %s", doc_id, e)
        return None


async def _extract_in_background(
    hashed_uid: str,
    raw_user_id: str,
    doc_id: str,
    mode: str,
    target_lang: str,
) -> None:
    """背景執行抽取，完成後透過 Push API 通知使用者。"""
    line_client = get_line_client()

    # 抽取與推播分開 try/except，避免抽取成功但推播失敗時發送錯誤的「分析失敗」訊息
    summary = None
    try:
        summary = await _auto_extract(hashed_uid, doc_id, mode, target_lang)
    except Exception as e:
        logger.error("Background extraction failed for doc %s: %s", doc_id, e, exc_info=True)

    msg = (
        Messages.format("EXTRACT_COMPLETE_PUSH", summary=summary)
        if summary
        else Messages.format("EXTRACT_FAILED_PUSH")
    )
    try:
        await line_client.push_message(raw_user_id, msg)
    except Exception:
        logger.warning("Failed to push extraction notification for doc %s", doc_id)


_T = TypeVar("_T")


async def _with_thinking_indicator(
    raw_user_id: str,
    coro: Coroutine[Any, Any, _T],
    initial_delay: float = 20.0,
    interval: float = 20.0,
    max_timeout: float = 120.0,
) -> _T:
    """包裝耗時操作，等待超過 initial_delay 後顯示載入動畫並每 interval 秒推送思考提示。

    - 大多數請求（free mode）<5s 完成，不會觸發任何通知
    - 超過 initial_delay 後：顯示 LINE 載入動畫 + 推送「思考中⋯」
    - 每 interval 秒重複推送 + 刷新動畫
    - 超過 max_timeout 秒後取消任務並拋出 TimeoutError
    """
    task = asyncio.ensure_future(coro)
    line_client = get_line_client()

    try:
        # Phase 1: 等待初始延遲，大多數請求會在此完成
        done, _ = await asyncio.wait({task}, timeout=initial_delay)
        if done:
            return task.result()

        # Phase 2: 超時 → 開始定期通知
        # 先顯示載入動畫（即時視覺反饋）
        await line_client.show_loading_animation(raw_user_id, loading_seconds=60)

        elapsed = initial_delay
        while elapsed < max_timeout:
            remaining = min(interval, max_timeout - elapsed)
            done, _ = await asyncio.wait({task}, timeout=remaining)
            if done:
                return task.result()
            elapsed += remaining
            if elapsed >= max_timeout:
                break
            # 推送文字提示 + 刷新載入動畫
            await line_client.push_message(raw_user_id, "思考中，請稍候⋯")
            await line_client.show_loading_animation(raw_user_id, loading_seconds=60)

        # 超過最大超時：取消任務
        task.cancel()
        raise TimeoutError(f"Processing exceeded max_timeout={max_timeout}s")
    except BaseException:
        if not task.done():
            task.cancel()
        raise


def _schedule_background_extraction(
    hashed_uid: str,
    raw_user_id: str,
    doc_id: str,
    mode: str,
    target_lang: str,
) -> None:
    """排程背景抽取 asyncio.Task，使用 _background_tasks 防止 GC。"""
    task = asyncio.create_task(
        _extract_in_background(hashed_uid, raw_user_id, doc_id, mode, target_lang)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


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

    # 背景抽取（不阻塞回覆）
    doc_id = str(result.data["doc_id"]) if result.data.get("doc_id") else None
    if doc_id:
        _schedule_background_extraction(hashed_uid, line_user_id, doc_id, mode, target_lang)
        return Messages.SAVE_PROCESSING
    return result.message


# 批次入庫合法字元：字母、hyphen、日文（平假名/片假名/漢字）
_BATCH_WORD_PATTERN = re.compile(
    r"^[a-zA-Z\-\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff\uff65-\uff9f]+$"
)


def _split_batch_save_keywords(keyword: str) -> list[str] | None:
    """嘗試將 keyword 切分為多個單字。

    回傳 None 表示不應切分（單字或 compound word）。
    切分條件：2-10 個 token、每個 ≤30 字元、全部是合法字元。
    """
    # 用空白分割
    tokens = keyword.split()

    # compound word 例外：≤2 token 且整體 ≤15 字元 → 不切分
    if len(tokens) <= 1:
        return None
    if len(tokens) == 2 and len(keyword) <= 15:
        return None

    # 範圍檢查
    if not (2 <= len(tokens) <= 10):
        return None

    for token in tokens:
        if len(token) > 30 or not _BATCH_WORD_PATTERN.match(token):
            return None

    return tokens


async def _handle_word_save(
    line_user_id: str,
    word: str | None,
    mode: str = "free",
    target_lang: str = "ja",
) -> str:
    """處理「單字 入庫」直接入庫指令。"""
    if not word or not _has_meaningful_content(word):
        return Messages.SAVE_NO_CONTENT

    # 偵測多字批次入庫
    batch_words = _split_batch_save_keywords(word)
    if batch_words:
        return await _handle_batch_word_save(
            line_user_id, batch_words, mode, target_lang
        )

    hashed_uid = hash_user_id(line_user_id)

    async with get_session() as session:
        service = CommandService(session)
        result = await service.save_raw(
            line_user_id=line_user_id,
            content_text=word,
        )

    if not result.success:
        return result.message

    # 背景抽取（不阻塞回覆）
    doc_id = str(result.data["doc_id"]) if result.data.get("doc_id") else None
    if doc_id:
        _schedule_background_extraction(hashed_uid, line_user_id, doc_id, mode, target_lang)
        return Messages.SAVE_PROCESSING
    return result.message


async def _handle_batch_word_save(
    line_user_id: str,
    words: list[str],
    mode: str = "free",
    target_lang: str = "ja",
) -> str:
    """批次入庫多個單字（單次 LLM 呼叫）。"""
    from src.repositories.api_usage_log_repo import ApiUsageLogRepository
    from src.repositories.document_repo import DocumentRepository
    from src.repositories.item_repo import ItemRepository
    from src.schemas.extractor import ExtractedItem
    from src.services.router_service import get_router_service

    hashed_uid = hash_user_id(line_user_id)
    router_service = get_router_service()

    # 單次 LLM 呼叫取得所有單字的解釋
    try:
        results, trace = await router_service.get_batch_word_explanation_structured(
            words, mode=mode, target_lang=target_lang
        )
    except Exception as e:
        logger.error("Batch word explanation failed: %s", e)
        results = [(w, "", None) for w in words]
        trace = None

    # 記錄 token 用量
    if trace:
        try:
            async with get_session() as session:
                await ApiUsageLogRepository(session).create_log(
                    hashed_uid, trace, "batch_word_explanation"
                )
        except Exception:
            logger.warning("Failed to write batch word explanation trace", exc_info=True)

    saved_words: list[str] = []
    pending_words: list[str] = []
    failed_words: list[str] = []

    # 逐字入庫 raw + document，收集 doc_id
    word_doc_map: list[tuple[str, str, dict[str, Any] | None, str | None]] = []
    for word, display, extracted_item in results:
        try:
            async with get_session() as session:
                service = CommandService(session)
                result = await service.save_raw(
                    line_user_id=line_user_id,
                    content_text=word,
                )
            if not result.success:
                logger.warning("Batch save_raw failed for '%s': %s", word, result.message)
                failed_words.append(word)
                continue
            doc_id = str(result.data["doc_id"]) if result.data.get("doc_id") else None
            word_doc_map.append((word, display, extracted_item, doc_id))
        except Exception as e:
            logger.error("Batch save_raw error for '%s': %s", word, e)
            failed_words.append(word)

    # 批次 upsert items（共用一個 session）
    if word_doc_map:
        try:
            async with get_session() as session:
                item_repo = ItemRepository(session)
                doc_repo = DocumentRepository(session)
                for word, display, extracted_item, doc_id in word_doc_map:
                    if extracted_item and doc_id:
                        try:
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
                            await doc_repo.update(
                                doc_id, parse_status="parsed", parser_version="v1.0.0"
                            )
                            saved_words.append(word)
                        except Exception as e:
                            logger.warning("Direct item creation failed for '%s': %s", word, e)
                            _schedule_background_extraction(
                                hashed_uid, line_user_id, doc_id, mode, target_lang
                            )
                            pending_words.append(word)
                    elif doc_id:
                        # LLM 未回傳結構化資料 → 背景抽取
                        _schedule_background_extraction(
                            hashed_uid, line_user_id, doc_id, mode, target_lang
                        )
                        pending_words.append(word)
        except Exception as e:
            logger.error("Batch item upsert session error: %s", e)
            # session 級錯誤 → 尚未處理的字全部走背景抽取
            for word, _display, _item, doc_id in word_doc_map:
                if word not in saved_words and word not in pending_words and doc_id:
                    _schedule_background_extraction(
                        hashed_uid, line_user_id, doc_id, mode, target_lang
                    )
                    pending_words.append(word)

    # 組裝回覆訊息
    if saved_words and not pending_words:
        return Messages.format(
            "BATCH_SAVE_SUCCESS",
            count=len(saved_words),
            words="、".join(saved_words),
        )
    elif saved_words and pending_words:
        return Messages.format(
            "BATCH_SAVE_PARTIAL",
            saved="、".join(saved_words),
            pending="、".join(pending_words),
        )
    elif pending_words:
        return Messages.format(
            "BATCH_SAVE_PARTIAL",
            saved="（無）",
            pending="、".join(pending_words),
        )
    else:
        return Messages.ERROR_SAVE


async def _handle_confirm_save(
    hashed_uid: str,
    line_user_id: str,
    mode: str = "free",
    target_lang: str = "ja",
) -> str:
    """處理確認入庫（用戶輸入「1」）。支援單字與多字 pending。"""
    async with get_session() as session:
        user_state_repo = UserStateRepository(session)
        raw_content = await user_state_repo.get_pending_save(hashed_uid)

        if not raw_content:
            return Messages.PENDING_EXPIRED

        entries = UserStateRepository.parse_pending_save_content(raw_content)
        await user_state_repo.clear_pending_save(hashed_uid)

    # ── 單字入庫（維持現有邏輯）──
    if len(entries) == 1:
        pending_word, extracted_item = entries[0]

        async with get_session() as session:
            service = CommandService(session)
            result = await service.save_raw(
                line_user_id=line_user_id,
                content_text=pending_word,
            )

        if not result.success:
            return result.message

        doc_id = str(result.data["doc_id"]) if result.data.get("doc_id") else None

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
                    from src.repositories.document_repo import DocumentRepository

                    doc_repo = DocumentRepository(session)
                    await doc_repo.update(
                        doc_id, parse_status="parsed", parser_version="v1.0.0"
                    )

                return Messages.format("WORD_SAVE_AND_EXTRACT", word=pending_word)
            except Exception as e:
                logger.warning("Direct item creation failed, falling back to auto-extract: %s", e)

        if doc_id:
            _schedule_background_extraction(hashed_uid, line_user_id, doc_id, mode, target_lang)
            return Messages.SAVE_PROCESSING

        return result.message

    # ── 多字入庫 ──
    from src.repositories.document_repo import DocumentRepository
    from src.repositories.item_repo import ItemRepository
    from src.schemas.extractor import ExtractedItem

    saved_words: list[str] = []
    pending_words: list[str] = []

    for pending_word, extracted_item in entries:
        try:
            async with get_session() as session:
                service = CommandService(session)
                result = await service.save_raw(
                    line_user_id=line_user_id,
                    content_text=pending_word,
                )
            if not result.success:
                logger.warning("Multi save_raw failed for '%s': %s", pending_word, result.message)
                continue
            doc_id = str(result.data["doc_id"]) if result.data.get("doc_id") else None
            if extracted_item and doc_id:
                try:
                    async with get_session() as session:
                        item_repo = ItemRepository(session)
                        doc_repo = DocumentRepository(session)
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
                        await doc_repo.update(
                            doc_id, parse_status="parsed", parser_version="v1.0.0"
                        )
                        saved_words.append(pending_word)
                except Exception as e:
                    logger.warning("Item creation failed for '%s': %s", pending_word, e)
                    _schedule_background_extraction(
                        hashed_uid, line_user_id, doc_id, mode, target_lang
                    )
                    pending_words.append(pending_word)
            elif doc_id:
                _schedule_background_extraction(
                    hashed_uid, line_user_id, doc_id, mode, target_lang
                )
                pending_words.append(pending_word)
        except Exception as e:
            logger.error("Multi save error for '%s': %s", pending_word, e)

    if saved_words and not pending_words:
        return Messages.format(
            "BATCH_SAVE_SUCCESS",
            count=len(saved_words),
            words="、".join(saved_words),
        )
    elif saved_words and pending_words:
        return Messages.format(
            "BATCH_SAVE_PARTIAL",
            saved="、".join(saved_words),
            pending="、".join(pending_words),
        )
    elif pending_words:
        return Messages.format(
            "BATCH_SAVE_PARTIAL",
            saved="（無）",
            pending="、".join(pending_words),
        )
    else:
        return Messages.ERROR_SAVE


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
            logger.error("Search failed: %s", e)
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
            logger.error("Practice session creation failed: %s", e)
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
            logger.error("Cost query failed: %s", e)
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
            logger.error("Stats query failed: %s", e)
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
            logger.error("List items failed: %s", e)
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
            logger.error("Practice answer submission failed: %s", e)
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
            logger.error("Delete item failed: %s", e)
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
        label = DeleteService.format_item_label(item)
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
            logger.error("Clear all failed: %s", e)
            return Messages.ERROR_CLEAR


async def _handle_unknown(
    line_user_id: str,
    raw_text: str,
    mode: str = "free",
    target_lang: str = "ja",
) -> str:
    """以結構特徵分類處理未被指令匹配的輸入。"""
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

    # Edge Case 26: 超長文本 → 翻譯 + 進入文章閱讀模式
    if len(raw_text) > LONG_TEXT_THRESHOLD:
        return await _handle_article_translation(
            line_user_id, raw_text, mode, target_lang,
        )

    # 結構特徵分類（取代 LLM Router）
    category = _classify_input(raw_text, target_lang)

    if category == InputCategory.WORD:
        return await _handle_word_input(line_user_id, raw_text, mode, target_lang)

    if category == InputCategory.MATERIAL:
        return await _handle_article_translation(
            line_user_id, raw_text, mode, target_lang,
        )

    if category == InputCategory.CHAT:
        from src.services.router_service import get_router_service

        hashed_user_id = hash_user_id(line_user_id)
        router_service = get_router_service()
        try:
            chat_resp = await router_service.get_chat_response(
                raw_text, mode=mode, target_lang=target_lang,
            )
            # 寫入 LLM trace
            try:
                from src.repositories.api_usage_log_repo import ApiUsageLogRepository

                async with get_session() as session:
                    repo = ApiUsageLogRepository(session)
                    await repo.create_log(
                        user_id=hashed_user_id,
                        trace=chat_resp.to_trace(),
                        operation="chat",
                    )
            except Exception:
                logger.warning("Failed to write chat LLM trace to DB", exc_info=True)
            return chat_resp.content
        except Exception as e:
            logger.error("Chat response failed: %s", e)
            return Messages.ERROR_GENERIC

    # UNKNOWN — fallback
    return Messages.FALLBACK_UNKNOWN


async def _handle_word_input(
    line_user_id: str,
    raw_text: str,
    mode: str = "free",
    target_lang: str = "ja",
) -> str:
    """處理 WORD 分類的輸入：DB 搜尋 → LLM 解釋 → pending save。

    支援多單字統一處理：所有偵測到的單字都走完整流程。
    """
    from src.lib.llm_client import LLMTrace
    from src.services.router_service import get_router_service

    hashed_user_id = hash_user_id(line_user_id)
    router_service = get_router_service()
    llm_traces: list[tuple[LLMTrace, str]] = []

    try:
        stripped = raw_text.strip()
        tokens = stripped.split()

        # 多單字偵測：2+ 個短 token
        is_multi_word = (
            len(tokens) >= 2
            and all(len(t) <= 30 for t in tokens)
            and all(
                t.isalpha() or all(ch.isalpha() or ch == "-" for ch in t)
                for t in tokens
            )
        )

        # compound word 偵測（ice cream, to be）— 僅英文，日文不合併
        _has_any_kana = any(
            "\u3040" <= c <= "\u309f" or "\u30a0" <= c <= "\u30ff" or "\uff65" <= c <= "\uff9f"
            for t in tokens for c in t
        )
        if (
            is_multi_word
            and not _has_any_kana
            and len(tokens) <= _COMPOUND_WORD_MAX_TOKENS
            and len(stripped.replace(" ", "")) <= _COMPOUND_WORD_MAX_CHARS
        ):
            is_multi_word = False

        if not is_multi_word:
            # ── 單字流程（含 compound word）──
            word = stripped
            db_items = await _search_user_items(hashed_user_id, word)
            if db_items:
                return _format_search_results(db_items, show_display=True)

            try:
                display, items, word_trace = (
                    await router_service.get_word_explanation_structured(
                        word, mode=mode, target_lang=target_lang
                    )
                )
                if word_trace:
                    llm_traces.append((word_trace, "word_explanation"))
            except Exception:
                logger.exception("Word explanation failed (single word=%s)", word)
                return Messages.ERROR_WORD_LOOKUP_BUSY

            if not items:
                # 0 items — LLM 無法確定詞條，僅回顯示不設 pending_save
                return display

            if len(items) == 1:
                async with get_session() as session:
                    user_state_repo = UserStateRepository(session)
                    await user_state_repo.set_pending_save_with_item(
                        hashed_user_id, items[0]["surface"], items[0]
                    )
                return Messages.format("WORD_EXPLANATION", explanation=display)

            # 2+ items — 句子分析出多詞條
            async with get_session() as session:
                user_state_repo = UserStateRepository(session)
                entries = [
                    {"word": item["surface"], "extracted_item": item}
                    for item in items
                ]
                await user_state_repo.set_pending_save_multi(
                    hashed_user_id, entries
                )
            pending_hint = Messages.format("WORD_MULTI_PENDING", count=len(items))
            return f"{display}\n\n{pending_hint}"

        # ── 多單字統一處理 ──

        # 1. 逐 token 查 DB
        db_hit_map: dict[str, list[Item]] = {}
        db_miss_words: list[str] = []
        for token in tokens:
            db_items = await _search_user_items(hashed_user_id, token)
            if db_items:
                db_hit_map[token] = db_items
            else:
                db_miss_words.append(token)

        # 2. DB misses 呼叫 LLM
        llm_result_map: dict[str, tuple[str, dict[str, Any] | None]] = {}
        llm_failed = False

        if len(db_miss_words) == 1:
            word = db_miss_words[0]
            try:
                display, items, word_trace = (
                    await router_service.get_word_explanation_structured(
                        word, mode=mode, target_lang=target_lang
                    )
                )
                if word_trace:
                    llm_traces.append((word_trace, "word_explanation"))
                llm_result_map[word] = (display, items[0] if items else None)
            except Exception:
                logger.exception("Word explanation failed (multi, word=%s)", word)
                llm_failed = True
        elif len(db_miss_words) >= 2:
            try:
                results, trace = await router_service.get_batch_word_explanation_structured(
                    db_miss_words, mode=mode, target_lang=target_lang
                )
                if trace:
                    llm_traces.append((trace, "batch_word_explanation"))
                for word, display, extracted_item in results:
                    llm_result_map[word] = (display, extracted_item)
            except Exception:
                logger.exception("Batch word explanation failed")
                llm_failed = True

        # LLM 全部失敗且無 DB hit → 直接回報錯誤
        if llm_failed and not db_hit_map:
            return Messages.ERROR_WORD_LOOKUP_BUSY

        # 3. 組合回覆（按輸入順序）
        _LINE_MSG_BUDGET = 4500
        parts: list[str] = []
        char_count = 0

        for token in tokens:
            if token in db_hit_map:
                section = f"[已入庫] {_format_search_results(db_hit_map[token], show_display=True)}"
            elif token in llm_result_map:
                display, _ = llm_result_map[token]
                section = display if display else f"「{token}」"
            elif llm_failed:
                section = f"「{token}」查詢失敗"
            else:
                section = f"「{token}」"

            # 訊息過長時後續單字改為簡要摘要
            if char_count + len(section) > _LINE_MSG_BUDGET and parts:
                item_data = llm_result_map.get(token, (None, None))[1] if token in llm_result_map else None
                if item_data and isinstance(item_data, dict):
                    glossary = item_data.get("glossary_zh", [])
                    section = f"【{token}】{glossary[0] if glossary else ''}"

            parts.append(section)
            char_count += len(section) + 12  # +12 估算分隔線長度

        separator = "\n━━━━━━━━━━\n"
        reply = separator.join(parts)

        # 4. 存入 pending_save（僅 LLM 成功解釋的字）
        pending_entries = [
            {"word": w, "extracted_item": llm_result_map[w][1]}
            for w in db_miss_words
            if w in llm_result_map
        ]

        if pending_entries:
            async with get_session() as session:
                user_state_repo = UserStateRepository(session)
                if len(pending_entries) == 1:
                    entry = pending_entries[0]
                    if entry["extracted_item"]:
                        await user_state_repo.set_pending_save_with_item(
                            hashed_user_id, entry["word"], entry["extracted_item"]
                        )
                    else:
                        await user_state_repo.set_pending_save(hashed_user_id, entry["word"])
                else:
                    await user_state_repo.set_pending_save_multi(
                        hashed_user_id, pending_entries
                    )
            pending_hint = Messages.format("WORD_MULTI_PENDING", count=len(pending_entries))
            reply = f"{reply}\n\n{pending_hint}"

        return reply

    except Exception as e:
        logger.error("Word input handling failed: %s", e)
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
    """入庫原始內容並排程背景抽取單字/文法。"""
    hashed_uid = hash_user_id(line_user_id)

    async with get_session() as session:
        service = CommandService(session)
        result = await service.save_raw(line_user_id=line_user_id, content_text=content)
    if not result.success:
        return result.message

    doc_id = str(result.data["doc_id"]) if result.data.get("doc_id") else None

    if doc_id:
        _schedule_background_extraction(hashed_uid, line_user_id, doc_id, mode, target_lang)
        return Messages.SAVE_PROCESSING
    return result.message


async def _handle_article_translation(
    line_user_id: str,
    raw_text: str,
    mode: str = "free",
    target_lang: str = "ja",
) -> str:
    """翻譯長文並進入 article mode。"""
    from src.lib.llm_client import get_llm_client
    from src.prompts.article import (
        ARTICLE_TRANSLATION_SYSTEM_PROMPT,
        format_article_translation_request,
    )
    from src.repositories.api_usage_log_repo import ApiUsageLogRepository

    hashed_uid = hash_user_id(line_user_id)
    llm_client = get_llm_client()

    # 截斷至 5000 字
    text_to_translate = raw_text[:5000]

    # LLM 翻譯（純文字回傳）
    try:
        response = await llm_client.complete_with_mode(
            mode=mode,
            system_prompt=ARTICLE_TRANSLATION_SYSTEM_PROMPT,
            user_message=format_article_translation_request(text_to_translate),
            temperature=0.3,
            max_tokens=4096,
            total_timeout=60,
        )
    except Exception as e:
        logger.error("Article translation LLM call failed: %s", e)
        return Messages.ERROR_GENERIC

    translation = response.content
    trace = response.to_trace()

    # 記錄 token 用量
    if trace:
        try:
            async with get_session() as session:
                await ApiUsageLogRepository(session).create_log(
                    hashed_uid, trace, "article_translation"
                )
        except Exception:
            logger.warning("Failed to write article translation trace", exc_info=True)

    # 進入 article mode
    async with get_session() as session:
        repo = UserStateRepository(session)
        await repo.set_article_mode(hashed_uid, text_to_translate)

    # 組裝回覆：翻譯 + 操作提示（注意 LINE 5000 字限制）
    header = Messages.ARTICLE_TRANSLATION_HEADER
    instructions = Messages.ARTICLE_MODE_INSTRUCTIONS
    max_translation_len = (
        LINE_MESSAGE_MAX_LENGTH - len(header) - len(instructions)
        - FOOTER_RESERVE - 10
    )
    if len(translation) > max_translation_len:
        translation = translation[:max_translation_len - 3] + "..."

    return f"{header}\n{translation}{instructions}"


async def _handle_article_word_lookup(
    line_user_id: str,
    word_text: str,
    article_text: str,
    mode: str = "free",
    target_lang: str = "ja",
) -> str:
    """在 article mode 中查詢單字/文法（帶文章語境）。"""
    from src.lib.llm_client import LLMTrace
    from src.repositories.api_usage_log_repo import ApiUsageLogRepository
    from src.services.router_service import get_router_service

    hashed_uid = hash_user_id(line_user_id)
    router_service = get_router_service()
    llm_traces: list[tuple[LLMTrace, str]] = []

    try:
        # 先查 DB（與現有 _handle_word_input 相同）
        items = await _search_user_items(hashed_uid, word_text)
        if items:
            result = _format_search_results(items, show_display=True)
            return result + Messages.ARTICLE_WORD_SAVE_REMINDER

        # DB 未命中 → LLM 查詞（帶文章語境）
        display, items, trace = (
            await router_service.get_word_explanation_with_context(
                word=word_text,
                article_context=article_text,
                mode=mode,
                target_lang=target_lang,
            )
        )
        if trace:
            llm_traces.append((trace, "article_word_lookup"))

        # 設定 pending_save — 依 items 數量決定
        if not items:
            # 0 items — 無法確定詞條，不設 pending_save
            return display + Messages.ARTICLE_WORD_SAVE_REMINDER

        if len(items) == 1:
            async with get_session() as session:
                repo = UserStateRepository(session)
                await repo.set_pending_save_with_item(
                    hashed_uid, items[0]["surface"], items[0],
                )
        else:
            # 2+ items
            async with get_session() as session:
                repo = UserStateRepository(session)
                entries = [
                    {"word": item["surface"], "extracted_item": item}
                    for item in items
                ]
                await repo.set_pending_save_multi(hashed_uid, entries)

        explanation = Messages.format(
            "WORD_EXPLANATION", explanation=display,
        )
        return explanation + Messages.ARTICLE_WORD_SAVE_REMINDER

    except Exception as e:
        logger.error("Article word lookup failed: %s", e)
        return Messages.ERROR_WORD_LOOKUP_BUSY

    finally:
        # 批次寫入 LLM traces
        if llm_traces:
            try:
                async with get_session() as session:
                    repo = ApiUsageLogRepository(session)
                    for t, operation in llm_traces:
                        await repo.create_log(
                            user_id=hashed_uid,
                            trace=t,
                            operation=operation,
                        )
            except Exception:
                logger.warning(
                    "Failed to write article word lookup traces",
                    exc_info=True,
                )


# ============================================================================
# Helper Functions
# ============================================================================



async def _search_user_items(hashed_user_id: str, keyword: str, limit: int = MAX_SEARCH_RESULTS) -> list[Item]:
    """在使用者 items 中搜尋關鍵字。"""
    from src.repositories.item_repo import ItemRepository

    async with get_session() as session:
        item_repo = ItemRepository(session)
        return await item_repo.search_by_keyword(
            user_id=hashed_user_id, keyword=keyword, limit=limit,
        )


def _format_search_results(items: "Sequence[Item]", *, show_display: bool = False) -> str:
    """格式化搜尋結果為使用者友善的訊息。

    show_display=True 且單筆結果有 display 全文時，回傳 header + 完整 LLM 分析；
    其餘情況走摘要格式。
    """
    # 單筆且有 display → 回傳完整 LLM 分析（僅單字查詢 DB hit 使用）
    if show_display and len(items) == 1 and items[0].payload and items[0].payload.get("display"):
        return f"{format_search_result_header(1)}\n{items[0].payload['display']}"

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

