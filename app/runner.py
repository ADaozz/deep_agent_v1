from __future__ import annotations

import os

from app.agent import build_agent
from app.config import load_settings
from app.logging_utils import setup_logging
from app.streaming import StreamLogger


def run() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)

    # 日志目录不存在时自动创建，便于落 JSONL 运行日志。
    log_dir = os.path.dirname(settings.log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    agent = build_agent(settings, query=settings.prompt)
    stream_logger = StreamLogger(log_file=settings.log_file)

    try:
        # 同时订阅调度更新、消息流和自定义事件，用于完整观察内部执行过程。
        for chunk in agent.stream(
            {"messages": [{"role": "user", "content": settings.prompt}]},
            stream_mode=["updates", "messages", "custom"],
            subgraphs=True,
            version="v2",
        ):
            stream_logger.handle(chunk)
    finally:
        stream_logger.close()

    print("\n\n===== FINAL RESPONSE =====")
    final_response = "".join(
        stream_logger.text_buffers.get("supervisor")
        or stream_logger.text_buffers.get("main-agent")
        or stream_logger.text_buffers.get("main")
        or []
    )
    if final_response:
        print(final_response)
    else:
        print("Final response was only visible in the token stream.")

    print("\n===== SUBAGENT STATES =====")
    if stream_logger.active_subagents:
        for sub_id, sub_state in stream_logger.active_subagents.items():
            print(
                f"- id={sub_id} type={sub_state.subagent_type} "
                f"status={sub_state.status} pregel={sub_state.pregel_id}"
            )
    else:
        print("- no subagent call captured")

    print(f"\nJSONL 日志已写入: {settings.log_file}")
