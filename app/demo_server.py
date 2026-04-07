from __future__ import annotations

import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.agent import get_subagent_catalog, register_subagent
from app.config import load_settings
from app.demo_session import run_demo_session_stream


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_ROOT = PROJECT_ROOT / "frontend_demo"


class DemoRequestHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_ROOT), **kwargs)

    def do_POST(self) -> None:
        if self.path == "/api/demo/subagents":
            self._handle_create_subagent()
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
        max_rounds = int(payload.get("max_rounds", 12) or 12)
        raw_messages = payload.get("messages", [])
        if not query:
            self._send_json({"error": "query_required"}, status=HTTPStatus.BAD_REQUEST)
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
            self._send_ndjson_stream(settings=settings, query=query, max_rounds=max_rounds, messages=messages)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

    def _handle_create_subagent(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "invalid_json"}, status=HTTPStatus.BAD_REQUEST)
            return

        required_fields = ["name", "display_name", "role", "description", "system_prompt"]
        missing = [field for field in required_fields if not str(payload.get(field, "")).strip()]
        if missing:
            self._send_json(
                {"error": f"missing_fields: {', '.join(missing)}"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        try:
            created = register_subagent(
                name=str(payload["name"]),
                display_name=str(payload["display_name"]),
                role=str(payload["role"]),
                description=str(payload["description"]),
                system_prompt=str(payload["system_prompt"]),
            )
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._send_json({"agent": created, "agents": get_subagent_catalog()}, status=HTTPStatus.CREATED)

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self._send_json({"ok": True})
            return
        if self.path == "/api/demo/meta":
            self._send_json({"agents": get_subagent_catalog()})
            return
        if self.path == "/":
            self.path = "/index.html"
        super().do_GET()

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

    def _send_ndjson_stream(self, settings, query: str, max_rounds: int, messages: list[dict[str, str]] | None = None) -> None:
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
            except (BrokenPipeError, ConnectionResetError):
                break


def run_demo_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    server = ThreadingHTTPServer((host, port), DemoRequestHandler)
    print(f"Demo server listening on http://{host}:{port}")
    print("POST /api/demo/run 会执行真实 create_deep_agent 调度。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
