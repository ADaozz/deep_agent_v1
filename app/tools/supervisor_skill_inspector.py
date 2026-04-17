from __future__ import annotations

import json
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.skill_store import get_supervisor_skill, list_supervisor_skill_headers, normalize_supervisor_skill_ids


class InspectSupervisorSkillsInput(BaseModel):
    mode: Literal["headers", "full"] = Field(
        default="headers",
        description="`headers` 只返回 supervisor skill 的 YAML 头摘要；`full` 返回所选 skill 的完整正文。",
    )
    skill_ids: list[str] = Field(
        default_factory=list,
        description="当 mode=`full` 时要展开的 supervisor skill id 列表。",
    )


def make_inspect_supervisor_skills_tool():
    @tool("inspect_supervisor_skills", args_schema=InspectSupervisorSkillsInput)
    def inspect_supervisor_skills(mode: str = "headers", skill_ids: list[str] | None = None) -> str:
        """按渐进式披露方式查看 supervisor skills。

        使用规则：
        - 仅 supervisor 使用。
        - 默认先调用 `mode=headers`，只查看可用 supervisor skill 的 YAML 头摘要。
        - 判断当前 query 命中哪些 skill 后，再调用 `mode=full` 请求所需 skill 的完整正文。
        - 不要一次性展开全部 skill 正文；只展开当前真正需要的 skill。
        - 该工具只暴露 supervisor skills，不暴露 worker skills。
        """

        normalized_mode = (mode or "headers").strip().lower()
        if normalized_mode == "headers":
            payload = {
                "mode": "headers",
                "skills": list_supervisor_skill_headers(),
                "usage_hint": "先根据 YAML 头判断当前 query 命中哪些 skill，再用 mode=full 拉取所需 skill 全文。",
            }
            return json.dumps(payload, ensure_ascii=False)

        if normalized_mode != "full":
            raise ValueError("unsupported_mode: expected headers or full")

        normalized_ids = normalize_supervisor_skill_ids(skill_ids)
        if not normalized_ids:
            raise ValueError("skill_ids_required_for_full")

        payload = {
            "mode": "full",
            "skills": [get_supervisor_skill(skill_id) for skill_id in normalized_ids],
        }
        return json.dumps(payload, ensure_ascii=False)

    return inspect_supervisor_skills
