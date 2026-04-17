from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from app.agent import build_agent_bundle
from app.config import Settings
from app.logging_utils import short_text
from app.workspace_files import build_workspace_file_card
from langgraph.types import Overwrite

SYSTEM_FAILURE_INDICATORS = (
    "执行环境受限",
    "环境受限",
    "执行环境完全不可用",
    "permission denied",
    "docker api",
    "docker.sock",
    "无法执行 `docker exec`",
    "runtime guard",
    "运行时守卫",
    "traceback",
    "exception",
    "internal error",
    "程序报错",
    "工具执行异常",
    "backend 自检失败",
    "timed out",
    "timeout",
)

BUSINESS_BLOCK_INDICATORS = (
    "不可达",
    "无响应",
    "连接不上",
    "无法连接",
    "拒绝连接",
    "connection refused",
    "no route to host",
    "host is down",
    "network is unreachable",
    "认证失败",
    "authentication failed",
)

PARTIAL_BLOCK_INDICATORS = (
    "未能获取",
    "无法获取",
    "无法执行",
    "无法收集",
    "无法确认",
    "缺少 ping",
    "缺少 netcat",
    "缺少工具",
    "系统中无",
    "无法安装",
)


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
    worker_error: dict[str, str] = field(default_factory=dict)


@dataclass
class PublishedFile:
    id: str
    path: str
    name: str
    title: str
    extension: str
    size: int
    updated_at: str
    mime_type: str
    preview_url: str
    preview_json_url: str
    download_url: str


@dataclass
class RoundPanel:
    index: int
    thought: str
    dispatches: list[str] = field(default_factory=list)
    reports: list[str] = field(default_factory=list)
    conclusion: str = ""
    failed: bool = False
    blocked: bool = False
    pending_tool_call_ids: set[str] = field(default_factory=set)


