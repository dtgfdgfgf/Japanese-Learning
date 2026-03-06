"""_classify_input() 結構特徵分類的單元測試。

純函式測試，不需 mock。
"""

import pytest

from src.api.webhook import InputCategory, _classify_input


# ============================================================================
# 1. 含假名 → 日文內容
# ============================================================================


class TestKanaDetection:
    """含假名的輸入應被視為日文內容。"""

    def test_single_hiragana_word(self) -> None:
        assert _classify_input("たべる") == InputCategory.WORD

    def test_single_katakana_word(self) -> None:
        assert _classify_input("コーヒー") == InputCategory.WORD

    def test_kanji_with_kana_short(self) -> None:
        """漢字+假名短詞 → WORD"""
        assert _classify_input("食べる") == InputCategory.WORD

    def test_kana_with_sentence_punctuation(self) -> None:
        """含句讀 → MATERIAL"""
        assert _classify_input("今日は天気がいいですね。") == InputCategory.MATERIAL

    def test_kana_with_exclamation(self) -> None:
        # NFKC 正規化後 ！→!
        assert _classify_input("すごい!") == InputCategory.MATERIAL

    def test_kana_with_question_mark(self) -> None:
        assert _classify_input("何ですか?") == InputCategory.MATERIAL

    def test_kana_with_comma(self) -> None:
        assert _classify_input("赤い、青い") == InputCategory.MATERIAL

    def test_kana_short_words_with_newline(self) -> None:
        """短日文單字換行分隔 → WORD（多單字輸入）"""
        assert _classify_input("食べる\n飲む") == InputCategory.WORD

    def test_kana_short_words_with_space(self) -> None:
        """短日文單字空格分隔 → WORD（多單字輸入）"""
        assert _classify_input("はんしゃする はしのした") == InputCategory.WORD

    def test_kana_many_short_words_with_newline(self) -> None:
        """多個短日文單字換行分隔（≤5） → WORD"""
        assert _classify_input("食べる\n飲む\n走る") == InputCategory.WORD

    def test_kana_many_words_with_newline_no_limit(self) -> None:
        """6+ 個短日文 token + 換行 → WORD（移除上限後）"""
        text = "\n".join(["食べる", "飲む", "走る", "泳ぐ", "読む", "書く"])
        assert _classify_input(text) == InputCategory.WORD

    def test_kana_long_text_with_newline(self) -> None:
        """長日文含換行（每個 token 超過閾值） → MATERIAL"""
        text = "あ" * 15 + "\n" + "い" * 15
        assert _classify_input(text) == InputCategory.MATERIAL

    def test_kana_long_text_no_punct(self) -> None:
        """超過 20 字元、無標點但有假名 → MATERIAL"""
        text = "あ" * 21
        assert _classify_input(text) == InputCategory.MATERIAL

    def test_kana_exactly_20_chars(self) -> None:
        """正好 20 字元（≤ 20）→ WORD"""
        text = "あ" * 20
        assert _classify_input(text) == InputCategory.WORD

    def test_mixed_kanji_kana_paragraph(self) -> None:
        """真實日文段落（有句讀）→ MATERIAL"""
        text = "日本語の勉強は楽しいです。毎日少しずつ頑張っています。"
        assert _classify_input(text) == InputCategory.MATERIAL

    def test_kana_short_no_punct(self) -> None:
        """短假名字串（<= 20、無標點）→ WORD"""
        assert _classify_input("おはよう") == InputCategory.WORD

    def test_mixed_kana_ascii_short(self) -> None:
        """含假名+英文混合但短 → WORD（假名優先判定）"""
        assert _classify_input("appleは") == InputCategory.WORD


# ============================================================================
# 2. 無假名、有 CJK → 歧義
# ============================================================================


