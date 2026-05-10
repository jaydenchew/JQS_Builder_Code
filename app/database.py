"""Async MySQL connection pool — unified single database"""
import asyncio
import aiomysql
import logging
from app.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

logger = logging.getLogger(__name__)

_pool = None

# Hang protection. aiomysql 0.3.2 honors connect_timeout for new TCP handshakes
# but has no read_timeout for in-flight queries — a half-open zombie socket
# (remote side gone but TCP not RST/FIN'd) makes cur.execute() wait forever
# unless each call is wrapped in its own timeout. 15s is generous: slowest
# observed query is <100ms (worker fetch ~13ms, heaviest report ~94ms).
DB_CONNECT_TIMEOUT_S = 10
DB_CALL_TIMEOUT_S = 15


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await aiomysql.create_pool(
            host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, db=DB_NAME,
            autocommit=True, charset="utf8mb4", cursorclass=aiomysql.DictCursor,
            minsize=2, maxsize=20,
            connect_timeout=DB_CONNECT_TIMEOUT_S,
        )
        logger.info("DB pool created: %s:%d/%s", DB_HOST, DB_PORT, DB_NAME)
    return _pool


async def close_pool():
    global _pool
    if _pool:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
        logger.info("DB pool closed")


async def _run(op):
    """Execute one pooled DB op with hang protection.

    On timeout/cancel mid-query, force-close the connection so pool.release
    evicts it from _free. Without this, a half-open zombie that aiomysql's
    at_eof()/exception() probe can't detect would be re-added to the free
    list and the next caller would hang on it again — that's the failure
    mode that took workers offline on 2026-05-10 01:23.
    """
    pool = await get_pool()
    conn = await pool.acquire()
    try:
        return await asyncio.wait_for(op(conn), timeout=DB_CALL_TIMEOUT_S)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        conn.close()
        raise
    finally:
        pool.release(conn)


async def fetchone(query, args=None):
    async def _op(conn):
        async with conn.cursor() as cur:
            await cur.execute(query, args)
            return await cur.fetchone()
    return await _run(_op)


async def fetchall(query, args=None):
    async def _op(conn):
        async with conn.cursor() as cur:
            await cur.execute(query, args)
            return await cur.fetchall()
    return await _run(_op)


async def execute(query, args=None):
    async def _op(conn):
        async with conn.cursor() as cur:
            await cur.execute(query, args)
            return cur.lastrowid
    return await _run(_op)


async def execute_many(query, args_list):
    async def _op(conn):
        async with conn.cursor() as cur:
            await cur.executemany(query, args_list)
            return cur.rowcount
    return await _run(_op)
