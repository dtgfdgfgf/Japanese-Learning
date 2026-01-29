"""
Pytest configuration and fixtures.

T014: Test configuration and fixtures
DoD: pytest discover 成功
"""

import json
import os
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from linebot.v3.webhooks import MessageEvent, TextMessageContent, UserSource, DeliveryContext
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker


# Set test environment before importing app modules
os.environ["LINE_CHANNEL_SECRET"] = "test_secret_for_testing_only"
os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = "test_access_token"
os.environ["ANTHROPIC_API_KEY"] = "test_anthropic_key"
os.environ["OPENAI_API_KEY"] = "sk-test_openai_key_for_testing"
os.environ["USER_ID_SALT"] = "test_salt_for_user_id_hashing_must_be_at_least_32_chars_long"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@localhost:5432/test_db"


# Now import app modules after env vars are set
from src.database import Base


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def japanese_samples() -> dict:
    """Load Japanese test samples."""
    with open(FIXTURES_DIR / "japanese_samples.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def vocab_samples(japanese_samples: dict) -> list:
    """Get vocabulary test samples."""
    return japanese_samples["vocab_samples"]


@pytest.fixture
def grammar_samples(japanese_samples: dict) -> list:
    """Get grammar test samples."""
    return japanese_samples["grammar_samples"]


@pytest.fixture
def command_samples(japanese_samples: dict) -> list:
    """Get command test samples."""
    return japanese_samples["command_samples"]


@pytest.fixture
def edge_cases(japanese_samples: dict) -> list:
    """Get edge case test samples."""
    return japanese_samples["edge_cases"]


@pytest_asyncio.fixture
async def async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    建立測試用的資料庫 session。
    
    行為：
    - 預設 skip（SKIP_DB_TESTS=true 或未設定）
    - 設定 SKIP_DB_TESTS=false 且有 PostgreSQL 測試資料庫時啟用
    
    Note: SQLite 不支援 JSONB，因此需要真實的 PostgreSQL 測試資料庫。
    """
    skip_db = os.environ.get("SKIP_DB_TESTS", "true").lower()
    if skip_db == "true":
        pytest.skip("Skipping DB test: set SKIP_DB_TESTS=false to enable")
    
    # 使用環境變數中的測試資料庫 URL
    test_db_url = os.environ.get("TEST_DATABASE_URL", os.environ.get("DATABASE_URL"))
    if not test_db_url or "test" not in test_db_url:
        pytest.skip("Skipping DB test: TEST_DATABASE_URL not configured")
    
    engine = create_async_engine(test_db_url, echo=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        yield session
    
    # 清理測試資料（可選）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest.fixture
def mock_line_client() -> MagicMock:
    """Create a mock LINE client."""
    client = MagicMock()
    client.verify_signature = MagicMock(return_value=True)
    client.reply_message = AsyncMock()
    client.parse_events = MagicMock(return_value=[])
    return client


@pytest.fixture
def mock_line_client_factory():
    """Factory fixture that returns a mock LINE client.
    
    Use with patch('src.lib.line_client.get_line_client', return_value=mock)
    """
    def _create_mock():
        client = MagicMock()
        client.verify_signature = MagicMock(return_value=True)
        client.reply_message = AsyncMock()
        client.parse_events = MagicMock(return_value=[])
        return client
    return _create_mock


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """Create a mock LLM client."""
    client = MagicMock()
    client.complete = AsyncMock(return_value="test response")
    client.complete_json = AsyncMock(return_value={"items": []})
    return client


@pytest.fixture
def sample_line_webhook_body() -> bytes:
    """Sample LINE webhook request body."""
    return json.dumps({
        "destination": "Uxxxxx",
        "events": [
            {
                "type": "message",
                "message": {
                    "type": "text",
                    "id": "12345678901234",
                    "text": "入庫"
                },
                "timestamp": 1625665600000,
                "source": {
                    "type": "user",
                    "userId": "U0123456789abcdef0123456789abcdef"
                },
                "replyToken": "nHuyWiB7yP5Zw52FIkcQobQuGDXCTA",
                "mode": "active"
            }
        ]
    }).encode("utf-8")


@pytest.fixture
def sample_japanese_text() -> str:
    """Sample Japanese text for testing."""
    return "考える（かんがえる）：思考、考慮"


@pytest.fixture
def sample_user_id() -> str:
    """Sample user ID (hashed)."""
    return "hashed_user_id_for_testing"


def create_message_event(
    text: str,
    user_id: str = "Utest_user",
    reply_token: str = "test_reply_token",
    message_id: str = "12345678901234",
    timestamp: int = 1625665600000,
) -> MessageEvent:
    """建立用於測試的 LINE MessageEvent 物件。
    
    Args:
        text: 訊息文字
        user_id: LINE user ID
        reply_token: Reply token
        message_id: Message ID
        timestamp: Timestamp in milliseconds
        
    Returns:
        MessageEvent 物件
    """
    return MessageEvent(
        type="message",
        message=TextMessageContent(
            type="text",
            id=message_id,
            text=text,
            quoteToken="test_quote_token",  # LINE SDK 必要欄位
        ),
        source=UserSource(
            type="user",
            user_id=user_id,
        ),
        reply_token=reply_token,
        timestamp=timestamp,
        mode="active",
        webhookEventId="test_webhook_event_id",  # LINE SDK 必要欄位
        deliveryContext=DeliveryContext(isRedelivery=False),  # LINE SDK 必要欄位
    )
