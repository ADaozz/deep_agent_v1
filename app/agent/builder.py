from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agent.todo_enforcer import EvidenceTodoMiddleware
from app.backends import DockerWorkspaceBackend
from app.config import Settings
from app.prompts import (
    RUNTIME_WORKER_PLANNER_PROMPT,
    build_supervisor_system_prompt,
)
from app.tools import make_generate_subagents_tool, ssh_execute


_EXTRA_SUBAGENT_DEFS: list[dict[str, str]] = []
PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT / "workspace"


def _worker_tools() -> list[Any]:
    return [ssh_execute]


class RuntimeWorkerDef(BaseModel):
    name: str = Field(description="本轮专属 worker 的英文 snake_case 标识。")
    display_name: str = Field(description="本轮专属 worker 的英文显示名。")
    role: str = Field(description="本轮专属 worker 的中文职责概括。")
    description: str = Field(description="本轮专属 worker 的中文说明。")
    system_prompt: str = Field(description="本轮专属 worker 的中文系统提示词。")


class RuntimeWorkerPlan(BaseModel):
    delegation_needed: bool = Field(description="当前 query 是否需要为本轮准备专属 worker。")
    reasoning: str = Field(description="为什么需要或不需要为本轮准备专属 worker。")
    planner_error: str = Field(
        default="",
        description="worker planner 的异常明文；正常情况下为空。",
    )
    workers: list[RuntimeWorkerDef] = Field(
        default_factory=list,
        description="当前 query 需要准备的本轮专属 worker 列表。",
    )


def _build_subagent_spec(
    *,
    name: str,
    display_name: str,
    description: str,
    role: str,
    system_prompt: str,
    tools: list | None = None,
    dynamic: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "display_name": display_name,
        "description": description,
        "role": role,
        "system_prompt": system_prompt,
        "tools": tools if tools is not None else _worker_tools(),
        "middleware": [EvidenceTodoMiddleware()],
        "dynamic": dynamic,
    }


def _disabled_fallback_spec() -> dict[str, Any]:
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
        tools=[],
    )


def _registered_subagent_specs() -> list[dict[str, Any]]:
    return [
        _build_subagent_spec(
            name=item["name"],
            display_name=item["display_name"],
            description=item["description"],
            role=item["role"],
            system_prompt=item["system_prompt"],
            tools=_worker_tools(),
            dynamic=True,
        )
        for item in _EXTRA_SUBAGENT_DEFS
    ]


def _catalog_item(spec: dict[str, Any]) -> dict[str, str]:
    return {
        "id": spec["name"],
        "name": spec["display_name"],
        "role": spec["role"],
        "description": spec["description"],
    }


def get_subagent_specs() -> list[dict[str, Any]]:
    return [_disabled_fallback_spec(), *_registered_subagent_specs()]


def get_subagent_catalog() -> list[dict[str, str]]:
    return [
        _catalog_item(spec)
        for spec in get_subagent_specs()
        if spec["name"] != "general-purpose"
    ]


def register_subagent(
    *,
    name: str,
    display_name: str,
    role: str,
    description: str,
    system_prompt: str,
) -> dict[str, str]:
    normalized_name = _sanitize_agent_name(name, {spec["name"] for spec in get_subagent_specs()})
    if any(spec["name"] == normalized_name for spec in get_subagent_specs()):
        raise ValueError(f"subagent '{normalized_name}' already exists")

    entry = {
        "name": normalized_name,
        "display_name": display_name.strip() or _fallback_display_name(normalized_name, 1),
        "role": role.strip(),
        "description": description.strip(),
        "system_prompt": system_prompt.strip(),
    }
    _EXTRA_SUBAGENT_DEFS.append(entry)
    return {
        "id": entry["name"],
        "name": entry["display_name"],
        "role": entry["role"],
        "description": entry["description"],
    }


def build_agent(settings: Settings, query: str | None = None):
    runtime_query = (query or settings.prompt).strip()
    agent, _ = build_agent_bundle(settings, query=runtime_query)
    return agent


def build_agent_bundle(
    settings: Settings,
    query: str | None = None,
) -> tuple[Any, list[dict[str, str]]]:
    runtime_query = (query or settings.prompt).strip()
    model = _make_model(settings)
    runtime_specs, roster_payload = _build_runtime_subagent_specs(model=model, query=runtime_query)
    runtime_catalog = roster_payload["workers"]
    system_prompt = build_supervisor_system_prompt(max_rounds=12)
    generate_subagents_tool = make_generate_subagents_tool(
        query=runtime_query,
        reasoning=roster_payload["reasoning"],
        planner_error=roster_payload["planner_error"],
        workers=runtime_catalog,
    )

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
        tools=[generate_subagents_tool],
        subagents=subagents,
        system_prompt=system_prompt,
        backend=backend,
        name="supervisor",
        debug=True,
    )
    return agent, runtime_catalog


