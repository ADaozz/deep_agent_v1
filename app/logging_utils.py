from __future__ import annotations

import json
import logging
from typing import Any


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def short_text(value: Any, limit: int = 160) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except TypeError:
            # LangGraph streaming payloads may include wrapper objects such as Overwrite.
            text = repr(value)
    text = text.replace("\n", "\\n")
    return text if len(text) <= limit else f"{text[:limit]}..."
