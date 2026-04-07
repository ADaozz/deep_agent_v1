from __future__ import annotations

import ast
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.agent import build_agent_bundle, get_subagent_catalog
from app.config import Settings
from app.logging_utils import short_text
from langgraph.types import Overwrite


@dataclass
class AgentPanel:
    name: str
    role: str
    description: str = ""
    status: str = "idle"
    current_task_title: str = ""
    report: str = ""
    todo_list: list[dict[str, str]] = field(default_factory=list)
    rounds: int = 0
    pregel_id: str | None = None
    guard_hits: int = 0
    last_guard_message: str = ""


@dataclass
class RoundPanel:
    index: int
    thought: str
    dispatches: list[str] = field(default_factory=list)
    reports: list[str] = field(default_factory=list)
    conclusion: str = ""
    pending_tool_call_ids: set[str] = field(default_factory=set)


class DemoRunCollector:
    def __init__(self, log_file: str, runtime_catalog: list[dict[str, str]] | None = None):
        self.log_file = log_file
        self._file = open(log_file, "a", encoding="utf-8")
        self.main_text: list[str] = []
        self.main_todos: list[dict[str, str]] = []
        self.logs: list[dict[str, str]] = []
        self.rounds: list[RoundPanel] = []
        self.active_round: RoundPanel | None = None
        self.status = "idle"
        self.direct_completion_logged = False
        self.seen_main_task_call_ids: set[str] = set()
        self.source_tool_name: dict[str, str] = {}
        self.tool_call_to_agent: dict[str, str] = {}
        self.pregel_to_agent: dict[str, str] = {}
        catalog = runtime_catalog or get_subagent_catalog()
        self.agents: dict[str, AgentPanel] = {
            item["id"]: AgentPanel(name=item["name"], role=item["role"], description=item["description"])
            for item in catalog
        }

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    def handle(self, chunk: dict[str, Any]) -> None:
        chunk_type = chunk["type"]
        ns = tuple(chunk.get("ns", ()))
        if ns and ns[0].startswith("tools:"):
            self._capture_subagent_binding(ns)
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
            self._handle_messages(source, ns, chunk["data"])
        elif chunk_type == "custom":
            self._push_log(source, f"自定义事件: {short_text(chunk['data'])}")

    def build_payload(
        self,
        query: str,
        max_rounds: int,
        *,
        final: bool = True,
        error: str = "",
    ) -> dict[str, Any]:
        final_summary = "".join(self.main_text).strip()
        if final:
            status = "done" if final_summary and not error else "stopped"
            stop_reason = (
                error
                or (
                    "supervisor执行完成。"
                    if final_summary
                    else "执行未产出最终答复，请检查模型配置或提示词。"
                )
            )
        else:
            status = "running"
            stop_reason = ""

        if self.rounds and self.rounds[-1].conclusion:
            scheduler_thought = self.rounds[-1].conclusion
        elif self.rounds:
            scheduler_thought = self.rounds[-1].thought
        elif final and stop_reason:
            scheduler_thought = stop_reason
        else:
            scheduler_thought = "Supervisor 正在分析 query，准备建立本轮 Action List。"

        if final and status == "done" and self.main_todos and not self.rounds and not self.direct_completion_logged:
            self._push_log("scheduler", "supervisor 直接完成当前任务，未派发子 agent。")
            self.direct_completion_logged = True

        return {
            "query": query,
            "max_rounds": max_rounds,
            "status": status,
            "current_round": len(self.rounds),
            "scheduler_thought": scheduler_thought,
            "stop_reason": stop_reason,
            "final_summary": final_summary or (stop_reason if final else ""),
            "tasks": self._convert_main_todos(status=status),
            "rounds": [self._round_to_dict(round_panel) for round_panel in reversed(self.rounds)],
            "agents": [self._agent_to_dict(agent_id, panel) for agent_id, panel in self.agents.items()],
            "logs": self.logs[:60],
        }

    def _handle_updates(self, source: str, ns: tuple[str, ...], data: dict[str, Any]) -> None:
        for node_name, node_data in data.items():
            if node_data is None:
                continue
            self._capture_guard_messages(ns, node_data)
            self._capture_subagent_todos_from_updates(ns, node_data)
            if not ns:
                self._capture_main_tool_calls(node_data)
            if ns and ns[0].startswith("tools:"):
                self._capture_subagent_binding(ns)
            if node_name == "tools":
                self._capture_tool_results(source, ns, node_data)

    def _handle_messages(self, source: str, ns: tuple[str, ...], payload: tuple[Any, dict[str, Any]]) -> None:
        token, metadata = payload
        agent_name = metadata.get("lc_agent_name") or source

        tool_chunks = getattr(token, "tool_call_chunks", None) or []
        if tool_chunks:
            for tool_chunk in tool_chunks:
                if tool_chunk.get("name"):
                    self.source_tool_name[source] = tool_chunk["name"]
                    self._push_log(agent_name, f"调用工具 {tool_chunk['name']}")

        if getattr(token, "type", None) == "tool":
            tool_name = getattr(token, "name", None) or self.source_tool_name.get(source, "unknown")
            content = getattr(token, "content", "")
            if tool_name == "write_todos":
                todos = _parse_todos_from_tool_output(content)
                if ns and ns[0].startswith("tools:"):
                    agent_id = self.pregel_to_agent.get(ns[0].split(":", 1)[1])
                    if agent_id:
                        self.agents[agent_id].todo_list = todos
                else:
                    self.main_todos = todos
            if tool_name == "write_evidence_todos":
                todos = _parse_evidence_todos_from_tool_output(content)
                if ns and ns[0].startswith("tools:"):
                    agent_id = self.pregel_to_agent.get(ns[0].split(":", 1)[1])
                    if agent_id:
                        self.agents[agent_id].todo_list = todos
            preview_limit = 1200 if tool_name == "inspect_architecture" else 160
            self._push_log(agent_name, f"{tool_name} => {short_text(content, preview_limit)}")
            return

        content = getattr(token, "content", None)
        if content:
            self._capture_guard_text(ns, content)
            if not ns:
                self.main_text.append(content)

    def _capture_main_tool_calls(self, node_data: dict[str, Any]) -> None:
        task_calls: list[dict[str, Any]] = []
        for msg in _extract_messages(node_data):
            for tool_call in getattr(msg, "tool_calls", []):
                if tool_call["name"] == "task" and tool_call.get("id") not in self.seen_main_task_call_ids:
                    task_calls.append(tool_call)

        if not task_calls:
            return

        round_panel = RoundPanel(
            index=len(self.rounds) + 1,
            thought=f"第 {len(self.rounds) + 1} 轮：supervisor 派发真实子任务。",
        )
        for tool_call in task_calls:
            args = tool_call.get("args", {})
            agent_id = args.get("subagent_type", "unknown")
            description = args.get("description", "")
            if agent_id not in self.agents:
                self.agents[agent_id] = AgentPanel(name=agent_id, role="动态发现的子代理", description="运行时发现")
            round_panel.dispatches.append(f"{agent_id} <- {description}")
            round_panel.pending_tool_call_ids.add(tool_call["id"])
            self.seen_main_task_call_ids.add(tool_call["id"])
            self.tool_call_to_agent[tool_call["id"]] = agent_id
            if agent_id in self.agents:
                self.agents[agent_id].status = "pending"
                self.agents[agent_id].current_task_title = description
            self._push_log("scheduler", f"派发给 {agent_id}: {short_text(description, 120)}")

        self.rounds.append(round_panel)
        self.active_round = round_panel

    def _capture_subagent_binding(self, ns: tuple[str, ...]) -> None:
        pregel_id = ns[0].split(":", 1)[1]
        for round_panel in reversed(self.rounds):
            unresolved = [
                tool_call_id
                for tool_call_id in round_panel.pending_tool_call_ids
                if self.tool_call_to_agent.get(tool_call_id) not in self.pregel_to_agent.values()
            ]
            if not unresolved:
                continue
            tool_call_id = unresolved[0]
            agent_id = self.tool_call_to_agent.get(tool_call_id)
            if agent_id and agent_id in self.agents:
                self.pregel_to_agent[pregel_id] = agent_id
                agent = self.agents[agent_id]
                agent.status = "running"
                agent.pregel_id = pregel_id
                self._push_log(agent.name, f"开始执行，pregel={pregel_id}")
            return

    def _capture_tool_results(self, source: str, ns: tuple[str, ...], node_data: dict[str, Any]) -> None:
        for msg in _extract_messages(node_data):
            if getattr(msg, "type", "") != "tool":
                continue

            tool_name = getattr(msg, "name", "unknown")
            if not ns and tool_name == "write_todos":
                self.main_todos = _parse_todos_from_tool_output(getattr(msg, "content", ""))
                self._push_log("scheduler", "supervisor 更新了原子任务列表。")
                continue

            if ns and ns[0].startswith("tools:") and tool_name == "write_todos":
                agent_id = self.pregel_to_agent.get(ns[0].split(":", 1)[1])
                if agent_id and agent_id in self.agents:
                    self.agents[agent_id].todo_list = _parse_todos_from_tool_output(getattr(msg, "content", ""))
                    self._push_log(self.agents[agent_id].name, "更新了私有 to_do_list。")
                continue

            if ns and ns[0].startswith("tools:") and tool_name == "write_evidence_todos":
                agent_id = self.pregel_to_agent.get(ns[0].split(":", 1)[1])
                if agent_id and agent_id in self.agents:
                    self.agents[agent_id].todo_list = _parse_evidence_todos_from_tool_output(
                        getattr(msg, "content", "")
                    )
                    self._push_log(self.agents[agent_id].name, "更新了带证据的私有待办列表。")
                continue

            if not ns and tool_name == "task":
                tool_call_id = getattr(msg, "tool_call_id", "")
                agent_id = self.tool_call_to_agent.get(tool_call_id)
                if agent_id and agent_id not in self.agents:
                    self.agents[agent_id] = AgentPanel(name=agent_id, role="动态发现的子代理", description="运行时发现")
                if agent_id and agent_id in self.agents:
                    agent = self.agents[agent_id]
                    agent.status = "done"
                    agent.report = getattr(msg, "content", "")
                    agent.rounds += 1
                    self._push_log(agent.name, f"回报结果: {short_text(agent.report, 120)}")
                if self.active_round is not None:
                    self.active_round.reports.append(f"{agent_id}: {short_text(getattr(msg, 'content', ''), 160)}")
                    self.active_round.pending_tool_call_ids.discard(tool_call_id)
                    if not self.active_round.pending_tool_call_ids:
                        self.active_round.conclusion = (
                            f"第 {self.active_round.index} 轮完成，"
                            "所有子 agent 已完成私有 todo 并回报 supervisor。"
                        )
                        self._push_log("scheduler", self.active_round.conclusion)

    def _convert_main_todos(self, *, status: str = "") -> list[dict[str, Any]]:
        tasks = []
        for index, todo in enumerate(self.main_todos, start=1):
            round_index = _last_round_for_task(index, self.rounds)
            round_status = _status_from_round_index(round_index, self.rounds)
            todo_status = _map_todo_status(todo.get("status", "pending"))
            if not round_status and status == "done":
                round_status = "done"
            tasks.append(
                {
                    "id": f"task-{index}",
                    "title": todo.get("label", ""),
                    "detail": "来自 supervisor 的 write_todos。",
                    "status": round_status or todo_status,
                    "owner": "",
                    "summary": "",
                    "last_round": round_index,
                }
            )
        return tasks

    def _round_to_dict(self, round_panel: RoundPanel) -> dict[str, Any]:
        return {
            "id": f"round-{round_panel.index}",
            "index": round_panel.index,
            "thought": round_panel.thought,
            "dispatches": round_panel.dispatches,
            "reports": round_panel.reports,
            "conclusion": round_panel.conclusion,
        }

    def _agent_to_dict(self, agent_id: str, panel: AgentPanel) -> dict[str, Any]:
        return {
            "id": agent_id,
            "name": panel.name,
            "role": panel.role,
            "description": panel.description,
            "status": panel.status,
            "current_task_title": panel.current_task_title,
            "report": panel.report,
            "todo_list": panel.todo_list,
            "completed_rounds": panel.rounds,
            "guard_hits": panel.guard_hits,
            "last_guard_message": panel.last_guard_message,
        }

    def _capture_guard_messages(self, ns: tuple[str, ...], node_data: dict[str, Any]) -> None:
        if not ns or not ns[0].startswith("tools:"):
            return
        for msg in _extract_messages(node_data):
            content = getattr(msg, "content", None)
            if content:
                self._capture_guard_text(ns, content)

    def _capture_guard_text(self, ns: tuple[str, ...], content: Any) -> None:
        text = str(content)
        if (
            "Runtime guard:" not in text
            and "运行时守卫：" not in text
        ) or not ns or not ns[0].startswith("tools:"):
            return
        agent_id = self.pregel_to_agent.get(ns[0].split(":", 1)[1])
        if not agent_id or agent_id not in self.agents:
            return
        agent = self.agents[agent_id]
        if agent.last_guard_message == text:
            return
        agent.guard_hits += 1
        agent.last_guard_message = text
        agent.status = "blocked"
        self._push_log(agent.name, f"被运行时守卫拦截: {short_text(text, 140)}")

    def _capture_subagent_todos_from_updates(self, ns: tuple[str, ...], node_data: Any) -> None:
        if not ns or not ns[0].startswith("tools:") or not isinstance(node_data, dict):
            return
        agent_todos = node_data.get("agent_todos")
        if not isinstance(agent_todos, list):
            return
        agent_id = self.pregel_to_agent.get(ns[0].split(":", 1)[1])
        if not agent_id or agent_id not in self.agents:
            return
        self.agents[agent_id].todo_list = _convert_agent_todos(agent_todos)

    def _source(self, ns: tuple[str, ...]) -> str:
        if not ns:
            return "main"
        sub_ns = next((item for item in ns if item.startswith("tools:")), None)
        if sub_ns:
            agent_id = self.pregel_to_agent.get(sub_ns.split(":", 1)[1])
            if agent_id and agent_id in self.agents:
                return self.agents[agent_id].name
        return sub_ns or " > ".join(ns)

    def _push_log(self, source: str, message: str) -> None:
        self.logs.append(
            {
                "time": datetime.now().strftime("%H:%M:%S"),
                "source": source,
                "message": message,
            }
        )
        self.logs = self.logs[-100:]

    def _write_jsonl(self, record: dict[str, Any]) -> None:
        payload = {"ts": datetime.now().isoformat(timespec="seconds"), **record}
        self._file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._file.flush()


