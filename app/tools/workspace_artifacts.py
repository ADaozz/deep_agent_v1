from __future__ import annotations

import json

from langchain_core.tools import tool

from app.workspace_files import build_workspace_file_card


@tool
def publish_workspace_file(relative_path: str, title: str = "") -> str:
    """将当前文件根目录下的文件发布为前端可预览/下载的会话产物卡片。

    何时使用：
    - supervisor 已经生成 markdown、txt、py、json、csv、xlsx 等结果文件。
    - 用户需要在前端看到、预览或下载该文件。
    - 最终答复中不应只手写路径，而应先发布文件卡片。

    使用要求：
    - `relative_path` 必须是相对当前文件根目录的路径。
    - 路径只能写成 `foo.py`、`subdir/foo.py`、`report.md` 这类相对形式。
    - 不要传绝对路径，不要手动补 workspace 目录前缀。
    - 该工具只负责发布已有文件，不会创建文件。
    - `title` 可选，用于前端文件卡片展示。

    返回：
    - JSON 字符串，ok=true 时包含可预览/下载的文件卡片信息。
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
