"""
complete_with_mode 的單元測試。

測試 provider 分派、fallback 邏輯、mode 映射。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.lib.llm_client import LLMClient, LLMResponse, MODE_MODEL_MAP, _MODE_FALLBACK


# ============================================================================
# MODE_MODEL_MAP 映射
# ============================================================================


class TestModeModelMap:
    """測試模式 → provider/model 映射。"""

    def test_cheap_maps_to_openai(self):
        assert MODE_MODEL_MAP["cheap"]["provider"] == "openai"

    def test_balanced_maps_to_google(self):
        assert MODE_MODEL_MAP["balanced"]["provider"] == "google"

    def test_rigorous_maps_to_anthropic(self):
        assert MODE_MODEL_MAP["rigorous"]["provider"] == "anthropic"

    def test_all_modes_have_model(self):
        for mode, mapping in MODE_MODEL_MAP.items():
            assert "model" in mapping, f"{mode} 缺少 model"
            assert "provider" in mapping, f"{mode} 缺少 provider"


class TestModeFallback:
    """測試 fallback 順序設定。"""

    def test_cheap_fallback_order(self):
        assert _MODE_FALLBACK["cheap"] == ["google", "anthropic"]

    def test_balanced_fallback_order(self):
        assert _MODE_FALLBACK["balanced"] == ["openai", "anthropic"]

    def test_rigorous_fallback_order(self):
        assert _MODE_FALLBACK["rigorous"] == ["openai", "google"]


# ============================================================================
# complete_with_mode
# ============================================================================


class TestCompleteWithMode:
    """測試 complete_with_mode 方法。"""

    @pytest.mark.asyncio
    @patch.object(LLMClient, "__init__", lambda self, **kw: None)
    async def test_primary_provider_success(self):
        """主要 provider 成功時應直接回傳，不觸發 fallback。"""
        client = LLMClient.__new__(LLMClient)
        client._call_provider = AsyncMock(return_value={
            "content": "test response",
            "input_tokens": 10,
            "output_tokens": 20,
        })

        result = await client.complete_with_mode(
            mode="cheap",
            system_prompt="test",
            user_message="hello",
        )

        assert result.provider == "openai"
        assert result.is_fallback is False
        assert result.content == "test response"
        client._call_provider.assert_awaited_once()

    @pytest.mark.asyncio
    @patch.object(LLMClient, "__init__", lambda self, **kw: None)
    async def test_fallback_on_primary_failure(self):
        """主要 provider 失敗時應嘗試 fallback。"""
        client = LLMClient.__new__(LLMClient)

        call_count = 0

        async def _mock_call_provider(
            provider: str, model: str, **kwargs
        ) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Primary failed")
            return {
                "content": "fallback response",
                "input_tokens": 5,
                "output_tokens": 10,
            }

        client._call_provider = AsyncMock(side_effect=_mock_call_provider)

        result = await client.complete_with_mode(
            mode="cheap",
            system_prompt="test",
            user_message="hello",
        )

        assert result.is_fallback is True
        assert result.content == "fallback response"

    @pytest.mark.asyncio
    @patch.object(LLMClient, "__init__", lambda self, **kw: None)
    async def test_all_providers_fail_raises(self):
        """所有 provider 都失敗時應拋出例外。"""
        client = LLMClient.__new__(LLMClient)
        client._call_provider = AsyncMock(side_effect=RuntimeError("all fail"))

        with pytest.raises(RuntimeError, match="all fail"):
            await client.complete_with_mode(
                mode="cheap",
                system_prompt="test",
                user_message="hello",
            )

    @pytest.mark.asyncio
    @patch.object(LLMClient, "__init__", lambda self, **kw: None)
    async def test_unknown_mode_uses_balanced_default(self):
        """未知模式應使用 balanced 預設。"""
        client = LLMClient.__new__(LLMClient)
        client._call_provider = AsyncMock(return_value={
            "content": "ok",
            "input_tokens": 1,
            "output_tokens": 1,
        })

        result = await client.complete_with_mode(
            mode="nonexistent",
            system_prompt="test",
            user_message="hello",
        )

        # balanced 的 provider 是 google
        assert result.provider == "google"


# ============================================================================
# _call_provider 分派
# ============================================================================


class TestCallProviderDispatch:
    """測試 _call_provider 正確分派到各 provider。"""

    @pytest.mark.asyncio
    @patch.object(LLMClient, "__init__", lambda self, **kw: None)
    async def test_dispatch_anthropic(self):
        """provider='anthropic' 應呼叫 _call_anthropic。"""
        client = LLMClient.__new__(LLMClient)
        client._call_anthropic = AsyncMock(return_value={
            "content": "anthropic", "input_tokens": 1, "output_tokens": 1,
        })

        result = await client._call_provider(
            provider="anthropic", model="claude-sonnet-4-20250514",
            system_prompt="s", user_message="u", max_tokens=100, temperature=0.5,
        )
        assert result["content"] == "anthropic"

    @pytest.mark.asyncio
    @patch.object(LLMClient, "__init__", lambda self, **kw: None)
    async def test_dispatch_openai(self):
        """provider='openai' 應呼叫 _call_openai。"""
        client = LLMClient.__new__(LLMClient)
        client._call_openai = AsyncMock(return_value={
            "content": "openai", "input_tokens": 1, "output_tokens": 1,
        })

        result = await client._call_provider(
            provider="openai", model="gpt-4o-mini",
            system_prompt="s", user_message="u", max_tokens=100, temperature=0.5,
        )
        assert result["content"] == "openai"

    @pytest.mark.asyncio
    @patch.object(LLMClient, "__init__", lambda self, **kw: None)
    async def test_dispatch_google(self):
        """provider='google' 應呼叫 _call_google。"""
        client = LLMClient.__new__(LLMClient)
        client._call_google = AsyncMock(return_value={
            "content": "google", "input_tokens": 1, "output_tokens": 1,
        })

        result = await client._call_provider(
            provider="google", model="gemini-2.5-flash",
            system_prompt="s", user_message="u", max_tokens=100, temperature=0.5,
        )
        assert result["content"] == "google"

    @pytest.mark.asyncio
    @patch.object(LLMClient, "__init__", lambda self, **kw: None)
    async def test_dispatch_unknown_raises(self):
        """未知 provider 應拋出 ValueError。"""
        client = LLMClient.__new__(LLMClient)

        with pytest.raises(ValueError, match="Unknown provider"):
            await client._call_provider(
                provider="azure", model="test",
                system_prompt="s", user_message="u", max_tokens=100, temperature=0.5,
            )