@dataclass
class TaskBinding:
    task_index: int
    agent_id: str
    round_index: int
    description: str = ""


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
        self.logged_integrity_issues: set[str] = set()
        self.seen_main_task_call_ids: set[str] = set()
        self.source_tool_name: dict[str, str] = {}
        self.tool_call_to_agent: dict[str, str] = {}
        self.pregel_to_agent: dict[str, str] = {}
        self.task_bindings: dict[int, TaskBinding] = {}
        catalog = runtime_catalog or []
        self.runtime_catalog = list(catalog)
        self.runtime_catalog_by_id: dict[str, dict[str, str]] = {item["id"]: item for item in catalog}
        self.generated_runtime_catalog: list[dict[str, str]] = []
        self.roster_generated = False
        self.agents: dict[str, AgentPanel] = {}
        self.files: dict[str, PublishedFile] = {}

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    def log_session_start(self, *, query: str, max_rounds: int, model: str, mode: str) -> None:
        self._write_event(
            "session_started",
            query=query,
            max_rounds=max_rounds,
            model=model,
            mode=mode,
            prepared_workers=[],
        )

    def log_session_finish(self, *, payload: dict[str, Any], event_type: str) -> None:
        self._write_event(
            "session_finished",
            event_type=event_type,
            status=payload.get("status", ""),
            stop_reason=payload.get("stop_reason", ""),
            current_round=payload.get("current_round", 0),
            task_status_counts=_status_counts(payload.get("tasks", [])),
            agent_status_counts=_status_counts(payload.get("agents", [])),
            final_summary_preview=short_text(payload.get("final_summary", ""), 320),
        )

    def handle(self, chunk: dict[str, Any]) -> None:
        chunk_type = chunk["type"]
        ns = tuple(chunk.get("ns", ()))
        if ns and ns[0].startswith("tools:"):
            self._capture_subagent_binding(ns)
        source = self._source(ns)

        if chunk_type == "updates":
            self._handle_updates(source, ns, chunk["data"])
        elif chunk_type == "messages":
            self._handle_messages(source, ns, chunk["data"])
        elif chunk_type == "custom":
            preview = short_text(chunk["data"], 240)
            self._push_log(source, f"自定义事件: {preview}")
            self._write_event("custom_event", source=source, preview=preview)

    def build_payload(
        self,
        query: str,
        max_rounds: int,
        *,
        final: bool = True,
        error: str = "",
    ) -> dict[str, Any]:
        final_summary = "".join(self.main_text).strip()
        self._capture_workspace_files_from_summary(final_summary)
        tasks, task_errors = self._convert_main_todos(final=final)

        if final:
            if error:
                status = "stopped"
                stop_reason = error
            elif task_errors:
                status = "stopped"
                stop_reason = "Supervisor 主任务状态校验失败：" + "；".join(task_errors[:2])
                if len(task_errors) > 2:
                    stop_reason += f" 等 {len(task_errors)} 项。"
            else:
                status = "done" if final_summary else "stopped"
                stop_reason = (
                    "supervisor执行完成。"
                    if final_summary
                    else "执行未产出最终答复，请检查模型配置或提示词。"
                )
        else:
            status = "running"
            stop_reason = ""

        if final and status == "stopped" and stop_reason:
            scheduler_thought = stop_reason
        elif self.rounds and self.rounds[-1].conclusion:
            scheduler_thought = self.rounds[-1].conclusion
        elif self.rounds:
            scheduler_thought = self.rounds[-1].thought
        elif final and stop_reason:
            scheduler_thought = stop_reason
        else:
            scheduler_thought = "Supervisor 正在分析 query，准备建立本轮 Action List。"

        for issue in task_errors:
            if issue not in self.logged_integrity_issues:
                self._push_log("scheduler", f"主任务状态校验失败: {issue}")
                self.logged_integrity_issues.add(issue)

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
            "tasks": tasks,
            "rounds": [self._round_to_dict(round_panel) for round_panel in self.rounds],
            "agents": [self._agent_to_dict(agent_id, panel) for agent_id, panel in self.agents.items()],
            "files": [self._file_to_dict(item) for item in self.files.values()],
            "logs": self.logs[-60:],
        }

    def _handle_updates(self, source: str, ns: tuple[str, ...], data: dict[str, Any]) -> None:
        for node_name, node_data in data.items():
            if node_data is None:
                continue
            if ns and ns[0].startswith("tools:"):
                self._capture_subagent_binding(ns)
            self._capture_guard_messages(ns, node_data)
            self._capture_subagent_todos_from_updates(ns, node_data)
            self._capture_subagent_error_from_updates(ns, node_data)
            if not ns:
                self._capture_main_tool_calls(node_data)
            if node_name == "tools":
                self._capture_tool_results(source, ns, node_data)

    def _handle_messages(self, source: str, ns: tuple[str, ...], payload: tuple[Any, dict[str, Any]]) -> None:
        token, metadata = payload
        agent_name = metadata.get("lc_agent_name") or source
        agent_id = self._agent_id_from_ns(ns)

        tool_chunks = getattr(token, "tool_call_chunks", None) or []
        if tool_chunks:
            for tool_chunk in tool_chunks:
                if tool_chunk.get("name"):
                    self.source_tool_name[source] = tool_chunk["name"]
                    self._push_log(agent_name, f"调用工具 {tool_chunk['name']}")
                    self._write_event(
                        "tool_called",
                        source=agent_name,
                        agent_id=agent_id,
                        tool_name=tool_chunk["name"],
                        args_preview=short_text(tool_chunk.get("args", ""), 200),
                    )

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
            if agent_id and tool_name == "write_file":
                self._capture_written_workspace_file(content, source=agent_name, agent_id=agent_id)
            if tool_name == "publish_workspace_file":
                self._capture_published_file(content)
            self._push_log(agent_name, f"{tool_name} => {short_text(content, 160)}")
            self._write_event(
                "tool_result",
                source=agent_name,
                agent_id=agent_id,
                tool_name=tool_name,
                preview=short_text(content, 280),
            )
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

        if not self.roster_generated:
            self._push_log("scheduler", "supervisor 在未先调用 generate_subagents 的情况下直接派发了 task。")
            self._write_event(
                "dispatch_before_roster",
                source="scheduler",
                dispatch_count=len(task_calls),
            )

        round_panel = RoundPanel(
            index=len(self.rounds) + 1,
            thought=f"第 {len(self.rounds) + 1} 轮：supervisor 派发真实子任务。",
        )
        self._write_event(
            "round_started",
            source="scheduler",
            round_index=round_panel.index,
            thought=round_panel.thought,
            dispatch_count=len(task_calls),
        )
        assigned_task_indexes: set[int] = set()
        for tool_call in task_calls:
            args = tool_call.get("args", {})
            agent_id = args.get("subagent_type", "unknown")
            description = args.get("description", "")
            task_index = _match_main_todo_index(description, self.main_todos, assigned_task_indexes)
            agent = self._ensure_agent_panel(agent_id)
            round_panel.dispatches.append(f"{agent_id} <- {description}")
            round_panel.pending_tool_call_ids.add(tool_call["id"])
            self.seen_main_task_call_ids.add(tool_call["id"])
            self.tool_call_to_agent[tool_call["id"]] = agent_id
            if task_index:
                assigned_task_indexes.add(task_index)
                self.task_bindings[task_index] = TaskBinding(
                    task_index=task_index,
                    agent_id=agent_id,
                    round_index=round_panel.index,
                    description=description,
                )
            agent.status = "pending"
            agent.current_task_title = description
            agent.worker_error = {}
            self._push_log("scheduler", f"派发给 {agent_id}: {short_text(description, 120)}")
            self._write_event(
                "task_dispatched",
                source="scheduler",
                round_index=round_panel.index,
                task_index=task_index,
                agent_id=agent_id,
                agent_name=agent.name,
                agent_role=agent.role,
                description=description,
            )

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
            if agent_id:
                self.pregel_to_agent[pregel_id] = agent_id
                agent = self._ensure_agent_panel(agent_id)
                agent.status = "running"
                agent.pregel_id = pregel_id
                self._push_log(agent.name, f"开始执行，pregel={pregel_id}")
                self._write_event(
                    "agent_started",
                    source=agent.name,
                    agent_id=agent_id,
                    agent_name=agent.name,
                    pregel_id=pregel_id,
                    round_index=self._round_index_for_agent(agent_id),
                    current_task=agent.current_task_title,
                )
            return

    def _capture_tool_results(self, source: str, ns: tuple[str, ...], node_data: dict[str, Any]) -> None:
        for msg in _extract_messages(node_data):
            if getattr(msg, "type", "") != "tool":
                continue

            tool_name = getattr(msg, "name", "unknown")
            if not ns and tool_name == "write_todos":
                self.main_todos = _parse_todos_from_tool_output(getattr(msg, "content", ""))
                self._push_log("scheduler", "supervisor 更新了原子任务列表。")
                self._write_event(
                    "main_todos_updated",
                    source="scheduler",
                    todo_count=len(self.main_todos),
                    todo_status_counts=_status_counts(self.main_todos),
                    todo_titles=[todo.get("label", "") for todo in self.main_todos],
                )
                continue

            if not ns and tool_name == "generate_subagents":
                roster = _parse_subagent_roster_from_tool_output(getattr(msg, "content", ""))
                if roster:
                    self.roster_generated = True
                    self.generated_runtime_catalog = roster["workers"]
                    if roster["planner_error"]:
                        self._push_log("scheduler", f"worker planner 失败: {short_text(roster['planner_error'], 220)}")
                    if roster["workers"]:
                        preview = "、".join(
                            item.get("name", item.get("id", "")) for item in roster["workers"][:4]
                        )
                        self._push_log(
                            "scheduler",
                            f"生成本轮子 agent 名册，共 {len(roster['workers'])} 个：{preview}",
                        )
                    else:
                        self._push_log("scheduler", "generate_subagents 返回空名册，本轮无需派发子 agent。")
                    self._write_event(
                        "subagent_roster_generated",
                        source="scheduler",
                        delegation_needed=roster["delegation_needed"],
                        worker_count=len(roster["workers"]),
                        reasoning=roster["reasoning"],
                        planner_error=roster["planner_error"],
                        workers=roster["workers"],
                        task_breakdown=roster["task_breakdown"],
                    )
                continue

            if ns and ns[0].startswith("tools:") and tool_name == "write_todos":
                agent_id = self.pregel_to_agent.get(ns[0].split(":", 1)[1])
                if agent_id and agent_id in self.agents:
                    self.agents[agent_id].todo_list = _parse_todos_from_tool_output(getattr(msg, "content", ""))
                    self._push_log(self.agents[agent_id].name, "更新了私有 to_do_list。")
                    self._write_event(
                        "agent_todos_updated",
                        source=self.agents[agent_id].name,
                        agent_id=agent_id,
                        round_index=self._round_index_for_agent(agent_id),
                        todo_count=len(self.agents[agent_id].todo_list),
                        todo_status_counts=_status_counts(self.agents[agent_id].todo_list),
                        evidence_mode=False,
                    )
                continue

            if ns and ns[0].startswith("tools:") and tool_name == "write_evidence_todos":
                agent_id = self.pregel_to_agent.get(ns[0].split(":", 1)[1])
                if agent_id and agent_id in self.agents:
                    self.agents[agent_id].todo_list = _parse_evidence_todos_from_tool_output(
                        getattr(msg, "content", "")
                    )
                    self._push_log(self.agents[agent_id].name, "更新了带证据的私有待办列表。")
                    self._write_event(
                        "agent_todos_updated",
                        source=self.agents[agent_id].name,
                        agent_id=agent_id,
                        round_index=self._round_index_for_agent(agent_id),
                        todo_count=len(self.agents[agent_id].todo_list),
                        todo_status_counts=_status_counts(self.agents[agent_id].todo_list),
                        evidence_mode=True,
                    )
                continue

            if not ns and tool_name == "task":
                tool_call_id = getattr(msg, "tool_call_id", "")
                agent_id = self.tool_call_to_agent.get(tool_call_id)
                report_text = getattr(msg, "content", "")
                structured_error = {}
                if agent_id:
                    structured_error = self._ensure_agent_panel(agent_id).worker_error
                failed = bool(structured_error) or _report_indicates_system_failure(report_text)
                blocked = (not failed) and _report_indicates_blocked_result(report_text)
                if agent_id:
                    agent = self._ensure_agent_panel(agent_id)
                    agent.status = "error" if failed else "blocked" if blocked else "done"
                    agent.report = report_text
                    agent.rounds += 1
                    self._push_log(agent.name, f"回报结果: {short_text(agent.report, 120)}")
                    self._write_event(
                        "agent_reported",
                        source=agent.name,
                        agent_id=agent_id,
                        agent_name=agent.name,
                        round_index=self._round_index_for_agent(agent_id),
                        status=agent.status,
                        report_preview=short_text(report_text, 280),
                        worker_error=structured_error,
                    )
                if self.active_round is not None:
                    self.active_round.reports.append(f"{agent_id}: {short_text(report_text, 160)}")
                    self.active_round.failed = self.active_round.failed or failed
                    self.active_round.blocked = self.active_round.blocked or blocked
                    self.active_round.pending_tool_call_ids.discard(tool_call_id)
                    if not self.active_round.pending_tool_call_ids:
                        if self.active_round.failed:
                            self.active_round.conclusion = (
                                f"第 {self.active_round.index} 轮结束，"
                                "至少一个子 agent 返回了错误或受限结果。"
                            )
                        elif self.active_round.blocked:
                            self.active_round.conclusion = (
                                f"第 {self.active_round.index} 轮结束，"
                                "至少一个子 agent 返回了受阻或部分完成结果。"
                            )
                        else:
                            self.active_round.conclusion = (
                                f"第 {self.active_round.index} 轮完成，"
                                "所有子 agent 已完成私有 todo 并回报 supervisor。"
                            )
                        self._push_log("scheduler", self.active_round.conclusion)
                        self._write_event(
                            "round_completed",
                            source="scheduler",
                            round_index=self.active_round.index,
                            status=(
                                "error"
                                if self.active_round.failed
                                else "blocked"
                                if self.active_round.blocked
                                else "done"
                            ),
                            report_count=len(self.active_round.reports),
                            conclusion=self.active_round.conclusion,
                        )

    def _convert_main_todos(self, *, final: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
        tasks: list[dict[str, Any]] = []
        errors: list[str] = []
        for index, todo in enumerate(self.main_todos, start=1):
            title = todo.get("label", "")
            todo_status = _map_todo_status(todo.get("status", "pending"))
            binding = self.task_bindings.get(index)
            bound_agent = self.agents.get(binding.agent_id) if binding else None
            bound_status = _task_status_from_runtime_status(bound_agent.status) if bound_agent else ""
            round_index = binding.round_index if binding else _last_round_for_task(index, self.rounds)
            round_status = _status_from_round_index(round_index, self.rounds)
            task_status = bound_status or round_status or todo_status
            owner = bound_agent.name if bound_agent else ""
            detail = "来自 supervisor 的 write_todos。"

            if not final and not binding and self.rounds:
                task_status = "running"
                owner = "Supervisor"
                detail = "supervisor 正在基于已返回的 worker 结果进行汇总与收口。"

            if final:
                if binding and bound_agent:
                    if bound_status == "done":
                        task_status = "done"
                        if _report_indicates_business_block(bound_agent.report):
                            detail = "对应子任务已完成，但结果表明目标不可达或条件不满足。"
                        else:
                            detail = f"对应子任务已由 {bound_agent.name} 完成并回报 supervisor。"
                    elif bound_status == "error":
                        task_status = "error"
                        detail = "对应子任务执行报错。"
                        errors.append(f"{title or f'任务 {index}'}: 对应子任务执行报错")
                    elif bound_status == "blocked":
                        task_status = "blocked"
                        detail = "对应子任务返回了受阻或部分完成结果。"
                    else:
                        task_status = "error"
                        detail = "执行结束时，对应子任务仍未完成。"
                        errors.append(f"{title or f'任务 {index}'}: 对应子任务未完成")
                elif round_status == "done":
                    task_status = "done"
                elif round_status == "blocked":
                    task_status = "blocked"
                    detail = "对应子任务返回了受阻或部分完成结果。"
                elif round_status == "error":
                    task_status = "error"
                    detail = "对应子任务执行失败或受限。"
                    errors.append(f"{title or f'任务 {index}'}: 对应子任务执行失败或受限")
                elif round_status == "running":
                    task_status = "error"
                    detail = "执行结束时，对应子任务轮次仍未完成。"
                    errors.append(f"{title or f'任务 {index}'}: 对应子任务轮次未完成")
                elif _has_prior_blocking_result(index, self.task_bindings, self.agents):
                    task_status = "blocked"
                    detail = "前置子任务已给出否定结果，本任务未继续执行。"
                elif todo_status == "done":
                    task_status = "done"
                    owner = owner or "Supervisor"
                    detail = "该主任务已由 supervisor 收口完成。"
                else:
                    task_status = "error"
                    detail = "执行结束时该主任务仍未完成。"
                    errors.append(
                        f"{title or f'任务 {index}'}: 执行结束时状态仍为 {todo.get('status', 'pending')}"
                    )

            tasks.append(
                {
                    "id": f"task-{index}",
                    "title": title,
                    "detail": detail,
                    "status": task_status,
                    "owner": owner,
                    "summary": "",
                    "last_round": round_index,
                }
            )
        return tasks, errors

    def _round_to_dict(self, round_panel: RoundPanel) -> dict[str, Any]:
        return {
            "id": f"round-{round_panel.index}",
            "index": round_panel.index,
            "thought": round_panel.thought,
            "dispatches": round_panel.dispatches,
            "reports": round_panel.reports,
            "conclusion": round_panel.conclusion,
            "status": (
                "error"
                if round_panel.failed
                else "blocked"
                if round_panel.blocked
                else ("done" if round_panel.conclusion else "running")
            ),
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
            "worker_error": panel.worker_error,
        }

    def _file_to_dict(self, file: PublishedFile) -> dict[str, Any]:
        return {
            "id": file.id,
            "path": file.path,
            "name": file.name,
            "title": file.title,
            "extension": file.extension,
            "size": file.size,
            "updated_at": file.updated_at,
            "mime_type": file.mime_type,
            "preview_url": file.preview_url,
            "preview_json_url": file.preview_json_url,
            "download_url": file.download_url,
        }

    def _capture_published_file(self, content: Any) -> None:
        payload = _parse_published_file_from_tool_output(content)
        if not payload:
            return
        published = PublishedFile(
            id=payload["id"],
            path=payload["path"],
            name=payload["name"],
            title=payload["title"],
            extension=payload["extension"],
            size=payload["size"],
            updated_at=payload["updated_at"],
            mime_type=payload["mime_type"],
            preview_url=payload["preview_url"],
            preview_json_url=payload["preview_json_url"],
            download_url=payload["download_url"],
        )
        self.files[published.path] = published
        self._push_log("scheduler", f"发布文件产物: {published.path}")
        self._write_event(
            "workspace_file_published",
            source="scheduler",
            path=published.path,
            title=published.title,
            mime_type=published.mime_type,
            size=published.size,
        )

    def _capture_workspace_files_from_summary(self, final_summary: str) -> None:
        if not final_summary:
            return
        for relative_path in _extract_workspace_paths(final_summary):
            if relative_path in self.files:
                continue
            try:
                payload = build_workspace_file_card(relative_path)
            except Exception:
                continue
            published = PublishedFile(
                id=payload["id"],
                path=payload["path"],
                name=payload["name"],
                title=payload["title"],
                extension=payload["extension"],
                size=payload["size"],
                updated_at=payload["updated_at"],
                mime_type=payload["mime_type"],
                preview_url=payload["preview_url"],
                preview_json_url=payload["preview_json_url"],
                download_url=payload["download_url"],
            )
            self.files[published.path] = published
            self._push_log("scheduler", f"根据最终答复自动补发布文件产物: {published.path}")

    def _capture_written_workspace_file(self, content: Any, *, source: str, agent_id: str) -> None:
        relative_path = _parse_written_workspace_file_path(content)
        if not relative_path or relative_path in self.files:
            return
        try:
            payload = build_workspace_file_card(relative_path)
        except Exception:
            return
        published = PublishedFile(
            id=payload["id"],
            path=payload["path"],
            name=payload["name"],
            title=payload["title"],
            extension=payload["extension"],
            size=payload["size"],
            updated_at=payload["updated_at"],
            mime_type=payload["mime_type"],
            preview_url=payload["preview_url"],
            preview_json_url=payload["preview_json_url"],
            download_url=payload["download_url"],
        )
        self.files[published.path] = published
        self._push_log(source, f"检测到 worker 生成文件产物: {published.path}")
        self._write_event(
            "workspace_file_detected",
            source=source,
            agent_id=agent_id,
            path=published.path,
            title=published.title,
            mime_type=published.mime_type,
            size=published.size,
        )

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
        if not agent_id:
            return
        agent = self._ensure_agent_panel(agent_id)
        if agent.last_guard_message == text:
            return
        agent.guard_hits += 1
        agent.last_guard_message = text
        agent.status = "blocked"
        self._push_log(agent.name, f"被运行时守卫拦截: {short_text(text, 140)}")
        self._write_event(
            "agent_guard_blocked",
            source=agent.name,
            agent_id=agent_id,
            guard_hits=agent.guard_hits,
            message=short_text(text, 240),
        )

    def _capture_subagent_todos_from_updates(self, ns: tuple[str, ...], node_data: Any) -> None:
        if not ns or not ns[0].startswith("tools:") or not isinstance(node_data, dict):
            return
        agent_todos = node_data.get("agent_todos")
        if not isinstance(agent_todos, list):
            return
        agent_id = self.pregel_to_agent.get(ns[0].split(":", 1)[1])
        if not agent_id:
            return
        self._ensure_agent_panel(agent_id).todo_list = _convert_agent_todos(agent_todos)

    def _capture_subagent_error_from_updates(self, ns: tuple[str, ...], node_data: Any) -> None:
        if not ns or not ns[0].startswith("tools:") or not isinstance(node_data, dict):
            return
        worker_error = node_data.get("worker_error")
        if not isinstance(worker_error, dict):
            return
        agent_id = self.pregel_to_agent.get(ns[0].split(":", 1)[1])
        if not agent_id:
            return
        normalized = {
            "phase": str(worker_error.get("phase", "")).strip(),
            "source": str(worker_error.get("source", "")).strip(),
            "error_type": str(worker_error.get("error_type", "")).strip(),
            "message": str(worker_error.get("message", "")).strip(),
        }
        agent = self._ensure_agent_panel(agent_id)
        if agent.worker_error == normalized:
            return
        agent.worker_error = normalized
        agent.status = "error"
        detail = normalized.get("message") or normalized.get("error_type") or "未知异常"
        self._push_log(agent.name, f"捕获到 worker 运行异常: {short_text(detail, 160)}")
        self._write_event(
            "agent_runtime_error",
            source=agent.name,
            agent_id=agent_id,
            round_index=self._round_index_for_agent(agent_id),
            worker_error=normalized,
        )

    def _ensure_agent_panel(self, agent_id: str) -> AgentPanel:
        panel = self.agents.get(agent_id)
        if panel is not None:
            return panel

        catalog_item = self.runtime_catalog_by_id.get(agent_id)
        if catalog_item:
            panel = AgentPanel(
                name=catalog_item["name"],
                role=catalog_item["role"],
                description=catalog_item["description"],
            )
            self._push_log("scheduler", f"创建子 agent: {catalog_item['name']} ({agent_id})")
            self._write_event(
                "agent_created",
                source="scheduler",
                agent_id=agent_id,
                agent_name=catalog_item["name"],
                agent_role=catalog_item["role"],
                description=catalog_item["description"],
            )
        else:
            panel = AgentPanel(name=agent_id, role="动态发现的子代理", description="运行时发现")
            self._push_log("scheduler", f"发现未注册子 agent: {agent_id}")
            self._write_event(
                "agent_discovered",
                source="scheduler",
                agent_id=agent_id,
                agent_name=agent_id,
                agent_role=panel.role,
                description=panel.description,
            )

        self.agents[agent_id] = panel
        return panel

    def _agent_id_from_ns(self, ns: tuple[str, ...]) -> str:
        if not ns:
            return ""
        sub_ns = next((item for item in ns if item.startswith("tools:")), None)
        if not sub_ns:
            return ""
        return self.pregel_to_agent.get(sub_ns.split(":", 1)[1], "")

    def _round_index_for_agent(self, agent_id: str) -> int:
        for binding in self.task_bindings.values():
            if binding.agent_id == agent_id:
                return binding.round_index
        return 0

    def _write_event(self, event: str, **fields: Any) -> None:
        self._write_jsonl({"kind": "event", "event": event, **fields})

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
    user_files: list[dict[str, Any]] | None = None,
    agent_query: str | None = None,
) -> dict[str, Any]:
    os.makedirs(os.path.dirname(settings.log_file) or ".", exist_ok=True)
    effective_query = (agent_query or query).strip()
    agent, runtime_catalog, _bootstrap_meta = build_agent_bundle(settings=settings, query=effective_query)
    collector = DemoRunCollector(log_file=settings.log_file, runtime_catalog=runtime_catalog)
    collector.status = "running"
    collector.log_session_start(query=query, max_rounds=max_rounds, model=settings.model, mode="sync")
    message_payload = messages or [{"role": "user", "content": effective_query}]
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
        payload = collector.build_payload(query=query, max_rounds=max_rounds)
        payload["user_files"] = _sanitize_user_files_payload(user_files)
        collector.log_session_finish(payload=payload, event_type="done")
        return payload
    finally:
        collector.close()


