from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class GenerateSubagentsInput(BaseModel):
    task_breakdown: str = Field(
        default="",
        description="当前已经拆解出的原子任务列表或简要任务分解说明。",
    )


def make_generate_subagents_tool(
    *,
    query: str,
    reasoning: str,
    planner_error: str,
    workers: list[dict[str, Any]],
):
    roster_payload = {
        "query": query,
        "delegation_needed": bool(workers),
        "reasoning": reasoning.strip() or ("当前 query 适合派发专属 worker。" if workers else "当前 query 无需额外 worker。"),
        "planner_error": planner_error.strip(),
        "workers": [
            {
                "id": item["id"],
                "name": item["name"],
                "scope": item.get("scope", ""),
                "role": item["role"],
                "description": item["description"],
            }
            for item in workers
        ],
        "usage_hint": "后续调用 task 时，必须严格使用 workers[*].id 作为 subagent_type。",
    }

    @tool("generate_subagents", args_schema=GenerateSubagentsInput)
    def generate_subagents(task_breakdown: str = "") -> str:
        """根据当前 query 返回本轮 worker 名册。

        何时使用：
        - 仅 supervisor 使用。
        - 已经完成主 Action List，且判断当前任务不适合由 supervisor 独立完成。
        - 需要确认本轮可以派发给哪些 worker。

        使用规则：
        - 在首次调用 task 之前必须先调用本工具。
        - 不要猜测、编造或复用历史 worker 名称。
        - 工具返回 JSON，其中 workers[*].id 是后续 task.subagent_type 唯一允许使用的值。
        - workers[*].scope 描述该 worker 的对象、维度或边界，派发任务时必须遵守。
        - 如果 workers 为空，说明本轮没有可派发 worker，应由 supervisor 继续处理或向用户说明限制。

        输入：
        - `task_breakdown`：当前已拆解出的任务列表或简要分片说明，用于核对 worker 覆盖范围。
        """
        payload = dict(roster_payload)
        payload["task_breakdown"] = task_breakdown.strip()
        return json.dumps(payload, ensure_ascii=False)

    return generate_subagents
