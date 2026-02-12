"""
Unit tests for command service.

T033: Unit tests for command parser
DoD: 測試涵蓋所有 CommandType；邊界案例通過
"""

import pytest
from src.schemas.command import CommandType
from src.services.command_service import parse_command


class TestParseCommand:
    """Tests for the parse_command function."""

    def test_parse_save_command(self):
        """Test parsing '入庫' command."""
        result = parse_command("入庫")
        assert result.command_type == CommandType.SAVE
        assert result.keyword is None

    def test_parse_analyze_command(self):
        """Test parsing '分析' command."""
        result = parse_command("分析")
        assert result.command_type == CommandType.ANALYZE
        assert result.keyword is None

    def test_parse_practice_command(self):
        """Test parsing '練習' command."""
        result = parse_command("練習")
        assert result.command_type == CommandType.PRACTICE
        assert result.keyword is None

    def test_parse_search_command_with_keyword(self):
        """Test parsing '查詢' command with keyword."""
        result = parse_command("查詢 考える")
        assert result.command_type == CommandType.SEARCH
        assert result.keyword == "考える"

    def test_parse_search_command_without_keyword(self):
        """Test parsing '查詢' command without keyword."""
        result = parse_command("查詢")
        assert result.command_type == CommandType.SEARCH
        assert result.keyword is None

    def test_parse_search_with_japanese_keyword(self):
        """Test parsing '查詢' with complex Japanese keyword."""
        result = parse_command("查詢 食べてしまった")
        assert result.command_type == CommandType.SEARCH
        assert result.keyword == "食べてしまった"

    def test_parse_delete_item_with_keyword(self):
        """Test parsing '刪除 食べる' command."""
        result = parse_command("刪除 食べる")
        assert result.command_type == CommandType.DELETE_ITEM
        assert result.keyword == "食べる"

    def test_parse_delete_item_without_keyword(self):
        """Test parsing '刪除' command without keyword."""
        result = parse_command("刪除")
        assert result.command_type == CommandType.DELETE_ITEM
        assert result.keyword is None

    def test_parse_delete_item_with_spaces_in_keyword(self):
        """Test parsing '刪除 te form' command with spaces in keyword."""
        result = parse_command("刪除 te form")
        assert result.command_type == CommandType.DELETE_ITEM
        assert result.keyword == "te form"

    def test_parse_delete_last_no_longer_matches(self):
        """Test '刪除最後一筆' no longer matches (requires space after 刪除)."""
        result = parse_command("刪除最後一筆")
        assert result.command_type == CommandType.UNKNOWN

    def test_parse_delete_all_command(self):
        """Test parsing '清空資料' command."""
        result = parse_command("清空資料")
        assert result.command_type == CommandType.DELETE_ALL
        assert result.keyword is None

    def test_parse_privacy_command(self):
        """Test parsing '隱私' command."""
        result = parse_command("隱私")
        assert result.command_type == CommandType.PRIVACY
        assert result.keyword is None

    def test_parse_help_command(self):
        """Test parsing '說明' command."""
        result = parse_command("說明")
        assert result.command_type == CommandType.HELP
        assert result.keyword is None

    def test_parse_stats_command(self):
        """Test parsing '統計' command."""
        result = parse_command("統計")
        assert result.command_type == CommandType.STATS
        assert result.keyword is None

    def test_parse_stats_progress_command(self):
        """Test parsing '進度' command."""
        result = parse_command("進度")
        assert result.command_type == CommandType.STATS
        assert result.keyword is None

    def test_parse_unknown_command(self):
        """Test parsing unknown command."""
        result = parse_command("隨便打的文字")
        assert result.command_type == CommandType.UNKNOWN
        assert result.keyword is None

    def test_parse_empty_string(self):
        """Test parsing empty string."""
        result = parse_command("")
        assert result.command_type == CommandType.UNKNOWN
        assert result.keyword is None

    def test_parse_whitespace_only(self):
        """Test parsing whitespace only."""
        result = parse_command("   ")
        assert result.command_type == CommandType.UNKNOWN
        assert result.keyword is None

    def test_parse_command_with_extra_whitespace(self):
        """Test parsing command with extra whitespace."""
        result = parse_command("  入庫  ")
        assert result.command_type == CommandType.SAVE

    def test_parse_search_with_extra_whitespace(self):
        """Test parsing '查詢' with extra whitespace."""
        result = parse_command("查詢    考える  ")
        assert result.command_type == CommandType.SEARCH
        assert result.keyword == "考える"

    def test_raw_text_preserved(self):
        """Test that raw_text is preserved in result."""
        result = parse_command("入庫")
        assert result.raw_text == "入庫"

    def test_parse_japanese_only_text(self):
        """Test parsing pure Japanese text (not a command)."""
        result = parse_command("美しい景色を見た")
        assert result.command_type == CommandType.UNKNOWN
        assert result.keyword is None
        assert result.raw_text == "美しい景色を見た"

    def test_parse_english_text(self):
        """Test parsing English text."""
        result = parse_command("Hello world")
        assert result.command_type == CommandType.UNKNOWN

    def test_all_commands_from_samples(self, command_samples):
        """Test all commands from the fixture samples."""
        command_mapping = {
            "save": CommandType.SAVE,
            "analyze": CommandType.ANALYZE,
            "practice": CommandType.PRACTICE,
            "search": CommandType.SEARCH,
            "delete_item": CommandType.DELETE_ITEM,
            "delete_all": CommandType.DELETE_ALL,
            "privacy": CommandType.PRIVACY,
            "help": CommandType.HELP,
            "unknown": CommandType.UNKNOWN,
        }
        
        for sample in command_samples:
            result = parse_command(sample["input"])
            expected_type = command_mapping[sample["expected_command"]]
            assert result.command_type == expected_type, (
                f"Failed for input: {sample['input']}, "
                f"expected: {expected_type}, got: {result.command_type}"
            )
            
            # Check keyword if specified
            if "expected_keyword" in sample:
                assert result.keyword == sample["expected_keyword"], (
                    f"Failed keyword for input: {sample['input']}"
                )


