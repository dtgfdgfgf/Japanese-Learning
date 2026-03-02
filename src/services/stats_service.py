"""統計服務 — 查詢使用者學習進度。"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.item_repo import ItemRepository
from src.repositories.practice_log_repo import PracticeLogRepository
from src.schemas.command import CommandResult
from src.templates.messages import format_stats_summary

logger = logging.getLogger(__name__)


class StatsService:
    """學習進度統計服務。"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.item_repo = ItemRepository(session)
        self.practice_log_repo = PracticeLogRepository(session)

    async def get_stats_summary(self, user_id: str) -> CommandResult:
        """取得使用者學習進度摘要。

        Args:
            user_id: Hashed LINE user ID

        Returns:
            CommandResult 包含格式化的統計摘要
        """
        # 素材數量
        total_vocab = await self.item_repo.count_by_user(user_id, item_type="vocab")
        total_grammar = await self.item_repo.count_by_user(user_id, item_type="grammar")

        # 練習總數與正確數
        total_practice = await self.practice_log_repo.count_by_user(user_id)
        total_correct = await self.practice_log_repo.count_by_user(user_id, correct_only=True)

        # 近 7 日
        since_7d = datetime.now(timezone.utc) - timedelta(days=7)
        recent_practice = await self.practice_log_repo.count_by_user_since(user_id, since=since_7d)
        recent_correct = await self.practice_log_repo.count_by_user_since(
            user_id, since=since_7d, correct_only=True
        )

        # 計算正確率
        correct_rate = int(total_correct / total_practice * 100) if total_practice > 0 else 0
        recent_rate = int(recent_correct / recent_practice * 100) if recent_practice > 0 else 0

        message = format_stats_summary(
            total_vocab=total_vocab,
            total_grammar=total_grammar,
            total_practice=total_practice,
            correct_rate=correct_rate,
            recent_practice=recent_practice,
            recent_rate=recent_rate,
        )

        return CommandResult.ok(message=message)