def run_demo_session(
    settings: Settings,
    query: str,
    max_rounds: int = 12,
    messages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    os.makedirs(os.path.dirname(settings.log_file) or ".", exist_ok=True)
    agent, runtime_catalog = build_agent_bundle(settings=settings, query=query)
    collector = DemoRunCollector(log_file=settings.log_file, runtime_catalog=runtime_catalog)
    collector.status = "running"
    message_payload = messages or [{"role": "user", "content": query}]
    try:
        for chunk in agent.stream(
            {"messages": message_payload},
            stream_mode=["updates", "messages", "custom"],
            subgraphs=True,
            version="v2",
        ):
            collector.handle(chunk)
            if len(collector.rounds) >= max_rounds:
                break
    finally:
        collector.close()
    return collector.build_payload(query=query, max_rounds=max_rounds)


def run_demo_session_stream(
    settings: Settings,
    query: str,
    max_rounds: int = 12,
    messages: list[dict[str, str]] | None = None,
):
    os.makedirs(os.path.dirname(settings.log_file) or ".", exist_ok=True)
    agent, runtime_catalog = build_agent_bundle(settings=settings, query=query)
    collector = DemoRunCollector(log_file=settings.log_file, runtime_catalog=runtime_catalog)
    collector.status = "running"
    last_signature = ""
    message_payload = messages or [{"role": "user", "content": query}]

    def emit(payload: dict[str, Any], event_type: str) -> dict[str, Any] | None:
        nonlocal last_signature
        signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if event_type == "snapshot" and signature == last_signature:
            return None
        last_signature = signature
        return {"type": event_type, "payload": payload}

    try:
        initial = collector.build_payload(query=query, max_rounds=max_rounds, final=False)
        first_event = emit(initial, "snapshot")
        if first_event:
            yield first_event

        for chunk in agent.stream(
            {"messages": message_payload},
            stream_mode=["updates", "messages", "custom"],
            subgraphs=True,
            version="v2",
        ):
            collector.handle(chunk)
            snapshot = collector.build_payload(query=query, max_rounds=max_rounds, final=False)
            event = emit(snapshot, "snapshot")
            if event:
                yield event
            if len(collector.rounds) >= max_rounds:
                break
    except Exception as exc:  # noqa: BLE001
        error_payload = collector.build_payload(query=query, max_rounds=max_rounds, final=True, error=str(exc))
        yield {"type": "error", "payload": error_payload}
    else:
        final_payload = collector.build_payload(query=query, max_rounds=max_rounds, final=True)
        yield {"type": "done", "payload": final_payload}
    finally:
        collector.close()


def _parse_todos_from_tool_output(content: Any) -> list[dict[str, str]]:
    text = _extract_structured_block(str(content), prefix="Updated todo list to ")
    if not text:
        return []
    try:
        todos = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        try:
            todos = json.loads(text)
        except json.JSONDecodeError:
            return []
    parsed = []
    for index, item in enumerate(todos, start=1):
        parsed.append(
            {
                "id": f"todo-{index}",
                "label": item.get("content", ""),
                "status": _map_todo_status(item.get("status", "pending")),
                "note": "来自真实 write_todos 工具输出。",
                "result": "",
            }
        )
    return parsed


def _parse_evidence_todos_from_tool_output(content: Any) -> list[dict[str, str]]:
    text = _extract_structured_block(str(content))
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            payload = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return []
    if not isinstance(payload, dict):
        return []
    todos = payload.get("agent_todos", [])
    return _convert_agent_todos(todos)


def _convert_agent_todos(todos: list[dict[str, Any]]) -> list[dict[str, str]]:
    parsed = []
    for index, item in enumerate(todos, start=1):
        parsed.append(
            {
                "id": f"evidence-todo-{index}",
                "label": item.get("content", ""),
                "status": _map_todo_status(item.get("status", "pending")),
                "note": f"证据类型: {item.get('evidence_type', 'unknown')}",
                "result": item.get("evidence", ""),
            }
        )
    return parsed


def _map_todo_status(status: str) -> str:
    mapping = {
        "pending": "pending",
        "in_progress": "running",
        "completed": "done",
    }
    return mapping.get(status, "pending")


def _last_round_for_task(index: int, rounds: list[RoundPanel]) -> int:
    for round_panel in reversed(rounds):
        if len(round_panel.dispatches) >= index:
            return round_panel.index
    return 0


def _status_from_round_index(index: int, rounds: list[RoundPanel]) -> str:
    if not index:
        return ""
    for round_panel in rounds:
        if round_panel.index != index:
            continue
        if round_panel.conclusion:
            return "done"
        if round_panel.dispatches:
            return "running"
    return ""


def _extract_structured_block(text: str, prefix: str = "") -> str:
    raw = text.strip()
    if prefix and raw.startswith(prefix):
        raw = raw[len(prefix) :].strip()

    if raw.startswith("```"):
        raw = _strip_code_fence(raw)

    for opener, closer in (("[", "]"), ("{", "}")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if start != -1 and end != -1 and end > start:
            return raw[start : end + 1].strip()

    return raw


def _strip_code_fence(text: str) -> str:
    lines = text.strip().splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return text.strip()


def _extract_messages(node_data: Any) -> list[Any]:
    if not isinstance(node_data, dict):
        return []
    messages = node_data.get("messages", [])
    if isinstance(messages, Overwrite):
        messages = messages.value
    if messages is None:
        return []
    return list(messages)
