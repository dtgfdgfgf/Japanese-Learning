"""文章閱讀模式相關 prompt 模板。"""

import re


def _escape_xml_tags(text: str) -> str:
    """跳脫使用者文字中的 XML-like tag，防止 prompt injection 跳脫分隔符。

    將 < 和 > 替換為全形 ＜ ＞，避免使用者偽造 </article_context> 等 tag。
    僅處理看起來像 XML tag 的 pattern（<word> 或 </word>），
    不影響一般數學符號（如 3 < 5）。
    """
    return re.sub(r"<(/?\w+[^>]*)>", r"＜\1＞", text)


ARTICLE_TRANSLATION_SYSTEM_PROMPT = """你是日語學習助教。
將以下日文文章翻譯成繁體中文。
要求：自然通順、保留原文語氣、專有名詞附原文。
回覆必須使用繁體中文（zh-TW）。"""


def format_article_translation_request(text: str) -> str:
    """組裝文章翻譯的 user message。"""
    safe_text = _escape_xml_tags(text)
    return f"<article>\n{safe_text}\n</article>"


def build_article_word_lookup_system_prompt(
    base_system_prompt: str,
    article_text: str,
) -> str:
    """在既有單字查詞 system prompt 後面注入文章語境。

    Args:
        base_system_prompt: 原始 get_word_explanation_structured 的 system prompt
        article_text: 使用者正在閱讀的文章原文

    Returns:
        附帶文章語境的 system prompt
    """
    safe_text = _escape_xml_tags(article_text)
    context_block = f"""

## 額外語境
以下是使用者正在閱讀的文章，請根據此語境提供更精準的解釋：
<article_context>
{safe_text}
</article_context>

如果使用者輸入的是中文，請先找出文章中對應的日文詞彙/文法，再進行解釋。"""
    return base_system_prompt + context_block
