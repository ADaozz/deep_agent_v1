from __future__ import annotations

import re
from typing import Any

from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agent.todo_enforcer import EvidenceTodoMiddleware
from app.config import Settings
from app.prompts import (
    DEFAULT_WORKER_DESCRIPTION,
    DEFAULT_WORKER_SYSTEM_PROMPT,
    DYNAMIC_SUBAGENT_PLANNER_PROMPT,
    build_supervisor_system_prompt,
)
from app.tools import inspect_architecture, query_internal_kb


_EXTRA_SUBAGENT_DEFS: list[dict[str, str]] = []


class DynamicSubagentDef(BaseModel):
    name: str = Field(description="动态 worker 的英文 snake_case 标识。")
    display_name: str = Field(description="动态 worker 的英文显示名。")
    role: str = Field(description="动态 worker 的中文职责概括。")
    description: str = Field(description="动态 worker 的中文说明。")
    system_prompt: str = Field(description="动态 worker 的中文系统提示词。")


class DynamicSubagentPlan(BaseModel):
    spawn_needed: bool = Field(description="是否需要在默认 worker 之外新增动态 worker。")
    reasoning: str = Field(description="为什么需要或不需要新增动态 worker。")
    subagents: list[DynamicSubagentDef] = Field(
        default_factory=list,
        description="需要新增的动态 worker 列表。",
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
        "tools": tools if tools is not None else [query_internal_kb, inspect_architecture],
        "middleware": [EvidenceTodoMiddleware()],
        "dynamic": dynamic,
    }


def _default_subagent_specs() -> list[dict[str, Any]]:
    shared_tools = [query_internal_kb, inspect_architecture]
    return [
        _build_subagent_spec(
            name="general-purpose",
            display_name="Disabled Fallback Agent",
            description="禁用的后备代理。除非用户明确要求，否则 supervisor 不应把任务派发给它。",
            role="后备代理，占位禁用",
            system_prompt=(
                "你是一个被禁用的后备子代理。"
                "在这个 demo 中不应承接任务。"
                "如果被调用，直接简短返回：该任务不应派发给 general-purpose，请改派并行 worker。"
            ),
            tools=[],
        ),
        _build_subagent_spec(
            name="worker_alpha",
            display_name="Worker Alpha",
            description=DEFAULT_WORKER_DESCRIPTION,
            role="通用并行 worker，负责第一个独立维度分片",
            system_prompt=DEFAULT_WORKER_SYSTEM_PROMPT,
            tools=shared_tools,
        ),
        _build_subagent_spec(
            name="worker_beta",
            display_name="Worker Beta",
            description=DEFAULT_WORKER_DESCRIPTION,
            role="通用并行 worker，负责第二个独立维度分片",
            system_prompt=DEFAULT_WORKER_SYSTEM_PROMPT,
            tools=shared_tools,
        ),
        _build_subagent_spec(
            name="worker_gamma",
            display_name="Worker Gamma",
            description=DEFAULT_WORKER_DESCRIPTION,
            role="通用并行 worker，负责第三个独立维度分片",
            system_prompt=DEFAULT_WORKER_SYSTEM_PROMPT,
            tools=shared_tools,
        ),
    ]


def _registered_subagent_specs() -> list[dict[str, Any]]:
    shared_tools = [query_internal_kb, inspect_architecture]
    return [
        _build_subagent_spec(
            name=item["name"],
            display_name=item["display_name"],
            description=item["description"],
            role=item["role"],
            system_prompt=item["system_prompt"],
            tools=shared_tools,
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
    return [*_default_subagent_specs(), *_registered_subagent_specs()]


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


def build_runtime_subagent_catalog(
    settings: Settings,
    query: str | None = None,
) -> list[dict[str, str]]:
    runtime_query = (query or settings.prompt).strip()
    model = _make_model(settings)
    runtime_specs = _build_runtime_subagent_specs(model=model, query=runtime_query)
    return [
        _catalog_item(spec) for spec in runtime_specs if spec["name"] != "general-purpose"
    ]


def build_agent_bundle(
    settings: Settings,
    query: str | None = None,
) -> tuple[Any, list[dict[str, str]]]:
    runtime_query = (query or settings.prompt).strip()
    model = _make_model(settings)
    runtime_specs = _build_runtime_subagent_specs(model=model, query=runtime_query)
    runtime_catalog = [
        _catalog_item(spec) for spec in runtime_specs if spec["name"] != "general-purpose"
    ]
    system_prompt = build_supervisor_system_prompt(
        subagent_catalog=runtime_catalog,
        max_rounds=12,
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
    agent = create_deep_agent(
        model=model,
        tools=[],
        subagents=subagents,
        system_prompt=system_prompt,
        name="supervisor",
        debug=True,
    )
    return agent, runtime_catalog


def _build_runtime_subagent_specs(
    *,
    model: ChatOpenAI,
    query: str,
) -> list[dict[str, Any]]:
    base_specs = get_subagent_specs()
    derived_specs = _derive_dynamic_subagents(model=model, query=query, existing_specs=base_specs)
    return [*base_specs, *derived_specs]


def _derive_dynamic_subagents(
    *,
    model: ChatOpenAI,
    query: str,
    existing_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_names = {spec["name"] for spec in existing_specs}
    default_workers = [
        spec for spec in existing_specs if spec["name"].startswith("worker_")
    ]
    default_workers_text = "\n".join(
        f"- {spec['name']} / {spec['display_name']}：{spec['role']}。{spec['description']}"
        for spec in default_workers
    )

    planner = model.with_structured_output(DynamicSubagentPlan)
    try:
        plan = planner.invoke(
            DYNAMIC_SUBAGENT_PLANNER_PROMPT.format(
                default_workers=default_workers_text or "- 当前没有默认 worker。",
                query=query,
            )
        )
    except Exception:
        return []

    if not plan.spawn_needed:
        return []

    specs: list[dict[str, Any]] = []
    for index, item in enumerate(plan.subagents[:4], start=1):
        safe_name = _sanitize_agent_name(item.name, existing_names)
        existing_names.add(safe_name)
        display_name = item.display_name.strip() or _fallback_display_name(safe_name, index)
        role = item.role.strip() or "负责额外维度并行处理"
        description = item.description.strip() or "用于承接 query 中未被默认 worker 覆盖的额外维度任务。"
        system_prompt = item.system_prompt.strip() or (
            "你是一个由 supervisor 动态派生的并行 worker。"
            "收到任务后，必须先调用 write_evidence_todos 创建私有证据型待办列表。"
            "你只负责自己这个维度，不要越界总结全局。"
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
    return f"Dynamic Worker {index}"


def _make_model(settings: Settings) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=0,
    )
