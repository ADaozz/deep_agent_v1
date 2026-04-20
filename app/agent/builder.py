from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.backends import DockerWorkspaceBackend
from app.config import Settings
from app.prompts import (
    build_supervisor_system_prompt,
    get_bootstrap_supervisor_prompt,
    get_runtime_worker_planner_prompt,
)
from app.skill_store import (
    build_supervisor_skill_prompt_suffix,
    list_supervisor_skill_headers,
    normalize_supervisor_skill_ids,
)
from app.tool_registry import load_runtime_tool_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT / "workspace"


def _worker_tools(runtime_tools: dict[str, Any]) -> list[Any]:
    return list(runtime_tools.get("custom_worker_tools") or [])


class RuntimeWorkerDef(BaseModel):
    name: str = Field(description="本轮专属 worker 的英文 snake_case 标识。")
    display_name: str = Field(description="本轮专属 worker 的英文显示名。")
    scope: str = Field(default="", description="本轮专属 worker 只负责的对象、维度或边界。")
    role: str = Field(description="本轮专属 worker 的中文职责概括。")
    description: str = Field(description="本轮专属 worker 的中文说明。")
    system_prompt: str = Field(description="本轮专属 worker 的中文系统提示词。")


class RuntimeWorkerPlan(BaseModel):
    delegation_needed: bool = Field(description="当前 query 是否需要为本轮准备专属 worker。")
    complexity: Literal["low", "medium", "high"] = Field(
        default="low",
        description="当前 query 的任务复杂度。",
    )
    reasoning: str = Field(description="为什么需要或不需要为本轮准备专属 worker。")
    planner_error: str = Field(
        default="",
        description="worker planner 的异常明文；正常情况下为空。",
    )
    workers: list[RuntimeWorkerDef] = Field(
        default_factory=list,
        description="当前 query 需要准备的本轮专属 worker 列表。",
    )


class BootstrapTaskProfile(BaseModel):
    objective: str = Field(default="", description="对当前任务目标的简明理解。")
    constraints: list[str] = Field(default_factory=list, description="执行约束。")
    expected_deliverables: list[str] = Field(default_factory=list, description="预期产物。")
    decomposition_axes: list[str] = Field(default_factory=list, description="如果要拆分，最自然的拆分维度。")
    reasoning: str = Field(default="", description="当前任务为什么会落入这类执行路径。")


class BootstrapContextRecord(BaseModel):
    selected_skill_ids: list[str] = Field(default_factory=list, description="bootstrap 阶段命中的 supervisor skill id 列表。")
    selected_skills_reasoning_by_id: dict[str, str] = Field(
        default_factory=dict,
        description="每个命中的 supervisor skill 的命中理由。",
    )
    objective: str = Field(default="", description="对当前任务目标的简明理解。")
    constraints: list[str] = Field(default_factory=list, description="执行约束。")
    expected_deliverables: list[str] = Field(default_factory=list, description="预期产物。")
    decomposition_axes: list[str] = Field(default_factory=list, description="最自然的拆分维度。")
    reasoning: str = Field(default="", description="为什么后续 supervisor 应按此路径推进。")


def _build_subagent_spec(
    *,
    name: str,
    display_name: str,
    description: str,
    role: str,
    system_prompt: str,
    runtime_tools: dict[str, Any],
    scope: str = "",
    tools: list | None = None,
    dynamic: bool = False,
) -> dict[str, Any]:
    middleware_cls = runtime_tools.get("evidence_todo_middleware")
    return {
        "name": name,
        "display_name": display_name,
        "description": description,
        "role": role,
        "scope": scope,
        "system_prompt": system_prompt,
        "tools": tools if tools is not None else _worker_tools(runtime_tools),
        "middleware": [middleware_cls()] if middleware_cls is not None else [],
        "dynamic": dynamic,
    }


