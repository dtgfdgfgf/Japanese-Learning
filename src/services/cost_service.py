"""Cost service - API 用量統計查詢。

提供使用者查詢 API 用量與費用的功能。
"""

from dataclasses import dataclass
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.lib.llm_client import MODE_MODEL_MAP
from src.lib.security import hash_user_id
from src.repositories.api_usage_log_repo import ApiUsageLogRepository, UsageSummary
from src.schemas.command import CommandResult
from src.templates.messages import format_cost_summary

logger = logging.getLogger(__name__)

MODE_ORDER = ("free", "cheap", "rigorous")
MODE_BY_PROVIDER_MODEL: dict[tuple[str, str], str] = {
    (mapping["provider"], mapping["model"]): mode
    for mode, mapping in MODE_MODEL_MAP.items()
}
PROVIDER_UNIQUE_MODE: dict[str, str] = {}
for mode_name, mapping in MODE_MODEL_MAP.items():
    provider = mapping["provider"]
    if provider not in PROVIDER_UNIQUE_MODE:
        PROVIDER_UNIQUE_MODE[provider] = mode_name
    elif PROVIDER_UNIQUE_MODE[provider] != mode_name:
        PROVIDER_UNIQUE_MODE.pop(provider, None)


@dataclass
class ModeUsageSummary:
    """模式用量摘要資料結構。"""

    mode: str
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    call_count: int


def _resolve_mode(provider: str, model: str) -> str | None:
    """將 provider/model 解析為模式。"""
    mode = MODE_BY_PROVIDER_MODEL.get((provider, model))
    if mode:
        return mode

    unique_mode = PROVIDER_UNIQUE_MODE.get(provider)
    if unique_mode:
        return unique_mode

    if provider == "anthropic":
        model_name = model.lower()
        if "opus" in model_name:
            return "rigorous"
        if "sonnet" in model_name:
            return "cheap"

    return None


def _aggregate_mode_summary(summary_list: list[UsageSummary]) -> list[ModeUsageSummary]:
    """將 provider/model 摘要聚合為模式摘要。"""
    grouped: dict[str, ModeUsageSummary] = {
        mode: ModeUsageSummary(
            mode=mode,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cost_usd=0.0,
            call_count=0,
        )
        for mode in MODE_ORDER
    }

    for summary in summary_list:
        mode = _resolve_mode(summary.provider, summary.model)
        if not mode or mode not in grouped:
            continue

        bucket = grouped[mode]
        bucket.total_input_tokens += summary.total_input_tokens
        bucket.total_output_tokens += summary.total_output_tokens
        bucket.total_cost_usd += summary.total_cost_usd
        bucket.call_count += summary.call_count

    return [grouped[mode] for mode in MODE_ORDER]


class CostService:
    """API 用量統計服務。

    提供用量查詢與格式化功能。
    """

    def __init__(self, session: AsyncSession):
        """初始化服務。

        Args:
            session: 資料庫 session
        """
        self.session = session
        self.usage_repo = ApiUsageLogRepository(session)

    async def get_usage_summary(
        self,
        line_user_id: str,
    ) -> CommandResult:
        """取得使用者的 API 用量摘要。

        Args:
            line_user_id: 原始 LINE user ID (會被 hash)

        Returns:
            CommandResult 包含格式化的用量摘要
        """
        user_id = hash_user_id(line_user_id)

        # 取得本月起始時間
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # 查詢用量摘要
        all_time_summary = await self.usage_repo.get_summary_by_user(user_id)
        month_summary = await self.usage_repo.get_summary_by_user(user_id, since=month_start)

        # 計算總費用
        all_time_total = sum(s.total_cost_usd for s in all_time_summary)
        month_total = sum(s.total_cost_usd for s in month_summary)
        all_time_mode_summary = _aggregate_mode_summary(all_time_summary)
        month_mode_summary = _aggregate_mode_summary(month_summary)

        # 格式化回應
        message = format_cost_summary(
            all_time_summary=all_time_summary,
            month_summary=month_summary,
            all_time_total=all_time_total,
            month_total=month_total,
            all_time_mode_summary=all_time_mode_summary,
            month_mode_summary=month_mode_summary,
        )

        return CommandResult.ok(
            message=message,
            all_time_total=all_time_total,
            month_total=month_total,
        )
