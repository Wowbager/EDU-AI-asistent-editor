"""Database utility functions for webchat."""
import os
import aiomysql
from typing import Any, Dict, List, Optional


_pool: Optional[aiomysql.Pool] = None


async def get_db_pool() -> aiomysql.Pool:
    """Get or create the async database connection pool."""
    global _pool
    if _pool is None:
        _pool = await aiomysql.create_pool(
            host=os.getenv("MYSQL_HOST", "mysql"),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.environ.get("MYSQL_ROOT_PASSWORD", ""),
            db=os.getenv("MYSQL_DATABASE", "edu"),
            autocommit=True,
            minsize=int(os.getenv("WEBCHAT_DB_POOL_MIN", "2")),
            maxsize=int(os.getenv("WEBCHAT_DB_POOL_MAX", "20")),
            pool_recycle=3600,
            connect_timeout=10,
        )
    return _pool


async def close_db_pool():
    """Close the database connection pool."""
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None


async def get_db_all(sql: str, parameters: List[Any]) -> List[Dict[str, Any]]:
    """Execute a SQL query and return all rows."""
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, parameters)
            result = await cursor.fetchall()
            return result


async def get_db_row(sql: str, parameters: List[Any]) -> Optional[Dict[str, Any]]:
    """Execute a SQL query and return a single row."""
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, parameters)
            result = await cursor.fetchone()
            return result
