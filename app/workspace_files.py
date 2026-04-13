from __future__ import annotations

import mimetypes
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = PROJECT_ROOT / "workspace"


def resolve_workspace_file(relative_path: str) -> Path:
    normalized = (relative_path or "").strip()
    if not normalized:
        raise ValueError("缺少 relative_path。")
    if normalized.startswith("/workspace/") or normalized == "/workspace":
        raise ValueError("不允许使用 /workspace 前缀；请直接传相对路径，例如 report.md 或 subdir/report.md。")
    if normalized.startswith("workspace/") or normalized == "workspace":
        raise ValueError("不允许使用 workspace/ 前缀；请直接传相对路径，例如 report.md 或 subdir/report.md。")
    normalized = normalized.lstrip("/")

    candidate = (WORKSPACE_ROOT / normalized).resolve()
    workspace_root = WORKSPACE_ROOT.resolve()
    if workspace_root not in {candidate, *candidate.parents}:
        raise ValueError("只允许访问当前文件根目录内的文件。")
    if not candidate.exists():
        raise FileNotFoundError(f"文件不存在: {normalized}")
    if not candidate.is_file():
        raise ValueError(f"目标不是文件: {normalized}")
    return candidate


def build_workspace_file_card(relative_path: str, *, title: str = "") -> dict[str, str | int]:
    file_path = resolve_workspace_file(relative_path)
    mime_type, _ = mimetypes.guess_type(file_path.name)
    mime_type = mime_type or "application/octet-stream"
    rel_path = file_path.relative_to(WORKSPACE_ROOT.resolve()).as_posix()
    query = urlencode({"path": rel_path})
    suffix = file_path.suffix.lower() or Path(file_path.name).suffix.lower() or ""
    return {
        "id": rel_path,
        "path": rel_path,
        "name": file_path.name,
        "title": (title or "").strip() or file_path.name,
        "extension": suffix or "(无后缀)",
        "size": file_path.stat().st_size,
        "updated_at": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
        "mime_type": mime_type,
        "preview_url": f"/api/demo/workspace-file?{query}",
        "download_url": f"/api/demo/workspace-file?{query}&download=1",
    }


def write_workspace_text_file(relative_path: str, content: str) -> dict[str, str | int]:
    file_path = resolve_workspace_file(relative_path)
    file_path.write_text(content, encoding="utf-8")
    return build_workspace_file_card(relative_path)
