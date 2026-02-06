"""
統一訊息模板模組。

提供多語系支援架構與集中管理的使用者回應訊息。
所有對使用者的回覆訊息都應透過此模組取得，確保一致性與可維護性。

使用方式：
    from src.templates.messages import Messages, get_message
    
    # 直接使用 (預設繁體中文)
    msg = Messages.ERROR_GENERIC
    
    # 帶參數的訊息
    msg = Messages.format("SEARCH_NO_RESULT", keyword="考える")
    
    # 多語系支援 (未來擴展)
    msg = get_message("ERROR_GENERIC", locale="ja")
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Locale(str, Enum):
    """支援的語系。"""
    
    ZH_TW = "zh-TW"  # 繁體中文（預設）
    JA = "ja"        # 日本語（未來支援）
    EN = "en"        # English（未來支援）


# 預設語系
DEFAULT_LOCALE = Locale.ZH_TW


@dataclass(frozen=True)
class MessageTemplate:
    """訊息模板，支援參數替換。"""
    
    template: str
    
    def format(self, **kwargs: Any) -> str:
        """格式化訊息模板。"""
        return self.template.format(**kwargs)


# ============================================================================
# 訊息定義 - 繁體中文
# ============================================================================

_MESSAGES_ZH_TW: dict[str, str] = {
    # ========== 通用錯誤訊息 ==========
    "ERROR_GENERIC": "發生錯誤，請稍後再試 🙇",
    "ERROR_ANALYZE": "分析時發生錯誤 😢\n請稍後再試一次",
    "ERROR_PRACTICE": "練習功能暫時無法使用，請稍後再試 🙇",
    "ERROR_PRACTICE_ANSWER": "處理答案時發生錯誤，請重新開始練習",
    "ERROR_SEARCH": "搜尋時發生錯誤，請稍後再試",
    "ERROR_DELETE": "刪除時發生錯誤，請稍後再試",
    "ERROR_CLEAR": "清空資料時發生錯誤，請稍後再試",
    "ERROR_CHAT": "抱歉，我現在無法回答這個問題 🙇\n請稍後再試，或輸入「說明」查看我能幫你做什麼。",
    "ERROR_SAVE": "入庫失敗，請稍後再試",
    
    # ========== 入庫相關 ==========
    "SAVE_SUCCESS": "已入庫：{content_preview}",
    "SAVE_SUCCESS_WITH_HINT": "已入庫：{content_preview}\n\n💡 輸入「分析」來抽取單字和文法",
    "SAVE_NO_CONTENT": "請先貼上要入庫的內容，再輸入「入庫」",
    "WORD_EXPLANATION": "{explanation}\n\n尚未入庫，請在 5 分鐘內輸入「1」即可入庫，輸入其他內容將視為新查詢\n若非你要查的字，請重新輸入正確的拼寫",
    "PENDING_EXPIRED": "沒有待入庫的內容（可能已超過 5 分鐘）。\n請重新輸入想查詢的單字。",
    "PENDING_DISCARDED": "⚠️「{word}」的入庫已取消。",
    "INPUT_NO_MEANINGFUL_CONTENT": "請輸入文字內容（日文或英文），純符號或 emoji 無法處理 🙏\n輸入「說明」查看使用方式",
    "COMMAND_SUGGESTION": "💡 你可能想輸入指令「{command}」\n如果不是，請重新輸入你想查詢的內容",
    "INPUT_URL_DETECTED": "目前不支援直接輸入 URL 🔗\n請複製文章的文字內容後貼上",
    "INPUT_LIKELY_ROMAJI": "看起來是日語的羅馬字拼音 ✏️\n請開啟日文輸入法後重新輸入，或直接貼上日文文字",
    "PENDING_WRONG_NUMBER": "只有輸入「1」可以確認入庫喔 ☝️\n輸入「1」入庫，或輸入其他單字繼續查詢",
    "INPUT_LONG_TEXT_SAVED": "📄 文章較長（{length} 字），已直接入庫\n\n💡 輸入「分析」來抽取單字和文法",
    "INPUT_NON_TEXT": "目前僅支援文字訊息 📝\n請將想查詢的內容以文字方式輸入",
    "INPUT_UNSUPPORTED_LANG": "目前支援日文和英文內容 🌐\n請輸入日文或英文的學習素材",
    
    # ========== 分析相關 ==========
    "ANALYZE_NO_DEFERRED": "沒有待分析的素材 📭\n請先「入庫」一些學習內容",
    "ANALYZE_EMPTY_RESULT": "沒有發現可學習的單字或文法 📝",
    "ANALYZE_SUCCESS": "✨ 抽出 {summary}",
    "ANALYZE_TRUNCATED_NOTE": "\n（內容較長，已限制抽取數量）",
    
    # ========== 搜尋相關 ==========
    "SEARCH_HINT": "請提供查詢關鍵字，例如：查詢 考える",
    "SEARCH_NO_RESULT": "找不到「{keyword}」相關的項目 🔍",
    "SEARCH_RESULT_HEADER": "🔍 找到 {count} 筆：",
    "SEARCH_RESULT_MORE": "...還有 {remaining} 筆",
    
    # ========== 練習相關 ==========
    "PRACTICE_INSUFFICIENT_ITEMS": (
        "你的題庫還不夠 📚\n"
        "目前只有 {current} 個項目\n"
        "請先入庫更多素材（至少需要 {required} 個）"
    ),
    "PRACTICE_GENERATE_FAILED": "無法產生練習題，請稍後再試",
    "PRACTICE_NO_ACTIVE_SESSION": "沒有進行中的練習，請先輸入「練習」開始",
    "PRACTICE_EXIT": "已結束練習 📝\n可隨時輸入「練習」重新開始。",
    "PRACTICE_EXIT_NO_SESSION": "目前沒有進行中的練習。",
    "PRACTICE_HEADER": "📝 今日練習題：\n",
    "PRACTICE_FOOTER": "\n請依序回答，輸入答案即可 ✍️",
    "PRACTICE_ANSWER_CORRECT": "✅ 正確！",
    "PRACTICE_ANSWER_WRONG": "❌ 答案是：{expected}",
    "PRACTICE_NEXT_QUESTION": "\n\n下一題：\n{question}",
    
    # 練習結果
    "PRACTICE_RESULT_PERFECT": "🎉 練習結束！\n得分：{correct}/{total}\n太棒了！全部答對！",
    "PRACTICE_RESULT_GREAT": "👍 練習結束！\n得分：{correct}/{total}\n做得很好！",
    "PRACTICE_RESULT_GOOD": "💪 練習結束！\n得分：{correct}/{total}\n繼續加油！",
    "PRACTICE_RESULT_NEEDS_WORK": "📚 練習結束！\n得分：{correct}/{total}\n多複習一下吧！",
    
    # 題目格式
    "QUESTION_VOCAB_RECALL": "{index}. 「{prompt}」的日文是？",
    "QUESTION_GRAMMAR_CLOZE": "{index}. {prompt}",
    "QUESTION_VOCAB_MEANING": "{index}. 「{prompt}」是什麼意思？",
    "QUESTION_GRAMMAR_USAGE": "{index}. {prompt}",

    # ========== 統計相關 ==========
    "STATS_SUMMARY": (
        "📊 學習進度\n\n"
        "📦 素材庫：{total_items} 項（單字 {total_vocab} / 文法 {total_grammar}）\n\n"
        "✏️ 練習紀錄：{total_practice} 題（正確率 {correct_rate}%）\n\n"
        "📅 近 7 日：{recent_practice} 題（正確率 {recent_rate}%）"
    ),
    "STATS_EMPTY": "📊 尚無學習紀錄\n\n先入庫一些學習內容，再開始練習吧！",
    
    # ========== 刪除相關 ==========
    "DELETE_NOTHING": "沒有可刪除的資料 📭",
    "DELETE_LAST_SUCCESS": "已刪除最後一筆（共 {count} 筆資料）🗑️",
    "DELETE_ITEM_HINT": "請輸入要刪除的關鍵字，例如：刪除 食べる",
    "DELETE_ITEM_SUCCESS": "已刪除「{label}」🗑️",
    "DELETE_ITEM_NOT_FOUND": "找不到「{keyword}」相關的項目 📭",
    "DELETE_ITEM_SELECT": "找到 {count} 筆符合「{keyword}」的項目：\n{list}\n\n請輸入編號選擇要刪除的項目（輸入其他內容取消）",
    "DELETE_ITEM_TOO_MANY": "找到 {count} 筆符合「{keyword}」的項目（僅顯示前 5 筆）：\n{list}\n\n請輸入更精確的關鍵字縮小範圍",
    "DELETE_ITEM_INVALID_NUMBER": "請輸入有效的編號（1-{max}），或輸入其他內容取消刪除",
    "DELETE_CONFIRM_PROMPT": (
        "⚠️ 確定要清空所有資料嗎？\n\n"
        "這將刪除：\n"
        "• 所有入庫的素材\n"
        "• 所有分析出的單字和文法\n"
        "• 所有練習紀錄\n\n"
        "請在 60 秒內回覆「確定清空資料」確認\n"
        "或輸入任何其他內容取消"
    ),
    "DELETE_CONFIRM_NOT_PENDING": "沒有待確認的清空請求 🤔\n如需清空資料，請先輸入「清空資料」",
    "DELETE_CLEAR_SUCCESS": (
        "已清空所有資料 🗑️\n\n"
        "刪除了：\n"
        "• {raws} 筆原始訊息\n"
        "• {docs} 筆文件\n"
        "• {items} 筆單字/文法"
    ),
    
    # ========== 導引訊息 ==========
    "FALLBACK_UNKNOWN": (
        "我不太確定你想做什麼 🤔\n\n"
        "如果你想保存剛才的內容，請輸入「入庫」\n"
        "輸入「說明」查看所有指令"
    ),
    
    # ========== 說明訊息 ==========
    "HELP": """📖 可用指令：

