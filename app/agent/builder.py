from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.backends import DockerWorkspaceBackend
from app.config import Settings
from app.prompts import (
    build_supervisor_system_prompt,
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


class SupervisorSkillSelection(BaseModel):
    skill_ids: list[str] = Field(
        default_factory=list,
        description="当前 query 命中的 supervisor skill id 列表。",
    )
    reasoning: str = Field(
        default="",
        description="为什么这些 supervisor skill 与当前 query 相关。",
    )


class BootstrapTaskProfile(BaseModel):
    objective: str = Field(default="", description="对当前任务目标的简明理解。")
    constraints: list[str] = Field(default_factory=list, description="执行约束。")
    expected_deliverables: list[str] = Field(default_factory=list, description="预期产物。")
    decomposition_axes: list[str] = Field(default_factory=list, description="如果要拆分，最自然的拆分维度。")
    reasoning: str = Field(default="", description="当前任务为什么会落入这类执行路径。")


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


def build_agent_bundle(
    settings: Settings,
    query: str | None = None,
) -> tuple[Any, list[dict[str, str]], dict[str, Any]]:
    runtime_query = (query or settings.prompt).strip()
    model = _make_model(settings)
    runtime_tools = load_runtime_tool_bundle()
    selected_skill_ids, skill_selection_reasoning, skill_selection_error = _select_supervisor_skill_ids(
        model=model,
        query=runtime_query,
    )
    supervisor_skill_context = build_supervisor_skill_prompt_suffix(skill_ids=selected_skill_ids)
    bootstrap_task_profile, bootstrap_task_error = _build_bootstrap_task_profile(
        model=model,
        query=runtime_query,
        supervisor_skill_context=supervisor_skill_context,
    )
    bootstrap_task_context = _render_bootstrap_task_context(bootstrap_task_profile)
    runtime_specs, roster_payload = _build_runtime_subagent_specs(
        model=model,
        query=runtime_query,
        runtime_tools=runtime_tools,
        supervisor_skill_context=supervisor_skill_context,
        bootstrap_task_context=bootstrap_task_context,
    )
    runtime_catalog = roster_payload["workers"]
    system_prompt = build_supervisor_system_prompt(
        max_rounds=12,
        selected_skill_ids=selected_skill_ids,
        bootstrap_task_context=bootstrap_task_context,
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
        "skill_selection_reasoning": skill_selection_reasoning,
        "skill_selection_error": skill_selection_error,
        "bootstrap_task_profile": bootstrap_task_profile.model_dump(),
        "bootstrap_task_error": bootstrap_task_error,
    }


def _build_runtime_subagent_specs(
    *,
    model: ChatOpenAI,
    query: str,
    runtime_tools: dict[str, Any],
    supervisor_skill_context: str,
    bootstrap_task_context: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base_specs = get_subagent_specs(runtime_tools)
    runtime_plan = _plan_query_workers(
        model=model,
        query=query,
        supervisor_skill_context=supervisor_skill_context,
        bootstrap_task_context=bootstrap_task_context,
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
    bootstrap_task_context: str,
    existing_specs: list[dict[str, Any]],
) -> RuntimeWorkerPlan:
    planner = model.with_structured_output(RuntimeWorkerPlan, include_raw=True)
    try:
        result = planner.invoke(
            get_runtime_worker_planner_prompt().format(
                query=query,
                supervisor_skill_context=supervisor_skill_context.strip() or "无",
                bootstrap_task_context=bootstrap_task_context.strip() or "无",
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


def _select_supervisor_skill_ids(
    *,
    model: ChatOpenAI,
    query: str,
) -> tuple[list[str], str, str]:
    skill_headers = list_supervisor_skill_headers()
    if not skill_headers:
        return [], "", ""

    selector = model.with_structured_output(SupervisorSkillSelection, include_raw=True)
    prompt = _build_supervisor_skill_selector_prompt(query=query, skill_headers=skill_headers)
    try:
        result = selector.invoke(prompt)
    except Exception as exc:
        return [], "", _format_planner_error(exc)

    parsed = result.get("parsed")
    if parsed is not None:
        selected_ids = normalize_supervisor_skill_ids(parsed.skill_ids)
        return selected_ids, parsed.reasoning.strip(), ""

    raw = result.get("raw")
    try:
        content = getattr(raw, "content", None) or ""
        payload = json.loads(content) if isinstance(content, str) else content
        if isinstance(payload, dict):
            selected_ids = normalize_supervisor_skill_ids(payload.get("skill_ids") or [])
            reasoning = str(payload.get("reasoning") or "").strip()
            return selected_ids, reasoning, ""
    except Exception:
        pass

    return [], "", _format_planner_error(result.get("parsing_error") or Exception("skill_selector_parsing_failed"))


def _build_supervisor_skill_selector_prompt(*, query: str, skill_headers: list[dict[str, Any]]) -> str:
    headers_json = json.dumps(skill_headers, ensure_ascii=False, indent=2)
    return (
        "# Supervisor Skill Selector\n\n"
        "你正在做 bootstrap 阶段的 supervisor skill 选择。\n"
        "这一步只允许查看 supervisor skill 的 YAML 头摘要，不允许直接假设 skill 全文内容。\n\n"
        "## 当前用户 query\n"
        f"{query}\n\n"
        "## 可用的 supervisor skill YAML 头摘要\n"
        f"{headers_json}\n\n"
        "## 任务\n"
        "从给定 skill 里挑出真正与当前 query 直接相关的 supervisor skill id。"
        "如果没有命中，就返回空数组。\n\n"
        "## 输出要求\n"
        "你必须返回纯 JSON 对象，且能被 json.loads 直接解析。\n"
        "返回字段：\n"
        '- "skill_ids": list[str]\n'
        '- "reasoning": str\n\n'
        "规则：\n"
        "- 只根据 query 与 YAML 头字段判断，不要臆造 skill 全文。\n"
        "- 允许命中多个 skill，但不要为求稳把所有 skill 都选上。\n"
        "- 如果 query 只是普通本地问题且不需要额外 supervisor 指南，就返回空数组。\n"
    )


def _build_bootstrap_task_profile(
    *,
    model: ChatOpenAI,
    query: str,
    supervisor_skill_context: str,
) -> tuple[BootstrapTaskProfile, str]:
    profiler = model.with_structured_output(BootstrapTaskProfile, include_raw=True)
    prompt = _build_bootstrap_task_profile_prompt(
        query=query,
        supervisor_skill_context=supervisor_skill_context,
    )
    try:
        result = profiler.invoke(prompt)
    except Exception as exc:
        return BootstrapTaskProfile(), _format_planner_error(exc)

    parsed = result.get("parsed")
    if parsed is not None:
        return parsed, ""

    raw = result.get("raw")
    try:
        content = getattr(raw, "content", None) or ""
        payload = json.loads(content) if isinstance(content, str) else content
        if isinstance(payload, dict):
            return BootstrapTaskProfile(**payload), ""
    except Exception:
        pass

    return BootstrapTaskProfile(), _format_planner_error(result.get("parsing_error") or Exception("bootstrap_task_profile_parsing_failed"))


def _build_bootstrap_task_profile_prompt(*, query: str, supervisor_skill_context: str) -> str:
    return (
        "# Bootstrap Task Profiler\n\n"
        "你正在做最终 supervisor 启动前的 bootstrap 阶段任务理解。\n\n"
        "## 当前用户 query\n"
        f"{query}\n\n"
        "## 已命中的 supervisor skills 全文\n"
        f"{supervisor_skill_context.strip() or '无'}\n\n"
        "## 任务\n"
        "基于 query 与已命中的 supervisor skills，总结本轮任务目标、约束、预期产物以及自然拆分维度。"
        "这份结果会同时提供给后续 worker planner 与最终 supervisor。\n\n"
        "## 输出要求\n"
        "你必须返回纯 JSON 对象，且能被 json.loads 直接解析。\n"
        "返回字段：\n"
        '- "objective": str\n'
        '- "constraints": list[str]\n'
        '- "expected_deliverables": list[str]\n'
        '- "decomposition_axes": list[str]\n'
        '- "reasoning": str\n'
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
