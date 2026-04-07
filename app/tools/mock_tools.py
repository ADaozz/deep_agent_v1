from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool
from langgraph.config import get_stream_writer


@tool
def query_internal_kb(topic: str) -> str:
    """Query the internal knowledge base and return mock findings for a topic."""
    # 在工具内部发 custom 事件，外部可以实时看到执行进度。
    writer = get_stream_writer()
    writer({"stage": "kb_lookup", "status": "started", "topic": topic})

    kb = {
        "langchain": [
            "LangChain 提供模型、提示词、工具和 agent 相关抽象。",
            "Deep Agents 基于 LangGraph 运行时，支持规划、文件系统和 subagent。",
            "astream/stream 可以暴露 messages、updates、custom 等流式事件。",
        ],
        "deep agent": [
            "create_deep_agent 内置 write_todos、task、文件系统工具。",
            "subgraphs=True 时可以拿到子 agent 的事件命名空间。",
            "version='v2' 时流式块统一为 type/ns/data 三段结构。",
        ],
        "logging": [
            "可以在 stream_mode=['updates','messages','custom'] 下汇总执行过程。",
            "tool call chunks 能看到工具名和参数流。",
            "tool 类型消息可以看到工具返回结果。",
        ],
    }

    matched = []
    lowered = topic.lower()
    for key, values in kb.items():
        if key in lowered:
            matched.extend(values)

    if not matched:
        matched = [
            f"未命中精确主题 {topic}，返回默认内部资料。",
            "建议结合 write_todos 先规划，再使用 task 或业务工具执行。",
        ]

    writer({"stage": "kb_lookup", "status": "finished", "matches": len(matched)})
    return "\n".join(f"- {item}" for item in matched)


@tool
def inspect_architecture(question: str) -> str:
    """Inspect the current project architecture and return a concise answer."""
    writer = get_stream_writer()
    writer({"stage": "arch_inspect", "status": "started", "question": question})

    answer = _build_live_architecture_snapshot()

    writer({"stage": "arch_inspect", "status": "finished"})
    return json.dumps(answer, ensure_ascii=False, indent=2)


def _build_live_architecture_snapshot() -> dict[str, object]:
    project_root = Path(__file__).resolve().parents[2]

    builder_text = (project_root / "app/agent/builder.py").read_text(encoding="utf-8")
    demo_session_text = (project_root / "app/demo_session.py").read_text(encoding="utf-8")
    todo_text = (project_root / "app/agent/todo_enforcer.py").read_text(encoding="utf-8")
    demo_server_text = (project_root / "app/demo_server.py").read_text(encoding="utf-8")
    frontend_text = (project_root / "frontend_demo/app.js").read_text(encoding="utf-8")

    return {
        "question": "基于当前项目文件生成的实时架构摘要",
        "supervisor": {
            "agent_name": "supervisor" if 'name="supervisor"' in builder_text else "unknown",
            "top_level_tools": "顶层 tools=[]，主要通过 task 派发 subagent" if "tools=[]" in builder_text else "顶层工具配置已变化",
            "subagent_dispatch": "支持默认 worker + 动态派生 worker" if "_derive_dynamic_subagents" in builder_text else "仅默认 worker",
        },
        "subagents": {
            "default_workers": [
                item
                for item in ["worker_alpha", "worker_beta", "worker_gamma"]
                if item in builder_text
            ],
            "shared_tools": [
                item
                for item in ["query_internal_kb", "inspect_architecture"]
                if item in builder_text
            ],
            "todo_guard": "每个子 agent 强制维护 evidence todo checklist"
            if "write_evidence_todos" in todo_text and "after_agent" in todo_text
            else "未检测到 evidence todo guard",
        },
        "streaming": {
            "server_mode": "NDJSON stream /api/demo/run" if "application/x-ndjson" in demo_server_text else "non-stream",
            "collector_modes": [
                item
                for item in ["updates", "messages", "custom"]
                if item in demo_session_text
            ],
            "subgraph_visibility": "已启用 subgraphs=True" if "subgraphs=True" in demo_session_text else "未启用 subgraphs",
        },
        "frontend": {
            "multi_turn": "前端会回传历史 messages 形成多轮上下文" if "messageHistory" in frontend_text else "单轮 query",
            "worker_checklist_ui": "worker 面板包含 todo_list 可视化" if "TodoList" in frontend_text else "未检测到 checklist UI",
            "status_card": "顶部 stats-row 含 Status 卡片" if "StatusCard" in frontend_text else "未检测到状态卡片",
        },
    }
