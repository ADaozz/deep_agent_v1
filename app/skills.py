from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import frontmatter


class ToolType(str, Enum):
    NONE = "none"
    TOOL = "tool"
    MCP = "mcp"
    CODEMODE = "codemode"
    MIX = "mix"


@dataclass(slots=True)
class Skill:
    name: str
    description: str
    tool_type: ToolType
    metadata: dict[str, object] = field(default_factory=dict)
    tool_list: list[str] = field(default_factory=list)
    content: str = ""
    route_keywords: list[str] = field(default_factory=list)
    source_path: Path | None = None


def _build_skill(*, metadata: dict[object, object], content: str, skill_dir_name: str, source_path: Path | None, runtime_target: str | None) -> Skill:
    normalized_metadata = {str(key): value for key, value in metadata.items()}
    raw_name = str(normalized_metadata.get("name") or "").strip()
    if not raw_name:
        raise ValueError(f"skill_name_required: {source_path or skill_dir_name}")
    if raw_name != skill_dir_name:
        raise ValueError(f"skill_name_mismatch: {raw_name} != {skill_dir_name}")

    raw_description = str(normalized_metadata.get("description") or "").strip()
    if not raw_description:
        raise ValueError(f"skill_description_required: {source_path or skill_dir_name}")

    raw_tool_type = str(normalized_metadata.get("tool_type") or ToolType.NONE.value).strip().lower()
    try:
        tool_type = ToolType(raw_tool_type)
    except ValueError as exc:
        supported = ", ".join(item.value for item in ToolType)
        raise ValueError(f"unsupported_tool_type: {raw_tool_type}; expected one of {supported}") from exc

    tool_list = _normalize_str_list(normalized_metadata.get("tool_list"), field_name="tool_list")
    route_keywords = _normalize_str_list(normalized_metadata.get("route_keywords"), field_name="route_keywords")

    if runtime_target == "supervisor":
        if tool_type is not ToolType.NONE:
            raise ValueError(f"supervisor_skill_tool_type_must_be_none: {source_path or skill_dir_name}")
        if tool_list:
            raise ValueError(f"supervisor_skill_tool_list_not_allowed: {source_path or skill_dir_name}")

    return Skill(
        name=raw_name,
        description=raw_description,
        tool_type=tool_type,
        metadata=normalized_metadata,
        tool_list=tool_list,
        content=content.strip(),
        route_keywords=route_keywords,
        source_path=source_path,
    )


def _normalize_str_list(value: object, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if not isinstance(value, list):
        raise ValueError(f"{field_name}_must_be_list")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name}_must_be_list_of_strings")
        normalized = item.strip()
        if normalized:
            items.append(normalized)
    return items


def load_skill(*, skill_dir: Path, runtime_target: str | None = None) -> Skill:
    skill_file = skill_dir / "SKILL.md"
    post = frontmatter.load(skill_file)
    return _build_skill(
        metadata=post.metadata,
        content=post.content,
        skill_dir_name=skill_dir.name,
        source_path=skill_file,
        runtime_target=runtime_target,
    )


def load_skill_text(*, raw_text: str, skill_dir_name: str, runtime_target: str | None = None, source_path: Path | None = None) -> Skill:
    post = frontmatter.loads(raw_text)
    return _build_skill(
        metadata=post.metadata,
        content=post.content,
        skill_dir_name=skill_dir_name,
        source_path=source_path,
        runtime_target=runtime_target,
    )
