"""UserState model - 持久化使用者暫存狀態。

取代 webhook.py 的 _user_last_message dict 和 delete_service.py 的 _confirmation_pending dict。
"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class UserStateModel(Base):
    """使用者暫存狀態（last message、刪除確認等）。

    Attributes:
        user_id: Hashed LINE user ID（PK）
        last_message: 最後一則非指令訊息（供「入庫」使用）
        last_message_at: 最後訊息時間
        delete_confirm_at: 清空資料確認請求時間
    """

    __tablename__ = "user_states"

    user_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="Hashed LINE user ID",
    )
    last_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="最後一則非指令訊息",
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最後訊息時間",
    )
    delete_confirm_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="清空資料確認請求時間",
    )

    def __repr__(self) -> str:
        return f"<UserStateModel(user_id={self.user_id[:8]}...)>"