def _build_runtime_subagent_specs(
    *,
    model: ChatOpenAI,
    query: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base_specs = get_subagent_specs()
    runtime_plan = _plan_query_workers(model=model, query=query, existing_specs=base_specs)
    auto_worker_specs = _build_auto_worker_specs(
        runtime_plan=runtime_plan,
        existing_specs=base_specs,
    )
    registered_specs = [spec for spec in base_specs if spec["name"] != "general-purpose"]
    runtime_specs = [*base_specs, *auto_worker_specs]
    roster_specs = [*registered_specs, *auto_worker_specs]
    roster_payload = {
        "delegation_needed": bool(roster_specs),
        "reasoning": _build_roster_reasoning(
            runtime_plan=runtime_plan,
            registered_specs=registered_specs,
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
    existing_specs: list[dict[str, Any]],
) -> RuntimeWorkerPlan:
    registered_workers = [
        spec for spec in existing_specs if spec["name"] != "general-purpose"
    ]
    registered_workers_text = "\n".join(
        f"- {spec['name']} / {spec['display_name']}：{spec['role']}。{spec['description']}"
        for spec in registered_workers
    )

    planner = model.with_structured_output(RuntimeWorkerPlan, include_raw=True)
    try:
        result = planner.invoke(
            RUNTIME_WORKER_PLANNER_PROMPT.format(
                registered_workers=registered_workers_text or "- 当前没有长期注册 worker。",
                query=query,
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
            workers = [RuntimeWorkerDef(**item) for item in data]
            return RuntimeWorkerPlan(
                delegation_needed=bool(workers),
                reasoning="worker planner 返回了 worker 列表（已自动恢复）。",
                workers=workers,
            )

        if isinstance(data, dict) and "workers" in data:
            return RuntimeWorkerPlan(**data)

        return None
    except Exception:
        return None


def _build_auto_worker_specs(
    *,
    runtime_plan: RuntimeWorkerPlan,
    existing_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not runtime_plan.delegation_needed:
        return []

    existing_names = {spec["name"] for spec in existing_specs}
    specs: list[dict[str, Any]] = []
    for index, item in enumerate(runtime_plan.workers[:4], start=1):
        safe_name = _sanitize_agent_name(item.name, existing_names)
        existing_names.add(safe_name)
        display_name = item.display_name.strip() or _fallback_display_name(safe_name, index)
        role = item.role.strip() or f"负责当前 query 的第 {index} 个独立维度"
        description = item.description.strip() or "用于承接当前 query 的一个专属独立维度任务。"
        system_prompt = item.system_prompt.strip() or (
            "你是一个由 supervisor 针对当前 query 准备的专属并行 worker。"
            "收到任务后，必须先调用 write_evidence_todos 创建私有证据型待办列表。"
            "你只负责自己这个维度，不要越界总结全局。"
            "`execute` 只用于本地 sandbox / workspace 内的命令操作，不能当作 SSH 或远程执行工具。"
            "如果任务涉及远程主机访问、远程目录检查、远程日志排查或远程服务探测，优先使用 ssh_execute。"
            "所有待办完成并附带 evidence 后，才能向 supervisor 汇报。"
        )
        specs.append(
            _build_subagent_spec(
                name=safe_name,
                display_name=display_name,
                description=description,
                role=role,
                system_prompt=system_prompt,
                dynamic=True,
            )
        )

    return specs


def _build_roster_reasoning(
    *,
    runtime_plan: RuntimeWorkerPlan,
    registered_specs: list[dict[str, Any]],
    auto_worker_specs: list[dict[str, Any]],
) -> str:
    base_reasoning = runtime_plan.reasoning.strip()
    if auto_worker_specs:
        return base_reasoning or "当前 query 已生成一组本轮专属 worker。"
    if registered_specs:
        if base_reasoning:
            return f"{base_reasoning} 当前仍可使用已注册的长期 worker。"
        return "当前没有额外生成本轮专属 worker，但仍可使用已注册的长期 worker。"
    return base_reasoning or "当前 query 不需要额外 worker，可由 supervisor 直接处理。"


def _format_planner_error(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return type(exc).__name__


def _sanitize_agent_name(raw_name: str, existing_names: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", raw_name.strip().lower())
    base = re.sub(r"_+", "_", base).strip("_")
    if not base:
        base = "dynamic_worker"
    candidate = base
    suffix = 2
    while candidate in existing_names:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _fallback_display_name(name: str, index: int) -> str:
    words = [part.capitalize() for part in name.split("_") if part]
    if words:
        return " ".join(words)
    return f"Task Worker {index}"


def _make_model(settings: Settings) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=0,
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
