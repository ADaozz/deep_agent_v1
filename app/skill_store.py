from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from app.skills import Skill, load_skill_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = PROJECT_ROOT / "skill"
PREFERRED_SKILL_ORDER = ("deep_research", "coding_principles")

_SUPERVISOR_SKILL_ORDER: tuple[str, ...] = ()
_SUPERVISOR_SKILL_PATHS: dict[str, Path] = {}
_SUPERVISOR_SKILL_DEFAULT_RAW: dict[str, str] = {}
_SUPERVISOR_SKILL_STORE: dict[str, str] = {}
_SUPERVISOR_SKILL_META: dict[str, dict[str, str]] = {}


def _refresh_supervisor_skill_registry() -> None:
    global _SUPERVISOR_SKILL_ORDER
    global _SUPERVISOR_SKILL_PATHS
    global _SUPERVISOR_SKILL_DEFAULT_RAW
    global _SUPERVISOR_SKILL_STORE
    global _SUPERVISOR_SKILL_META

    discovered: list[tuple[str, Path, Skill, dict[str, str], str]] = []
    if SKILLS_ROOT.exists():
        for skill_dir in sorted(path for path in SKILLS_ROOT.iterdir() if path.is_dir()):
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            raw_text = skill_file.read_text(encoding="utf-8")
            generic_skill = load_skill_text(
                raw_text=raw_text,
                skill_dir_name=skill_dir.name,
                source_path=skill_file,
            )
            skill_scope = str(generic_skill.metadata.get("skill_scope") or "supervisor").strip().lower()
            if skill_scope != "supervisor":
                continue
            skill = load_skill_text(
                raw_text=raw_text,
                skill_dir_name=skill_dir.name,
                runtime_target="supervisor",
                source_path=skill_file,
            )
            meta = {
                "title": str(generic_skill.metadata.get("title") or skill.name).strip() or skill.name,
                "route_note": (
                    str(generic_skill.metadata.get("route_note") or "").strip()
                    or "以下 supervisor skill 会在 bootstrap 阶段先披露 YAML 头，再按 query 与 route_keywords 命中后注入全文。"
                ),
                "source": skill_file.relative_to(PROJECT_ROOT).as_posix(),
            }
            discovered.append((skill.name, skill_file, skill, meta, raw_text))

    def order_key(item: tuple[str, Path, Skill, dict[str, str], str]) -> tuple[int, int | str]:
        skill_id = item[0]
        if skill_id in PREFERRED_SKILL_ORDER:
            return (0, PREFERRED_SKILL_ORDER.index(skill_id))
        return (1, skill_id)

    discovered.sort(key=order_key)
    skill_ids = tuple(item[0] for item in discovered)
    paths = {skill_id: path for skill_id, path, _, _, _ in discovered}
    defaults = {skill_id: raw_text for skill_id, _, _, _, raw_text in discovered}
    meta_map = {skill_id: meta for skill_id, _, _, meta, _ in discovered}

    next_store: dict[str, str] = {}
    for skill_id in skill_ids:
        next_store[skill_id] = _SUPERVISOR_SKILL_STORE.get(skill_id, defaults[skill_id])

    _SUPERVISOR_SKILL_ORDER = skill_ids
    _SUPERVISOR_SKILL_PATHS = paths
    _SUPERVISOR_SKILL_DEFAULT_RAW = defaults
    _SUPERVISOR_SKILL_STORE = next_store
    _SUPERVISOR_SKILL_META = meta_map


def _load_runtime_skill(*, skill_id: str, raw_text: str | None = None) -> Skill:
    _refresh_supervisor_skill_registry()
    content = _SUPERVISOR_SKILL_STORE[skill_id] if raw_text is None else raw_text
    return load_skill_text(
        raw_text=content,
        skill_dir_name=skill_id,
        runtime_target="supervisor",
        source_path=_SUPERVISOR_SKILL_PATHS[skill_id],
    )


