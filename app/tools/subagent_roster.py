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

        这是 supervisor 专用工具。正常顺序应当是：
        1. 先调用 write_todos 拆解主任务
        2. 再调用 generate_subagents 获取本轮 worker 名册
        3. 最后基于返回结果调用 task，把叶子任务派发给对应 worker

        `task_breakdown` 用于向工具说明当前已拆解出的原子任务，有助于你在
        推理时核对本轮 worker 是否覆盖了这些维度。工具返回 JSON，其中
        `workers[*].id` 就是后续 `task.subagent_type` 必须使用的值。
        """
        payload = dict(roster_payload)
        payload["task_breakdown"] = task_breakdown.strip()
        return json.dumps(payload, ensure_ascii=False)

    return generate_subagents