def run_demo_session_stream(
    settings: Settings,
    query: str,
    max_rounds: int = 12,
    messages: list[dict[str, str]] | None = None,
    user_files: list[dict[str, Any]] | None = None,
    agent_query: str | None = None,
):
    os.makedirs(os.path.dirname(settings.log_file) or ".", exist_ok=True)
    collector = DemoRunCollector(log_file=settings.log_file, runtime_catalog=[])
    collector.status = "running"
    collector.log_session_start(query=query, max_rounds=max_rounds, model=settings.model, mode="stream")
    collector._push_log("scheduler", "正在准备执行环境，构建 supervisor、worker 名册与运行时工具。")
    last_signature = ""
    effective_query = (agent_query or query).strip()
    message_payload = messages or [{"role": "user", "content": effective_query}]
    normalized_user_files = _sanitize_user_files_payload(user_files)

    def emit(payload: dict[str, Any], event_type: str) -> dict[str, Any] | None:
        nonlocal last_signature
        payload = {**payload, "user_files": normalized_user_files}
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

        bootstrap_logs = [
            "正在加载配置、提示词与会话上下文。",
            "正在披露 supervisor skill YAML 头并选择命中 skill。",
            "正在基于命中的 supervisor skill 准备运行时 worker 名册与调度规则。",
            "正在构建 supervisor、工具链与执行后端。",
        ]
        for message in bootstrap_logs:
            collector._push_log("scheduler", message)
            bootstrap_payload = collector.build_payload(query=query, max_rounds=max_rounds, final=False)
            bootstrap_event = emit(bootstrap_payload, "snapshot")
            if bootstrap_event:
                yield bootstrap_event

        agent, runtime_catalog, bootstrap_meta = build_agent_bundle(settings=settings, query=effective_query)
        collector.runtime_catalog = list(runtime_catalog)
        collector.runtime_catalog_by_id = {item["id"]: item for item in runtime_catalog}
        selected_skill_ids = bootstrap_meta.get("selected_skill_ids") or []
        if selected_skill_ids:
            collector._push_log(
                "scheduler",
                f"bootstrap 阶段已命中 supervisor skills: {', '.join(selected_skill_ids)}",
            )
        elif bootstrap_meta.get("skill_selection_error"):
            collector._push_log(
                "scheduler",
                f"bootstrap supervisor skill 选择失败，回退为空: {short_text(str(bootstrap_meta['skill_selection_error']), 180)}",
            )
        else:
            collector._push_log("scheduler", "bootstrap 阶段未命中额外 supervisor skill。")
        if bootstrap_meta.get("bootstrap_task_error"):
            collector._push_log(
                "scheduler",
                f"bootstrap 任务理解失败，回退为空: {short_text(str(bootstrap_meta['bootstrap_task_error']), 180)}",
            )
        elif (bootstrap_meta.get("bootstrap_task_profile") or {}).get("objective"):
            collector._push_log(
                "scheduler",
                f"bootstrap 任务理解完成: {short_text(str(bootstrap_meta['bootstrap_task_profile']['objective']), 120)}",
            )
        collector._push_log("scheduler", "执行环境准备完成，开始进入 agent 流式执行阶段。")

        prepared = collector.build_payload(query=query, max_rounds=max_rounds, final=False)
        prepared_event = emit(prepared, "snapshot")
        if prepared_event:
            yield prepared_event

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
        fallback_summary = _build_fallback_summary_from_worker_reports(collector, exc)
        if fallback_summary:
            collector.main_text = [fallback_summary]
            collector._push_log("scheduler", "模型连接在最终收敛阶段中断，已基于已完成 worker report 生成降级汇总。")
            fallback_payload = collector.build_payload(query=query, max_rounds=max_rounds, final=True)
            fallback_payload = {
                **fallback_payload,
                "status": "done",
                "stop_reason": "模型连接在最终收敛阶段中断，已基于已完成 worker report 生成降级汇总。",
                "final_summary": fallback_summary,
            }
            collector.log_session_finish(payload=fallback_payload, event_type="done")
            yield {"type": "done", "payload": fallback_payload}
            return
        error_payload = collector.build_payload(query=query, max_rounds=max_rounds, final=True, error=str(exc))
        collector.log_session_finish(payload=error_payload, event_type="error")
        yield {"type": "error", "payload": error_payload}
    else:
        final_payload = collector.build_payload(query=query, max_rounds=max_rounds, final=True)
        collector.log_session_finish(payload=final_payload, event_type="done")
        yield {"type": "done", "payload": final_payload}
    finally:
        collector.close()


