from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from app.prompts import get_default_user_prompt


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


@lru_cache(maxsize=1)
def load_project_env() -> Path:
    """Load environment variables from the project-level .env file once."""
    load_dotenv(dotenv_path=ENV_FILE, override=False)
    return ENV_FILE


def env_str(name: str, default: str = "") -> str:
    load_project_env()
    value = os.getenv(name)
    return default if value is None else value


def env_int(name: str, default: int) -> int:
    raw = env_str(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = env_str(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass
class Settings:
    # 用户问题，作为本次 agent 的输入。
    prompt: str
    # 模型名、API Key 和 Base URL 都从 .env / 环境变量读取。
    model: str
    api_key: str
    base_url: str | None
    model_timeout: int
    model_max_retries: int
    log_level: str
    log_file: str
    backend: str
    docker_container_name: str
    docker_workspace_dir: str
    docker_timeout: int
    pg_host: str
    pg_port: int
    pg_user: str
    pg_password: str
    pg_database: str


def load_settings(argv: Sequence[str] | None = None) -> Settings:
    # 启动时自动加载项目根目录下的 .env。
    load_project_env()

    parser = argparse.ArgumentParser(description="LangChain create_deep_agent logging demo")
    parser.add_argument(
        "--prompt",
        default=get_default_user_prompt(),
        help="发送给 deep agent 的用户问题。",
    )
    parser.add_argument(
        "--model",
        default=(
            env_str("OPENAI_MODEL")
            or env_str("DASHSCOPE_MODEL")
            or "gpt-4o-mini"
        ),
        help="OpenAI-compatible chat model name.",
    )
    parser.add_argument(
        "--model-timeout",
        default=env_int("DEEP_AGENT_MODEL_TIMEOUT", 300),
        type=int,
        help="Model request timeout in seconds.",
    )
    parser.add_argument(
        "--model-max-retries",
        default=env_int("DEEP_AGENT_MODEL_MAX_RETRIES", 2),
        type=int,
        help="Model request retry count for transient network failures.",
    )
    parser.add_argument(
        "--log-level",
        default=env_str("LOG_LEVEL", "INFO"),
        help="Python logging level.",
    )
    parser.add_argument(
        "--log-file",
        default=env_str("DEEP_AGENT_LOG_FILE", "runtime_logs/deep_agent_stream.jsonl"),
        help="Path to the jsonl log file.",
    )
    parser.add_argument(
        "--backend",
        default=env_str("DEEP_AGENT_BACKEND", "filesystem"),
        choices=["filesystem", "docker"],
        help="Backend mode for file operations and command execution.",
    )
    parser.add_argument(
        "--docker-container-name",
        default=env_str("DEEP_AGENT_DOCKER_CONTAINER", "deep-agent-sandbox"),
        help="Docker container name used when --backend docker.",
    )
    parser.add_argument(
        "--docker-workspace-dir",
        default=env_str("DEEP_AGENT_DOCKER_WORKSPACE", "/workspace"),
        help="Workspace directory inside the Docker container.",
    )
    parser.add_argument(
        "--docker-timeout",
        default=env_int("DEEP_AGENT_DOCKER_TIMEOUT", 120),
        type=int,
        help="Default command timeout in seconds for Docker-backed execute().",
    )
    parser.add_argument(
        "--pg-host",
        default=env_str("DEEP_AGENT_PG_HOST", "127.0.0.1"),
        help="PostgreSQL host for chat history persistence.",
    )
    parser.add_argument(
        "--pg-port",
        default=env_int("DEEP_AGENT_PG_PORT", 5432),
        type=int,
        help="PostgreSQL port for chat history persistence.",
    )
    parser.add_argument(
        "--pg-user",
        default=env_str("DEEP_AGENT_PG_USER", "postgresql"),
        help="PostgreSQL user for chat history persistence.",
    )
    parser.add_argument(
        "--pg-password",
        default=env_str("DEEP_AGENT_PG_PASSWORD", "postgresql"),
        help="PostgreSQL password for chat history persistence.",
    )
    parser.add_argument(
        "--pg-database",
        default=env_str("DEEP_AGENT_PG_DATABASE", "postgresql"),
        help="PostgreSQL database for chat history persistence.",
    )
    args = parser.parse_args(argv)

    api_key = env_str("OPENAI_API_KEY") or env_str("DASHSCOPE_API_KEY")
    base_url = env_str("OPENAI_BASE_URL") or env_str("DASHSCOPE_BASE_URL")

    if not api_key:
        raise RuntimeError(
            "缺少 OPENAI_API_KEY 或 DASHSCOPE_API_KEY，请先在环境变量或 .env 中配置。"
        )

    return Settings(
        prompt=args.prompt,
        model=args.model,
        api_key=api_key,
        base_url=base_url,
        model_timeout=max(30, args.model_timeout),
        model_max_retries=max(0, args.model_max_retries),
        log_level=args.log_level,
        log_file=args.log_file,
        backend=args.backend,
        docker_container_name=args.docker_container_name,
        docker_workspace_dir=args.docker_workspace_dir,
        docker_timeout=args.docker_timeout,
        pg_host=args.pg_host,
        pg_port=args.pg_port,
        pg_user=args.pg_user,
        pg_password=args.pg_password,
        pg_database=args.pg_database,
    )
