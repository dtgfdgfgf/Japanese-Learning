"""ApiUsageLog repository - API 用量記錄的資料存取層。

提供 API 用量記錄的建立與查詢功能，包含費用計算邏輯。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.lib.llm_client import LLMTrace
from src.models.api_usage_log import ApiUsageLog
from src.repositories.base import BaseRepository


# LLM 定價表 (USD per 1M tokens)
# 參考：https://anthropic.com/pricing, https://ai.google.dev/pricing
PRICING: dict[str, dict[str, dict[str, float]]] = {
    "anthropic": {
        "claude-sonnet-4-5-20250929": {"input": 3.0, "output": 15.0},
        "claude-opus-4-6": {"input": 5.0, "output": 25.0},
        # 預設定價 (未知模型使用)
        "default": {"input": 3.0, "output": 15.0},
    },
    "google": {
        "gemini-3-pro-preview": {"input": 2.0, "output": 12.0},
        # 預設定價
        "default": {"input": 2.0, "output": 12.0},
    },
}


def calculate_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """計算 API 呼叫費用。

    Args:
        provider: LLM 提供者 (anthropic/google)
        model: 模型名稱
        input_tokens: 輸入 token 數量
        output_tokens: 輸出 token 數量

    Returns:
        費用 (美元)
    """
    provider_pricing = PRICING.get(provider, PRICING["anthropic"])
    model_pricing = provider_pricing.get(model, provider_pricing["default"])

    input_cost = (input_tokens / 1_000_000) * model_pricing["input"]
    output_cost = (output_tokens / 1_000_000) * model_pricing["output"]

    return input_cost + output_cost


@dataclass
class UsageSummary:
    """用量摘要資料結構。"""

    provider: str
    model: str
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    call_count: int


class ApiUsageLogRepository(BaseRepository[ApiUsageLog]):
    """API 用量記錄 Repository。

    提供用量記錄的建立與統計查詢功能。
    """

    model = ApiUsageLog
    pk_field = "log_id"

    async def create_log(
        self,
        user_id: str,
        trace: LLMTrace,
        operation: str,
    ) -> ApiUsageLog:
        """建立 API 用量記錄。

        自動計算費用並儲存。

        Args:
            user_id: Hashed LINE user ID
            trace: LLM 呼叫追蹤資訊
            operation: 操作類型 (extraction/practice/router)

        Returns:
            建立的用量記錄
        """
        cost_usd = calculate_cost(
            provider=trace.provider,
            model=trace.model,
            input_tokens=trace.input_tokens,
            output_tokens=trace.output_tokens,
        )

        return await self.create(
            user_id=user_id,
            provider=trace.provider,
            model=trace.model,
            operation=operation,
            input_tokens=trace.input_tokens,
            output_tokens=trace.output_tokens,
            cost_usd=cost_usd,
            latency_ms=trace.latency_ms,
        )

    async def get_summary_by_user(
        self,
        user_id: str,
        since: datetime | None = None,
    ) -> list[UsageSummary]:
        """取得使用者的用量摘要（按 provider + model 分組）。

        Args:
            user_id: Hashed LINE user ID
            since: 起始時間 (None 表示不限)

        Returns:
            各模型的用量摘要列表
        """
        stmt = (
            select(
                ApiUsageLog.provider,
                ApiUsageLog.model,
                func.sum(ApiUsageLog.input_tokens).label("total_input_tokens"),
                func.sum(ApiUsageLog.output_tokens).label("total_output_tokens"),
                func.sum(ApiUsageLog.cost_usd).label("total_cost_usd"),
                func.count(ApiUsageLog.log_id).label("call_count"),
            )
            .where(ApiUsageLog.user_id == user_id)
            .group_by(ApiUsageLog.provider, ApiUsageLog.model)
            .order_by(func.sum(ApiUsageLog.cost_usd).desc())
        )

        if since:
            stmt = stmt.where(ApiUsageLog.created_at >= since)

        result = await self.session.execute(stmt)
        rows = result.all()

        return [
            UsageSummary(
                provider=row.provider,
                model=row.model,
                total_input_tokens=row.total_input_tokens or 0,
                total_output_tokens=row.total_output_tokens or 0,
                total_cost_usd=row.total_cost_usd or 0.0,
                call_count=row.call_count or 0,
            )
            for row in rows
        ]

    async def get_total_cost_by_user(
        self,
        user_id: str,
        since: datetime | None = None,
    ) -> float:
        """取得使用者的總費用。

        Args:
            user_id: Hashed LINE user ID
            since: 起始時間 (None 表示不限)

        Returns:
            總費用 (美元)
        """
        stmt = select(func.sum(ApiUsageLog.cost_usd)).where(
            ApiUsageLog.user_id == user_id
        )

        if since:
            stmt = stmt.where(ApiUsageLog.created_at >= since)

        result = await self.session.execute(stmt)
        total = result.scalar()

        return total or 0.0