def _make_record_bootstrap_context_tool():
    @tool("record_bootstrap_context", args_schema=BootstrapContextRecord)
    def record_bootstrap_context(
        selected_skill_ids: list[str] | None = None,
        selected_skills_reasoning_by_id: dict[str, str] | None = None,
        objective: str = "",
        constraints: list[str] | None = None,
        expected_deliverables: list[str] | None = None,
        decomposition_axes: list[str] | None = None,
        reasoning: str = "",
    ) -> str:
        """记录 bootstrap supervisor 选中的 skills、第一版任务理解和拆分依据。"""
        normalized_selected_skill_ids = normalize_supervisor_skill_ids(selected_skill_ids or [])
        normalized_skill_reasons: dict[str, str] = {}
        for skill_id in normalized_selected_skill_ids:
            reason = str((selected_skills_reasoning_by_id or {}).get(skill_id, "")).strip()
            if reason:
                normalized_skill_reasons[skill_id] = reason
        payload = BootstrapContextRecord(
            selected_skill_ids=normalized_selected_skill_ids,
            selected_skills_reasoning_by_id=normalized_skill_reasons,
            objective=objective.strip(),
            constraints=[str(item).strip() for item in constraints or [] if str(item).strip()],
            expected_deliverables=[str(item).strip() for item in expected_deliverables or [] if str(item).strip()],
            decomposition_axes=[str(item).strip() for item in decomposition_axes or [] if str(item).strip()],
            reasoning=reasoning.strip(),
        )
        return json.dumps(payload.model_dump(), ensure_ascii=False)

    return record_bootstrap_context


def _disabled_fallback_spec(runtime_tools: dict[str, Any]) -> dict[str, Any]:
    return _build_subagent_spec(
        name="general-purpose",
        display_name="Disabled Fallback Agent",
        description="禁用的后备代理。除非用户明确要求，否则 supervisor 不应把任务派发给它。",
        role="后备代理，占位禁用",
        system_prompt=(
            "你是一个被禁用的后备子代理。"
            "在这个 demo 中不应承接任务。"
            "如果被调用，直接简短返回：该任务不应派发给 general-purpose，请改派当前 query 对应的专属 worker。"
        ),
        runtime_tools=runtime_tools,
        tools=[],
    )


def _catalog_item(spec: dict[str, Any]) -> dict[str, str]:
    return {
        "id": spec["name"],
        "name": spec["display_name"],
        "scope": spec.get("scope", ""),
        "role": spec["role"],
        "description": spec["description"],
    }


def get_subagent_specs(runtime_tools: dict[str, Any]) -> list[dict[str, Any]]:
    return [_disabled_fallback_spec(runtime_tools)]


def build_agent(settings: Settings, query: str | None = None):
    runtime_query = (query or settings.prompt).strip()
    agent, _, _ = build_agent_bundle(settings, query=runtime_query)
    return agent