class TestCjkWithoutKana:
    """無假名但有 CJK 漢字的輸入。"""

    def test_short_kanji_word(self) -> None:
        """短漢字詞 → WORD"""
        assert _classify_input("勉強") == InputCategory.WORD

    def test_single_kanji(self) -> None:
        assert _classify_input("食") == InputCategory.WORD

    def test_chinese_question(self) -> None:
        """中文問句 → CHAT"""
        assert _classify_input("這個文法怎麼用?") == InputCategory.CHAT

    def test_chinese_question_ma(self) -> None:
        assert _classify_input("你會日文嗎") == InputCategory.CHAT

    def test_chinese_question_shenme(self) -> None:
        assert _classify_input("什麼意思") == InputCategory.CHAT

    def test_chinese_question_ruhe(self) -> None:
        assert _classify_input("如何學習") == InputCategory.CHAT

    def test_long_cjk_no_kana(self) -> None:
        """長漢字文本（>20字）→ MATERIAL"""
        text = "漢" * 21
        assert _classify_input(text) == InputCategory.MATERIAL

    def test_cjk_exactly_threshold(self) -> None:
        """正好 20 字漢字 → WORD"""
        text = "漢" * 20
        assert _classify_input(text) == InputCategory.WORD


# ============================================================================
# 3. 英文為主
# ============================================================================


class TestEnglishDominant:
    """英文比例 > 0.5 的輸入。"""

    def test_single_english_word(self) -> None:
        assert _classify_input("apple") == InputCategory.WORD

    def test_single_english_word_with_hyphen(self) -> None:
        assert _classify_input("well-known") == InputCategory.WORD

    def test_english_sentence_with_period(self) -> None:
        assert _classify_input("I like sushi.") == InputCategory.MATERIAL

    def test_english_sentence_with_exclamation(self) -> None:
        assert _classify_input("Hello world!") == InputCategory.MATERIAL

    def test_english_with_newline(self) -> None:
        """英文短單字換行分隔 → WORD（移除上限後）"""
        assert _classify_input("hello\nworld") == InputCategory.WORD

    def test_multi_word_short_tokens(self) -> None:
        """2-5 個短 alpha token → WORD（multi-word）"""
        assert _classify_input("apple banana cherry") == InputCategory.WORD

    def test_multi_word_five_tokens(self) -> None:
        assert _classify_input("one two three four five") == InputCategory.WORD

    def test_multi_word_six_tokens(self) -> None:
        """6+ 個短 alpha token → WORD（移除上限後）"""
        assert _classify_input("one two three four five six") == InputCategory.WORD

    def test_multi_word_ten_plus_tokens(self) -> None:
        """10+ 個短 alpha token → WORD"""
        text = "one two three four five six seven eight nine ten eleven"
        assert _classify_input(text) == InputCategory.WORD

    def test_english_question_mark(self) -> None:
        """英文問句有 '?' 標點 → MATERIAL（英文句讀優先）"""
        assert _classify_input("What is this?") == InputCategory.MATERIAL

    def test_two_word_phrase(self) -> None:
        """兩個短單字 → WORD"""
        assert _classify_input("good morning") == InputCategory.WORD

    def test_short_word_ok(self) -> None:
        """'ok' → WORD"""
        assert _classify_input("ok") == InputCategory.WORD


# ============================================================================
# 4. 中文問句標記（非英文、非 CJK/假名主導）
# ============================================================================


class TestChatFallback:
    """含問句標記但不屬於前三類的輸入。"""

    def test_pure_question_mark(self) -> None:
        """純 '?' 字元（ascii_alpha_count=0）→ 不走英文路徑，走問句路徑"""
        assert _classify_input("???") == InputCategory.CHAT


# ============================================================================
# 5. UNKNOWN
# ============================================================================


class TestUnknown:
    """無法分類的輸入。"""

    def test_empty_string(self) -> None:
        assert _classify_input("") == InputCategory.UNKNOWN

    def test_whitespace_only(self) -> None:
        assert _classify_input("   ") == InputCategory.UNKNOWN

    def test_numbers_only(self) -> None:
        """純數字 → UNKNOWN"""
        assert _classify_input("12345") == InputCategory.UNKNOWN

    def test_symbols_only(self) -> None:
        """純符號 → UNKNOWN"""
        assert _classify_input("@#$%^&") == InputCategory.UNKNOWN


# ============================================================================
# target_lang 不影響分類邏輯（分類只看結構特徵）
# ============================================================================


class TestTargetLangIndependent:
    """target_lang 參數不影響 _classify_input 的結果。"""

    def test_kana_word_en_mode(self) -> None:
        assert _classify_input("たべる", target_lang="en") == InputCategory.WORD

    def test_english_word_ja_mode(self) -> None:
        assert _classify_input("apple", target_lang="ja") == InputCategory.WORD

    def test_kana_material_en_mode(self) -> None:
        assert _classify_input("今日は天気がいいですね。", target_lang="en") == InputCategory.MATERIAL
