from __future__ import annotations

import json
import mimetypes
import re
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.backends import validate_docker_backend_access
from app.chat_history_store import (
    delete_thread_history,
    ensure_chat_history_schema,
    fetch_latest_thread_history,
    fetch_thread_history,
    fetch_thread_ui_state,
    list_history_threads,
    upsert_thread_ui_state,
    upsert_chat_session,
)
from app.config import load_settings
from app.demo_session import run_demo_session_stream
from app.prompts import get_prompt_sections, reset_prompt_section, update_prompt_section
from app.workspace_files import resolve_workspace_file, write_workspace_text_file


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_ROOT = PROJECT_ROOT / "frontend_demo"


class DemoRequestHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_ROOT), **kwargs)

    def do_POST(self) -> None:
        if self.path == "/api/demo/prompts":
            self._handle_update_prompt()
            return
        if self.path == "/api/demo/prompts/reset":
            self._handle_reset_prompt()
            return
        if self.path == "/api/demo/thread-state":
            self._handle_update_thread_state()
            return
        if self.path == "/api/demo/workspace-file":
            self._handle_update_workspace_file()
            return
        if self.path != "/api/demo/run":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "invalid_json"}, status=HTTPStatus.BAD_REQUEST)
            return

        query = str(payload.get("query", "")).strip()
        thread_id = str(payload.get("thread_id", "")).strip()
        session_id = str(payload.get("session_id", "")).strip()
        max_rounds = int(payload.get("max_rounds", 12) or 12)
        raw_messages = payload.get("messages", [])
        if not query:
            self._send_json({"error": "query_required"}, status=HTTPStatus.BAD_REQUEST)
            return
        if not thread_id:
            self._send_json({"error": "thread_id_required"}, status=HTTPStatus.BAD_REQUEST)
            return
        if not session_id:
            self._send_json({"error": "session_id_required"}, status=HTTPStatus.BAD_REQUEST)
            return

        messages = []
        if isinstance(raw_messages, list):
            for item in raw_messages:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role", "")).strip()
                content = str(item.get("content", "")).strip()
                if role in {"user", "assistant", "system"} and content:
                    messages.append({"role": role, "content": content})

        try:
            settings = load_settings(argv=[])
            self._send_ndjson_stream(
                settings=settings,
                query=query,
                thread_id=thread_id,
                session_id=session_id,
                max_rounds=max_rounds,
                messages=messages,
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

    def _handle_update_prompt(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "invalid_json"}, status=HTTPStatus.BAD_REQUEST)
            return

        prompt_id = str(payload.get("id", "")).strip()
        content = str(payload.get("content", ""))
        if not prompt_id:
            self._send_json({"error": "prompt_id_required"}, status=HTTPStatus.BAD_REQUEST)
            return
        if not content.strip():
            self._send_json({"error": "prompt_content_required"}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            updated = update_prompt_section(prompt_id=prompt_id, content=content)
        except KeyError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._send_json({"prompt": updated, "prompts": get_prompt_sections(max_rounds=12)}, status=HTTPStatus.OK)

    def _handle_reset_prompt(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "invalid_json"}, status=HTTPStatus.BAD_REQUEST)
            return

        prompt_id = str(payload.get("id", "")).strip()
        if not prompt_id:
            self._send_json({"error": "prompt_id_required"}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            reset_prompt = reset_prompt_section(prompt_id=prompt_id)
        except KeyError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._send_json({"prompt": reset_prompt, "prompts": get_prompt_sections(max_rounds=12)}, status=HTTPStatus.OK)

    def _handle_update_thread_state(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "invalid_json"}, status=HTTPStatus.BAD_REQUEST)
            return

        thread_id = str(payload.get("thread_id", "")).strip()
        ui_state = payload.get("ui_state", {})
        if not thread_id:
            self._send_json({"error": "thread_id_required"}, status=HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(ui_state, dict):
            self._send_json({"error": "ui_state_must_be_object"}, status=HTTPStatus.BAD_REQUEST)
            return

        settings = load_settings(argv=[])
        upsert_thread_ui_state(settings=settings, thread_id=thread_id, ui_state=ui_state)
        self._send_json({"ok": True})

    def _handle_update_workspace_file(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "invalid_json"}, status=HTTPStatus.BAD_REQUEST)
            return

        relative_path = str(payload.get("path", "")).strip()
        content = payload.get("content")
        if not relative_path:
            self._send_json({"error": "path_required"}, status=HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(content, str):
            self._send_json({"error": "content_must_be_string"}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            file_payload = write_workspace_text_file(relative_path, content)
        except FileNotFoundError:
            self._send_json({"error": "file_not_found"}, status=HTTPStatus.NOT_FOUND)
            return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._send_json({"ok": True, "file": file_payload}, status=HTTPStatus.OK)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if self.path == "/api/health":
            self._send_json({"ok": True})
            return
        if self.path == "/api/demo/meta":
            settings = load_settings(argv=[])
            self._send_json({"agents": [], "model": settings.model})
            return
        if self.path == "/api/demo/prompts":
            settings = load_settings(argv=[])
            self._send_json({"prompts": get_prompt_sections(max_rounds=12), "model": settings.model})
            return
        if parsed.path == "/api/demo/history":
            settings = load_settings(argv=[])
            params = parse_qs(parsed.query)
            thread_id = (params.get("thread_id") or [""])[0].strip()
            history = (
                fetch_thread_history(settings=settings, thread_id=thread_id)
                if thread_id
                else fetch_latest_thread_history(settings=settings)
            )
            if history:
                history["ui_state"] = fetch_thread_ui_state(settings=settings, thread_id=history["thread_id"]) or {}
            self._send_json(history or {"thread_id": "", "sessions": [], "ui_state": {}})
            return
        if parsed.path == "/api/demo/history/threads":
            settings = load_settings(argv=[])
            self._send_json({"threads": list_history_threads(settings)})
            return
        if parsed.path == "/api/demo/thread-state":
            settings = load_settings(argv=[])
            params = parse_qs(parsed.query)
            thread_id = (params.get("thread_id") or [""])[0].strip()
            self._send_json({"thread_id": thread_id, "ui_state": fetch_thread_ui_state(settings=settings, thread_id=thread_id) or {}})
            return
        if parsed.path == "/api/demo/workspace-file":
            self._handle_workspace_file(parsed)
            return
        if self.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/demo/history":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")
            return

        settings = load_settings(argv=[])
        params = parse_qs(parsed.query)
        thread_id = (params.get("thread_id") or [""])[0].strip()
        if not thread_id:
            self._send_json({"error": "thread_id_required"}, status=HTTPStatus.BAD_REQUEST)
            return

        deleted = delete_thread_history(settings=settings, thread_id=thread_id)
        latest = fetch_latest_thread_history(settings=settings)
        self._send_json(
            {
                "ok": deleted,
                "deleted_thread_id": thread_id,
                "latest_thread_id": latest["thread_id"] if latest else "",
            },
            status=HTTPStatus.OK if deleted else HTTPStatus.NOT_FOUND,
        )

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_ndjson_stream(
        self,
        settings,
        query: str,
        thread_id: str,
        session_id: str,
        max_rounds: int,
        messages: list[dict[str, str]] | None = None,
    ) -> None:
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        for event in run_demo_session_stream(settings=settings, query=query, max_rounds=max_rounds, messages=messages):
            try:
                line = json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"
                self.wfile.write(line)
                self.wfile.flush()
                if event["type"] in {"done", "error"}:
                    upsert_chat_session(
                        settings=settings,
                        thread_id=thread_id,
                        session_id=session_id,
                        query_text=query,
                        payload=event["payload"],
                        error_text=event["payload"].get("stop_reason", "") if event["type"] == "error" else "",
                    )
            except (BrokenPipeError, ConnectionResetError):
                break

    def _handle_workspace_file(self, parsed) -> None:
        params = parse_qs(parsed.query)
        relative_path = (params.get("path") or [""])[0]
        download = ((params.get("download") or ["0"])[0] == "1")
        if not relative_path.strip():
            self._send_json({"error": "path_required"}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            file_path = resolve_workspace_file(relative_path)
        except FileNotFoundError:
            self._send_json({"error": "file_not_found"}, status=HTTPStatus.NOT_FOUND)
            return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        body = file_path.read_bytes()
        mime_type, _ = mimetypes.guess_type(file_path.name)
        mime_type = mime_type or "application/octet-stream"
        disposition = "attachment" if download else "inline"
        download_name = _ascii_download_name(file_path.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'{disposition}; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(body)


def _ascii_download_name(name: str) -> str:
    base = name.encode("ascii", errors="ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return base or "download"


def run_demo_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    settings = load_settings(argv=[])
    ensure_chat_history_schema(settings)
    if settings.backend == "docker":
        validate_docker_backend_access(
            container_name=settings.docker_container_name,
            workspace_dir=settings.docker_workspace_dir,
            timeout=min(settings.docker_timeout, 10),
        )

    server = ThreadingHTTPServer((host, port), DemoRequestHandler)
    print(f"Demo server listening on http://{host}:{port}")
    print("POST /api/demo/run 会执行真实 create_deep_agent 调度。")
    if settings.backend == "docker":
        print(
            "Docker backend 已通过启动自检："
            f" container={settings.docker_container_name}, workspace={settings.docker_workspace_dir}"
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
