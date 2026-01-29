"""LLM prompt templates package."""
from src.prompts.extractor import (
    EXTRACTOR_SYSTEM_PROMPT,
    format_extractor_request,
    get_system_prompt,
)
from src.prompts.router import (
    INTENT_EXAMPLES,
    ROUTER_SYSTEM_PROMPT,
    format_router_request,
    get_system_prompt as get_router_system_prompt,
)

__all__ = [
    # Extractor
    "EXTRACTOR_SYSTEM_PROMPT",
    "format_extractor_request",
    "get_system_prompt",
    # Router
    "INTENT_EXAMPLES",
    "ROUTER_SYSTEM_PROMPT",
    "format_router_request",
    "get_router_system_prompt",
]