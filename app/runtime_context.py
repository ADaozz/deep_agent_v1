from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


_RUN_MODE: ContextVar[str] = ContextVar("deep_agent_run_mode", default="interactive")


def get_run_mode() -> str:
    return _RUN_MODE.get()


@contextmanager
def runtime_mode(mode: str) -> Iterator[None]:
    token = _RUN_MODE.set((mode or "interactive").strip() or "interactive")
    try:
        yield
    finally:
        _RUN_MODE.reset(token)
