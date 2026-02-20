"""format_cost_summary() provider 分組顯示測試。"""

from dataclasses import dataclass

import pytest

from src.templates.messages import format_cost_summary


@dataclass
class FakeUsageSummary:
    """測試用 UsageSummary。"""

    provider: str
    model: str
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    call_count: int


class TestFormatCostSummary:
    """format_cost_summary provider 分組顯示。"""

    def test_empty_all_time_returns_no_data(self) -> None:
        """累計為空 → 回傳無紀錄訊息。"""
        result = format_cost_summary([], [], 0.0, 0.0)
        assert "尚無" in result

    def test_single_provider_month_and_alltime(self) -> None:
        """單一 provider（Anthropic）同時出現在本月與累計。"""
        summary = FakeUsageSummary(
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            total_input_tokens=1000,
            total_output_tokens=500,
            total_cost_usd=0.0105,
            call_count=3,
        )
        result = format_cost_summary(
            all_time_summary=[summary],
            month_summary=[summary],
            all_time_total=0.0105,
            month_total=0.0105,
        )

        assert "Anthropic" in result
        assert "claude-sonnet-4-5-20250929" in result
        assert "3 次" in result
        assert "0.0105" in result

    def test_multiple_providers_grouped(self) -> None:
        """多 provider 應各自分組顯示。"""
        anthropic_summary = FakeUsageSummary(
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            total_input_tokens=2000,
            total_output_tokens=1000,
            total_cost_usd=0.021,
            call_count=5,
        )
        google_summary = FakeUsageSummary(
            provider="google",
            model="gemini-3-pro-preview",
            total_input_tokens=3000,
            total_output_tokens=1500,
            total_cost_usd=0.024,
            call_count=8,
        )

        result = format_cost_summary(
            all_time_summary=[anthropic_summary, google_summary],
            month_summary=[anthropic_summary, google_summary],
            all_time_total=0.045,
            month_total=0.045,
        )

        assert "Anthropic" in result
        assert "Google" in result
        assert "5 次" in result
        assert "8 次" in result
        # 本月、累計各出現一次 provider header
        assert result.count("Anthropic") == 2
        assert result.count("Google") == 2

    def test_month_empty_alltime_has_data(self) -> None:
        """本月無紀錄但累計有資料。"""
        summary = FakeUsageSummary(
            provider="google",
            model="gemini-3-pro-preview",
            total_input_tokens=5000,
            total_output_tokens=2000,
            total_cost_usd=0.034,
            call_count=12,
        )
        result = format_cost_summary(
            all_time_summary=[summary],
            month_summary=[],
            all_time_total=0.034,
            month_total=0.0,
        )

        assert "無紀錄" in result
        assert "Google" in result
        assert "12 次" in result

    def test_provider_display_names(self) -> None:
        """provider 名稱應顯示為友善名稱（Anthropic / Google）。"""
        summary = FakeUsageSummary(
            provider="anthropic",
            model="claude-opus-4-6",
            total_input_tokens=100,
            total_output_tokens=50,
            total_cost_usd=0.002,
            call_count=1,
        )
        result = format_cost_summary(
            all_time_summary=[summary],
            month_summary=[summary],
            all_time_total=0.002,
            month_total=0.002,
        )

        # 不應顯示小寫的原始 provider 名
        assert "🔹 Anthropic" in result
