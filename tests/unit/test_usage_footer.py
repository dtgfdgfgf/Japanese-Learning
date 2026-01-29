"""
format_usage_footer 的單元測試。

測試各種情境：正常、額度用盡、升級提示、零 token。
"""

import pytest

from src.templates.messages import format_usage_footer, format_mode_switch_confirm


class TestFormatUsageFooter:
    """測試 format_usage_footer 各種情境。"""

    def test_normal_usage(self):
        """正常使用量應顯示百分比和 token 資訊。"""
        result = format_usage_footer(
            daily_used=10000,
            daily_cap=50000,
            in_tokens=100,
            out_tokens=50,
            mode="balanced",
        )
        assert "20%" in result
        assert "10.0k" in result
        assert "50k" in result
        assert "100 in" in result
        assert "50 out" in result
        assert "推薦" in result

    def test_zero_tokens_this_request(self):
        """本次 token 為 0 的情況（如 postback 事件）。"""
        result = format_usage_footer(
            daily_used=5000,
            daily_cap=50000,
            in_tokens=0,
            out_tokens=0,
            mode="cheap",
        )
        assert "0 in" in result
        assert "0 out" in result
        assert "省錢" in result

    def test_cap_exceeded_warning(self):
        """額度用盡應顯示警告。"""
        result = format_usage_footer(
            daily_used=50000,
            daily_cap=50000,
            in_tokens=200,
            out_tokens=100,
            mode="balanced",
        )
        assert "已用完" in result
        assert "100%" in result

    def test_upgrade_hint_when_low(self):
        """剩餘不足 15% 且非嚴謹模式應顯示升級提示。"""
        result = format_usage_footer(
            daily_used=44000,
            daily_cap=50000,
            in_tokens=100,
            out_tokens=50,
            mode="cheap",
        )
        assert "嚴謹" in result
        # 應有升級提示
        assert "額度" in result or "切換" in result

    def test_no_upgrade_hint_for_rigorous(self):
        """嚴謹模式下即使額度低也不應顯示升級提示。"""
        result = format_usage_footer(
            daily_used=44000,
            daily_cap=50000,
            in_tokens=100,
            out_tokens=50,
            mode="rigorous",
        )
        # 不應包含升級提示文字
        lines = result.split("\n")
        upgrade_lines = [l for l in lines if "免費額度剩餘" in l]
        assert len(upgrade_lines) == 0

    def test_zero_cap(self):
        """daily_cap 為 0 時不應 division by zero。"""
        result = format_usage_footer(
            daily_used=0,
            daily_cap=0,
            in_tokens=10,
            out_tokens=5,
            mode="balanced",
        )
        assert "0%" in result

    def test_estimated_cost(self):
        """提供成本估算時應顯示。"""
        result = format_usage_footer(
            daily_used=10000,
            daily_cap=50000,
            in_tokens=100,
            out_tokens=50,
            mode="balanced",
            estimated_cost=0.0123,
        )
        assert "$0.0123" in result

    def test_all_modes_have_labels(self):
        """三種模式都應有對應的中文標籤。"""
        for mode in ("cheap", "balanced", "rigorous"):
            result = format_usage_footer(
                daily_used=1000,
                daily_cap=50000,
                in_tokens=10,
                out_tokens=5,
                mode=mode,
            )
            assert "模式" in result


class TestFormatModeSwitchConfirm:
    """測試模式切換確認訊息。"""

    @pytest.mark.parametrize(
        "mode,expected_label",
        [
            ("cheap", "省錢"),
            ("balanced", "推薦"),
            ("rigorous", "嚴謹"),
        ],
    )
    def test_confirm_message(self, mode: str, expected_label: str):
        """確認訊息應包含對應的模式標籤。"""
        result = format_mode_switch_confirm(mode)
        assert expected_label in result
        assert "已切換" in result
