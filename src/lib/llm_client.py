"""LLM client wrapper with mode-based provider selection.

支援 Anthropic Claude 與 Google Gemini，依據 mode (free/cheap/rigorous) 選擇 provider/model。
"""

import asyncio
import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import anthropic
from google import genai
from google.genai import types
from google.genai.errors import ServerError as GeminiServerError

from src.config import settings

logger = logging.getLogger(__name__)

# Gemini 瞬態錯誤重試設定
_GEMINI_MAX_RETRIES = 3
_GEMINI_RETRY_BASE_DELAY = 2  # 秒，指數退避基數


@dataclass
class LLMResponse:
    """Response from LLM API call."""

    content: str
    model: str
    provider: str  # "anthropic" or "google"
    input_tokens: int
    output_tokens: int
    latency_ms: int
    raw_response: dict[str, Any] | None = None

    def to_trace(self) -> "LLMTrace":
        """將 LLMResponse 轉為 LLMTrace（用於 api_usage_logs 記錄）。"""
        return LLMTrace(
            model=self.model,
            provider=self.provider,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            latency_ms=self.latency_ms,
        )


@dataclass
class LLMTrace:
    """Trace information for LLM call (for logging/storage)."""

    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
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
    """

    Features:
    - Mode-based provider selection (Anthropic Claude / Google Gemini)
    - Structured JSON output support
    - Trace logging for monitoring
    - Request-level token accumulation via UsageContext
    """

    # Model configurations
    ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"

    def __init__(
        self,
        anthropic_api_key: str | None = None,
        timeout_seconds: int | None = None,
    ):
        """Initialize LLM client.

        Args:
            anthropic_api_key: Anthropic API key (defaults to settings)
            timeout_seconds: LLM API timeout in seconds (defaults to settings)
        """
        self.anthropic_client = anthropic.AsyncAnthropic(
            api_key=anthropic_api_key or settings.anthropic_api_key
        )
        self.timeout = timeout_seconds or settings.llm_timeout_seconds

        # Gemini client 初始化（key 為空時跳過）
        if settings.gemini_api_key:
            self._gemini_client = genai.Client(api_key=settings.gemini_api_key)
            self._gemini_configured = True
        else:
            self._gemini_client = None
            self._gemini_configured = False

    # Anthropic API 必須傳 max_tokens，預設上限用於一般呼叫
    DEFAULT_MAX_TOKENS = 4096

    async def _call_anthropic(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float,
        json_mode: bool = False,
        model: str | None = None,
        timeout: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Call Anthropic API with timeout.

        Args:
            json_mode: Anthropic 無原生 json_mode，但傳入此參數以保持介面一致。
                       JSON 輸出由 system prompt 指示控制。
            model: 指定 model，預設使用 ANTHROPIC_MODEL。
            timeout: 覆蓋預設 timeout（秒）。
            max_tokens: 覆蓋預設 max_tokens。

        Returns:
            Dict with content, input_tokens, output_tokens
        """
        use_model = model or self.ANTHROPIC_MODEL
        async with asyncio.timeout(timeout if timeout is not None else self.timeout):
            response = await self.anthropic_client.messages.create(
                model=use_model,
                max_tokens=max_tokens or self.DEFAULT_MAX_TOKENS,
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

    async def _call_google(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float,
        model: str = "gemini-3-pro-preview",
        json_mode: bool = False,
        timeout: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Call Google Gemini API（原生 async），含瞬態錯誤指數退避重試。

        Args:
            json_mode: 為 True 時設定 response_mime_type="application/json"。
            timeout: 覆蓋預設 timeout（秒）。
            max_tokens: 覆蓋預設 max_output_tokens。

        Returns:
            Dict with content, input_tokens, output_tokens
        """
        if not self._gemini_configured or self._gemini_client is None:
            raise RuntimeError("Gemini API key not configured")

        config_kwargs: dict[str, Any] = {
            "system_instruction": system_prompt,
            "temperature": temperature,
            "max_output_tokens": max_tokens or self.DEFAULT_MAX_TOKENS,
        }
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"

        last_error: Exception | None = None
        for attempt in range(_GEMINI_MAX_RETRIES + 1):
            try:
                async with asyncio.timeout(timeout if timeout is not None else self.timeout):
                    response = await self._gemini_client.aio.models.generate_content(
                        model=model,
                        contents=user_message,
                        config=types.GenerateContentConfig(**config_kwargs),
                    )

                content = response.text or ""
                usage = response.usage_metadata
                return {
                    "content": content,
                    "input_tokens": usage.prompt_token_count if usage else 0,
                    "output_tokens": usage.candidates_token_count if usage else 0,
                }
            except (GeminiServerError, TimeoutError) as e:
                last_error = e
                if attempt < _GEMINI_MAX_RETRIES:
                    delay = _GEMINI_RETRY_BASE_DELAY * (2 ** attempt)
                    err_code = getattr(e, "code", "timeout")
                    logger.warning(
                        "Gemini %s 錯誤，第 %d/%d 次重試（%ds 後）: %s",
                        err_code, attempt + 1, _GEMINI_MAX_RETRIES, delay, e,
                    )
                    await asyncio.sleep(delay)

        # 重試用盡，拋出最後的錯誤
        raise last_error  # type: ignore[misc]

    async def complete_with_mode(
        self,
        mode: str,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.7,
        json_mode: bool = False,
        timeout: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """根據模式選擇 provider/model 完成 LLM 呼叫。

        無 fallback 機制，主 provider 失敗直接拋出例外。

        Args:
            mode: free / cheap / rigorous
            system_prompt: System 指令
            user_message: 使用者輸入
            temperature: 取樣溫度
            json_mode: 是否要求 JSON 輸出
            max_tokens: 最大輸出 token 數（預設 DEFAULT_MAX_TOKENS）

        Returns:
            LLMResponse
        """
        mapping = MODE_MODEL_MAP.get(mode, MODE_MODEL_MAP["free"])
        provider = mapping["provider"]
        model = mapping["model"]

        start_time = time.monotonic()

        response = await self._call_provider(
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=temperature,
            json_mode=json_mode,
            timeout=timeout,
            max_tokens=max_tokens,
        )
        latency_ms = int((time.monotonic() - start_time) * 1000)
        resp = LLMResponse(
            content=response["content"],
            model=model,
            provider=provider,
            input_tokens=response["input_tokens"],
            output_tokens=response["output_tokens"],
            latency_ms=latency_ms,
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
        timeout: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """統一的 provider 呼叫分派。"""
        if provider == "anthropic":
            return await self._call_anthropic(
                system_prompt=system_prompt,
                user_message=user_message,
                temperature=temperature,
                json_mode=json_mode,
                model=model,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        elif provider == "google":
            return await self._call_google(
                system_prompt=system_prompt,
                user_message=user_message,
                temperature=temperature,
                model=model,
                json_mode=json_mode,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        else:
            raise ValueError(f"Unknown provider: {provider}")

    async def complete_json_with_mode(
        self,
        mode: str,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        timeout: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], LLMTrace]:
        """根據模式完成 JSON 回應，與 complete_json 相同解析邏輯。"""
        response = await self.complete_with_mode(
            mode=mode,
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=temperature,
            json_mode=True,
            timeout=timeout,
            max_tokens=max_tokens,
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
        # 關閉 Gemini client，釋放底層 HTTP connection pool
        if _llm_client._gemini_client is not None:
            try:
                await _llm_client._gemini_client.aio.close()
            except Exception:
                pass  # Gemini SDK 關閉失敗不影響 shutdown
        _llm_client = None
