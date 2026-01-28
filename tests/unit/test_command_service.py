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

    def test_parse_delete_last_command(self):
        """Test parsing '刪除最後一筆' command."""
        result = parse_command("刪除最後一筆")
        assert result.command_type == CommandType.DELETE_LAST
        assert result.keyword is None

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
            "delete_last": CommandType.DELETE_LAST,
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
