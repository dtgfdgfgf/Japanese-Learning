"""CostService 模式聚合測試。"""

import pytest

from src.repositories.api_usage_log_repo import UsageSummary
from src.services.cost_service import _aggregate_mode_summary


def _to_mode_map(summary_list: list) -> dict[str, object]:
    return {s.mode: s for s in summary_list}


def test_aggregate_mode_summary_maps_current_modes() -> None:
    """應將 provider/model 摘要聚合到免費/便宜/嚴謹模式。"""
    source = [
        UsageSummary(
            provider="google",
            model="gemini-2.5-flash-lite",
            total_input_tokens=1000,
            total_output_tokens=500,
            total_cost_usd=0.0011,
            call_count=3,
        ),
        UsageSummary(
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            total_input_tokens=2000,
            total_output_tokens=1000,
            total_cost_usd=0.0060,
            call_count=2,
        ),
        UsageSummary(
            provider="anthropic",
            model="claude-opus-4-6",
            total_input_tokens=800,
            total_output_tokens=400,
            total_cost_usd=0.0040,
            call_count=1,
        ),
    ]

    result = _aggregate_mode_summary(source)
    mode_map = _to_mode_map(result)

    assert mode_map["free"].call_count == 3
    assert mode_map["free"].total_cost_usd == pytest.approx(0.0011)
    assert mode_map["cheap"].call_count == 2
    assert mode_map["cheap"].total_cost_usd == pytest.approx(0.0060)
    assert mode_map["rigorous"].call_count == 1
    assert mode_map["rigorous"].total_cost_usd == pytest.approx(0.0040)


def test_aggregate_mode_summary_uses_anthropic_name_fallback() -> None:
    """Anthropic 非精準 model 名稱，仍可透過名稱判斷模式。"""
    source = [
        UsageSummary(
            provider="anthropic",
            model="claude-sonnet-4-7",
            total_input_tokens=500,
            total_output_tokens=200,
            total_cost_usd=0.0020,
            call_count=1,
        ),
        UsageSummary(
            provider="anthropic",
            model="claude-opus-4-7",
            total_input_tokens=400,
            total_output_tokens=100,
            total_cost_usd=0.0030,
            call_count=1,
        ),
    ]

    result = _aggregate_mode_summary(source)
    mode_map = _to_mode_map(result)

    assert mode_map["cheap"].call_count == 1
    assert mode_map["cheap"].total_cost_usd == pytest.approx(0.0020)
    assert mode_map["rigorous"].call_count == 1
    assert mode_map["rigorous"].total_cost_usd == pytest.approx(0.0030)
