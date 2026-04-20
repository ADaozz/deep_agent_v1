from __future__ import annotations

import glob
import json
import shlex
import smtplib
from functools import lru_cache
from email.message import EmailMessage
from pathlib import Path
import mimetypes
import re

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import PROJECT_ROOT, env_bool, env_int, env_str


CUSTOM_TOOL_METADATA = {
    "resolve_cmdb_service_context": {"scope": "shared"},
    "send_email_with_attachment": {"scope": "supervisor"},
    "tavily_search": {"scope": "worker"},
    "ssh_execute": {"scope": "worker"},
}


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


def _tavily_credentials() -> list[tuple[str, str]]:
    primary_key = env_str("TAVILY_API_KEY_LWT").strip()
    backup_key = env_str("TAVILY_API_KEY_LWT_BK").strip()
    credentials: list[tuple[str, str]] = []
    if primary_key:
        credentials.append(("primary", primary_key))
    if backup_key and backup_key != primary_key:
        credentials.append(("backup", backup_key))
    return credentials


def _should_try_backup_tavily_key(exc: Exception) -> bool:
    message = f"{type(exc).__name__}: {exc}".lower()
    fallback_markers = (
        "quota",
        "credit",
        "usage",
        "exhaust",
        "limit",
        "rate",
        "429",
        "402",
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "payment",
        "insufficient",
    )
    return any(marker in message for marker in fallback_markers)


def _format_tavily_failure(query: str, failures: list[str]) -> str:
    failure_text = "\n".join(failures) if failures else "unknown_error"
    return (
        "tavily_search 失败\n"
        f"query: {query}\n"
        f"output:\n{failure_text}"
    )


CMDB_ROOT = PROJECT_ROOT / "sys_cmdb"
CMDB_MARKDOWN = CMDB_ROOT / "CMDB.md"
DEPLOYMENT_MAP_ROOT = CMDB_ROOT / "deployment_map"
WORKSPACE_ROOT = PROJECT_ROOT / "workspace"


class RelatedService(BaseModel):
    service_name: str = Field(description="与 query 相关的服务名，必须与 CMDB 中服务名一致。")
    upstream_services: list[str] = Field(default_factory=list, description="该服务在当前问题语境下的一跳上游服务名。")
    downstream_services: list[str] = Field(default_factory=list, description="该服务在当前问题语境下的一跳下游服务名。")


class CmdbServiceSelection(BaseModel):
    services: list[RelatedService] = Field(default_factory=list, description="与 query 最相关的服务及其一跳上下游。")
    reasoning: str = Field(default="", description="为什么这些服务与 query 相关。")


CmdbServiceSelection.model_rebuild()


def _make_internal_llm() -> ChatOpenAI:
    api_key = env_str("OPENAI_API_KEY") or env_str("DASHSCOPE_API_KEY")
    base_url = env_str("OPENAI_BASE_URL") or env_str("DASHSCOPE_BASE_URL")
    model = env_str("OPENAI_MODEL") or env_str("DASHSCOPE_MODEL") or "gpt-4o-mini"
    if not api_key:
        raise RuntimeError("模型凭据未配置。")
    kwargs = {
        "model": model,
        "api_key": api_key,
        "timeout": max(30, env_int("DEEP_AGENT_MODEL_TIMEOUT", 300)),
        "max_retries": max(0, env_int("DEEP_AGENT_MODEL_MAX_RETRIES", 2)),
    }
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


def _mail_settings() -> dict[str, object]:
    smtp_host = env_str("DEEP_AGENT_MAIL_SMTP_HOST", "smtp.163.com").strip() or "smtp.163.com"
    smtp_port = env_int("DEEP_AGENT_MAIL_SMTP_PORT", 465)
    smtp_user = env_str("DEEP_AGENT_MAIL_SMTP_USER").strip()
    smtp_password = env_str("DEEP_AGENT_MAIL_SMTP_PASSWORD").strip()
    from_name = env_str("DEEP_AGENT_MAIL_FROM_NAME", "Deep Agent").strip() or "Deep Agent"
    subject = env_str("DEEP_AGENT_MAIL_SUBJECT", "Deep Agent Notification").strip() or "Deep Agent Notification"
    return {
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_user": smtp_user,
        "smtp_password": smtp_password,
        "from_name": from_name,
        "subject": subject,
    }


def _resolve_mail_attachment_path(attachment_path: str) -> Path:
    raw_path = attachment_path.strip()
    if not raw_path:
        raise ValueError("缺少 attachment_path。")
    path = Path(raw_path)
    candidate = path if path.is_absolute() else (PROJECT_ROOT / path).resolve()
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"附件不存在: {raw_path}")
    try:
        candidate.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("附件路径必须位于项目目录内。") from exc
    return candidate


