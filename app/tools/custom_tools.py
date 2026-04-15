from __future__ import annotations

import json
import shlex

from langchain_core.tools import tool

from app.config import env_bool, env_int, env_str


def _split_domains(raw_domains: str) -> list[str]:
    return [domain.strip() for domain in raw_domains.split(",") if domain.strip()]


def _bounded_int(value: int, *, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


def _bounded_float(value: float, *, minimum: float, maximum: float, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


@tool
def tavily_search(
    query: str,
    search_depth: str = "basic",
    topic: str = "general",
    max_results: int = 5,
    include_answer: bool = False,
    include_raw_content: bool = False,
    include_images: bool = False,
    include_image_descriptions: bool = False,
    include_domains: str = "",
    exclude_domains: str = "",
    time_range: str = "",
    start_date: str = "",
    end_date: str = "",
    country: str = "",
    auto_parameters: bool = False,
    exact_match: bool = False,
    include_favicon: bool = False,
    include_usage: bool = False,
    timeout: float = 30.0,
) -> str:
    """使用 Tavily Search 搜索互联网信息。

    何时使用：
    - 用户问题依赖最新互联网信息、新闻、外部资料、官网文档或公开网页来源。
    - 当前 workspace 和已有上下文不足以回答，需要补充外部证据。

    使用边界：
    - 查询必须具体，避免只写宽泛关键词。
    - 默认使用 `basic` 搜索；只有需要更高相关性或更多片段时才使用 `advanced`。
    - `include_raw_content=True` 会显著增加返回体积，只在确实需要网页正文时使用。
    - 如果用户要求引用来源，优先返回 title、url、content 和 score。
    - 不要把搜索结果当作最终事实，重要结论需要结合来源内容说明。

    关键参数：
    - `query`：搜索问题或关键词。
    - `topic`：`general`、`news` 或 `finance`。
    - `max_results`：返回结果数，0 到 20。
    - `include_domains` / `exclude_domains`：英文逗号分隔的域名列表。
    - `time_range`、`start_date`、`end_date`：用于限制时效范围。

    返回：
    - JSON 字符串，包含 query、answer、results、images、response_time、request_id 等字段。
    """
    try:
        from tavily import TavilyClient
    except ImportError:
        return "tavily_search 失败：搜索工具依赖不可用，请让用户检查后端依赖配置。"

    cleaned_query = query.strip()
    if not cleaned_query:
        return "tavily_search 失败：缺少 query。"

    api_key = env_str("TAVILY_API_KEY_LWT").strip()
    if not api_key:
        return "tavily_search 失败：搜索凭据未配置，请让用户检查工具后端配置。"

    normalized_depth = search_depth.strip().lower()
    if normalized_depth not in {"basic", "advanced"}:
        normalized_depth = "basic"

    normalized_topic = topic.strip().lower()
    if normalized_topic not in {"general", "news", "finance"}:
        normalized_topic = "general"

    request_kwargs = {
        "query": cleaned_query,
        "search_depth": normalized_depth,
        "topic": normalized_topic,
        "max_results": _bounded_int(max_results, minimum=0, maximum=20, default=5),
        "include_answer": bool(include_answer),
        "include_raw_content": bool(include_raw_content),
        "include_images": bool(include_images),
        "include_image_descriptions": bool(include_image_descriptions),
        "include_domains": _split_domains(include_domains),
        "exclude_domains": _split_domains(exclude_domains),
        "auto_parameters": bool(auto_parameters),
        "exact_match": bool(exact_match),
        "include_favicon": bool(include_favicon),
        "include_usage": bool(include_usage),
        "timeout": _bounded_float(timeout, minimum=1.0, maximum=60.0, default=30.0),
    }
    optional_text_params = {
        "time_range": time_range.strip(),
        "start_date": start_date.strip(),
        "end_date": end_date.strip(),
        "country": country.strip(),
    }
    request_kwargs.update({key: value for key, value in optional_text_params.items() if value})

    try:
        client = TavilyClient(api_key=api_key)
        response = client.search(**request_kwargs)
    except Exception as exc:  # noqa: BLE001
        return (
            "tavily_search 失败\n"
            f"query: {cleaned_query}\n"
            f"output:\n{type(exc).__name__}: {exc}"
        )

    return json.dumps(response, ensure_ascii=False, indent=2)


@tool
def ssh_execute(host_ip: str, command: str) -> str:
    """通过 SSH 连接远程机器并执行 shell 命令。

    何时使用：
    - 用户要求检查远程主机、远程目录、远程日志、服务状态、端口、进程或系统参数。
    - 任务目标明确需要在指定 `host_ip` 上取证。

    使用边界：
    - 默认只做只读检查、信息收集和状态诊断。
    - 除非用户明确要求且动作没有歧义，不要执行写入、删除、安装、重启、停止服务等会改变远程状态的命令。
    - 优先使用单一、聚焦的命令，避免复杂 shell 控制流。
    - 需要多步取证时，分多次调用，每次只验证一个明确事实。
    - 不要把本地 `execute` 当作远程执行工具；远程命令必须使用本工具。

    输入：
    - `host_ip`：目标主机地址。
    - `command`：要在目标主机上执行的 shell 命令。

    返回：
    - 文本结果，包含 target、command、exit_code 和 output。
    """
    try:
        import paramiko
    except ImportError:
        return "ssh_execute 失败：SSH 工具依赖不可用，请让用户检查后端依赖配置。"

    host_ip = host_ip.strip()
    command = command.strip()
    if not host_ip:
        return "ssh_execute 失败：缺少 host_ip。"
    if not command:
        return "ssh_execute 失败：缺少 command。"

    ssh_user = env_str("DEEP_AGENT_SSH_USER").strip()
    ssh_port = env_int("DEEP_AGENT_SSH_PORT", 22)
    connect_timeout = env_int("DEEP_AGENT_SSH_CONNECT_TIMEOUT", 10)
    command_timeout = env_int("DEEP_AGENT_SSH_TIMEOUT", 120)
    ssh_password = env_str("DEEP_AGENT_SSH_PASSWORD")
    ssh_key_path = env_str("DEEP_AGENT_SSH_KEY_PATH").strip()
    allow_agent = env_bool("DEEP_AGENT_SSH_ALLOW_AGENT", True)
    look_for_keys = env_bool("DEEP_AGENT_SSH_LOOK_FOR_KEYS", True)
    strict_host_key = env_bool("DEEP_AGENT_SSH_STRICT_HOST_KEY", False)

    target = f"{ssh_user}@{host_ip}" if ssh_user else host_ip
    remote_command = f"bash -lc {shlex.quote(command)}"
    client = paramiko.SSHClient()
    if strict_host_key:
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs = {
        "hostname": host_ip,
        "port": ssh_port,
        "timeout": connect_timeout,
        "banner_timeout": connect_timeout,
        "auth_timeout": connect_timeout,
        "allow_agent": allow_agent,
        "look_for_keys": look_for_keys,
    }
    if ssh_user:
        connect_kwargs["username"] = ssh_user
    if ssh_password:
        connect_kwargs["password"] = ssh_password
    if ssh_key_path:
        connect_kwargs["key_filename"] = ssh_key_path

    try:
        client.connect(**connect_kwargs)
        _stdin, stdout, stderr = client.exec_command(remote_command, timeout=command_timeout)
        stdout_text = stdout.read().decode("utf-8", errors="replace")
        stderr_text = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
    except paramiko.AuthenticationException as exc:
        return (
            f"ssh_execute 认证失败\n"
            f"target: {target}\n"
            f"command: {command}\n"
            f"output:\n{exc}"
        )
    except paramiko.BadHostKeyException as exc:
        return (
            f"ssh_execute 主机密钥校验失败\n"
            f"target: {target}\n"
            f"command: {command}\n"
            f"output:\n{exc}"
        )
    except TimeoutError:
        return (
            f"ssh_execute 超时\n"
            f"target: {target}\n"
            f"command: {command}\n"
            f"exit_code: 124\n"
            f"output:\n命令执行超时（{command_timeout}s）。"
        )
    except Exception as exc:  # noqa: BLE001
        return (
            f"ssh_execute 失败\n"
            f"target: {target}\n"
            f"command: {command}\n"
            f"output:\n{exc}"
        )
    finally:
        client.close()

    output = stdout_text + (("\n" + stderr_text) if stderr_text else "")
    output = output.strip() or "(no output)"
    return (
        f"ssh_execute 完成\n"
        f"target: {target}\n"
        f"command: {command}\n"
        f"exit_code: {exit_code}\n"
        f"output:\n{output}"
    )