• 入庫 - 儲存上一則訊息的學習內容
• 分析 - 分析已入庫的內容，抽取單字/文法
• 練習 - 開始練習題
• 結束練習 - 中途結束練習
• 查詢 <關鍵字> - 搜尋已入庫的內容
• 統計 - 查看學習進度
• 用量 - 查看 API 使用量與費用
• 英文/日文 - 切換學習語言
• 免費模式/便宜模式/嚴謹模式 - 切換 LLM 模式
• 刪除 <關鍵字> - 刪除指定的單字或文法
• 清空資料 - 刪除所有資料（需二次確認）
• 隱私 - 查看資料保存說明

💡 使用方式：
1. 貼上學習內容（日文或英文）
2. 輸入「入庫」
3. 輸入「分析」
4. 輸入「練習」開始複習！""",
    
    # ========== 隱私訊息 ==========
    "PRIVACY": """🔒 隱私說明

📦 資料保存：
• 您的 LINE ID 經過雜湊處理，無法還原
• 僅保存您主動入庫的文字內容
• 資料儲存於加密的雲端資料庫

🤖 AI 使用：
• 使用 AI 分析日文內容（單字、文法抽取）
• 使用 AI 生成練習題目
• AI 不會記憶您的對話內容

🗑️ 資料刪除：
• 輸入「刪除 <關鍵字>」刪除指定項目
• 輸入「清空資料」刪除所有資料
• 刪除後資料無法恢復

