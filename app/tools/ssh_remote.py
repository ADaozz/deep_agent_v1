from __future__ import annotations

import shlex

from langchain_core.tools import tool

from app.config import env_bool, env_int, env_str


@tool
def ssh_execute(host_ip: str, command: str) -> str:
    """通过 SSH 连接远程机器并执行 shell 命令。

    该工具基于 paramiko，以非交互方式执行远程命令。
    除非任务目标非常明确，否则尽量使用单一、聚焦的命令，避免使用
    `&&`、`;`、管道或复杂 shell 控制流组成的复合命令。更简单的命令
    更利于 LLM 推理、验证和收敛。
    默认应以只读检查、信息收集、状态诊断为主。不要在远程机器上执行
    新增、删除、修改、安装、重启或其他会改变系统状态的操作，除非
    任务明确要求且目标动作没有歧义。

    环境变量：
    - `DEEP_AGENT_SSH_USER`：默认远程用户名，可选
    - `DEEP_AGENT_SSH_PORT`：SSH 端口，可选，默认 `22`
    - `DEEP_AGENT_SSH_CONNECT_TIMEOUT`：连接超时，可选，默认 `10`
    - `DEEP_AGENT_SSH_TIMEOUT`：命令执行超时，可选，默认 `120`
    - `DEEP_AGENT_SSH_PASSWORD`：密码，可选
    - `DEEP_AGENT_SSH_KEY_PATH`：私钥路径，可选
    - `DEEP_AGENT_SSH_ALLOW_AGENT`：是否使用 ssh-agent，默认 `true`
    - `DEEP_AGENT_SSH_LOOK_FOR_KEYS`：是否搜索本地密钥，默认 `true`
    - `DEEP_AGENT_SSH_STRICT_HOST_KEY`：是否强制校验 known_hosts，默认 `false`
    """
    try:
        import paramiko
    except ImportError:
        return "ssh_execute 失败：未安装 paramiko，请先执行 `pip install paramiko` 或重新安装 requirements。"

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
