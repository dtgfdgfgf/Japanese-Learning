"""
Unit tests for list items (清單) command.
"""

from unittest.mock import MagicMock

import pytest

from src.schemas.command import CommandType
from src.services.command_service import parse_command
from src.templates.messages import Messages


def _make_item(item_type: str, **payload_fields: object) -> MagicMock:
    """建立 mock Item 物件。"""
    item = MagicMock()
    item.item_type = item_type
    item.payload = payload_fields
    return item


class TestFormatListItems:
    """Tests for _format_list_items formatting function."""

    def test_format_mixed_items(self) -> None:
        """混合單字和文法的格式化。"""
        from src.api.webhook import _format_list_items

        items = [
            _make_item("vocab", surface="食べる", reading="たべる", glossary_zh=["吃"]),
            _make_item("vocab", surface="飲む", reading="のむ", glossary_zh=["喝"]),
            _make_item("grammar", pattern="～ている", meaning_zh="正在進行"),
        ]

        result = _format_list_items(items, type_filter=None)

        assert "共 3 項" in result
        assert "【單字】(2 項)" in result
        assert "【文法】(1 項)" in result
        assert "食べる【たべる】- 吃" in result
        assert "飲む【のむ】- 喝" in result
        assert "～ている - 正在進行" in result

    def test_format_vocab_only_filter(self) -> None:
        """篩選單字清單。"""
        from src.api.webhook import _format_list_items

        items = [
            _make_item("vocab", surface="食べる", reading="たべる", glossary_zh=["吃"]),
        ]

        result = _format_list_items(items, type_filter="vocab")

        assert "共 1 項" in result
        assert "【單字】(1 項)" in result
        assert "【文法】" not in result

    def test_format_grammar_only_filter(self) -> None:
        """篩選文法清單。"""
        from src.api.webhook import _format_list_items

        items = [
            _make_item("grammar", pattern="～たい", meaning_zh="想要"),
        ]

        result = _format_list_items(items, type_filter="grammar")

        assert "共 1 項" in result
        assert "【文法】(1 項)" in result
        assert "【單字】" not in result

    def test_format_vocab_with_pronunciation(self) -> None:
        """英文單字使用 pronunciation 而非 reading。"""
        from src.api.webhook import _format_list_items

        items = [
            _make_item("vocab", surface="apple", pronunciation="AE-puhl", glossary_zh=["蘋果"]),
        ]

        result = _format_list_items(items, type_filter=None)

        assert "apple (AE-puhl) - 蘋果" in result

    def test_format_vocab_same_surface_reading(self) -> None:
        """surface 和 reading 相同時不顯示【reading】。"""
        from src.api.webhook import _format_list_items

        items = [
            _make_item("vocab", surface="すし", reading="すし", glossary_zh=["壽司"]),
        ]

        result = _format_list_items(items, type_filter=None)

        assert "すし - 壽司" in result
        assert "【すし】" not in result

    def test_format_empty_glossary(self) -> None:
        """glossary_zh 為空時仍能正常顯示。"""
        from src.api.webhook import _format_list_items

        items = [
            _make_item("vocab", surface="テスト", reading="テスト", glossary_zh=[]),
        ]

        result = _format_list_items(items, type_filter=None)

        assert "テスト - " in result
