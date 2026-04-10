from __future__ import annotations

import subprocess
from pathlib import Path

from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import ExecuteResponse, SandboxBackendProtocol


class DockerWorkspaceBackend(FilesystemBackend, SandboxBackendProtocol):
    """Workspace-scoped filesystem backend with command execution inside Docker.

    File operations are constrained to the local workspace root via FilesystemBackend
    with virtual_mode enabled. Shell execution is delegated to a running Docker
    container whose working directory is the mounted workspace path.
    """

    def __init__(
        self,
        *,
        root_dir: str | Path,
        container_name: str,
        workspace_dir: str = "/workspace",
        timeout: int = 120,
        max_output_bytes: int = 100_000,
    ) -> None:
        super().__init__(root_dir=root_dir, virtual_mode=True, max_file_size_mb=10)
        self._container_name = container_name
        self._workspace_dir = workspace_dir
        self._default_timeout = timeout
        self._max_output_bytes = max_output_bytes

    @property
    def id(self) -> str:
        return f"docker:{self._container_name}"

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        effective_timeout = timeout if timeout is not None else self._default_timeout

        try:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-w",
                    self._workspace_dir,
                    self._container_name,
                    "bash",
                    "-lc",
                    command,
                ],
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
        except FileNotFoundError:
            return ExecuteResponse(
                output="docker 命令不可用。请先安装 Docker，并确保 `docker` 在 PATH 中。",
                exit_code=127,
                truncated=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = _join_process_output(exc.stdout, exc.stderr)
            if not output.strip():
                output = f"命令执行超时（{effective_timeout}s）。"
            return ExecuteResponse(
                output=output,
                exit_code=124,
                truncated=False,
            )

        output = _join_process_output(result.stdout, result.stderr)
        encoded = output.encode("utf-8", errors="replace")
        truncated = len(encoded) > self._max_output_bytes
        if truncated:
            trimmed = encoded[: self._max_output_bytes].decode("utf-8", errors="ignore")
            output = trimmed + "\n...[output truncated]"

        return ExecuteResponse(
            output=output,
            exit_code=result.returncode,
            truncated=truncated,
        )


def validate_docker_backend_access(
    *,
    container_name: str,
    workspace_dir: str = "/workspace",
    timeout: int = 10,
) -> None:
    """Fail fast if the current process cannot use the configured Docker backend."""
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-w",
                workspace_dir,
                container_name,
                "bash",
                "-lc",
                "printf codex_docker_ready",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Docker backend 自检失败：未找到 `docker` 命令。请先安装 Docker，并确保当前进程 PATH 可见。"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Docker backend 自检失败：对容器 `{container_name}` 的 `docker exec` 检查超时（{timeout}s）。"
        ) from exc

    output = _join_process_output(result.stdout, result.stderr).strip()
    if result.returncode == 0:
        return

    lowered = output.lower()
    if "permission denied while trying to connect to the docker api" in lowered:
        hint = (
            "当前启动服务的用户无权访问 Docker socket。"
            "请把该用户加入 `docker` 组后重新登录，或使用具备 Docker 权限的用户启动服务。"
        )
    elif "no such container" in lowered:
        hint = f"目标容器 `{container_name}` 不存在或未运行。"
    else:
        hint = "请检查 Docker daemon、容器名称以及当前用户的执行权限。"

    raise RuntimeError(
        "Docker backend 自检失败：无法执行 `docker exec`。\n"
        f"container: {container_name}\n"
        f"workspace: {workspace_dir}\n"
        f"detail: {output or f'exit_code={result.returncode}'}\n"
        f"hint: {hint}"
    )


def _coerce_process_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _join_process_output(stdout: str | bytes | None, stderr: str | bytes | None) -> str:
    stdout_text = _coerce_process_text(stdout)
    stderr_text = _coerce_process_text(stderr)
    return stdout_text + (("\n" + stderr_text) if stderr_text else "")
