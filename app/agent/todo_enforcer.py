import json
from typing import Any, Literal
from typing_extensions import Annotated, NotRequired, TypedDict

from langchain.agents.middleware.todo import OmitFromInput, PlanningState, ToolRuntime
from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command
from pydantic import BaseModel, Field


EVIDENCE_TODO_SYSTEM_PROMPT = """## `write_evidence_todos`

你必须使用 `write_evidence_todos` 来维护你自己的私有待办列表。
这是每个子代理任务的强制要求。

每个待办项都必须包含：
- `content`：任务内容本身
- `status`：`pending`、`in_progress`、`completed` 或 `blocked`
- `evidence`：完成该任务的具体证据
- `evidence_type`：`file_observation`、`tool_result`、`command_result`、`subagent_report`、`reasoned_check` 之一

规则：
1. 在结束前，你必须先创建并维护自己的证据型私有待办列表。
2. 只有在能提供具体证据时，才允许把待办标记为 `completed`。
3. 证据必须引用真实观察、工具输出、命令结果、文件内容或复核结论。
4. 不要使用“已完成”“已检查”这类空泛证据。
5. 如果某一项因为环境、权限、依赖、目标条件等原因无法完成，必须标记为 `blocked`，并写清阻塞证据。
6. 如果证据本身说明“无法执行”“缺少工具”“无法获取数据”等，就不能把该项标记为 `completed`。
7. 只有当所有证据型待办都变成 `completed` 或 `blocked`，且每项都有充分证据时，才允许输出最终答案。
"""

BLOCKED_EVIDENCE_INDICATORS = (
    "缺少工具",
    "系统中无",
    "无法安装工具",
    "无法执行命令",
    "权限被拒绝",
    "认证失败",
    "执行环境受限",
    "被守卫拦截",
    "docker exec 失败",
)


class EvidenceTodo(TypedDict):
    content: str
    status: Literal["pending", "in_progress", "completed", "blocked"]
    evidence: str
    evidence_type: Literal[
        "file_observation",
        "tool_result",
        "command_result",
        "subagent_report",
        "reasoned_check",
    ]


class EvidencePlanningState(PlanningState[Any]):
    agent_todos: Annotated[NotRequired[list[EvidenceTodo]], OmitFromInput]


class EvidenceTodoItem(BaseModel):
    content: str = Field(description="待办项的内容描述。")
    status: Literal["pending", "in_progress", "completed", "blocked"] = Field(
        description="该待办项的当前状态。"
    )
    evidence: str = Field(
        default="",
        description="完成该待办的具体证据。状态为 completed 时必须提供。",
    )
    evidence_type: Literal[
        "file_observation",
        "tool_result",
        "command_result",
        "subagent_report",
        "reasoned_check",
    ] = Field(
        default="reasoned_check",
        description="该待办项附带证据的类型。",
    )


class WriteEvidenceTodosInput(BaseModel):
    todos: list[EvidenceTodoItem] = Field(
        description="当前子代理完整的私有证据型待办列表。"
    )


def _normalize_todos(todos: list[EvidenceTodoItem | dict[str, Any]]) -> list[EvidenceTodo]:
    normalized: list[EvidenceTodo] = []
    for item in todos:
        data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        normalized.append(
            EvidenceTodo(
                content=str(data.get("content", "")).strip(),
                status=data.get("status", "pending"),
                evidence=str(data.get("evidence", "")).strip(),
                evidence_type=data.get("evidence_type", "reasoned_check"),
            )
        )
    return normalized


@tool("write_evidence_todos", args_schema=WriteEvidenceTodosInput)
def write_evidence_todos(
    runtime: ToolRuntime[Any, EvidencePlanningState],
    todos: list[EvidenceTodoItem],
) -> Command[Any]:
    """创建并更新子代理自己的私有证据型待办列表。"""
    normalized = _normalize_todos(todos)
    return Command(
        update={
            "agent_todos": normalized,
            "messages": [
                ToolMessage(
                    content=json.dumps({"agent_todos": normalized}, ensure_ascii=False),
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )


class EvidenceTodoMiddleware(AgentMiddleware[EvidencePlanningState, Any, Any]):
    """提供证据型私有待办管理，并阻止子代理过早结束。"""

    state_schema = EvidencePlanningState

    def __init__(self) -> None:
        super().__init__()
        self.tools = [write_evidence_todos]

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Any,
    ) -> ModelResponse[Any] | AIMessage:
        if request.system_message is not None:
            content_blocks = [
                *request.system_message.content_blocks,
                {"type": "text", "text": f"\n\n{EVIDENCE_TODO_SYSTEM_PROMPT}"},
            ]
        else:
            content_blocks = [{"type": "text", "text": EVIDENCE_TODO_SYSTEM_PROMPT}]
        return handler(request.override(system_message=SystemMessage(content=content_blocks)))

    def after_agent(
        self,
        state: EvidencePlanningState,
        runtime: Any,
    ) -> dict[str, Any] | None:
        todos = state.get("agent_todos") or []
        if not todos:
            return {
                "messages": [
                    HumanMessage(
                        content=(
                            "运行时守卫：你必须先调用 `write_evidence_todos`，"
                            "创建自己的私有证据型待办列表，之后才能结束。"
                        )
                    )
                ],
                "jump_to": "model",
            }

        invalid: list[str] = []
        for todo in todos:
            status = todo.get("status")
            content = todo.get("content", "")
            evidence = todo.get("evidence", "").strip()
            if status == "completed":
                if not evidence:
                    invalid.append(f"{content}: 缺少证据")
                    continue
                if len(evidence) < 12:
                    invalid.append(f"{content}: 证据过弱")
                    continue
                if _evidence_sounds_blocked(evidence):
                    invalid.append(f"{content}: 证据表明该项受阻，应标记为 blocked")
                    continue
                continue
            if status == "blocked":
                if not evidence:
                    invalid.append(f"{content}: 缺少阻塞证据")
                    continue
                if len(evidence) < 12:
                    invalid.append(f"{content}: 阻塞证据过弱")
                    continue
                continue
            if status not in {"completed", "blocked"}:
                invalid.append(f"{content}: 状态为 {status}")

        if not invalid:
            return None

        message = (
            "运行时守卫：你现在还不能结束，因为你的私有证据型待办列表中仍有未解决项："
            f"{invalid}。请更新 `write_evidence_todos`，确保每一项都带有具体证据并标记为 "
            "`completed` 或 `blocked`；如果证据本身说明该项无法执行或无法获取结果，必须使用 `blocked`，然后再返回最终答案。"
        )
        return {
            "messages": [HumanMessage(content=message)],
            "jump_to": "model",
        }


EvidenceTodoMiddleware.after_agent.__can_jump_to__ = ["model"]


def _evidence_sounds_blocked(evidence: str) -> bool:
    lowered = evidence.lower()
    return any(indicator in lowered for indicator in BLOCKED_EVIDENCE_INDICATORS)
