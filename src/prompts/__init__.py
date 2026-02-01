"""LLM prompt templates package."""
from src.prompts.extractor import (
    format_extractor_request,
    get_system_prompt,
)
from src.prompts.router import (
    INTENT_EXAMPLES,
    format_router_request,
    get_system_prompt as get_router_system_prompt,
)

__all__ = [
    # Extractor
    "format_extractor_request",
    "get_system_prompt",
    # Router
    "INTENT_EXAMPLES",
    "format_router_request",
    "get_router_system_prompt",
]
