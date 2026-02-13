"""Text templates package.

提供統一的訊息模板管理，支援多語系架構。
"""

from src.templates.messages import (
    Locale,
    Messages,
    format_delete_clear_success,
    format_practice_answer_wrong,
    format_practice_insufficient,
    format_practice_result,
    format_save_success,
    format_search_no_result,
    format_search_result_header,
    format_search_result_more,
    get_message,
)
from src.templates.privacy import PRIVACY_SHORT, PRIVACY_TEXT

__all__ = [
    # 訊息類別
    "Locale",
    "Messages",
    "get_message",
    # 格式化輔助函數
    "format_delete_clear_success",
    "format_practice_answer_wrong",
    "format_practice_insufficient",
    "format_practice_result",
    "format_save_success",
    "format_search_no_result",
    "format_search_result_header",
    "format_search_result_more",
    # 隱私文字（向後相容）
    "PRIVACY_SHORT",
    "PRIVACY_TEXT",
]