def _build_fallback_summary_from_worker_reports(collector: DemoRunCollector, exc: Exception) -> str:
    if not _is_connection_error(exc):
        return ""

    completed_agents = [
        (agent_id, panel)
        for agent_id, panel in collector.agents.items()
        if panel.status == "done" and panel.report.strip()
    ]
    if not completed_agents:
        return ""

    chunks = [
        "模型连接在最终收敛阶段中断，以下为已完成 worker 的降级汇总。",
        "",
        "说明：本结果未经过 supervisor 的最终综合推理，只汇总已经完成并回报的 worker 结果，避免重复派发任务或重复调用外部工具。",
        "",
        "## Worker 结果",
    ]
    for _agent_id, panel in completed_agents:
        chunks.extend(
            [
                "",
                f"### {panel.name}",
                "",
                f"- 职责：{panel.role or '未定义'}",
                f"- 状态：{_status_label(panel.status)}",
                f"- 当前任务：{panel.current_task_title or '未记录'}",
                "",
                panel.report.strip(),
            ]
        )

    if collector.rounds and collector.rounds[-1].conclusion:
        chunks.extend(["", "## 已完成轮次", "", collector.rounds[-1].conclusion])

    chunks.extend(
        [
            "",
            "## 降级原因",
            "",
            f"最终汇总阶段连接中断：{str(exc).strip() or type(exc).__name__}",
        ]
    )
    return "\n".join(chunks).strip()