def _html_to_plain_text(html_body: str) -> str:
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", html_body, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or "请查看 HTML 正文。"


def _attach_file(message: EmailMessage, attachment_file: Path) -> None:
    mime_type, _encoding = mimetypes.guess_type(attachment_file.name)
    if mime_type:
        maintype, subtype = mime_type.split("/", 1)
    else:
        maintype, subtype = "application", "octet-stream"
    message.add_attachment(
        attachment_file.read_bytes(),
        maintype=maintype,
        subtype=subtype,
        filename=attachment_file.name,
    )


@lru_cache(maxsize=1)
def _read_cmdb_markdown() -> str:
    if not CMDB_MARKDOWN.exists():
        raise FileNotFoundError(f"CMDB 文件不存在: {CMDB_MARKDOWN}")
    return CMDB_MARKDOWN.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _load_deployment_map() -> dict[str, dict]:
    if not DEPLOYMENT_MAP_ROOT.exists():
        raise FileNotFoundError(f"deployment_map 目录不存在: {DEPLOYMENT_MAP_ROOT}")
    mapping: dict[str, dict] = {}
    for file_path in sorted(glob.glob(str(DEPLOYMENT_MAP_ROOT / "*.json"))):
        path = Path(file_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        service_name = str(payload.get("service_name", "")).strip()
        if service_name:
            mapping[service_name] = payload
    return mapping


def _dedupe_service_names(names: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in names:
        normalized = str(item).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _normalize_service_relation(item: RelatedService) -> dict[str, object]:
    service_name = item.service_name.strip()
    upstream = _dedupe_service_names(item.upstream_services)
    downstream = _dedupe_service_names(item.downstream_services)
    upstream = [name for name in upstream if name != service_name]
    downstream = [name for name in downstream if name != service_name]
    return {
        "service_name": service_name,
        "upstream_services": upstream,
        "downstream_services": downstream,
    }


@tool
def resolve_cmdb_service_context(query: str) -> str:
    """根据用户问题从 CMDB 中提取相关服务，并补全一跳上下游与部署信息。

    何时使用：
    - 用户问题涉及系统、服务、链路、故障、调用关系、部署位置、日志位置或上下游依赖。
    - 需要先从 CMDB 中确定问题相关的服务集合，再继续做排障、巡检或关系分析。

    使用规则：
    - 只接受一个自然语言 `query`。
    - 内部会读取 `sys_cmdb/CMDB.md`，提取与 query 相关的服务名以及一跳上下游服务。
    - 服务名必须使用 CMDB 中出现的标准名称，不要自行编造别名。
    - 提取出的服务会再去 `sys_cmdb/deployment_map/*.json` 匹配部署信息。

    返回：
    - JSON 字符串，包含 matched_service_names、services、deployment_missing_services 和 reasoning。
    - 每个 service 节点都会带 upstream_services、downstream_services 和 deployment 信息。
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        return "resolve_cmdb_service_context 失败：缺少 query。"

    try:
        cmdb_markdown = _read_cmdb_markdown()
        deployment_map = _load_deployment_map()
        llm = _make_internal_llm()
    except Exception as exc:  # noqa: BLE001
        return f"resolve_cmdb_service_context 失败：{type(exc).__name__}: {exc}"

    structured_llm = llm.with_structured_output(CmdbServiceSelection)
    prompt = (
        "你正在从 CMDB 文档中为一个排障/架构问题抽取相关服务。\n"
        "要求：\n"
        "1. 只返回 CMDB 文档里真实出现的标准服务名。\n"
        "2. 先找与 query 直接相关的核心服务，再补充这些核心服务的一跳上游和一跳下游。\n"
        "3. 不要返回中间件名称、数据库名称、产品名、页面标题；只返回服务名。\n"
        "4. upstream_services / downstream_services 只保留一跳，不要扩散成全链路。\n"
        "5. 如果 query 太模糊，尽量返回最可能相关的少量服务，不要泛化整个系统。\n\n"
        f"用户 query:\n{cleaned_query}\n\n"
        f"CMDB 文档:\n{cmdb_markdown}"
    )

    try:
        selection = structured_llm.invoke(prompt)
    except Exception as exc:  # noqa: BLE001
        return f"resolve_cmdb_service_context 失败：LLM 解析 CMDB 时出错: {type(exc).__name__}: {exc}"

    normalized_services = []
    matched_names: list[str] = []
    deployment_missing_services: list[str] = []
    for item in selection.services:
        normalized = _normalize_service_relation(item)
        service_name = str(normalized["service_name"]).strip()
        if not service_name:
            continue
        matched_names.append(service_name)
        deployment = deployment_map.get(service_name)
        if deployment is None:
            deployment_missing_services.append(service_name)
        normalized_services.append(
            {
                **normalized,
                "deployment": deployment,
            }
        )

    payload = {
        "query": cleaned_query,
        "matched_service_names": _dedupe_service_names(matched_names),
        "services": normalized_services,
        "deployment_missing_services": _dedupe_service_names(deployment_missing_services),
        "reasoning": selection.reasoning,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


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

    credentials = _tavily_credentials()
    if not credentials:
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

    failures: list[str] = []
    for index, (credential_label, api_key) in enumerate(credentials):
        try:
            client = TavilyClient(api_key=api_key)
            response = client.search(**request_kwargs)
            if credential_label == "backup":
                response["_tool_meta"] = {"credential": "backup", "fallback_used": index > 0}
            return json.dumps(response, ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{credential_label}: {type(exc).__name__}: {exc}")
            has_backup = any(label == "backup" for label, _key in credentials[index + 1 :])
            if credential_label == "primary" and has_backup and _should_try_backup_tavily_key(exc):
                continue
            return _format_tavily_failure(cleaned_query, failures)

    return _format_tavily_failure(cleaned_query, failures)


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


@tool
def send_email_with_attachment(target_email: str, html_body: str, attachment_path: str) -> str:
    """向目标邮箱发送 HTML 邮件，并附带一个项目目录内的附件。

    何时使用：
    - supervisor 已生成报告、结论或文件，需要通过邮件发送给指定收件人。
    - 用户明确要求邮件通知或邮件投递。

    使用边界：
    - 只接受一个目标邮箱、HTML 正文和一个附件路径。
    - 附件路径优先使用项目根目录内的相对路径，例如 `result/report.md` 或 `workspace/report.md`。
    - 不要传目录路径；只允许传单个已存在文件。

    推荐邮件模板（中文正式通用版）：
    - 标题模板：`【情况说明/结果通知】{主题关键词}`
    - HTML 正文模板：
      `<p>尊敬的同事/老师/负责人，您好：</p>`
      `<p>现将 <strong>{事项名称}</strong> 的处理结果同步如下：</p>`
      `<ul>`
      `<li><strong>背景</strong>：{一句话说明背景}</li>`
      `<li><strong>结论</strong>：{一句话说明结论}</li>`
      `<li><strong>附件说明</strong>：详见随附文件 {附件名称}</li>`
      `</ul>`
      `<p>如需我继续跟进，请直接回复此邮件。</p>`
      `<p>此致<br/>敬礼</p>`
      `<p>{署名}</p>`

    写作要求：
    - 标题保持正式、简洁、可检索，避免口语化表达。
    - 正文先交代背景，再给结论，最后说明附件和后续动作。
    - 附件是主要信息载体时，正文只做摘要，不要重复整份报告。

    返回：
    - JSON 字符串，包含 recipient、subject、attachment_path 和 status。
    """
    recipient = target_email.strip()
    if not recipient:
        return "send_email_with_attachment 失败：缺少 target_email。"
    if not html_body.strip():
        return "send_email_with_attachment 失败：缺少 html_body。"

    try:
        settings = _mail_settings()
        smtp_user = str(settings["smtp_user"]).strip()
        smtp_password = str(settings["smtp_password"]).strip()
        if not smtp_user or not smtp_password:
            return "send_email_with_attachment 失败：邮件凭据未配置，请检查 .env 中的 DEEP_AGENT_MAIL_* 配置。"
        attachment_file = _resolve_mail_attachment_path(attachment_path)
        message = EmailMessage()
        message["From"] = f'{settings["from_name"]} <{smtp_user}>'
        message["To"] = recipient
        message["Subject"] = str(settings["subject"])
        message.set_content(_html_to_plain_text(html_body))
        message.add_alternative(html_body, subtype="html")
        _attach_file(message, attachment_file)

        with smtplib.SMTP_SSL(str(settings["smtp_host"]), int(settings["smtp_port"])) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)
    except Exception as exc:  # noqa: BLE001
        return f"send_email_with_attachment 失败：{type(exc).__name__}: {exc}"

    payload = {
        "status": "sent",
        "recipient": recipient,
        "subject": str(settings["subject"]),
        "attachment_path": attachment_file.relative_to(PROJECT_ROOT).as_posix(),
        "sender": smtp_user,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
