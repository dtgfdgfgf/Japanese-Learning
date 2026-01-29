"""
模式切換指令解析的單元測試。

測試文字指令「省錢模式」「切換推薦」等解析為 MODE_SWITCH。
"""

import pytest

from src.schemas.command import CommandType
from src.services.command_service import MODE_NAME_MAP, parse_command


class TestModeSwitchParsing:
    """測試模式切換指令解析。"""

    @pytest.mark.parametrize(
        "text,expected_keyword",
        [
            ("省錢模式", "省錢模式"),
            ("推薦模式", "推薦模式"),
            ("嚴謹模式", "嚴謹模式"),
            ("切換省錢", "省錢"),
            ("切換推薦", "推薦"),
            ("切換嚴謹", "嚴謹"),
        ],
    )
    def test_mode_switch_commands(self, text: str, expected_keyword: str):
        """各種模式切換文字應被解析為 MODE_SWITCH。"""
        result = parse_command(text)
        assert result.command_type == CommandType.MODE_SWITCH
        assert result.keyword == expected_keyword
        assert result.confidence == 1.0

    def test_non_mode_text_is_unknown(self):
        """非模式切換指令應為 UNKNOWN。"""
        result = parse_command("隨便聊聊")
        assert result.command_type == CommandType.UNKNOWN

    def test_partial_mode_text_is_unknown(self):
        """不完整的模式指令應為 UNKNOWN。"""
        result = parse_command("切換")
        assert result.command_type == CommandType.UNKNOWN


class TestModeNameMap:
    """測試 MODE_NAME_MAP 映射。"""

    @pytest.mark.parametrize(
        "name,expected_key",
        [
            ("省錢", "cheap"),
            ("推薦", "balanced"),
            ("嚴謹", "rigorous"),
            ("省錢模式", "cheap"),
            ("推薦模式", "balanced"),
            ("嚴謹模式", "rigorous"),
        ],
    )
    def test_mode_name_mapping(self, name: str, expected_key: str):
        """MODE_NAME_MAP 應正確映射中文名稱到 mode key。"""
        assert MODE_NAME_MAP[name] == expected_key

    def test_unknown_name_not_in_map(self):
        """未知名稱不應在映射中。"""
        assert "一般模式" not in MODE_NAME_MAP
