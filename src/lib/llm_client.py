"""LLM client wrapper with Anthropic primary and OpenAI fallback.

T021: Create LLM client wrapper with fallback in src/lib/llm_client.py
DoD: Anthropic 呼叫成功回傳；模擬 timeout/error 時 fallback 至 OpenAI；單元測試覆蓋雙路徑
"""

import asyncio
import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import anthropic
import google.generativeai as genai
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


@dataclass
class UsageContext:
    """請求級別的 token 累計器（透過 contextvars 傳遞）。"""

    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, inp: int, out: int) -> None:
        self.input_tokens += inp
        self.output_tokens += out

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# 請求級別 context var，由 webhook handler 建立與讀取
usage_context_var: ContextVar[UsageContext | None] = ContextVar(
    "usage_context", default=None
)


# 模式 → provider / model 映射
MODE_MODEL_MAP: dict[str, dict[str, str]] = {
    "free": {"provider": "google", "model": "gemini-3-pro-preview"},
    "cheap": {"provider": "anthropic", "model": "claude-sonnet-4-5-20250929"},
    "rigorous": {"provider": "anthropic", "model": "claude-opus-4-6"},
}


def _accumulate_usage(inp: int, out: int) -> None:
    """將 token 使用量累加到當前請求的 UsageContext。"""
    ctx = usage_context_var.get()
    if ctx is not None:
        ctx.add(inp, out)


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
    ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
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

        # Gemini client 初始化（key 為空時跳過）
        if settings.gemini_api_key:
            genai.configure(api_key=settings.gemini_api_key)
            self._gemini_configured = True
        else:
            self._gemini_configured = False

    # Anthropic API 必須傳 max_tokens，設為模型上限以不限制輸出
    ANTHROPIC_MAX_TOKENS = 8192

    async def _call_anthropic(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float,
        json_mode: bool = False,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Call Anthropic API with timeout.

        Args:
            json_mode: Anthropic 無原生 json_mode，但傳入此參數以保持介面一致。
                       JSON 輸出由 system prompt 指示控制。
            model: 指定 model，預設使用 ANTHROPIC_MODEL。

        Returns:
            Dict with content, input_tokens, output_tokens
        """
        use_model = model or self.ANTHROPIC_MODEL
        async with asyncio.timeout(self.timeout):
            response = await self.anthropic_client.messages.create(
                model=use_model,
                max_tokens=self.ANTHROPIC_MAX_TOKENS,
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
        temperature: float,
        json_mode: bool = False,
    ) -> dict[str, Any]:
        """Call OpenAI API.

        Returns:
            Dict with content, input_tokens, output_tokens
        """
        kwargs: dict[str, Any] = {
            "model": self.OPENAI_MODEL,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }

        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        async with asyncio.timeout(self.timeout):
            response = await self.openai_client.chat.completions.create(**kwargs)

        content = response.choices[0].message.content or ""

        return {
            "content": content,
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": response.usage.completion_tokens if response.usage else 0,
        }

    async def _call_google(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float,
        model: str = "gemini-3-pro-preview",
        json_mode: bool = False,
    ) -> dict[str, Any]:
        """Call Google Gemini API (同步包裝為 async)。

        Args:
            json_mode: 為 True 時設定 response_mime_type="application/json"。

        Returns:
            Dict with content, input_tokens, output_tokens
        """
        if not self._gemini_configured:
            raise RuntimeError("Gemini API key not configured")
        def _sync_call() -> dict[str, Any]:
            gen_config_kwargs: dict[str, Any] = {
                "temperature": temperature,
            }
            if json_mode:
                gen_config_kwargs["response_mime_type"] = "application/json"
            client = genai.GenerativeModel(
                model_name=model,
                system_instruction=system_prompt,
                generation_config=genai.GenerationConfig(**gen_config_kwargs),
            )
            response = client.generate_content(user_message)
            # deprecated SDK 的 thinking model 可能在無可見輸出時
            # 對 response.text 拋出 ValueError
            try:
                content = response.text or ""
            except ValueError as e:
                logger.warning(f"Gemini response.text raised ValueError: {e}")
                raise
            # token 使用量
            usage = response.usage_metadata
            return {
                "content": content,
                "input_tokens": usage.prompt_token_count if usage else 0,
                "output_tokens": usage.candidates_token_count if usage else 0,
            }

        async with asyncio.timeout(self.timeout):
            return await asyncio.to_thread(_sync_call)

    async def complete_with_mode(
        self,
        mode: str,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> LLMResponse:
        """根據模式選擇 provider/model 完成 LLM 呼叫。

        無 fallback 機制，主 provider 失敗直接拋出例外。

        Args:
            mode: free / cheap / rigorous
            system_prompt: System 指令
            user_message: 使用者輸入
            temperature: 取樣溫度
            json_mode: 是否要求 JSON 輸出

        Returns:
            LLMResponse
        """
        mapping = MODE_MODEL_MAP.get(mode, MODE_MODEL_MAP["free"])
        provider = mapping["provider"]
        model = mapping["model"]

        start_time = time.time()

        response = await self._call_provider(
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=temperature,
            json_mode=json_mode,
        )
        latency_ms = int((time.time() - start_time) * 1000)
        resp = LLMResponse(
            content=response["content"],
            model=model,
            provider=provider,
            input_tokens=response["input_tokens"],
            output_tokens=response["output_tokens"],
            latency_ms=latency_ms,
            is_fallback=False,
        )
        _accumulate_usage(resp.input_tokens, resp.output_tokens)
        return resp

    async def _call_provider(
        self,
        provider: str,
        model: str,
        system_prompt: str,
        user_message: str,
        temperature: float,
        json_mode: bool = False,
    ) -> dict[str, Any]:
        """統一的 provider 呼叫分派。"""
        if provider == "anthropic":
            return await self._call_anthropic(
                system_prompt=system_prompt,
                user_message=user_message,
                temperature=temperature,
                json_mode=json_mode,
                model=model,
            )
        elif provider == "openai":
            return await self._call_openai(
                system_prompt=system_prompt,
                user_message=user_message,
                temperature=temperature,
                json_mode=json_mode,
            )
        elif provider == "google":
            return await self._call_google(
                system_prompt=system_prompt,
                user_message=user_message,
                temperature=temperature,
                model=model,
                json_mode=json_mode,
            )
        else:
            raise ValueError(f"Unknown provider: {provider}")

    async def complete_json_with_mode(
        self,
        mode: str,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
    ) -> tuple[dict[str, Any], LLMTrace]:
        """根據模式完成 JSON 回應，與 complete_json 相同解析邏輯。"""
        response = await self.complete_with_mode(
            mode=mode,
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=temperature,
            json_mode=True,
        )

        content = response.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        try:
            parsed = json.loads(content.strip())
        except json.JSONDecodeError:
            logger.error(
                "LLM JSON parse failed (provider=%s, model=%s): %s",
                response.provider, response.model, content[:200],
            )
            raise

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
