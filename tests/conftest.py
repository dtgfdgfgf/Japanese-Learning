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
    Create an in-memory SQLite session for testing.
    Note: For production-like tests, use a real PostgreSQL test database.
    
    Warning: This fixture has limited compatibility with PostgreSQL-specific
    features like JSONB. Tests that require actual database operations should
    use a real PostgreSQL test database or be marked with @pytest.mark.skip_sqlite.
    """
    # Note: SQLite doesn't support JSONB, so tests using this fixture
    # with models that have JSONB columns will fail at table creation.
    # For full database tests, use a PostgreSQL test database.
    pytest.skip("Skipping: SQLite doesn't support JSONB type used in models")
    
    # Use SQLite for unit tests (faster, no DB required)
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        yield session
    
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