def _is_connection_error(exc: Exception) -> bool:
    message = str(exc).strip().lower()
    exc_name = type(exc).__name__.lower()
    markers = (
        "connection error",
        "connectionerror",
        "apiconnectionerror",
        "remoteprotocolerror",
        "readtimeout",
        "read timeout",
        "connection reset",
        "connection aborted",
        "server disconnected",
        "peer closed connection",
    )
    return any(marker in message or marker in exc_name for marker in markers)


def _status_label(status: str) -> str:
    if status == "done":
        return "已完成"
    if status == "blocked":
        return "已阻塞"
    if status == "error":
        return "失败"
    if status == "running":
        return "进行中"
    return status or "未知"


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


def _parse_subagent_roster_from_tool_output(content: Any) -> dict[str, Any] | None:
    text = _extract_structured_block(str(content))
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            payload = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return None
    if not isinstance(payload, dict):
        return None
    workers = payload.get("workers", [])
    if not isinstance(workers, list):
        workers = []
    parsed_workers: list[dict[str, str]] = []
    for item in workers:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id", "")).strip()
        if not agent_id:
            continue
        parsed_workers.append(
            {
                "id": agent_id,
                "name": str(item.get("name", "")).strip() or agent_id,
                "role": str(item.get("role", "")).strip(),
                "description": str(item.get("description", "")).strip(),
            }
        )
    return {
        "delegation_needed": bool(payload.get("delegation_needed", parsed_workers)),
        "reasoning": str(payload.get("reasoning", "")).strip(),
        "planner_error": str(payload.get("planner_error", "")).strip(),
        "task_breakdown": str(payload.get("task_breakdown", "")).strip(),
        "workers": parsed_workers,
    }


