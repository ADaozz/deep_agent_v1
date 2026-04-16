from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from app.skills import Skill, load_skill, load_skill_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = PROJECT_ROOT / "skill"

SUPERVISOR_SKILL_CONFIGS = {
    "deep_research": {
        "title": "Deep Research Supervisor Skill",
        "route_note": "以下 supervisor skill 只在用户请求属于争议性技术话题、事实核验、benchmark 解读、立场判断或趋势分析时启用。",
        "source": "skill/deep_research/SKILL.md",
    },
    "coding_principles": {
        "title": "Karpathy Coding Principles Supervisor Skill",
        "route_note": "以下 supervisor skill 只在用户请求属于写代码、改代码、重构、工程化整理、代码评审或实现逻辑修改等编码任务时启用。",
        "source": "skill/coding_principles/SKILL.md",
    },
}

SUPERVISOR_SKILL_ORDER = tuple(SUPERVISOR_SKILL_CONFIGS.keys())
SUPERVISOR_SKILL_PATHS = {
    skill_id: SKILLS_ROOT / skill_id / "SKILL.md" for skill_id in SUPERVISOR_SKILL_ORDER
}
_SUPERVISOR_SKILL_DEFAULT_RAW = {
    skill_id: path.read_text(encoding="utf-8") for skill_id, path in SUPERVISOR_SKILL_PATHS.items()
}
_SUPERVISOR_SKILL_STORE = deepcopy(_SUPERVISOR_SKILL_DEFAULT_RAW)


def _load_runtime_skill(*, skill_id: str, raw_text: str | None = None) -> Skill:
    content = _SUPERVISOR_SKILL_STORE[skill_id] if raw_text is None else raw_text
    return load_skill_text(
        raw_text=content,
        skill_dir_name=skill_id,
        runtime_target="supervisor",
        source_path=SUPERVISOR_SKILL_PATHS[skill_id],
    )


def _query_hits_keywords(query: str | None, *, keywords: tuple[str, ...]) -> bool:
    normalized = (query or "").strip().lower()
    if not normalized:
        return False
    return any(keyword in normalized for keyword in keywords)


def _build_skill_section(*, skill_id: str) -> dict[str, object]:
    skill = _load_runtime_skill(skill_id=skill_id)
    meta = SUPERVISOR_SKILL_CONFIGS[skill_id]
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


def list_skill_sections() -> list[dict[str, object]]:
    return [_build_skill_section(skill_id=skill_id) for skill_id in SUPERVISOR_SKILL_ORDER]


def update_skill_section(*, skill_id: str, content: str) -> dict[str, object]:
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
    normalized_id = skill_id.strip()
    if normalized_id not in _SUPERVISOR_SKILL_DEFAULT_RAW:
        raise KeyError(f"unknown_skill_id: {normalized_id}")
    _SUPERVISOR_SKILL_STORE[normalized_id] = _SUPERVISOR_SKILL_DEFAULT_RAW[normalized_id]
    return _build_skill_section(skill_id=normalized_id)


def build_supervisor_skill_prompt_suffix(*, query: str | None) -> str:
    blocks: list[str] = []
    for skill_id in SUPERVISOR_SKILL_ORDER:
        skill = _load_runtime_skill(skill_id=skill_id)
        if not _query_hits_keywords(query, keywords=tuple(skill.route_keywords)):
            continue
        config = SUPERVISOR_SKILL_CONFIGS[skill_id]
        blocks.append(
            f"# Supervisor Skill: {skill_id}\n\n"
            f"{config['route_note']}\n\n"
            f"{skill.content}"
        )
    return "\n\n".join(blocks).strip()
