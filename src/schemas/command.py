"""Pydantic schemas for command parsing.

T025: Create Pydantic schemas for commands in src/schemas/command.py
DoD: CommandType enum 包含所有命令；ParsedCommand schema 定義完整
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CommandType(str, Enum):
    """Supported command types."""

    SAVE = "save"  # 入庫
    CONFIRM_SAVE = "confirm_save"  # 確認入庫（輸入「1」）
    ANALYZE = "analyze"  # 分析
    PRACTICE = "practice"  # 練習
    SEARCH = "search"  # 查詢
    DELETE_LAST = "delete_last"  # 刪除最後一筆
    DELETE_ALL = "delete_all"  # 清空資料
    DELETE_CONFIRM = "delete_confirm"  # 確定清空資料
    PRIVACY = "privacy"  # 隱私
    HELP = "help"  # 說明
    COST = "cost"  # 用量
    STATS = "stats"  # 統計
    MODE_SWITCH = "mode_switch"  # 模式切換
    SET_LANG = "set_lang"  # 語言切換
    EXIT_PRACTICE = "exit_practice"  # 結束練習
    UNKNOWN = "unknown"  # 未知指令


class ParsedCommand(BaseModel):
    """Parsed command from user message."""

    command_type: CommandType = Field(description="Identified command type")
    raw_text: str = Field(description="Original message text")
    keyword: str | None = Field(default=None, description="Extracted keyword (for search)")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Parse confidence")
    entities: dict[str, Any] = Field(default_factory=dict, description="Extracted entities")

    @property
    def is_hard_command(self) -> bool:
        """Check if this is a deterministic hard-coded command."""
        return self.command_type != CommandType.UNKNOWN

    @property
    def requires_previous_message(self) -> bool:
        """Check if command requires a previous message for context."""
        return self.command_type == CommandType.SAVE


class CommandResult(BaseModel):
    """Result of command execution."""

    success: bool = Field(description="Whether command executed successfully")
    message: str = Field(description="Response message to user")
    data: dict[str, Any] = Field(default_factory=dict, description="Additional data")
    error: str | None = Field(default=None, description="Error message if failed")

    @classmethod
    def ok(cls, message: str, **data: Any) -> "CommandResult":
        """Create successful result."""
        return cls(success=True, message=message, data=data)

    @classmethod
    def fail(cls, message: str, error: str | None = None) -> "CommandResult":
        """Create error result."""
        return cls(success=False, message=message, error=error)
