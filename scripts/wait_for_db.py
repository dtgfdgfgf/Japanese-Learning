#!/usr/bin/env python3
"""等待資料庫就緒，用於 Render cold start 時 DB 也在喚醒的情況。"""

import asyncio
import os
import sys


async def wait_for_db(max_retries: int = 30, delay: float = 2.0) -> bool:
    """嘗試連接資料庫，最多重試 max_retries 次（預設 60 秒）。"""
    import asyncpg

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("DATABASE_URL not set, skipping DB wait")
        return True

    # asyncpg 只接受 postgresql:// 或 postgres://，需移除 SQLAlchemy driver 後綴
    database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    for attempt in range(1, max_retries + 1):
        try:
            conn = await asyncpg.connect(database_url, timeout=10)
            await conn.execute("SELECT 1")
            await conn.close()
            print(f"DB ready (attempt {attempt}/{max_retries})")
            return True
        except Exception as e:
            print(f"DB not ready (attempt {attempt}/{max_retries}): {type(e).__name__}: {e}")
            if attempt < max_retries:
                await asyncio.sleep(delay)

    print("DB connection failed after all retries")
    return False


if __name__ == "__main__":
    success = asyncio.run(wait_for_db())
    sys.exit(0 if success else 1)