如有疑問，請聯繫開發者。""",
    
    # ========== 用量相關 ==========
    "COST_NO_DATA": "尚無 API 使用紀錄 📊\n統計將從現在開始累計",
    "COST_SUMMARY_HEADER": "📊 API 用量統計",
    "COST_MONTH_SECTION": "\n\n📅 本月",
    "COST_ALLTIME_SECTION": "\n\n📈 累計",
    "COST_MODEL_LINE": "\n• {model}: ${cost:.4f}",
    "COST_TOTAL_LINE": "\n💰 總計：${total:.4f}",

    # ========== Footer / 模式相關 ==========
    "FOOTER_USAGE": "📊本次：{in_tokens} in + {out_tokens} out ≈ ${cost}｜今日 {pct}%（{used} / {cap}）",
    "FOOTER_MODE": "⚙️模式：{mode_label}｜切換：〔免費〕〔便宜〕〔嚴謹〕",
    "FOOTER_MODE_ONLY": "⚙️模式：{mode_label}｜切換：〔免費〕〔便宜〕〔嚴謹〕",
    "FOOTER_UPGRADE_HINT": "💡 免費額度剩餘不多，可切換〔嚴謹〕模式獲得更精確回答",
    "FOOTER_COST_ESTIMATE": "💳若改用嚴謹模式：本次約 ${cost:.4f}",
    "FOOTER_CAP_WARNING": "⚠️ 今日免費額度已用完，仍可繼續使用",
    "MODE_SWITCH_CONFIRM": "已切換為 {mode_label}",

    # ========== 語言切換 ==========
    "LANG_SWITCH_CONFIRM": "已切換為學習{lang_name} 🌐",
    "LANG_SWITCH_INVALID": "不支援的語言，目前僅支援「學日文」或「學英文」",
}


# ============================================================================
# 訊息定義 - 日本語（未來支援）
# ============================================================================

_MESSAGES_JA: dict[str, str] = {
    "ERROR_GENERIC": "エラーが発生しました。しばらくしてから再試行してください 🙇",
    "SAVE_NO_CONTENT": "まず保存したい内容を送信してから「入庫」と入力してください",
    "FALLBACK_UNKNOWN": (
        "すみません、何をしたいのかわかりません 🤔\n\n"
        "内容を保存したい場合は「入庫」と入力してください\n"
        "「説明」でコマンド一覧を確認できます"
    ),
    # ... 其他訊息（未來擴展）
}


# ============================================================================
# 訊息定義 - English（未來支援）
# ============================================================================

_MESSAGES_EN: dict[str, str] = {
    "ERROR_GENERIC": "An error occurred. Please try again later 🙇",
    "SAVE_NO_CONTENT": "Please send the content you want to save first, then type \"入庫\"",
    "FALLBACK_UNKNOWN": (
        "I'm not sure what you'd like to do 🤔\n\n"
        "If you want to save content, type \"入庫\"\n"
        "Type \"說明\" to see all commands"
    ),
    # ... 其他訊息（未來擴展）
}


# 語系訊息對照表
_LOCALE_MESSAGES: dict[Locale, dict[str, str]] = {
    Locale.ZH_TW: _MESSAGES_ZH_TW,
    Locale.JA: _MESSAGES_JA,
    Locale.EN: _MESSAGES_EN,
}


# ============================================================================
# 訊息存取 API
# ============================================================================

class Messages:
    """統一訊息存取類別。
    
    提供靜態屬性直接存取常用訊息，以及 format() 方法處理帶參數的訊息。
    
    使用方式:
        # 直接存取
        Messages.ERROR_GENERIC
        
        # 帶參數
        Messages.format("SAVE_SUCCESS", short_id="abc123")
    """
    
    # 通用錯誤
    ERROR_GENERIC: str = _MESSAGES_ZH_TW["ERROR_GENERIC"]
    ERROR_ANALYZE: str = _MESSAGES_ZH_TW["ERROR_ANALYZE"]
    ERROR_PRACTICE: str = _MESSAGES_ZH_TW["ERROR_PRACTICE"]
    ERROR_PRACTICE_ANSWER: str = _MESSAGES_ZH_TW["ERROR_PRACTICE_ANSWER"]
    ERROR_SEARCH: str = _MESSAGES_ZH_TW["ERROR_SEARCH"]
    ERROR_DELETE: str = _MESSAGES_ZH_TW["ERROR_DELETE"]
    ERROR_CLEAR: str = _MESSAGES_ZH_TW["ERROR_CLEAR"]
    ERROR_CHAT: str = _MESSAGES_ZH_TW["ERROR_CHAT"]
    ERROR_SAVE: str = _MESSAGES_ZH_TW["ERROR_SAVE"]
    
    # 入庫
    SAVE_NO_CONTENT: str = _MESSAGES_ZH_TW["SAVE_NO_CONTENT"]
    PENDING_EXPIRED: str = _MESSAGES_ZH_TW["PENDING_EXPIRED"]
    
    # 分析
    ANALYZE_NO_DEFERRED: str = _MESSAGES_ZH_TW["ANALYZE_NO_DEFERRED"]
    ANALYZE_EMPTY_RESULT: str = _MESSAGES_ZH_TW["ANALYZE_EMPTY_RESULT"]
    
    # 搜尋
    SEARCH_HINT: str = _MESSAGES_ZH_TW["SEARCH_HINT"]
    
    # 練習
    PRACTICE_GENERATE_FAILED: str = _MESSAGES_ZH_TW["PRACTICE_GENERATE_FAILED"]
    PRACTICE_NO_ACTIVE_SESSION: str = _MESSAGES_ZH_TW["PRACTICE_NO_ACTIVE_SESSION"]
    PRACTICE_HEADER: str = _MESSAGES_ZH_TW["PRACTICE_HEADER"]
    PRACTICE_FOOTER: str = _MESSAGES_ZH_TW["PRACTICE_FOOTER"]
    PRACTICE_ANSWER_CORRECT: str = _MESSAGES_ZH_TW["PRACTICE_ANSWER_CORRECT"]
    
    # 刪除
    DELETE_NOTHING: str = _MESSAGES_ZH_TW["DELETE_NOTHING"]
    DELETE_ITEM_HINT: str = _MESSAGES_ZH_TW["DELETE_ITEM_HINT"]
    DELETE_CONFIRM_PROMPT: str = _MESSAGES_ZH_TW["DELETE_CONFIRM_PROMPT"]
    DELETE_CONFIRM_NOT_PENDING: str = _MESSAGES_ZH_TW["DELETE_CONFIRM_NOT_PENDING"]
    
    # 導引
    FALLBACK_UNKNOWN: str = _MESSAGES_ZH_TW["FALLBACK_UNKNOWN"]
    
    # 說明/隱私
    HELP: str = _MESSAGES_ZH_TW["HELP"]
    PRIVACY: str = _MESSAGES_ZH_TW["PRIVACY"]
    
    # 用量
    COST_NO_DATA: str = _MESSAGES_ZH_TW["COST_NO_DATA"]
    
    @classmethod
    def format(
        cls,
        key: str,
        locale: Locale = DEFAULT_LOCALE,
        **kwargs: Any,
    ) -> str:
        """格式化訊息模板。
        
        Args:
            key: 訊息鍵值
            locale: 語系（預設繁體中文）
            **kwargs: 訊息參數
            
        Returns:
            格式化後的訊息
            
        Raises:
            KeyError: 找不到指定的訊息鍵值
        """
        messages = _LOCALE_MESSAGES.get(locale, _MESSAGES_ZH_TW)
        template = messages.get(key)
        
        if template is None:
            # Fallback 到繁體中文
            template = _MESSAGES_ZH_TW.get(key)
            
        if template is None:
            raise KeyError(f"Message key not found: {key}")
            
        if kwargs:
            return template.format(**kwargs)
        return template
    
    @classmethod
    def get(
        cls,
        key: str,
        locale: Locale = DEFAULT_LOCALE,
        default: str | None = None,
    ) -> str:
        """安全取得訊息，找不到時回傳預設值。
        
        Args:
            key: 訊息鍵值
            locale: 語系
            default: 預設值（找不到時回傳）
            
        Returns:
            訊息內容或預設值
        """
        try:
            return cls.format(key, locale)
        except KeyError:
            return default or cls.ERROR_GENERIC


def get_message(
    key: str,
    locale: Locale | str = DEFAULT_LOCALE,
    **kwargs: Any,
) -> str:
    """取得格式化訊息的便捷函數。
    
    Args:
        key: 訊息鍵值
        locale: 語系（可以是 Locale enum 或字串）
        **kwargs: 訊息參數
        
    Returns:
        格式化後的訊息
    """
    if isinstance(locale, str):
        try:
            locale = Locale(locale)
        except ValueError:
            locale = DEFAULT_LOCALE
            
    return Messages.format(key, locale, **kwargs)


# ============================================================================
# 格式化輔助函數
# ============================================================================

def truncate_content_preview(content: str, max_length: int = 30) -> str:
    """截斷內容為預覽文字。"""
    first_line = content.split('\n')[0].strip()
    if len(first_line) <= max_length:
        return first_line
    return first_line[:max_length] + "..."


def format_save_success(content_preview: str, with_hint: bool = False) -> str:
    """格式化入庫成功訊息。"""
    key = "SAVE_SUCCESS_WITH_HINT" if with_hint else "SAVE_SUCCESS"
    return Messages.format(key, content_preview=content_preview)


def format_search_no_result(keyword: str) -> str:
    """格式化搜尋無結果訊息。"""
    return Messages.format("SEARCH_NO_RESULT", keyword=keyword)


def format_search_result_header(count: int) -> str:
    """格式化搜尋結果標題。"""
    return Messages.format("SEARCH_RESULT_HEADER", count=count)


def format_search_result_more(remaining: int) -> str:
    """格式化搜尋結果「還有 N 筆」。"""
    return Messages.format("SEARCH_RESULT_MORE", remaining=remaining)


def format_practice_insufficient(current: int, required: int) -> str:
    """格式化題庫不足訊息。"""
    return Messages.format(
        "PRACTICE_INSUFFICIENT_ITEMS",
        current=current,
        required=required,
    )


def format_practice_answer_wrong(expected: str) -> str:
    """格式化答案錯誤訊息。"""
    return Messages.format("PRACTICE_ANSWER_WRONG", expected=expected)


def format_practice_result(correct: int, total: int) -> str:
    """根據得分格式化練習結果訊息。"""
    if correct == total:
        key = "PRACTICE_RESULT_PERFECT"
    elif correct >= total * 0.8:
        key = "PRACTICE_RESULT_GREAT"
    elif correct >= total * 0.5:
        key = "PRACTICE_RESULT_GOOD"
    else:
        key = "PRACTICE_RESULT_NEEDS_WORK"
    return Messages.format(key, correct=correct, total=total)


def format_delete_last_success(count: int) -> str:
    """格式化刪除最後一筆成功訊息。"""
    return Messages.format("DELETE_LAST_SUCCESS", count=count)


def format_delete_item_success(label: str) -> str:
    """格式化刪除指定項目成功訊息。"""
    return Messages.format("DELETE_ITEM_SUCCESS", label=label)


def format_delete_item_not_found(keyword: str) -> str:
    """格式化刪除項目找不到訊息。"""
    return Messages.format("DELETE_ITEM_NOT_FOUND", keyword=keyword)


def format_delete_clear_success(raws: int, docs: int, items: int) -> str:
    """格式化清空資料成功訊息。"""
    return Messages.format("DELETE_CLEAR_SUCCESS", raws=raws, docs=docs, items=items)


# ============================================================================
# 模式標籤
# ============================================================================

MODE_LABELS: dict[str, str] = {
    "free": "免費",
    "cheap": "便宜",
    "rigorous": "嚴謹",
}

# 每模式的 input/output 每百萬 token 單價（USD）
MODE_PRICING: dict[str, tuple[float, float]] = {
    "free": (2.0, 12.0),        # gemini-3-pro-preview: $2/$12 per MTok
    "cheap": (3.0, 15.0),       # claude-sonnet-4-5: $3/$15 per MTok
    "rigorous": (5.0, 25.0),    # claude-opus-4-6: $5/$25 per MTok
}


def calculate_cost(mode: str, in_tokens: int, out_tokens: int) -> float:
    """計算本次請求的費用（USD）。"""
    input_price, output_price = MODE_PRICING.get(mode, (0.0, 0.0))
    return (in_tokens * input_price + out_tokens * output_price) / 1_000_000


def _format_tokens(n: int) -> str:
    """將 token 數格式化為易讀字串：< 1000 顯示原數字，≥ 1000 顯示 k。"""
    if n < 1000:
        return str(n)
    return f"{n / 1000:.1f}k"


def format_usage_footer(
    daily_used: int,
    daily_cap: int,
    in_tokens: int,
    out_tokens: int,
    mode: str,
) -> str:
    """組裝 API 使用度 footer。

    Args:
        daily_used: 今日已使用 token
        daily_cap: 每日 token 上限
        in_tokens: 本次 input tokens
        out_tokens: 本次 output tokens
        mode: 目前模式

    Returns:
        Footer 文字（2~4 行）
    """
    mode_label = MODE_LABELS.get(mode, mode)
    lines: list[str] = []

    cost = calculate_cost(mode, in_tokens, out_tokens)
    cost_str = f"{cost:.4f}" if cost > 0 else "0"

    if daily_cap > 0:
        pct = min(int(daily_used / daily_cap * 100), 100)
        lines.append(Messages.format(
            "FOOTER_USAGE",
            pct=pct,
            used=_format_tokens(daily_used),
            cap=_format_tokens(daily_cap),
            in_tokens=in_tokens,
            out_tokens=out_tokens,
            cost=cost_str,
        ))
    else:
        lines.append(Messages.format(
            "FOOTER_USAGE",
            pct=0,
            used="0",
            cap="0",
            in_tokens=in_tokens,
            out_tokens=out_tokens,
            cost=cost_str,
        ))

    lines.append(Messages.format("FOOTER_MODE", mode_label=mode_label))

    # 升級提示：剩餘 < 15%
    if daily_cap > 0 and (daily_cap - daily_used) < daily_cap * 0.15:
        if mode != "rigorous":
            lines.append(_MESSAGES_ZH_TW["FOOTER_UPGRADE_HINT"])

    # 額度用盡警告
    if daily_cap > 0 and daily_used >= daily_cap:
        lines.append(_MESSAGES_ZH_TW["FOOTER_CAP_WARNING"])

    return "\n".join(lines)


def format_lang_switch_confirm(lang: str) -> str:
    """格式化語言切換確認訊息。"""
    lang_name = {"ja": "日文", "en": "英文"}.get(lang, lang)
    return Messages.format("LANG_SWITCH_CONFIRM", lang_name=lang_name)


def format_mode_switch_confirm(mode: str) -> str:
    """格式化模式切換確認訊息。"""
    mode_label = MODE_LABELS.get(mode, mode)
    return Messages.format("MODE_SWITCH_CONFIRM", mode_label=mode_label)


def format_stats_summary(
    total_vocab: int,
    total_grammar: int,
    total_practice: int,
    correct_rate: int,
    recent_practice: int,
    recent_rate: int,
) -> str:
    """格式化學習進度統計訊息。"""
    total_items = total_vocab + total_grammar
    if total_items == 0 and total_practice == 0:
        return _MESSAGES_ZH_TW["STATS_EMPTY"]
    return Messages.format(
        "STATS_SUMMARY",
        total_items=total_items,
        total_vocab=total_vocab,
        total_grammar=total_grammar,
        total_practice=total_practice,
        correct_rate=correct_rate,
        recent_practice=recent_practice,
        recent_rate=recent_rate,
    )


def format_cost_summary(
    all_time_summary: list,
    month_summary: list,
    all_time_total: float,
    month_total: float,
) -> str:
    """格式化 API 用量摘要訊息。

    Args:
        all_time_summary: 累計用量摘要列表 (UsageSummary)
        month_summary: 本月用量摘要列表 (UsageSummary)
        all_time_total: 累計總費用
        month_total: 本月總費用

    Returns:
        格式化的用量摘要訊息
    """
    if not all_time_summary:
        return Messages.COST_NO_DATA

    lines = [Messages.format("COST_SUMMARY_HEADER")]

    # 本月摘要
    if month_summary:
        lines.append(Messages.format("COST_MONTH_SECTION"))
        for s in month_summary:
            lines.append(Messages.format("COST_MODEL_LINE", model=s.model, cost=s.total_cost_usd))
        lines.append(Messages.format("COST_TOTAL_LINE", total=month_total))
    else:
        lines.append(Messages.format("COST_MONTH_SECTION"))
        lines.append("\n• (無紀錄)")

    # 累計摘要
    lines.append(Messages.format("COST_ALLTIME_SECTION"))
    for s in all_time_summary:
        lines.append(Messages.format("COST_MODEL_LINE", model=s.model, cost=s.total_cost_usd))
    lines.append(Messages.format("COST_TOTAL_LINE", total=all_time_total))

    return "".join(lines)
