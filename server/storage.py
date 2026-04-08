"""Async SQLite storage for conversation persistence."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None


async def init_db(db_path: str) -> None:
    """Open (or create) the SQLite database and ensure tables exist."""
    global _db
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(db_path)
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id  TEXT PRIMARY KEY,
            summary     TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL REFERENCES sessions(session_id),
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            extra_json  TEXT,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, id);
        """
    )
    await _db.commit()
    logger.info("[Storage] database ready: %s", db_path)


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Session operations ────────────────────────────────────────────────────────

async def create_session(session_id: str) -> None:
    assert _db
    now = _now_iso()
    await _db.execute(
        "INSERT OR IGNORE INTO sessions (session_id, summary, created_at, updated_at) "
        "VALUES (?, '', ?, ?)",
        (session_id, now, now),
    )
    await _db.commit()


async def save_message(session_id: str, role: str, content: str, **extra: object) -> None:
    assert _db
    extra_json = json.dumps(extra, ensure_ascii=False) if extra else None
    now = _now_iso()
    await _db.execute(
        "INSERT INTO messages (session_id, role, content, extra_json, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, role, content, extra_json, now),
    )
    await _db.execute(
        "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
        (now, session_id),
    )
    await _db.commit()


async def save_summary(session_id: str, summary: str) -> None:
    assert _db
    await _db.execute(
        "UPDATE sessions SET summary = ?, updated_at = ? WHERE session_id = ?",
        (summary, _now_iso(), session_id),
    )
    await _db.commit()


async def load_session(session_id: str, max_messages: int = 40) -> dict | None:
    """Load a session's summary and most recent messages.

    Returns ``None`` if the session does not exist, otherwise::

        {
            "session_id": str,
            "summary": str,
            "messages": [{"role": ..., "content": ..., **extra}, ...],
        }
    """
    assert _db
    async with _db.execute(
        "SELECT session_id, summary FROM sessions WHERE session_id = ?",
        (session_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None

    messages: list[dict] = []
    async with _db.execute(
        "SELECT role, content, extra_json FROM messages "
        "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, max_messages),
    ) as cursor:
        rows = await cursor.fetchall()
    for role, content, extra_json in reversed(rows):  # restore chronological order
        msg: dict = {"role": role, "content": content}
        if extra_json:
            msg.update(json.loads(extra_json))
        messages.append(msg)

    return {"session_id": row[0], "summary": row[1], "messages": messages}


async def get_latest_session(timeout_minutes: int = 30, max_messages: int = 40) -> dict | None:
    """Return the most recently updated session if it is within *timeout_minutes*.

    Returns the same shape as :func:`load_session`, or ``None`` if no
    qualifying session exists.
    """
    assert _db
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
    async with _db.execute(
        "SELECT session_id FROM sessions "
        "WHERE updated_at >= ? ORDER BY updated_at DESC LIMIT 1",
        (cutoff.isoformat(),),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    return await load_session(row[0], max_messages)


async def list_sessions(limit: int = 20) -> list[dict]:
    """Return the most recently updated sessions."""
    assert _db
    async with _db.execute(
        "SELECT session_id, summary, created_at, updated_at "
        "FROM sessions ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {"session_id": r[0], "summary": r[1], "created_at": r[2], "updated_at": r[3]}
        for r in rows
    ]