def build_bootstrap_agent(
    settings: Settings,
    query: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    runtime_query = (query or settings.prompt).strip()
    runtime_tools = load_runtime_tool_bundle()
    backend = _make_backend(settings)
    model = _make_model(settings)
    agent_tools: list[Any] = [
        runtime_tools["inspect_supervisor_skills_factory"](),
        _make_record_bootstrap_context_tool(),
    ]
    subagents = [
        {
            "name": spec["name"],
            "description": spec["description"],
            "system_prompt": spec["system_prompt"],
            "tools": spec["tools"],
            "middleware": spec["middleware"],
        }
        for spec in get_subagent_specs(runtime_tools)
    ]
    agent = create_deep_agent(
        model=model,
        tools=agent_tools,
        subagents=subagents,
        system_prompt=get_bootstrap_supervisor_prompt(),
        backend=backend,
        name="bootstrap_supervisor",
        debug=True,
    )
    return agent, {"query": runtime_query}


def build_agent_bundle(
    settings: Settings,
    query: str | None = None,
    bootstrap_meta: dict[str, Any] | None = None,
) -> tuple[Any, list[dict[str, str]], dict[str, Any]]:
    runtime_query = (query or settings.prompt).strip()
    model = _make_model(settings)
    runtime_tools = load_runtime_tool_bundle()
    (
        selected_skill_ids,
        skill_selection_reasoning,
        skill_selection_error,
        selected_skills_reasoning_by_id,
        bootstrap_task_profile,
        bootstrap_task_error,
        bootstrap_todos,
    ) = _resolve_bootstrap_meta(
        bootstrap_meta=bootstrap_meta or {},
    )
    supervisor_skill_context = build_supervisor_skill_prompt_suffix(skill_ids=selected_skill_ids)
    bootstrap_skill_reasoning_context = _render_bootstrap_skill_reasoning_context(selected_skills_reasoning_by_id)
    bootstrap_task_context = _render_bootstrap_task_context(bootstrap_task_profile)
    bootstrap_action_list_context = _render_bootstrap_action_list_context(bootstrap_todos)
    runtime_specs, roster_payload = _build_runtime_subagent_specs(
        model=model,
        query=runtime_query,
        runtime_tools=runtime_tools,
        supervisor_skill_context=supervisor_skill_context,
        bootstrap_skill_reasoning_context=bootstrap_skill_reasoning_context,
        bootstrap_task_context=bootstrap_task_context,
        bootstrap_action_list_context=bootstrap_action_list_context,
    )
    runtime_catalog = roster_payload["workers"]
    system_prompt = build_supervisor_system_prompt(
        max_rounds=12,
        selected_skill_ids=selected_skill_ids,
        bootstrap_skill_reasoning_context=bootstrap_skill_reasoning_context,
        bootstrap_task_context=bootstrap_task_context,
        bootstrap_action_list_context=bootstrap_action_list_context,
    )
    agent_tools: list[Any] = []
    agent_tools.append(runtime_tools["inspect_supervisor_skills_factory"]())
    agent_tools.append(
        runtime_tools["generate_subagents_factory"](
            query=runtime_query,
            reasoning=roster_payload["reasoning"],
            planner_error=roster_payload["planner_error"],
            workers=runtime_catalog,
        )
    )
    agent_tools.append(runtime_tools["publish_workspace_file"])
    agent_tools.extend(runtime_tools.get("custom_supervisor_tools") or [])

    subagents = [
        {
            "name": spec["name"],
            "description": spec["description"],
            "system_prompt": spec["system_prompt"],
            "tools": spec["tools"],
            "middleware": spec["middleware"],
        }
        for spec in runtime_specs
    ]
    backend = _make_backend(settings)
    agent = create_deep_agent(
        model=model,
        tools=agent_tools,
        subagents=subagents,
        system_prompt=system_prompt,
        backend=backend,
        name="supervisor",
        debug=True,
    )
    return agent, runtime_catalog, {
        "selected_skill_ids": selected_skill_ids,
        "selected_skill_headers": [
            header for header in list_supervisor_skill_headers() if header["id"] in set(selected_skill_ids)
        ],
        "selected_skills_reasoning_by_id": selected_skills_reasoning_by_id,
        "skill_selection_reasoning": skill_selection_reasoning,
        "skill_selection_error": skill_selection_error,
        "bootstrap_task_profile": bootstrap_task_profile.model_dump(),
        "bootstrap_task_error": bootstrap_task_error,
        "bootstrap_todos": bootstrap_todos,
    }


def _resolve_bootstrap_meta(
    *,
    bootstrap_meta: dict[str, Any],
) -> tuple[list[str], str, str, dict[str, str], BootstrapTaskProfile, str, list[dict[str, str]]]:
    selected_skill_ids = normalize_supervisor_skill_ids(bootstrap_meta.get("selected_skill_ids") or [])
    skill_selection_reasoning = str(bootstrap_meta.get("skill_selection_reasoning") or "").strip()
    skill_selection_error = str(bootstrap_meta.get("skill_selection_error") or "").strip()
    raw_skill_reasoning = bootstrap_meta.get("selected_skills_reasoning_by_id") or {}
    selected_skills_reasoning_by_id: dict[str, str] = {}
    if isinstance(raw_skill_reasoning, dict):
        for skill_id in selected_skill_ids:
            reason = str(raw_skill_reasoning.get(skill_id, "")).strip()
            if reason:
                selected_skills_reasoning_by_id[skill_id] = reason

    profile_payload = bootstrap_meta.get("bootstrap_task_profile") or {}
    bootstrap_task_profile = BootstrapTaskProfile()
    bootstrap_task_error = str(bootstrap_meta.get("bootstrap_task_error") or "").strip()
    bootstrap_todos = list(bootstrap_meta.get("bootstrap_todos") or [])
    if isinstance(profile_payload, dict) and any(profile_payload.values()):
        try:
            bootstrap_task_profile = BootstrapTaskProfile(**profile_payload)
        except Exception as exc:
            bootstrap_task_error = _format_planner_error(exc)
    return (
        selected_skill_ids,
        skill_selection_reasoning,
        skill_selection_error,
        selected_skills_reasoning_by_id,
        bootstrap_task_profile,
        bootstrap_task_error,
        bootstrap_todos,
    )


def _build_runtime_subagent_specs(
    *,
    model: ChatOpenAI,
    query: str,
    runtime_tools: dict[str, Any],
    supervisor_skill_context: str,
    bootstrap_skill_reasoning_context: str,
    bootstrap_task_context: str,
    bootstrap_action_list_context: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base_specs = get_subagent_specs(runtime_tools)
    runtime_plan = _plan_query_workers(
        model=model,
        query=query,
        supervisor_skill_context=supervisor_skill_context,
        bootstrap_skill_reasoning_context=bootstrap_skill_reasoning_context,
        bootstrap_task_context=bootstrap_task_context,
        bootstrap_action_list_context=bootstrap_action_list_context,
        existing_specs=base_specs,
    )
    runtime_plan = _ensure_non_empty_worker_plan(
        runtime_plan=runtime_plan,
        query=query,
        bootstrap_task_context=bootstrap_task_context,
    )
    auto_worker_specs = _build_auto_worker_specs(
        runtime_plan=runtime_plan,
        existing_specs=base_specs,
        runtime_tools=runtime_tools,
    )
    runtime_specs = [*base_specs, *auto_worker_specs]
    roster_specs = list(auto_worker_specs)
    roster_payload = {
        "delegation_needed": bool(roster_specs),
        "reasoning": _build_roster_reasoning(
            runtime_plan=runtime_plan,
            auto_worker_specs=auto_worker_specs,
        ),
        "planner_error": runtime_plan.planner_error.strip(),
        "workers": [_catalog_item(spec) for spec in roster_specs],
    }
    return runtime_specs, roster_payload


def _plan_query_workers(
    *,
    model: ChatOpenAI,
    query: str,
    supervisor_skill_context: str,
    bootstrap_skill_reasoning_context: str,
    bootstrap_task_context: str,
    bootstrap_action_list_context: str,
    existing_specs: list[dict[str, Any]],
) -> RuntimeWorkerPlan:
    planner = model.with_structured_output(RuntimeWorkerPlan, include_raw=True)
    try:
        result = planner.invoke(
            get_runtime_worker_planner_prompt().format(
                query=query,
                supervisor_skill_context=supervisor_skill_context.strip() or "无",
                bootstrap_skill_reasoning_context=bootstrap_skill_reasoning_context.strip() or "无",
                bootstrap_task_context=bootstrap_task_context.strip() or "无",
                bootstrap_action_list_context=bootstrap_action_list_context.strip() or "无",
            )
        )
    except Exception as exc:
        return RuntimeWorkerPlan(
            delegation_needed=False,
            reasoning="运行时 worker planner 调用失败，回退为不额外生成本轮专属 worker。",
            planner_error=_format_planner_error(exc),
            workers=[],
        )

    if result["parsed"] is not None:
        return result["parsed"]

    recovered = _try_recover_worker_plan(result)
    if recovered is not None:
        return recovered

    return RuntimeWorkerPlan(
        delegation_needed=False,
        reasoning="运行时 worker planner 调用失败，回退为不额外生成本轮专属 worker。",
        planner_error=_format_planner_error(result["parsing_error"]),
        workers=[],
    )


def _render_bootstrap_task_context(profile: BootstrapTaskProfile) -> str:
    chunks: list[str] = []
    if profile.objective.strip():
        chunks.append(f"- 任务目标：{profile.objective.strip()}")
    if profile.constraints:
        chunks.append("- 执行约束：")
        chunks.extend(f"  - {item}" for item in profile.constraints if str(item).strip())
    if profile.expected_deliverables:
        chunks.append("- 预期产物：")
        chunks.extend(f"  - {item}" for item in profile.expected_deliverables if str(item).strip())
    if profile.decomposition_axes:
        chunks.append("- 自然拆分维度：")
        chunks.extend(f"  - {item}" for item in profile.decomposition_axes if str(item).strip())
    if profile.reasoning.strip():
        chunks.append(f"- 执行路径理解：{profile.reasoning.strip()}")
    return "\n".join(chunks).strip()


def _render_bootstrap_skill_reasoning_context(selected_skills_reasoning_by_id: dict[str, str]) -> str:
    chunks: list[str] = []
    for skill_id, reason in selected_skills_reasoning_by_id.items():
        normalized_reason = str(reason).strip()
        if normalized_reason:
            chunks.append(f"- {skill_id}: {normalized_reason}")
    return "\n".join(chunks).strip()


def _render_bootstrap_action_list_context(bootstrap_todos: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for index, todo in enumerate(bootstrap_todos, start=1):
        label = str(todo.get("label", "")).strip()
        if not label:
            continue
        status = _map_bootstrap_todo_status(str(todo.get("status", "pending")).strip())
        chunks.append(f"{index}. [{status}] {label}")
    return "\n".join(chunks).strip()


def _map_bootstrap_todo_status(status: str) -> str:
    normalized = status.lower()
    if normalized in {"completed", "done"}:
        return "done"
    if normalized in {"in_progress", "running"}:
        return "running"
    if normalized == "blocked":
        return "blocked"
    return "pending"


def _try_recover_worker_plan(result: dict[str, Any]) -> RuntimeWorkerPlan | None:
    """Try to recover a RuntimeWorkerPlan when structured output parsing fails.

    Handles the case where the model returns a JSON list of workers directly
    instead of the expected {delegation_needed, reasoning, workers} object.
    """
    try:
        raw = result.get("raw")
        if raw is None:
            return None
        content = getattr(raw, "content", None) or ""
        if not content:
            return None
        data = json.loads(content) if isinstance(content, str) else content

        if isinstance(data, list):
            workers = [_coerce_runtime_worker_def(item) for item in data]
            return RuntimeWorkerPlan(
                delegation_needed=bool(workers),
                complexity="medium" if workers else "low",
                reasoning="worker planner 返回了 worker 列表（已自动恢复）。",
                workers=workers,
            )

        if isinstance(data, dict) and "workers" in data:
            payload = dict(data)
            payload["workers"] = [_coerce_runtime_worker_def(item) for item in payload.get("workers") or []]
            return RuntimeWorkerPlan(**payload)

        return None
    except Exception:
        return None


def _coerce_runtime_worker_def(item: Any) -> RuntimeWorkerDef:
    payload = item.model_dump() if hasattr(item, "model_dump") else dict(item)
    if not str(payload.get("scope", "")).strip():
        payload["scope"] = str(payload.get("role") or payload.get("description") or "").strip()
    return RuntimeWorkerDef(**payload)


def _build_auto_worker_specs(
    *,
    runtime_plan: RuntimeWorkerPlan,
    existing_specs: list[dict[str, Any]],
    runtime_tools: dict[str, Any],
) -> list[dict[str, Any]]:
    if not runtime_plan.delegation_needed:
        return []

    existing_names = {spec["name"] for spec in existing_specs}
    specs: list[dict[str, Any]] = []
    for index, item in enumerate(runtime_plan.workers[:5], start=1):
        normalized_name = _normalize_agent_name(item.name)
        if normalized_name in existing_names:
            continue
        safe_name = _sanitize_agent_name(item.name, existing_names)
        existing_names.add(safe_name)
        display_name = item.display_name.strip() or _fallback_display_name(safe_name, index)
        scope = item.scope.strip()
        role = item.role.strip() or f"负责当前 query 的第 {index} 个独立维度"
        description = item.description.strip() or "用于承接当前 query 的一个专属独立维度任务。"
        system_prompt = item.system_prompt.strip() or _default_worker_system_prompt()
        specs.append(
            _build_subagent_spec(
                name=safe_name,
                display_name=display_name,
                description=description,
                role=role,
                system_prompt=system_prompt,
                runtime_tools=runtime_tools,
                scope=scope,
                dynamic=True,
            )
        )

    return specs


def _build_roster_reasoning(
    *,
    runtime_plan: RuntimeWorkerPlan,
    auto_worker_specs: list[dict[str, Any]],
) -> str:
    base_reasoning = runtime_plan.reasoning.strip()
    if auto_worker_specs:
        return base_reasoning or "当前 query 已生成一组本轮专属 worker。"
    return base_reasoning or "当前 query 已回退为单 worker 执行。"


def _ensure_non_empty_worker_plan(
    *,
    runtime_plan: RuntimeWorkerPlan,
    query: str,
    bootstrap_task_context: str,
) -> RuntimeWorkerPlan:
    if runtime_plan.delegation_needed and runtime_plan.workers:
        return runtime_plan

    fallback_worker = _build_single_worker_def(
        query=query,
        bootstrap_task_context=bootstrap_task_context,
    )
    fallback_reasoning = runtime_plan.reasoning.strip() or "当前配置要求 supervisor 不直接执行叶子任务，已自动回退为单 worker 执行。"
    planner_error = runtime_plan.planner_error.strip()
    if planner_error:
        fallback_reasoning = f"{fallback_reasoning} worker planner 原始异常：{planner_error}"
    return RuntimeWorkerPlan(
        delegation_needed=True,
        complexity=runtime_plan.complexity or "low",
        reasoning=fallback_reasoning,
        planner_error=planner_error,
        workers=[fallback_worker],
    )


def _build_single_worker_def(
    *,
    query: str,
    bootstrap_task_context: str,
) -> RuntimeWorkerDef:
    scope = _extract_single_worker_scope(bootstrap_task_context) or short_text_for_worker_scope(query)
    return RuntimeWorkerDef(
        name=_fallback_single_worker_name(query),
        display_name="Task Worker",
        scope=scope,
        role="负责当前任务的单 worker 执行",
        description="用于承接当前 query 的单一执行分片；当任务没有自然并行拆分时，由它独立完成落地执行。",
        system_prompt=_default_worker_system_prompt(),
    )


def _extract_single_worker_scope(bootstrap_task_context: str) -> str:
    for line in bootstrap_task_context.splitlines():
        normalized = line.strip()
        if normalized.startswith("- 任务目标："):
            return normalized.removeprefix("- 任务目标：").strip()
    return ""


def short_text_for_worker_scope(query: str, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", query.strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _fallback_single_worker_name(query: str) -> str:
    normalized = _normalize_agent_name(query)
    parts = [part for part in normalized.split("_") if part][:4]
    candidate = "_".join(parts) if parts else "task_worker"
    if not candidate or candidate[0].isdigit():
        candidate = f"task_{candidate or 'worker'}"
    return candidate


def _format_planner_error(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return type(exc).__name__


def _sanitize_agent_name(raw_name: str, existing_names: set[str]) -> str:
    base = _normalize_agent_name(raw_name)
    if not base:
        base = "dynamic_worker"
    candidate = base
    suffix = 2
    while candidate in existing_names:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _normalize_agent_name(raw_name: str) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", raw_name.strip().lower())
    return re.sub(r"_+", "_", base).strip("_")


def _fallback_display_name(name: str, index: int) -> str:
    words = [part.capitalize() for part in name.split("_") if part]
    if words:
        return " ".join(words)
    return f"Task Worker {index}"


def _default_worker_system_prompt() -> str:
    chunks = [
        "你是一个由 supervisor 针对当前 query 准备的专属并行 worker。",
    ]
    chunks.extend(
        [
            "收到任务后，必须先调用 write_evidence_todos 创建私有证据型待办列表。",
            "你只负责自己这个维度，不要越界总结全局。",
            "`execute` 只用于本地沙箱中的当前文件根目录命令操作，不能当作 SSH 或远程执行工具。",
            "当前文件系统工具已经把你放在文件根目录中，文件路径只能写 foo.py、subdir/foo.py、report.md 这类相对路径。",
            "不要给路径补任何根目录名、绝对路径前缀或重复目录层级；运行本地脚本时也只能使用 python3 foo.py 或 python3 subdir/foo.py。",
            "如果任务涉及远程主机访问、远程目录检查、远程日志排查或远程服务探测，优先使用 ssh_execute。",
            "所有待办完成并附带 evidence 后，才能向 supervisor 汇报。",
        ]
    )
    return "".join(chunks)


def _make_model(settings: Settings) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=0,
        timeout=settings.model_timeout,
        max_retries=settings.model_max_retries,
    )


def _make_backend(settings: Settings):
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    if settings.backend == "docker":
        return DockerWorkspaceBackend(
            root_dir=WORKSPACE_ROOT,
            container_name=settings.docker_container_name,
            workspace_dir=settings.docker_workspace_dir,
            timeout=settings.docker_timeout,
        )
    return FilesystemBackend(root_dir=WORKSPACE_ROOT, virtual_mode=True)
