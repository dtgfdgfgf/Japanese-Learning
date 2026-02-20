"""
complete_with_mode 的單元測試。

測試 provider 分派、mode 映射（無 fallback）。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.lib.llm_client import MODE_MODEL_MAP, LLMClient

# ============================================================================
# MODE_MODEL_MAP 映射
# ============================================================================


class TestModeModelMap:
    """測試模式 → provider/model 映射。"""

    def test_free_maps_to_google(self):
        assert MODE_MODEL_MAP["free"]["provider"] == "google"
        assert MODE_MODEL_MAP["free"]["model"] == "gemini-3-pro-preview"

    def test_cheap_maps_to_anthropic(self):
        assert MODE_MODEL_MAP["cheap"]["provider"] == "anthropic"
        assert MODE_MODEL_MAP["cheap"]["model"] == "claude-sonnet-4-5-20250929"

    def test_rigorous_maps_to_anthropic(self):
        assert MODE_MODEL_MAP["rigorous"]["provider"] == "anthropic"
        assert MODE_MODEL_MAP["rigorous"]["model"] == "claude-opus-4-6"

    def test_all_modes_have_model(self):
        for mode, mapping in MODE_MODEL_MAP.items():
            assert "model" in mapping, f"{mode} 缺少 model"
            assert "provider" in mapping, f"{mode} 缺少 provider"

    def test_no_balanced_mode(self):
        """balanced 模式已移除。"""
        assert "balanced" not in MODE_MODEL_MAP


# ============================================================================
# complete_with_mode
# ============================================================================


class TestCompleteWithMode:
    """測試 complete_with_mode 方法。"""

    @pytest.mark.asyncio
    @patch.object(LLMClient, "__init__", lambda self, **kw: None)
    async def test_primary_provider_success(self):
        """主要 provider 成功時應直接回傳。"""
        client = LLMClient.__new__(LLMClient)
        client._call_provider = AsyncMock(return_value={
            "content": "test response",
            "input_tokens": 10,
            "output_tokens": 20,
        })

        result = await client.complete_with_mode(
            mode="free",
            system_prompt="test",
            user_message="hello",
        )

        assert result.provider == "google"
        assert result.content == "test response"
        client._call_provider.assert_awaited_once()

    @pytest.mark.asyncio
    @patch.object(LLMClient, "__init__", lambda self, **kw: None)
    async def test_primary_failure_raises_directly(self):
        """主要 provider 失敗時應直接拋出例外，不做 fallback。"""
        client = LLMClient.__new__(LLMClient)
        client._call_provider = AsyncMock(side_effect=RuntimeError("provider failed"))

        with pytest.raises(RuntimeError, match="provider failed"):
            await client.complete_with_mode(
                mode="cheap",
                system_prompt="test",
                user_message="hello",
            )

        # 只呼叫一次，無 fallback
        assert client._call_provider.await_count == 1

    @pytest.mark.asyncio
    @patch.object(LLMClient, "__init__", lambda self, **kw: None)
    async def test_unknown_mode_uses_free_default(self):
        """未知模式應使用 free 預設。"""
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

        # free 的 provider 是 google
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
            provider="anthropic", model="claude-sonnet-4-5-20250929",
            system_prompt="s", user_message="u", temperature=0.5,
        )
        assert result["content"] == "anthropic"

    @pytest.mark.asyncio
    @patch.object(LLMClient, "__init__", lambda self, **kw: None)
    async def test_dispatch_google(self):
        """provider='google' 應呼叫 _call_google。"""
        client = LLMClient.__new__(LLMClient)
        client._call_google = AsyncMock(return_value={
            "content": "google", "input_tokens": 1, "output_tokens": 1,
        })

        result = await client._call_provider(
            provider="google", model="gemini-3-pro-preview",
            system_prompt="s", user_message="u", temperature=0.5,
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
                system_prompt="s", user_message="u", temperature=0.5,
            )


class TestGoogleTimeout:
    """測試 Gemini 呼叫 timeout 行為。"""

    @pytest.mark.asyncio
    @patch.object(LLMClient, "__init__", lambda self, **kw: None)
    async def test_call_google_timeout(self):
        """_call_google 應套用 client timeout。"""
        client = LLMClient.__new__(LLMClient)
        client.timeout = 0.01
        client._gemini_configured = True

        async def _slow_generate_content(**kwargs):
            await asyncio.sleep(0.05)
            return MagicMock(text="ok", usage_metadata=None)

        mock_models = MagicMock()
        mock_models.generate_content = AsyncMock(side_effect=_slow_generate_content)
        client._gemini_client = MagicMock()
        client._gemini_client.aio.models = mock_models

        with pytest.raises(TimeoutError):
            await client._call_google(
                system_prompt="s",
                user_message="u",
                temperature=0.3,
            )
