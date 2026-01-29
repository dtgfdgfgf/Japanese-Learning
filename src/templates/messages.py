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
    "SAVE_SUCCESS": "已入庫：#{short_id}",
    "SAVE_SUCCESS_WITH_HINT": "已入庫：#{short_id}\n\n💡 輸入「分析」來抽取單字和文法",
    "SAVE_NO_CONTENT": "請先貼上要入庫的內容，再輸入「入庫」",
    
    # ========== 分析相關 ==========
    "ANALYZE_NO_DEFERRED": "沒有待分析的素材 📭\n請先「入庫」一些日文內容",
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
    
    # ========== 刪除相關 ==========
    "DELETE_NOTHING": "沒有可刪除的資料 📭",
    "DELETE_LAST_SUCCESS": "已刪除最後一筆（共 {count} 筆資料）🗑️",
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

• 入庫 - 儲存上一則訊息的日文內容
• 分析 - 分析已入庫的內容，抽取單字/文法
• 練習 - 開始練習題
• 查詢 <關鍵字> - 搜尋已入庫的內容
• 用量 - 查看 API 使用量與費用
• 免費模式/便宜模式/嚴謹模式 - 切換 LLM 模式
• 刪除最後一筆 - 刪除最近一筆入庫
• 清空資料 - 刪除所有資料（需二次確認）
• 隱私 - 查看資料保存說明

💡 使用方式：
1. 貼上日文內容
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
• 輸入「刪除最後一筆」刪除最近一筆
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
    "FOOTER_USAGE": "📊API使用度：今日 {pct}%（{used_k}k / {cap_k}k tokens）｜本次 {in_tokens} in + {out_tokens} out",
    "FOOTER_MODE": "⚙️模式：{mode_label}｜切換：〔免費〕〔便宜〕〔嚴謹〕",
    "FOOTER_MODE_ONLY": "⚙️模式：{mode_label}｜切換：〔免費〕〔便宜〕〔嚴謹〕",
    "FOOTER_UPGRADE_HINT": "💡 免費額度剩餘不多，可切換〔嚴謹〕模式獲得更精確回答",
    "FOOTER_COST_ESTIMATE": "💳若改用嚴謹模式：本次約 ${cost:.4f}",
    "FOOTER_CAP_WARNING": "⚠️ 今日免費額度已用完，仍可繼續使用",
    "MODE_SWITCH_CONFIRM": "已切換為 {mode_label}",
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

def format_save_success(short_id: str, with_hint: bool = False) -> str:
    """格式化入庫成功訊息。"""
    key = "SAVE_SUCCESS_WITH_HINT" if with_hint else "SAVE_SUCCESS"
    return Messages.format(key, short_id=short_id)


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


def format_usage_footer(
    daily_used: int,
    daily_cap: int,
    in_tokens: int,
    out_tokens: int,
    mode: str,
    estimated_cost: float | None = None,
) -> str:
    """組裝 API 使用度 footer。

    Args:
        daily_used: 今日已使用 token
        daily_cap: 每日 token 上限
        in_tokens: 本次 input tokens
        out_tokens: 本次 output tokens
        mode: 目前模式
        estimated_cost: 嚴謹模式成本估算 (可選)

    Returns:
        Footer 文字（2~4 行）
    """
    mode_label = MODE_LABELS.get(mode, mode)
    lines: list[str] = []

    if daily_cap > 0:
        pct = min(int(daily_used / daily_cap * 100), 100)
        used_k = f"{daily_used / 1000:.1f}"
        cap_k = f"{daily_cap / 1000:.0f}"
        lines.append(Messages.format(
            "FOOTER_USAGE",
            pct=pct,
            used_k=used_k,
            cap_k=cap_k,
            in_tokens=in_tokens,
            out_tokens=out_tokens,
        ))
    else:
        lines.append(Messages.format(
            "FOOTER_USAGE",
            pct=0,
            used_k="0",
            cap_k="0",
            in_tokens=in_tokens,
            out_tokens=out_tokens,
        ))

    lines.append(Messages.format("FOOTER_MODE", mode_label=mode_label))

    # 升級提示：剩餘 < 15%
    if daily_cap > 0 and (daily_cap - daily_used) < daily_cap * 0.15:
        if mode != "rigorous":
            lines.append(_MESSAGES_ZH_TW["FOOTER_UPGRADE_HINT"])

    # 額度用盡警告
    if daily_cap > 0 and daily_used >= daily_cap:
        lines.append(_MESSAGES_ZH_TW["FOOTER_CAP_WARNING"])

    # 成本估算
    if estimated_cost is not None and estimated_cost > 0:
        lines.append(Messages.format("FOOTER_COST_ESTIMATE", cost=estimated_cost))

    return "\n".join(lines)


def format_mode_switch_confirm(mode: str) -> str:
    """格式化模式切換確認訊息。"""
    mode_label = MODE_LABELS.get(mode, mode)
    return Messages.format("MODE_SWITCH_CONFIRM", mode_label=mode_label)


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
