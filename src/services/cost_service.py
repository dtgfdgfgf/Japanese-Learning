"""Cost service - API 用量統計查詢。

提供使用者查詢 API 用量與費用的功能。
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.api_usage_log_repo import ApiUsageLogRepository
from src.schemas.command import CommandResult
from src.templates.messages import format_cost_summary

logger = logging.getLogger(__name__)


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
        user_id: str,
    ) -> CommandResult:
        """取得使用者的 API 用量摘要。

        Args:
            user_id: Hashed LINE user ID

        Returns:
            CommandResult 包含格式化的用量摘要
        """

        # 取得本月起始時間
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # 查詢用量摘要
        all_time_summary = await self.usage_repo.get_summary_by_user(user_id)
        month_summary = await self.usage_repo.get_summary_by_user(user_id, since=month_start)

        # 計算總費用
        all_time_total = sum(s.total_cost_usd for s in all_time_summary)
        month_total = sum(s.total_cost_usd for s in month_summary)

        # 格式化回應
        message = format_cost_summary(
            all_time_summary=all_time_summary,
            month_summary=month_summary,
            all_time_total=all_time_total,
            month_total=month_total,
        )

        return CommandResult.ok(
            message=message,
            all_time_total=all_time_total,
            month_total=month_total,
        )
