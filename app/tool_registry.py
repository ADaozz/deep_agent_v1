from __future__ import annotations

import ast
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CUSTOM_TOOLS_SOURCE = PROJECT_ROOT / "app" / "tools" / "custom_tools.py"
TOOL_CONTROL_STORE = PROJECT_ROOT / "runtime_logs" / "tool_controls.json"


@dataclass(frozen=True)
class ToolDescriptor:
    id: str
    title: str
    subtitle: str
    scope: str
    source_path: str
    function_name: str
    summary: str
    docstring: str
    pinned: bool
    switchable: bool
    runtime_symbol: str


PINNED_TOOL_DESCRIPTORS: tuple[ToolDescriptor, ...] = (
    ToolDescriptor(
        id="generate_subagents",
        title="generate_subagents",
        subtitle="Supervisor 的本轮 worker 名册生成器。",
        scope="supervisor",
        source_path="app/tools/subagent_roster.py",
        function_name="make_generate_subagents_tool",
        summary="根据当前 query 生成本轮动态 worker 名册。",
        docstring=(
            "Supervisor 在判断任务不适合独立完成后调用。"
            "它返回本轮可派发的 worker 名册。"
            "后续调用 task 时，subagent_type 必须严格使用 workers[*].id。"
            "不要在未调用该工具前猜测 worker 名称。"
        ),
        pinned=True,
        switchable=False,
        runtime_symbol="make_generate_subagents_tool",
    ),
    ToolDescriptor(
        id="publish_workspace_file",
        title="publish_workspace_file",
        subtitle="把 workspace 文件发布成前端文件卡片。",
        scope="supervisor",
        source_path="app/tools/workspace_artifacts.py",
        function_name="publish_workspace_file",
        summary="把已存在的 workspace 文件发布为前端可预览产物。",
        docstring=(
            "Supervisor 在生成结果文件后调用。"
            "它把当前文件根目录下已经存在的文件发布为前端可预览或下载的文件卡片。"
            "只传相对路径，不要传绝对路径或手动补目录前缀。"
            "该工具不会创建文件，只负责发布已有文件。"
        ),
        pinned=True,
        switchable=False,
        runtime_symbol="publish_workspace_file",
    ),
    ToolDescriptor(
        id="write_evidence_todos",
        title="write_evidence_todos",
        subtitle="Worker 的私有 evidence checklist 工具。",
        scope="worker",
        source_path="app/agent/todo_enforcer.py",
        function_name="write_evidence_todos",
        summary="维护 worker 私有的 evidence checklist。",
        docstring=(
            "Worker 收到任务后必须优先调用。"
            "它维护当前 worker 私有的 evidence checklist。"
            "每个 completed 项都必须包含具体证据；无法完成的项应标记为 blocked 并写清阻塞原因。"
            "不要用空泛表述代替 evidence。"
        ),
        pinned=True,
        switchable=False,
        runtime_symbol="write_evidence_todos",
    ),
)