def _build_skill_section(*, skill_id: str) -> dict[str, object]:
    skill = _load_runtime_skill(skill_id=skill_id)
    meta = _SUPERVISOR_SKILL_META[skill_id]
    return {
        "id": skill_id,
        "title": meta["title"],
        "subtitle": skill.description,
        "source": meta["source"],
        "kind": "skill",
        "skill_scope": "supervisor",
        "tool_type": skill.tool_type.value,
        "frontmatter": deepcopy(skill.metadata),
        "body": skill.content,
        "content": _SUPERVISOR_SKILL_STORE[skill_id].strip(),
    }


def _build_skill_header_payload(*, skill_id: str) -> dict[str, Any]:
    skill = _load_runtime_skill(skill_id=skill_id)
    meta = _SUPERVISOR_SKILL_META[skill_id]
    return {
        "id": skill_id,
        "name": skill.name,
        "description": skill.description,
        "tool_type": skill.tool_type.value,
        "route_note": meta["route_note"],
        "source": meta["source"],
        "frontmatter": deepcopy(skill.metadata),
    }


def list_skill_sections() -> list[dict[str, object]]:
    _refresh_supervisor_skill_registry()
    return [_build_skill_section(skill_id=skill_id) for skill_id in _SUPERVISOR_SKILL_ORDER]


def list_supervisor_skill_headers() -> list[dict[str, Any]]:
    _refresh_supervisor_skill_registry()
    return [_build_skill_header_payload(skill_id=skill_id) for skill_id in _SUPERVISOR_SKILL_ORDER]


def get_supervisor_skill(skill_id: str) -> dict[str, object]:
    _refresh_supervisor_skill_registry()
    normalized_id = skill_id.strip()
    if normalized_id not in _SUPERVISOR_SKILL_STORE:
        raise KeyError(f"unknown_skill_id: {normalized_id}")
    return _build_skill_section(skill_id=normalized_id)


def normalize_supervisor_skill_ids(skill_ids: list[str] | None) -> list[str]:
    _refresh_supervisor_skill_registry()
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_skill_id in skill_ids or []:
        skill_id = str(raw_skill_id).strip()
        if not skill_id or skill_id in seen or skill_id not in _SUPERVISOR_SKILL_STORE:
            continue
        seen.add(skill_id)
        normalized.append(skill_id)
    return normalized


def update_skill_section(*, skill_id: str, content: str) -> dict[str, object]:
    _refresh_supervisor_skill_registry()
    normalized_id = skill_id.strip()
    if normalized_id not in _SUPERVISOR_SKILL_STORE:
        raise KeyError(f"unknown_skill_id: {normalized_id}")

    normalized_content = content.strip()
    if not normalized_content:
        raise ValueError("skill_content_required")

    _load_runtime_skill(skill_id=normalized_id, raw_text=normalized_content)
    _SUPERVISOR_SKILL_STORE[normalized_id] = normalized_content
    return _build_skill_section(skill_id=normalized_id)


def reset_skill_section(*, skill_id: str) -> dict[str, object]:
    _refresh_supervisor_skill_registry()
    normalized_id = skill_id.strip()
    if normalized_id not in _SUPERVISOR_SKILL_DEFAULT_RAW:
        raise KeyError(f"unknown_skill_id: {normalized_id}")
    _SUPERVISOR_SKILL_STORE[normalized_id] = _SUPERVISOR_SKILL_DEFAULT_RAW[normalized_id]
    return _build_skill_section(skill_id=normalized_id)


def build_supervisor_skill_prompt_suffix(*, skill_ids: list[str] | None) -> str:
    _refresh_supervisor_skill_registry()
    blocks: list[str] = []
    for skill_id in normalize_supervisor_skill_ids(skill_ids):
        skill = _load_runtime_skill(skill_id=skill_id)
        config = _SUPERVISOR_SKILL_META[skill_id]
        blocks.append(
            f"# Supervisor Skill: {skill_id}\n\n"
            f"{config['route_note']}\n\n"
            f"{skill.content}"
        )
    return "\n\n".join(blocks).strip()
