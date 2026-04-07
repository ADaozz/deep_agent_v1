from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Sequence

from dotenv import load_dotenv

from app.prompts import DEFAULT_USER_PROMPT


@dataclass
class Settings:
    # 用户问题，作为本次 agent 的输入。
    prompt: str
    # 模型名、API Key 和 Base URL 都从 .env / 环境变量读取。
    model: str
    api_key: str
    base_url: str | None
    log_level: str
    log_file: str


def load_settings(argv: Sequence[str] | None = None) -> Settings:
    # 启动时自动加载项目根目录下的 .env。
    load_dotenv()

    parser = argparse.ArgumentParser(description="LangChain create_deep_agent logging demo")
    parser.add_argument(
        "--prompt",
        default=DEFAULT_USER_PROMPT,
        help="发送给 deep agent 的用户问题。",
    )
    parser.add_argument(
        "--model",
        default=(
            os.getenv("OPENAI_MODEL")
            or os.getenv("DASHSCOPE_MODEL")
            or "gpt-4o-mini"
        ),
        help="OpenAI-compatible chat model name.",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "INFO"),
        help="Python logging level.",
    )
    parser.add_argument(
        "--log-file",
        default=os.getenv("DEEP_AGENT_LOG_FILE", "runtime_logs/deep_agent_stream.jsonl"),
        help="Path to the jsonl log file.",
    )
    args = parser.parse_args(argv)

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("DASHSCOPE_BASE_URL")

    if not api_key:
        raise RuntimeError(
            "缺少 OPENAI_API_KEY 或 DASHSCOPE_API_KEY，请先在环境变量或 .env 中配置。"
        )

    return Settings(
        prompt=args.prompt,
        model=args.model,
        api_key=api_key,
        base_url=base_url,
        log_level=args.log_level,
        log_file=args.log_file,
    )
