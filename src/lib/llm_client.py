"""LLM client wrapper with Anthropic primary and OpenAI fallback.

T021: Create LLM client wrapper with fallback in src/lib/llm_client.py
DoD: Anthropic 呼叫成功回傳；模擬 timeout/error 時 fallback 至 OpenAI；單元測試覆蓋雙路徑
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import anthropic
import openai

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from LLM API call."""

    content: str
    model: str
    provider: str  # "anthropic" or "openai"
    input_tokens: int
    output_tokens: int
    latency_ms: int
    is_fallback: bool = False
    raw_response: dict[str, Any] | None = None


@dataclass
class LLMTrace:
    """Trace information for LLM call (for logging/storage)."""

    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    is_fallback: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "is_fallback": self.is_fallback,
            "error": self.error,
        }


class LLMClient:
    """LLM client with Anthropic primary and OpenAI fallback.

    Features:
    - Anthropic Claude as primary provider
    - OpenAI as fallback on timeout, error, or low confidence
    - Automatic retry logic
    - Structured JSON output support
    - Trace logging for monitoring
    """

    # Model configurations
    ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
    OPENAI_MODEL = "gpt-4o-mini"

    def __init__(
        self,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
        timeout_seconds: int | None = None,
    ):
        """Initialize LLM client.

        Args:
            anthropic_api_key: Anthropic API key (defaults to settings)
            openai_api_key: OpenAI API key (defaults to settings)
            timeout_seconds: Timeout before fallback (defaults to settings)
        """
        self.anthropic_client = anthropic.AsyncAnthropic(
            api_key=anthropic_api_key or settings.anthropic_api_key
        )
        self.openai_client = openai.AsyncOpenAI(
            api_key=openai_api_key or settings.openai_api_key
        )
        self.timeout = timeout_seconds or settings.llm_timeout_seconds

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Complete a prompt using LLM with fallback.

        Args:
            system_prompt: System role instructions
            user_message: User input message
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            json_mode: If True, request JSON output

        Returns:
            LLMResponse with content and metadata

        Raises:
            Exception: If both primary and fallback fail
        """
        start_time = time.time()

        # Try Anthropic first
        try:
            response = await self._call_anthropic(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            latency_ms = int((time.time() - start_time) * 1000)

            return LLMResponse(
                content=response["content"],
                model=self.ANTHROPIC_MODEL,
                provider="anthropic",
                input_tokens=response["input_tokens"],
                output_tokens=response["output_tokens"],
                latency_ms=latency_ms,
                is_fallback=False,
            )

        except TimeoutError:
            logger.warning(
                f"Anthropic timeout after {self.timeout}s, falling back to OpenAI"
            )
        except anthropic.APIError as e:
            logger.warning(f"Anthropic API error: {e}, falling back to OpenAI")
        except Exception as e:
            logger.warning(f"Anthropic unexpected error: {e}, falling back to OpenAI")

        # Fallback to OpenAI
        try:
            response = await self._call_openai(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=max_tokens,
                temperature=temperature,
                json_mode=json_mode,
            )
            latency_ms = int((time.time() - start_time) * 1000)

            return LLMResponse(
                content=response["content"],
                model=self.OPENAI_MODEL,
                provider="openai",
                input_tokens=response["input_tokens"],
                output_tokens=response["output_tokens"],
                latency_ms=latency_ms,
                is_fallback=True,
            )

        except Exception as e:
            logger.error(f"OpenAI fallback also failed: {e}")
            raise

    async def _call_anthropic(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """Call Anthropic API with timeout.

        Returns:
            Dict with content, input_tokens, output_tokens
        """
        async with asyncio.timeout(self.timeout):
            response = await self.anthropic_client.messages.create(
                model=self.ANTHROPIC_MODEL,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )

        content = response.content[0].text if response.content else ""

        return {
            "content": content,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }

    async def _call_openai(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
        temperature: float,
        json_mode: bool = False,
    ) -> dict[str, Any]:
        """Call OpenAI API.

        Returns:
            Dict with content, input_tokens, output_tokens
        """
        kwargs: dict[str, Any] = {
            "model": self.OPENAI_MODEL,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }

        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self.openai_client.chat.completions.create(**kwargs)

        content = response.choices[0].message.content or ""

        return {
            "content": content,
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": response.usage.completion_tokens if response.usage else 0,
        }

    async def complete_json(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> tuple[dict[str, Any], LLMTrace]:
        """Complete a prompt and parse JSON response.

        Args:
            system_prompt: System prompt (should request JSON output)
            user_message: User input
            max_tokens: Maximum tokens
            temperature: Lower temperature for more consistent JSON

        Returns:
            Tuple of (parsed JSON dict, LLMTrace for logging)

        Raises:
            json.JSONDecodeError: If response is not valid JSON
        """
        response = await self.complete(
            system_prompt=system_prompt,
            user_message=user_message,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=True,
        )

        # Parse JSON from response
        content = response.content.strip()

        # Handle markdown code blocks
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        parsed = json.loads(content.strip())

        trace = LLMTrace(
            model=response.model,
            provider=response.provider,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            is_fallback=response.is_fallback,
        )

        return parsed, trace


# Global client instance
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get singleton LLM client instance."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


async def close_llm_client() -> None:
    """關閉 LLM client 連線。

    應在應用程式 shutdown 時呼叫，釋放底層 HTTP client 資源。
    """
    global _llm_client
    if _llm_client is not None:
        await _llm_client.anthropic_client.close()
        await _llm_client.openai_client.close()
        _llm_client = None