class TestSetLangCommand:
    """Tests for SET_LANG command parsing."""

    def test_parse_english_lang(self):
        """Test parsing '英文' command."""
        result = parse_command("英文")
        assert result.command_type == CommandType.SET_LANG
        assert result.keyword == "英文"

    def test_parse_japanese_lang(self):
        """Test parsing '日文' command."""
        result = parse_command("日文")
        assert result.command_type == CommandType.SET_LANG
        assert result.keyword == "日文"

    def test_lang_name_map(self):
        """Test LANG_NAME_MAP contains expected mappings."""
        from src.services.command_service import LANG_NAME_MAP

        assert LANG_NAME_MAP["英文"] == "en"
        assert LANG_NAME_MAP["日文"] == "ja"

    def test_partial_lang_not_matched(self):
        """Test that partial text doesn't match SET_LANG."""
        result = parse_command("學英文")
        assert result.command_type == CommandType.UNKNOWN


class TestWordSaveCommand:
    """Tests for WORD_SAVE command parsing（「單字 入庫」直接入庫）。"""

    def test_word_save_parsed(self):
        """「するどい save」→ WORD_SAVE，keyword=するどい。"""
        result = parse_command("するどい save")
        assert result.command_type == CommandType.WORD_SAVE
        assert result.keyword == "するどい"

    def test_word_save_multi_word(self):
        """「hello world save」→ keyword=「hello world」（greedy .+ 匹配多字詞）。"""
        result = parse_command("hello world save")
        assert result.command_type == CommandType.WORD_SAVE
        assert result.keyword == "hello world"

    def test_plain_save_still_works(self):
        """純「入庫」仍匹配 SAVE（不受 WORD_SAVE pattern 影響）。"""
        result = parse_command("入庫")
        assert result.command_type == CommandType.SAVE
        assert result.keyword is None

    def test_word_save_whitespace(self):
        """前後空格應正常匹配（strip 後匹配）。"""
        result = parse_command("  するどい  save  ")
        assert result.command_type == CommandType.WORD_SAVE
        assert result.keyword == "するどい"

    def test_word_save_english(self):
        """英文單字「apple save」→ WORD_SAVE。"""
        result = parse_command("apple save")
        assert result.command_type == CommandType.WORD_SAVE
        assert result.keyword == "apple"

    def test_word_save_kanji(self):
        """漢字「鋭い save」→ WORD_SAVE。"""
        result = parse_command("鋭い save")
        assert result.command_type == CommandType.WORD_SAVE
        assert result.keyword == "鋭い"

    def test_word_save_case_insensitive(self):
        """「apple Save」→ case-insensitive 匹配。"""
        result = parse_command("apple Save")
        assert result.command_type == CommandType.WORD_SAVE
        assert result.keyword == "apple"

    def test_bare_save_is_unknown(self):
        """純「save」不匹配 WORD_SAVE（.+ 需至少一字元 + 空格）。"""
        result = parse_command("save")
        assert result.command_type == CommandType.UNKNOWN