def _parse_published_file_from_tool_output(content: Any) -> dict[str, Any] | None:
    text = _extract_structured_block(str(content))
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            payload = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return None
    if not isinstance(payload, dict) or not payload.get("ok"):
        return None
    file_payload = payload.get("file")
    if not isinstance(file_payload, dict):
        return None
    required_fields = (
        "id",
        "path",
        "name",
        "title",
        "extension",
        "size",
        "updated_at",
        "mime_type",
        "preview_url",
        "preview_json_url",
        "download_url",
    )
    if any(field not in file_payload for field in required_fields):
        return None
    return {
        "id": str(file_payload["id"]),
        "path": str(file_payload["path"]),
        "name": str(file_payload["name"]),
        "title": str(file_payload["title"]),
        "extension": str(file_payload["extension"]),
        "size": int(file_payload["size"]),
        "updated_at": str(file_payload["updated_at"]),
        "mime_type": str(file_payload["mime_type"]),
        "preview_url": str(file_payload["preview_url"]),
        "preview_json_url": str(file_payload["preview_json_url"]),
        "download_url": str(file_payload["download_url"]),
    }


def _sanitize_user_files_payload(user_files: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not user_files:
        return []
    normalized: list[dict[str, Any]] = []
    for item in user_files:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "id": str(item.get("id", "")),
                "path": str(item.get("path", "")),
                "name": str(item.get("name", "")),
                "title": str(item.get("title", "")),
                "extension": str(item.get("extension", "")),
                "size": int(item.get("size", 0) or 0),
                "updated_at": str(item.get("updated_at", "")),
                "mime_type": str(item.get("mime_type", "")),
                "preview_url": str(item.get("preview_url", "")),
                "preview_json_url": str(item.get("preview_json_url", "")),
                "download_url": str(item.get("download_url", "")),
                "original_name": str(item.get("original_name", item.get("name", ""))),
                "source": "user_upload",
            }
        )
    return normalized


