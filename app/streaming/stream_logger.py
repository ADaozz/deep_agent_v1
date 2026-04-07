from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.logging_utils import short_text


LOG = logging.getLogger("deep-agent-demo")


@dataclass
class SubagentState:
    # subagent_type 是 task 工具传入的子代理类型名。
    subagent_type: str
    description: str
    status: str = "pending"
    pregel_id: str | None = None


@dataclass
class StreamLogger:
    log_file: str
    active_subagents: dict[str, SubagentState] = field(default_factory=dict)
    last_token_source: str = ""
    last_tool_name_by_source: dict[str, str] = field(default_factory=dict)
    token_line_open: bool = False
    text_buffers: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._file = open(self.log_file, "a", encoding="utf-8")

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    def _write_jsonl(self, record: dict[str, Any]) -> None:
        # 每个流式 chunk 都写一条 JSONL，后续接日志平台会比较方便。
        payload = {"ts": datetime.now().isoformat(timespec="seconds"), **record}
        self._file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._file.flush()

    def _source(self, ns: tuple[str, ...]) -> str:
        # 主 agent 的 namespace 为空；子 agent 会落在 tools:<id> 命名空间下。
        if not ns:
            return "main"
        sub_ns = next((item for item in ns if item.startswith("tools:")), None)
        return sub_ns or " > ".join(ns)

    def _flush_token_line(self) -> None:
        if self.token_line_open:
            print()
            self.token_line_open = False

    def handle(self, chunk: dict[str, Any]) -> None:
        # v2 流格式统一包含 type / ns / data，便于集中处理。
        chunk_type = chunk["type"]
        ns = tuple(chunk.get("ns", ()))
        source = self._source(ns)

        self._write_jsonl(
            {
                "type": chunk_type,
                "ns": list(ns),
                "data_preview": short_text(chunk.get("data")),
            }
        )

        if chunk_type == "updates":
            self._handle_updates(source, ns, chunk["data"])
        elif chunk_type == "messages":
            self._handle_messages(source, chunk["data"])
        elif chunk_type == "custom":
            self._flush_token_line()
            LOG.info("[%s][custom] %s", source, short_text(chunk["data"]))

    def _handle_updates(self, source: str, ns: tuple[str, ...], data: dict[str, Any]) -> None:
        for node_name, node_data in data.items():
            self._flush_token_line()
            LOG.info("[%s][step] %s", source, node_name)

            if not ns and node_name == "model_request":
                # 主 agent 在 model_request 阶段发出 task 工具调用时，说明开始调度子代理。
                for msg in node_data.get("messages", []):
                    for tool_call in getattr(msg, "tool_calls", []):
                        if tool_call["name"] == "task":
                            tool_call_id = tool_call["id"]
                            args = tool_call.get("args", {})
                            subagent_type = args.get("subagent_type", "unknown")
                            description = args.get("description", "")
                            self.active_subagents[tool_call_id] = SubagentState(
                                subagent_type=subagent_type,
                                description=description,
                            )
                            LOG.info(
                                '[lifecycle] PENDING  -> subagent="%s" id=%s desc=%s',
                                subagent_type,
                                tool_call_id,
                                short_text(description, 100),
                            )

            if ns and ns[0].startswith("tools:"):
                # 一旦收到了子图事件，就把对应 subagent 标记为 running。
                pregel_id = ns[0].split(":", 1)[1]
                for state in self.active_subagents.values():
                    if state.status == "pending":
                        state.status = "running"
                        state.pregel_id = pregel_id
                        LOG.info(
                            '[lifecycle] RUNNING  -> subagent="%s" pregel=%s',
                            state.subagent_type,
                            pregel_id,
                        )
                        break

            if not ns and node_name == "tools":
                # 主 agent 的 tools 节点收到 ToolMessage，说明子代理或工具已经返回结果。
                for msg in node_data.get("messages", []):
                    if getattr(msg, "type", "") == "tool":
                        state = self.active_subagents.get(getattr(msg, "tool_call_id", ""))
                        if state:
                            state.status = "complete"
                            LOG.info(
                                '[lifecycle] COMPLETE -> subagent="%s" id=%s',
                                state.subagent_type,
                                msg.tool_call_id,
                            )
                        LOG.info(
                            "[main][tool-result] %s => %s",
                            getattr(msg, "name", "unknown"),
                            short_text(getattr(msg, "content", "")),
                        )

    def _handle_messages(self, source: str, payload: tuple[Any, dict[str, Any]]) -> None:
        token, metadata = payload
        agent_name = metadata.get("lc_agent_name") or source

        tool_chunks = getattr(token, "tool_call_chunks", None) or []
        if tool_chunks:
            self._flush_token_line()
            for tool_chunk in tool_chunks:
                if tool_chunk.get("name"):
                    self.last_tool_name_by_source[source] = tool_chunk["name"]
                    LOG.info("[%s][tool-call] %s", agent_name, tool_chunk["name"])
                if tool_chunk.get("args"):
                    LOG.info("[%s][tool-args] %s", agent_name, short_text(tool_chunk["args"]))

        if getattr(token, "type", None) == "tool":
            # tool 类型消息表示“工具已经执行完成并返回了内容”。
            self._flush_token_line()
            tool_name = getattr(token, "name", None) or self.last_tool_name_by_source.get(source, "unknown")
            LOG.info("[%s][tool-output] %s => %s", agent_name, tool_name, short_text(token.content))
            return

        content = getattr(token, "content", None)
        if content and not tool_chunks:
            # 普通文本 token 直接流式打印，同时缓存在内存里，便于最后汇总。
            self.text_buffers.setdefault(agent_name, []).append(content)
            if self.last_token_source != agent_name:
                self._flush_token_line()
                print(f"\n[{agent_name}] ", end="", flush=True)
                self.last_token_source = agent_name
            print(content, end="", flush=True)
            self.token_line_open = True
