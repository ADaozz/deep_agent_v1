from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

try:
    from croniter import croniter
except ImportError:  # pragma: no cover
    croniter = None

from app.chat_history_store import _connect, _isoformat
from app.config import Settings


HEARTBEAT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS demo_heartbeat_tasks (
    task_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    query_text TEXT NOT NULL,
    schedule_kind TEXT NOT NULL,
    schedule_type TEXT NOT NULL DEFAULT '',
    schedule_expr TEXT NOT NULL DEFAULT '',
    run_at TIMESTAMPTZ NULL,
    timezone TEXT NOT NULL DEFAULT 'Asia/Hong_Kong',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL DEFAULT 'active',
    created_by TEXT NOT NULL DEFAULT 'supervisor',
    runtime_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_run_at TIMESTAMPTZ NULL,
    last_status TEXT NOT NULL DEFAULT '',
    last_summary TEXT NOT NULL DEFAULT '',
    next_run_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_demo_heartbeat_tasks_next_run
    ON demo_heartbeat_tasks (enabled, next_run_at);

CREATE TABLE IF NOT EXISTS demo_heartbeat_runs (
    run_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES demo_heartbeat_tasks(task_id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ NULL,
    status TEXT NOT NULL DEFAULT 'running',
    stop_reason TEXT NOT NULL DEFAULT '',
    final_summary TEXT NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    artifacts_json JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_demo_heartbeat_runs_task_started
    ON demo_heartbeat_runs (task_id, started_at DESC);
"""


def ensure_heartbeat_schema(settings: Settings) -> None:
    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(HEARTBEAT_SCHEMA_SQL)


def _parse_timezone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo((timezone or "Asia/Hong_Kong").strip() or "Asia/Hong_Kong")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"invalid_timezone: {timezone}") from exc


def current_datetime_payload(*, timezone: str = "Asia/Hong_Kong") -> dict[str, Any]:
    zone = _parse_timezone(timezone)
    now = datetime.now(zone)
    return {
        "now_iso": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": now.strftime("%A"),
        "timezone": timezone,
        "unix_ts": int(now.timestamp()),
    }


def _parse_oneshot_run_at(run_at: str, *, timezone: str) -> datetime:
    if not str(run_at).strip():
        raise ValueError("run_at_required")
    try:
        parsed = datetime.fromisoformat(run_at.strip())
    except ValueError as exc:
        raise ValueError("invalid_run_at") from exc
    zone = _parse_timezone(timezone)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def _next_cron_occurrence(schedule_expr: str, *, timezone: str, base: datetime | None = None) -> datetime:
    expr = str(schedule_expr).strip()
    if not expr:
        raise ValueError("schedule_expr_required")
    zone = _parse_timezone(timezone)
    cursor = (base or datetime.now(zone)).astimezone(zone)
    if croniter is None:
        raise ValueError("croniter_not_installed")
    try:
        return croniter(expr, cursor).get_next(datetime)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid_cron_expression") from exc


def _next_interval_occurrence(schedule_expr: str, *, timezone: str, base: datetime | None = None) -> datetime:
    raw_expr = str(schedule_expr).strip()
    if not raw_expr:
        raise ValueError("schedule_expr_required")
    try:
        interval_seconds = int(raw_expr)
    except ValueError as exc:
        raise ValueError("invalid_interval_seconds") from exc
    if interval_seconds < 60:
        raise ValueError("interval_seconds_too_small")
    zone = _parse_timezone(timezone)
    cursor = (base or datetime.now(zone)).astimezone(zone)
    return cursor + timedelta(seconds=interval_seconds)


def compute_first_next_run_at(
    *,
    schedule_kind: str,
    schedule_type: str = "",
    schedule_expr: str = "",
    run_at: str = "",
    timezone: str = "Asia/Hong_Kong",
) -> datetime:
    normalized_kind = (schedule_kind or "").strip().lower()
    normalized_type = (schedule_type or "").strip().lower()
    if normalized_kind == "oneshot":
        next_run_at = _parse_oneshot_run_at(run_at, timezone=timezone)
        now = datetime.now(_parse_timezone(timezone))
        if next_run_at <= now:
            raise ValueError("run_at_must_be_future")
        return next_run_at
    if normalized_kind != "recurring":
        raise ValueError("invalid_schedule_kind")
    if normalized_type == "cron":
        return _next_cron_occurrence(schedule_expr, timezone=timezone)
    if normalized_type == "interval":
        return _next_interval_occurrence(schedule_expr, timezone=timezone)
    raise ValueError("invalid_schedule_type")


def compute_next_run_after_finish(task: dict[str, Any], *, finished_at: datetime | None = None) -> datetime | None:
    schedule_kind = str(task.get("schedule_kind", "")).strip().lower()
    schedule_type = str(task.get("schedule_type", "")).strip().lower()
    schedule_expr = str(task.get("schedule_expr", "")).strip()
    timezone = str(task.get("timezone", "Asia/Hong_Kong")).strip() or "Asia/Hong_Kong"
    if schedule_kind == "oneshot":
        return None
    if schedule_kind != "recurring":
        return None
    cursor = finished_at or datetime.now(_parse_timezone(timezone))
    if schedule_type == "cron":
        return _next_cron_occurrence(schedule_expr, timezone=timezone, base=cursor)
    if schedule_type == "interval":
        return _next_interval_occurrence(schedule_expr, timezone=timezone, base=cursor)
    return None


def create_heartbeat_task(
    *,
    settings: Settings,
    title: str,
    query_text: str,
    schedule_kind: str,
    schedule_type: str = "",
    schedule_expr: str = "",
    run_at: str = "",
    timezone: str = "Asia/Hong_Kong",
    created_by: str = "supervisor",
    runtime_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_title = str(title).strip()
    normalized_query = str(query_text).strip()
    if not normalized_title:
        raise ValueError("heartbeat_title_required")
    if not normalized_query:
        raise ValueError("heartbeat_query_required")
    next_run_at = compute_first_next_run_at(
        schedule_kind=schedule_kind,
        schedule_type=schedule_type,
        schedule_expr=schedule_expr,
        run_at=run_at,
        timezone=timezone,
    )
    task_id = f"hb_{uuid.uuid4().hex[:12]}"
    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO demo_heartbeat_tasks (
                task_id,
                title,
                query_text,
                schedule_kind,
                schedule_type,
                schedule_expr,
                run_at,
                timezone,
                enabled,
                status,
                created_by,
                runtime_config,
                next_run_at,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, 'active', %s, %s::jsonb, %s, NOW(), NOW())
            """,
            (
                task_id,
                normalized_title,
                normalized_query,
                schedule_kind.strip().lower(),
                schedule_type.strip().lower(),
                schedule_expr.strip(),
                _parse_oneshot_run_at(run_at, timezone=timezone) if schedule_kind.strip().lower() == "oneshot" else None,
                timezone,
                created_by,
                json.dumps(runtime_config or {}, ensure_ascii=False),
                next_run_at,
            ),
        )
    return get_heartbeat_task(settings=settings, task_id=task_id) or {
        "task_id": task_id,
        "title": normalized_title,
        "query_text": normalized_query,
        "next_run_at": next_run_at.isoformat(),
    }


def _row_to_task(row) -> dict[str, Any]:
    (
        task_id,
        title,
        query_text,
        schedule_kind,
        schedule_type,
        schedule_expr,
        run_at,
        timezone,
        enabled,
        status,
        created_by,
        runtime_config,
        created_at,
        updated_at,
        last_run_at,
        last_status,
        last_summary,
        next_run_at,
    ) = row
    return {
        "task_id": str(task_id),
        "title": str(title),
        "query_text": str(query_text),
        "schedule_kind": str(schedule_kind),
        "schedule_type": str(schedule_type or ""),
        "schedule_expr": str(schedule_expr or ""),
        "run_at": _isoformat(run_at),
        "timezone": str(timezone or "Asia/Hong_Kong"),
        "enabled": bool(enabled),
        "status": str(status or "active"),
        "created_by": str(created_by or "supervisor"),
        "runtime_config": runtime_config if isinstance(runtime_config, dict) else json.loads(runtime_config or "{}"),
        "created_at": _isoformat(created_at),
        "updated_at": _isoformat(updated_at),
        "last_run_at": _isoformat(last_run_at),
        "last_status": str(last_status or ""),
        "last_summary": str(last_summary or ""),
        "next_run_at": _isoformat(next_run_at),
    }


def list_heartbeat_tasks(settings: Settings) -> list[dict[str, Any]]:
    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                task_id,
                title,
                query_text,
                schedule_kind,
                schedule_type,
                schedule_expr,
                run_at,
                timezone,
                enabled,
                status,
                created_by,
                runtime_config,
                created_at,
                updated_at,
                last_run_at,
                last_status,
                last_summary,
                next_run_at
            FROM demo_heartbeat_tasks
            ORDER BY
                CASE WHEN status = 'running' THEN 0 ELSE 1 END,
                CASE WHEN next_run_at IS NULL THEN 1 ELSE 0 END,
                next_run_at ASC,
                last_run_at DESC NULLS LAST,
                created_at DESC
            """
        )
        return [_row_to_task(row) for row in cur.fetchall()]


def update_heartbeat_enabled(*, settings: Settings, task_id: str, enabled: bool) -> dict[str, Any] | None:
    normalized_task_id = task_id.strip()
    if not normalized_task_id:
        return None
    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE demo_heartbeat_tasks
            SET enabled = %s,
                status = CASE
                    WHEN %s = FALSE AND status <> 'completed' THEN 'disabled'
                    WHEN %s = TRUE AND status = 'disabled' THEN 'active'
                    ELSE status
                END,
                updated_at = NOW()
            WHERE task_id = %s
            """,
            (enabled, enabled, enabled, normalized_task_id),
        )
    return get_heartbeat_task(settings=settings, task_id=normalized_task_id)


def delete_heartbeat_task(*, settings: Settings, task_id: str) -> bool:
    normalized_task_id = task_id.strip()
    if not normalized_task_id:
        return False
    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM demo_heartbeat_tasks WHERE task_id = %s", (normalized_task_id,))
        return cur.rowcount > 0


def get_heartbeat_task(*, settings: Settings, task_id: str) -> dict[str, Any] | None:
    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                task_id,
                title,
                query_text,
                schedule_kind,
                schedule_type,
                schedule_expr,
                run_at,
                timezone,
                enabled,
                status,
                created_by,
                runtime_config,
                created_at,
                updated_at,
                last_run_at,
                last_status,
                last_summary,
                next_run_at
            FROM demo_heartbeat_tasks
            WHERE task_id = %s
            """,
            (task_id.strip(),),
        )
        row = cur.fetchone()
    return _row_to_task(row) if row else None


def start_heartbeat_task_now(*, settings: Settings, task_id: str) -> dict[str, Any] | None:
    normalized_task_id = task_id.strip()
    if not normalized_task_id:
        return None
    started_task: dict[str, Any] | None = None
    with _connect(settings) as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    task_id,
                    title,
                    query_text,
                    schedule_kind,
                    schedule_type,
                    schedule_expr,
                    run_at,
                    timezone,
                    enabled,
                    status,
                    created_by,
                    runtime_config,
                    created_at,
                    updated_at,
                    last_run_at,
                    last_status,
                    last_summary,
                    next_run_at
                FROM demo_heartbeat_tasks
                WHERE task_id = %s
                FOR UPDATE
                """,
                (normalized_task_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            task = _row_to_task(row)
            if str(task.get("status", "")).strip().lower() == "running":
                raise ValueError("heartbeat_task_already_running")
            cur.execute(
                """
                UPDATE demo_heartbeat_tasks
                SET status = 'running',
                    updated_at = NOW()
                WHERE task_id = %s
                """,
                (normalized_task_id,),
            )
            task["status"] = "running"
            started_task = task
    return started_task


def claim_due_heartbeat_tasks(settings: Settings, *, limit: int = 3) -> list[dict[str, Any]]:
    claimed: list[dict[str, Any]] = []
    with _connect(settings) as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """
                SELECT task_id
                FROM demo_heartbeat_tasks
                WHERE enabled = TRUE
                  AND next_run_at IS NOT NULL
                  AND next_run_at <= NOW()
                  AND status <> 'running'
                ORDER BY next_run_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT %s
                """,
                (limit,),
            )
            task_ids = [str(row[0]) for row in cur.fetchall()]
            if not task_ids:
                return []
            cur.execute(
                """
                UPDATE demo_heartbeat_tasks
                SET status = 'running',
                    updated_at = NOW()
                WHERE task_id = ANY(%s)
                """,
                (task_ids,),
            )
            cur.execute(
                """
                SELECT
                    task_id,
                    title,
                    query_text,
                    schedule_kind,
                    schedule_type,
                    schedule_expr,
                    run_at,
                    timezone,
                    enabled,
                    status,
                    created_by,
                    runtime_config,
                    created_at,
                    updated_at,
                    last_run_at,
                    last_status,
                    last_summary,
                    next_run_at
                FROM demo_heartbeat_tasks
                WHERE task_id = ANY(%s)
                ORDER BY next_run_at ASC
                """,
                (task_ids,),
            )
            claimed = [_row_to_task(row) for row in cur.fetchall()]
    return claimed


def start_heartbeat_run(*, settings: Settings, task_id: str) -> str:
    run_id = f"hbr_{uuid.uuid4().hex[:12]}"
    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO demo_heartbeat_runs (run_id, task_id, started_at, status)
            VALUES (%s, %s, NOW(), 'running')
            """,
            (run_id, task_id.strip()),
        )
    return run_id


def list_heartbeat_runs(*, settings: Settings, task_id: str, limit: int = 10) -> list[dict[str, Any]]:
    normalized_task_id = task_id.strip()
    if not normalized_task_id:
        return []
    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT run_id, task_id, started_at, finished_at, status, stop_reason, final_summary, payload_json, artifacts_json
            FROM demo_heartbeat_runs
            WHERE task_id = %s
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (normalized_task_id, limit),
        )
        rows = cur.fetchall()
    runs: list[dict[str, Any]] = []
    for run_id, task_id, started_at, finished_at, status, stop_reason, final_summary, payload_json, artifacts_json in rows:
        runs.append(
            {
                "run_id": str(run_id),
                "task_id": str(task_id),
                "started_at": _isoformat(started_at),
                "finished_at": _isoformat(finished_at),
                "status": str(status or ""),
                "stop_reason": str(stop_reason or ""),
                "final_summary": str(final_summary or ""),
                "payload": payload_json if isinstance(payload_json, dict) else json.loads(payload_json or "{}"),
                "artifacts": artifacts_json if isinstance(artifacts_json, list) else json.loads(artifacts_json or "[]"),
            }
        )
    return runs


def finish_heartbeat_run(
    *,
    settings: Settings,
    task: dict[str, Any],
    run_id: str,
    status: str,
    stop_reason: str,
    final_summary: str,
    payload: dict[str, Any],
    artifacts: list[dict[str, Any]] | None = None,
) -> None:
    finished_at = datetime.now(_parse_timezone(str(task.get("timezone", "Asia/Hong_Kong"))))
    next_run_at = compute_next_run_after_finish(task, finished_at=finished_at)
    enabled = bool(task.get("enabled", True))
    task_status = "active"
    if str(task.get("schedule_kind", "")).strip().lower() == "oneshot":
        enabled = False
        task_status = "completed" if status == "done" else "failed"
    elif status == "done":
        task_status = "active" if enabled else "disabled"
    else:
        task_status = "failed"

    with _connect(settings) as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE demo_heartbeat_runs
            SET finished_at = NOW(),
                status = %s,
                stop_reason = %s,
                final_summary = %s,
                payload_json = %s::jsonb,
                artifacts_json = %s::jsonb
            WHERE run_id = %s
            """,
            (
                status,
                stop_reason,
                final_summary,
                json.dumps(payload, ensure_ascii=False),
                json.dumps(artifacts or [], ensure_ascii=False),
                run_id,
            ),
        )
        cur.execute(
            """
            UPDATE demo_heartbeat_tasks
            SET enabled = %s,
                status = %s,
                last_run_at = NOW(),
                last_status = %s,
                last_summary = %s,
                next_run_at = %s,
                updated_at = NOW()
            WHERE task_id = %s
            """,
            (
                enabled,
                task_status,
                status,
                final_summary[:2000],
                next_run_at,
                str(task.get("task_id", "")).strip(),
            ),
        )