def _extract_workspace_paths(text: str) -> list[str]:
    matches = re.findall(r"(?:^|[\s`\"'（(])(?:/workspace/|workspace/)([^\s`\"'）)]+)", text)
    normalized: list[str] = []
    seen: set[str] = set()
    for item in matches:
        path = item.strip().lstrip("/")
        if not path or path in seen:
            continue
        seen.add(path)
        normalized.append(path)
    return normalized


def _parse_written_workspace_file_path(content: Any) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    match = re.search(
        r"(?:Updated|Created|Wrote)\s+file\s+[`\"']?(?P<path>/?(?:workspace/)?[^\s`\"']+)[`\"']?",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    path = match.group("path").strip()
    if path.startswith("/workspace/"):
        path = path[len("/workspace/") :]
    elif path.startswith("workspace/"):
        path = path[len("workspace/") :]
    else:
        path = path.lstrip("/")
    return path


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
        "done": "done",
        "blocked": "blocked",
        "skipped": "blocked",
        "error": "error",
        "failed": "error",
    }
    return mapping.get(status, "pending")


def _status_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status", "unknown") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _task_status_from_runtime_status(status: str) -> str:
    if status in {"done", "completed", "success"}:
        return "done"
    if status in {"error", "failed"}:
        return "error"
    if status == "blocked":
        return "blocked"
    if status in {"running", "in_progress"}:
        return "running"
    if status == "pending":
        return "pending"
    return ""


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
        if round_panel.failed:
            return "error"
        if round_panel.blocked:
            return "blocked"
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

    if raw.startswith("{"):
        end = raw.rfind("}")
        if end != -1:
            return raw[: end + 1].strip()

    if raw.startswith("["):
        end = raw.rfind("]")
        if end != -1:
            return raw[: end + 1].strip()

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


