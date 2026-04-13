from __future__ import annotations

import json

from langchain_core.tools import tool

from app.workspace_files import build_workspace_file_card


@tool
def publish_workspace_file(relative_path: str, title: str = "") -> str:
    """将当前文件根目录下的文件发布为前端可预览/下载的会话产物卡片。

    适用场景：
    - supervisor 已经在当前文件根目录中生成了 markdown、txt、py、json、csv、xlsx 等文件
    - 需要把该文件作为当前会话的结构化产物返回给前端展示

    使用要求：
    - `relative_path` 必须是相对当前文件根目录的路径
    - 路径只能写成 `foo.py`、`subdir/foo.py`、`report.md` 这类相对形式
    - 严禁传入 `workspace/foo.py`、`/workspace/foo.py`、`/workspace/workspace/foo.py`
    - 该工具只负责“发布现有文件”，不会创建文件
    - 如果你希望用户在前端看到更清晰的名称，可额外传 `title`
    """
    try:
        payload = build_workspace_file_card(relative_path, title=title)
    except Exception as exc:  # noqa: BLE001
        return json.dumps(
            {
                "ok": False,
                "error": str(exc),
                "relative_path": relative_path,
            },
            ensure_ascii=False,
        )

    return json.dumps({"ok": True, "file": payload}, ensure_ascii=False)