def _read_tool_store() -> dict[str, bool]:
    if not TOOL_CONTROL_STORE.exists():
        return {}
    try:
        payload = json.loads(TOOL_CONTROL_STORE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    custom_tools = payload.get("custom_tools", payload.get("tools", {}))
    if not isinstance(custom_tools, dict):
        return {}
    return {str(key): bool(value) for key, value in custom_tools.items() if isinstance(value, bool)}


def _write_tool_store(custom_tool_state: dict[str, bool]) -> None:
    TOOL_CONTROL_STORE.parent.mkdir(parents=True, exist_ok=True)
    TOOL_CONTROL_STORE.write_text(
        json.dumps({"custom_tools": custom_tool_state}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_module_from_path(module_key: str, source_path: str):
    module_spec = importlib.util.spec_from_file_location(module_key, PROJECT_ROOT / source_path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"无法加载工具源码: {source_path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _extract_docstring(node: ast.FunctionDef) -> str:
    return (ast.get_docstring(node) or "").strip()


def _extract_summary(docstring: str, fallback: str) -> str:
    first_line = next((line.strip() for line in docstring.splitlines() if line.strip()), "")
    return first_line or fallback


def _is_tool_decorator(decorator: ast.expr) -> bool:
    if isinstance(decorator, ast.Name):
        return decorator.id == "tool"
    if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
        return decorator.func.id == "tool"
    return False


def _decorated_tool_id(node: ast.FunctionDef) -> str:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "tool":
            return node.name
        if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name) and decorator.func.id == "tool":
            if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
                return decorator.args[0].value.strip() or node.name
            return node.name
    return node.name


def sniff_custom_tool_descriptors() -> list[ToolDescriptor]:
    if not CUSTOM_TOOLS_SOURCE.exists():
        return []
    source_text = CUSTOM_TOOLS_SOURCE.read_text(encoding="utf-8")
    module = ast.parse(source_text)
    descriptors: list[ToolDescriptor] = []
    for node in module.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if not any(_is_tool_decorator(decorator) for decorator in node.decorator_list):
            continue
        tool_id = _decorated_tool_id(node)
        docstring = _extract_docstring(node)
        descriptors.append(
            ToolDescriptor(
                id=tool_id,
                title=tool_id,
                subtitle=_extract_summary(docstring, "项目扩展工具。"),
                scope="worker",
                source_path="app/tools/custom_tools.py",
                function_name=node.name,
                summary=_extract_summary(docstring, "项目扩展工具。"),
                docstring=docstring,
                pinned=False,
                switchable=True,
                runtime_symbol=node.name,
            )
        )
    return descriptors


def _pinned_lookup() -> dict[str, ToolDescriptor]:
    return {item.id: item for item in PINNED_TOOL_DESCRIPTORS}


def _custom_lookup() -> dict[str, ToolDescriptor]:
    return {item.id: item for item in sniff_custom_tool_descriptors()}


def list_tool_controls() -> list[dict[str, Any]]:
    enabled_map = _read_tool_store()
    items: list[dict[str, Any]] = []
    for descriptor in PINNED_TOOL_DESCRIPTORS:
        items.append(_tool_payload(descriptor, enabled=True))
    for descriptor in sniff_custom_tool_descriptors():
        items.append(_tool_payload(descriptor, enabled=enabled_map.get(descriptor.id, True)))
    return items


def _tool_payload(descriptor: ToolDescriptor, *, enabled: bool) -> dict[str, Any]:
    return {
        "id": descriptor.id,
        "title": descriptor.title,
        "subtitle": descriptor.subtitle,
        "scope": descriptor.scope,
        "source_path": descriptor.source_path,
        "function_name": descriptor.function_name,
        "summary": descriptor.summary,
        "docstring": descriptor.docstring,
        "enabled": enabled,
        "pinned": descriptor.pinned,
        "switchable": descriptor.switchable,
    }


def get_tool_control(tool_id: str) -> dict[str, Any]:
    tool_key = tool_id.strip()
    for item in list_tool_controls():
        if item["id"] == tool_key:
            return item
    raise KeyError(f"unknown_tool_id: {tool_key}")


def update_tool_enabled(*, tool_id: str, enabled: bool) -> dict[str, Any]:
    pinned = _pinned_lookup()
    if tool_id in pinned:
        raise ValueError("固定工具不允许在工具控制台中禁用。")
    custom = _custom_lookup()
    if tool_id not in custom:
        raise KeyError(f"unknown_tool_id: {tool_id}")
    current = _read_tool_store()
    current[tool_id] = bool(enabled)
    _write_tool_store(current)
    return get_tool_control(tool_id)


def list_active_tool_ids() -> list[str]:
    active = [item.id for item in PINNED_TOOL_DESCRIPTORS]
    enabled_map = _read_tool_store()
    for descriptor in sniff_custom_tool_descriptors():
        if enabled_map.get(descriptor.id, True):
            active.append(descriptor.id)
    return active


def list_active_worker_tool_ids() -> list[str]:
    active = [item.id for item in PINNED_TOOL_DESCRIPTORS if item.scope == "worker"]
    enabled_map = _read_tool_store()
    for descriptor in sniff_custom_tool_descriptors():
        if descriptor.scope == "worker" and enabled_map.get(descriptor.id, True):
            active.append(descriptor.id)
    return active


def load_runtime_tool_bundle() -> dict[str, Any]:
    active_tool_ids = set(list_active_tool_ids())
    active_worker_tool_ids = list_active_worker_tool_ids()
    custom_descriptors = sniff_custom_tool_descriptors()
    fixed_modules = {
        "subagent_roster": _load_module_from_path("_deep_agent_fixed_subagent_roster", "app/tools/subagent_roster.py"),
        "workspace_artifacts": _load_module_from_path("_deep_agent_fixed_workspace_artifacts", "app/tools/workspace_artifacts.py"),
        "todo_enforcer": _load_module_from_path("_deep_agent_fixed_todo_enforcer", "app/agent/todo_enforcer.py"),
    }
    custom_module = _load_module_from_path("_deep_agent_custom_tools", "app/tools/custom_tools.py") if CUSTOM_TOOLS_SOURCE.exists() else None
    custom_worker_tools: list[Any] = []
    if custom_module is not None:
        for descriptor in custom_descriptors:
            if descriptor.id in active_tool_ids:
                custom_worker_tools.append(getattr(custom_module, descriptor.runtime_symbol))
    return {
        "active_tool_list": active_worker_tool_ids,
        "all_active_tool_list": list(active_tool_ids),
        "generate_subagents_factory": getattr(fixed_modules["subagent_roster"], "make_generate_subagents_tool"),
        "publish_workspace_file": getattr(fixed_modules["workspace_artifacts"], "publish_workspace_file"),
        "evidence_todo_middleware": getattr(fixed_modules["todo_enforcer"], "EvidenceTodoMiddleware"),
        "custom_worker_tools": custom_worker_tools,
    }
