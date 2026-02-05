"""
format_usage_footer 的單元測試。

測試各種情境：正常、額度用盡、升級提示、零 token、花費顯示。
"""

import pytest

from src.templates.messages import (
    calculate_cost,
    format_mode_switch_confirm,
    format_usage_footer,
)


class TestCalculateCost:
    """測試花費計算。"""

    def test_free_mode_cost(self):
        """免費模式：gemini-3-pro-preview $2/$12 per MTok。"""
        # 1000 in + 500 out: (1000*2 + 500*12) / 1M = 0.008
        assert calculate_cost("free", 1000, 500) == pytest.approx(0.008)

    def test_cheap_mode_cost(self):
        """便宜模式：$3/$15 per MTok。"""
        cost = calculate_cost("cheap", 1_000_000, 1_000_000)
        assert cost == pytest.approx(18.0)  # 3 + 15

    def test_rigorous_mode_cost(self):
        """嚴謹模式：$5/$25 per MTok。"""
        cost = calculate_cost("rigorous", 1_000_000, 1_000_000)
        assert cost == pytest.approx(30.0)  # 5 + 25

    def test_small_token_cost(self):
        """少量 token 的成本計算。"""
        # 404 in + 62 out with cheap: (404*3 + 62*15) / 1M = 0.002142
        cost = calculate_cost("cheap", 404, 62)
        assert cost == pytest.approx(0.002142)

    def test_unknown_mode_zero_cost(self):
        """未知模式花費應為 0。"""
        assert calculate_cost("unknown", 1000, 500) == 0.0


class TestFormatUsageFooter:
    """測試 format_usage_footer 各種情境。"""

    def test_normal_usage(self):
        """正常使用量應顯示百分比和 token 資訊。"""
        result = format_usage_footer(
            daily_used=10000,
            daily_cap=50000,
            in_tokens=100,
            out_tokens=50,
            mode="free",
        )
        assert "20%" in result
        assert "10.0k" in result
        assert "50.0k" in result
        assert "100 in" in result
        assert "50 out" in result
        assert "免費" in result
        assert "$0" in result

    def test_small_daily_used_shows_raw_number(self):
        """daily_used < 1000 時應顯示原始數字而非 k。"""
        result = format_usage_footer(
            daily_used=459,
            daily_cap=50000,
            in_tokens=404,
            out_tokens=55,
            mode="free",
        )
        # daily_used 顯示為 "459" 而非 "0.5k" 或 "0.0k"
        assert "459 /" in result

    def test_cheap_mode_shows_cost(self):
        """便宜模式應顯示非零花費。"""
        result = format_usage_footer(
            daily_used=1000,
            daily_cap=50000,
            in_tokens=404,
            out_tokens=62,
            mode="cheap",
        )
        assert "$0.0021" in result

    def test_rigorous_mode_shows_cost(self):
        """嚴謹模式應顯示花費。"""
        result = format_usage_footer(
            daily_used=1000,
            daily_cap=50000,
            in_tokens=1000,
            out_tokens=500,
            mode="rigorous",
        )
        # (1000*5 + 500*25) / 1M = 0.0175
        assert "$0.0175" in result

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
        assert "便宜" in result

    def test_cap_exceeded_warning(self):
        """額度用盡應顯示警告。"""
        result = format_usage_footer(
            daily_used=50000,
            daily_cap=50000,
            in_tokens=200,
            out_tokens=100,
            mode="free",
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
            mode="free",
        )
        assert "0%" in result

    def test_all_modes_have_labels(self):
        """三種模式都應有對應的中文標籤。"""
        for mode in ("free", "cheap", "rigorous"):
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
            ("free", "免費"),
            ("cheap", "便宜"),
            ("rigorous", "嚴謹"),
        ],
    )
    def test_confirm_message(self, mode: str, expected_label: str):
        """確認訊息應包含對應的模式標籤。"""
        result = format_mode_switch_confirm(mode)
        assert expected_label in result
        assert "已切換" in result
