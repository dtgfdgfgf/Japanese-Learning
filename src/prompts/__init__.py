"""LLM prompt templates package."""
from src.prompts.extractor import (
    EXTRACTOR_SYSTEM_PROMPT,
    format_extractor_request,
    get_system_prompt,
)

__all__ = [
    "EXTRACTOR_SYSTEM_PROMPT",
    "format_extractor_request",
    "get_system_prompt",
]