def _report_indicates_system_failure(text: str) -> bool:
    lowered = text.lower()

    # --- 强信号：无论出现在哪里都视为系统故障 ---
    strong_indicators = (
        "执行环境受限",
        "环境受限",
        "执行环境完全不可用",
        "docker api",
        "docker.sock",
        "无法执行 `docker exec`",
        "backend 自检失败",
        "工具执行异常",
    )
    if any(indicator in lowered for indicator in strong_indicators):
        return True

    # --- 弱信号：只检查报告前 400 字符（agent 自述区域） ---
    # 避免业务日志中引用的 exception/timeout/permission denied 导致误判
    preamble = lowered[:400]
    preamble_indicators = (
        "permission denied",
        "runtime guard",
        "运行时守卫",
        "traceback",
        "internal error",
        "程序报错",
        "timed out",
        "timeout",
    )
    if any(indicator in preamble for indicator in preamble_indicators):
        return True

    # "exception" 单独出现在报告正文中太容易误判（业务日志常有 XxxException）
    # 仅当前 400 字符中出现且伴随 agent 自身执行失败相关词语时才判断
    if "exception" in preamble:
        failure_context = ("执行失败", "调用失败", "工具报错", "agent 报错", "运行失败")
        if any(ctx in preamble for ctx in failure_context):
            return True

    return False


def _report_indicates_business_block(text: str) -> bool:
    lowered = text.lower()
    if _report_indicates_system_failure(lowered):
        return False
    preamble = lowered[:400]
    return any(indicator in preamble for indicator in BUSINESS_BLOCK_INDICATORS)

def _report_indicates_blocked_result(text: str) -> bool:
    lowered = text.lower()
    if _report_indicates_system_failure(lowered):
        return False
    if _report_indicates_business_block(lowered):
        return True
    preamble = lowered[:400]
    return any(indicator in preamble for indicator in PARTIAL_BLOCK_INDICATORS)


def _has_prior_blocking_result(
    task_index: int,
    task_bindings: dict[int, TaskBinding],
    agents: dict[str, AgentPanel],
) -> bool:
    for prior_index in range(1, task_index):
        binding = task_bindings.get(prior_index)
        if not binding:
            continue
        agent = agents.get(binding.agent_id)
        if not agent or _task_status_from_runtime_status(agent.status) not in {"done", "blocked"}:
            continue
        if _report_indicates_business_block(agent.report):
            return True
    return False


def _match_main_todo_index(
    description: str,
    todos: list[dict[str, str]],
    assigned_indexes: set[int],
) -> int:
    best_index = 0
    best_score = 0.0
    for index, todo in enumerate(todos, start=1):
        if index in assigned_indexes:
            continue
        title = todo.get("label", "")
        score = _task_match_score(title, description)
        if score > best_score:
            best_score = score
            best_index = index
    if best_index:
        return best_index
    remaining = [index for index in range(1, len(todos) + 1) if index not in assigned_indexes]
    return remaining[0] if len(remaining) == 1 else 0


def _task_match_score(title: str, description: str) -> float:
    if not title or not description:
        return 0.0
    normalized_title = _normalize_match_text(title)
    normalized_description = _normalize_match_text(description)
    ratio = SequenceMatcher(None, normalized_title, normalized_description).ratio()
    title_terms = set(_extract_match_terms(title))
    description_terms = set(_extract_match_terms(description))
    overlap = len(title_terms & description_terms)
    shared_ips = len(set(_extract_ips(title)) & set(_extract_ips(description)))
    return ratio + overlap * 0.18 + shared_ips * 0.35


def _normalize_match_text(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"[\s:：,，。；、()（）\\[\\]{}<>《》'\"`]+", "", lowered)
    for filler in ("执行", "进行", "通过", "使用", "确认", "返回", "分析", "获取", "查看"):
        lowered = lowered.replace(filler, "")
    return lowered


def _extract_match_terms(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"\d{1,3}(?:\.\d{1,3}){3}|[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", text.lower())
        if token not in {"当前", "目标", "执行", "通过", "使用", "包括", "返回", "以及"}
    ]


def _extract_ips(text: str) -> list[str]:
    return re.findall(r"(?<!\d)\d{1,3}(?:\.\d{1,3}){3}(?!\d)", text)
