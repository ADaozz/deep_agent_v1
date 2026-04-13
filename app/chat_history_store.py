from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import psycopg

from app.config import Settings


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS demo_chat_sessions (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    payload JSONB NOT NULL,
    error_text TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (thread_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_demo_chat_sessions_thread_created
    ON demo_chat_sessions (thread_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_demo_chat_sessions_updated_at
    ON demo_chat_sessions (updated_at DESC);

CREATE TABLE IF NOT EXISTS demo_chat_thread_state (
    thread_id TEXT PRIMARY KEY,
    ui_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


@contextmanager
def _connect(settings: Settings):
    conn = psycopg.connect(
        host=settings.pg_host,
        port=settings.pg_port,
        user=settings.pg_user,
        password=settings.pg_password,
        dbname=settings.pg_database,
        autocommit=True,
    )
    try:
        yield conn
    finally:
        conn.close()


def ensure_chat_history_schema(settings: Settings) -> None:
    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)


def upsert_chat_session(
    *,
    settings: Settings,
    thread_id: str,
    session_id: str,
    query_text: str,
    payload: dict[str, Any],
    error_text: str = "",
) -> None:
    normalized_thread = thread_id.strip()
    normalized_session = session_id.strip()
    if not normalized_thread or not normalized_session:
        return

    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO demo_chat_sessions (
                thread_id,
                session_id,
                query_text,
                payload,
                error_text,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s::jsonb, %s, NOW(), NOW())
            ON CONFLICT (thread_id, session_id)
            DO UPDATE SET
                query_text = EXCLUDED.query_text,
                payload = EXCLUDED.payload,
                error_text = EXCLUDED.error_text,
                updated_at = NOW()
            """,
            (
                normalized_thread,
                normalized_session,
                query_text,
                json.dumps(payload, ensure_ascii=False),
                error_text,
            ),
        )


def fetch_latest_thread_history(settings: Settings) -> dict[str, Any] | None:
    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT thread_id
            FROM demo_chat_sessions
            ORDER BY updated_at DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            return None
        thread_id = str(row[0])
        return fetch_thread_history(settings=settings, thread_id=thread_id)


def fetch_thread_history(*, settings: Settings, thread_id: str) -> dict[str, Any] | None:
    normalized_thread = thread_id.strip()
    if not normalized_thread:
        return None

    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                session_id,
                query_text,
                payload,
                error_text,
                created_at,
                updated_at
            FROM demo_chat_sessions
            WHERE thread_id = %s
            ORDER BY created_at ASC, id ASC
            """,
            (normalized_thread,),
        )
        rows = cur.fetchall()

    if not rows:
        return None

    sessions: list[dict[str, Any]] = []
    for session_id, query_text, payload, error_text, created_at, updated_at in rows:
        payload_dict = payload if isinstance(payload, dict) else json.loads(payload)
        sessions.append(
            {
                "id": str(session_id),
                "query": str(query_text),
                "state": payload_dict,
                "error": str(error_text or ""),
                "created_at": _isoformat(created_at),
                "updated_at": _isoformat(updated_at),
            }
        )

    return {
        "thread_id": normalized_thread,
        "sessions": sessions,
    }


def list_history_threads(settings: Settings, *, limit: int = 30) -> list[dict[str, Any]]:
    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                thread_id,
                MAX(updated_at) AS updated_at,
                COUNT(*) AS session_count,
                (
                    ARRAY_AGG(query_text ORDER BY created_at DESC, id DESC)
                )[1] AS latest_query
            FROM demo_chat_sessions
            GROUP BY thread_id
            ORDER BY MAX(updated_at) DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    threads: list[dict[str, Any]] = []
    for thread_id, updated_at, session_count, latest_query in rows:
        threads.append(
            {
                "thread_id": str(thread_id),
                "updated_at": _isoformat(updated_at),
                "session_count": int(session_count or 0),
                "latest_query": str(latest_query or ""),
            }
        )
    return threads


def delete_thread_history(*, settings: Settings, thread_id: str) -> bool:
    normalized_thread = thread_id.strip()
    if not normalized_thread:
        return False

    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM demo_chat_thread_state
            WHERE thread_id = %s
            """,
            (normalized_thread,),
        )
        cur.execute(
            """
            DELETE FROM demo_chat_sessions
            WHERE thread_id = %s
            """,
            (normalized_thread,),
        )
        deleted = cur.rowcount > 0
    return deleted


def upsert_thread_ui_state(
    *,
    settings: Settings,
    thread_id: str,
    ui_state: dict[str, Any],
) -> None:
    normalized_thread = thread_id.strip()
    if not normalized_thread:
        return

    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO demo_chat_thread_state (thread_id, ui_state, updated_at)
            VALUES (%s, %s::jsonb, NOW())
            ON CONFLICT (thread_id)
            DO UPDATE SET
                ui_state = EXCLUDED.ui_state,
                updated_at = NOW()
            """,
            (normalized_thread, json.dumps(ui_state, ensure_ascii=False)),
        )


def fetch_thread_ui_state(*, settings: Settings, thread_id: str) -> dict[str, Any] | None:
    normalized_thread = thread_id.strip()
    if not normalized_thread:
        return None

    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ui_state
            FROM demo_chat_thread_state
            WHERE thread_id = %s
            """,
            (normalized_thread,),
        )
        row = cur.fetchone()

    if not row:
        return None
    payload = row[0]
    return payload if isinstance(payload, dict) else json.loads(payload)


def _isoformat(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
