from __future__ import annotations

import threading
import time
from typing import Any

from app.config import Settings, env_bool, env_int
from app.demo_session import run_demo_session_stream
from app.heartbeat_store import (
    claim_due_heartbeat_tasks,
    finish_heartbeat_run,
    start_heartbeat_run,
)
from app.runtime_context import runtime_mode


class HeartbeatScheduler:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.poll_interval = max(15, env_int("DEEP_AGENT_HEARTBEAT_POLL_INTERVAL", 30))
        self.enabled = env_bool("DEEP_AGENT_HEARTBEAT_ENABLED", True)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run_loop, name="heartbeat-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                tasks = claim_due_heartbeat_tasks(self.settings, limit=2)
                for task in tasks:
                    self._execute_task(task)
            except Exception:
                pass
            self._stop_event.wait(self.poll_interval)

    def _execute_task(self, task: dict[str, Any]) -> None:
        execute_heartbeat_task(self.settings, task)


def execute_heartbeat_task(settings: Settings, task: dict[str, Any]) -> None:
    task_id = str(task.get("task_id", "")).strip()
    if not task_id:
        return
    run_id = start_heartbeat_run(settings=settings, task_id=task_id)
    final_event: dict[str, Any] | None = None
    try:
        with runtime_mode("heartbeat"):
            for event in run_demo_session_stream(
                settings=settings,
                query=str(task.get("query_text", "")),
                max_rounds=max(1, env_int("DEEP_AGENT_HEARTBEAT_MAX_ROUNDS", 12)),
                messages=None,
                user_files=None,
                agent_query=None,
                run_mode="heartbeat",
            ):
                final_event = event
        payload = (final_event or {}).get("payload") or {}
        finish_heartbeat_run(
            settings=settings,
            task=task,
            run_id=run_id,
            status=str((final_event or {}).get("type") or payload.get("status") or "done"),
            stop_reason=str(payload.get("stop_reason") or ""),
            final_summary=str(payload.get("final_summary") or ""),
            payload=payload,
            artifacts=list(payload.get("files") or []),
        )
    except Exception as exc:  # noqa: BLE001
        finish_heartbeat_run(
            settings=settings,
            task=task,
            run_id=run_id,
            status="error",
            stop_reason=f"{type(exc).__name__}: {exc}",
            final_summary="",
            payload={"status": "stopped", "stop_reason": f"{type(exc).__name__}: {exc}"},
            artifacts=[],
        )


def execute_heartbeat_task_async(settings: Settings, task: dict[str, Any]) -> threading.Thread:
    worker = threading.Thread(
        target=execute_heartbeat_task,
        args=(settings, task),
        name=f"heartbeat-run-{str(task.get('task_id', 'unknown'))}",
        daemon=True,
    )
    worker.start()
    return worker
