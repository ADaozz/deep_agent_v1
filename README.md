# deep_agent_v1

一个基于 `create_deep_agent` 的真实多 Agent 协同调度 Demo。

项目包含两套入口：

- CLI 运行模式：直接在终端里观察 `create_deep_agent` 的流式执行过程
- Web Demo 模式：通过一个零构建前端页面可视化展示 Supervisor、Action List、Round、Worker checklist、Execution Log 和 Final Summary

这个仓库的重点不是“静态模拟多 agent UI”，而是把真实 `create_deep_agent` 调度过程解析成前端可消费的结构化状态。

## 主页效果图

下面两张截图来自 `img/`，用于展示 Web Demo 首页的整体布局和主题效果。

![主页效果图（主题1）](img/主题1.jpg)

![主页效果图（主题2）](img/主题2.jpg)

## 完整测试流程（导出结果）

`Supervisor Conversation Runtime.html` 是一次完整测试流程的导出结果，包含当次会话内的 Action List、Round Trace、Worker checklist、Execution Log 与最终输出等信息。

- 入口文件：`Supervisor Conversation Runtime.html`
- 资源目录：`Supervisor Conversation Runtime_files/`

本地查看时直接用浏览器打开 `Supervisor Conversation Runtime.html` 即可（需要同目录下的 `_files/` 资源目录同时存在）。

## 主要能力

- Supervisor 先调用 `write_todos` 拆分主任务
- Supervisor 在 `write_todos` 之后调用 `generate_subagents` 获取“本轮 worker 名册”，再用 `task` 把独立维度派发给多个子 worker
- 子 worker 通过 `write_evidence_todos` 维护自己的私有 checklist
- 子 worker 只有在 checklist 全部 `completed` / `blocked` 且带 evidence 时才允许结束
- 将“业务受阻”和“系统错误”分开建模，避免把目标不可达误判成程序报错
- 支持真实流式事件订阅：`updates`、`messages`、`custom`
- 支持前端多轮对话
- 支持运行时注册长期子 Agent，同时支持按 query 生成动态 worker
- 支持 Markdown / Mermaid 格式的最终回答渲染
- 落盘结构化 JSONL 运行日志，便于后续排查和审计

## 项目结构

```text
deep_agent_v1/
├── app/
│   ├── agent/
│   │   ├── builder.py
│   │   └── todo_enforcer.py
│   ├── backends/
│   │   ├── __init__.py
│   │   └── docker_workspace.py
│   ├── streaming/
│   │   └── stream_logger.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── ssh_remote.py
│   │   └── subagent_roster.py
│   ├── config.py
│   ├── demo_server.py
│   ├── demo_session.py
│   ├── logging_utils.py
│   ├── prompts.py
│   └── runner.py
├── frontend_demo/
│   ├── app.js
│   ├── index.html
│   └── styles.css
├── runtime_logs/
├── img/
├── Supervisor Conversation Runtime.html
├── Supervisor Conversation Runtime_files/
├── main.py
├── requirements.txt
├── serve_demo.py
└── README.md
```

## 项目架构

当前实现可以理解为四层：

1. Agent 组装层
   - [builder.py](/mnt/d/pycode/agent/deep_agent_v1/app/agent/builder.py)
   - [prompts.py](/mnt/d/pycode/agent/deep_agent_v1/app/prompts.py)
   - [todo_enforcer.py](/mnt/d/pycode/agent/deep_agent_v1/app/agent/todo_enforcer.py)
   - 负责根据 query 生成本轮 worker 名册、拼出 supervisor / worker 提示词、挂载中间件和工具

2. 执行层
   - `create_deep_agent(...)`
   - [docker_workspace.py](/mnt/d/pycode/agent/deep_agent_v1/app/backends/docker_workspace.py)
   - 负责真正跑 supervisor 图和 worker 子图，并把文件工具 / `execute` 绑定到本地或 Docker backend

3. 状态收集与观测层
   - [demo_session.py](/mnt/d/pycode/agent/deep_agent_v1/app/demo_session.py)
   - [stream_logger.py](/mnt/d/pycode/agent/deep_agent_v1/app/streaming/stream_logger.py)
   - 负责把原始 LangGraph stream 转成前端状态、Execution Log 和结构化 JSONL 事件

4. 交互展示层
   - [demo_server.py](/mnt/d/pycode/agent/deep_agent_v1/app/demo_server.py)
   - [app.js](/mnt/d/pycode/agent/deep_agent_v1/frontend_demo/app.js)
   - [styles.css](/mnt/d/pycode/agent/deep_agent_v1/frontend_demo/styles.css)
   - 负责提供 Web API、推送 NDJSON 流，并在前端渲染会话、任务、round、worker 和最终回答

用一条链概括就是：

`用户 query -> build_agent_bundle(query) -> supervisor -> task 派发 -> worker 子图执行 -> collector 转状态/日志 -> 前端渲染`

## 核心模块说明

### 后端

- `app/agent/builder.py`
  - 入口是 `build_agent_bundle(settings, query)`
  - 先根据 query 规划本轮专属 worker，再拼出完整 `subagents`
  - 为 supervisor 注入 `generate_subagents` 工具，用于获取本轮 worker 名册（名册的 id 是唯一允许的 `subagent_type`）
  - supervisor 不挂载 `ssh_execute`；远程执行能力只给 worker
  - 选择 `filesystem` / `docker` backend，并统一把文件工具锚定到 `workspace/`

- `app/backends/docker_workspace.py`
  - Docker 执行 backend
  - 文件工具仍绑定本地 workspace
  - `execute` 通过 `docker exec` 进入容器执行
  - 启动时支持 Docker 权限与容器可达性自检

- `app/agent/todo_enforcer.py`
  - 子 worker 的 checklist 运行时守卫
  - 强制每个私有 todo 带 evidence
  - 防止 worker 在未完成 checklist 时提前结束
  - 把 `blocked` 作为正式状态，要求“做不成”也必须给出阻塞证据

- `app/tools/ssh_remote.py`
  - 提供可被 LLM 调用的 `ssh_execute(host_ip, command)`
  - 基于 `paramiko` 做非交互式 SSH 远程执行
  - 默认从 `.env` 读取用户名、端口、密钥和超时设置
  - 当前只暴露给 worker，不暴露给 supervisor

- `app/prompts.py`
  - supervisor 与 worker 的提示词
  - 约束“最终总结只能由 supervisor 完成”
  - 约束动态 worker 只能处理叶子分片任务
  - 明确远程检查、SSH、服务探测等落地执行必须先派发给 worker

- `app/demo_session.py`
  - Web Demo 的核心执行与状态收集器
  - 把真实 stream 转成前端可视状态
  - 维护 `tasks / rounds / agents / logs / final_summary`
  - 把原始工具调用和 round 收敛过程写成结构化 JSONL 事件
  - 只有当 supervisor 真正 `task` 派发后，才会在 collector 中物化对应 worker

- `app/demo_server.py`
  - 一个基于 `ThreadingHTTPServer` 的轻量 HTTP 服务
  - 提供前端页面和 API
  - `/api/demo/meta` 返回当前模型名和长期注册 worker 元数据
  - `/api/demo/run` 返回 NDJSON 流式状态快照

- `app/runner.py`
  - CLI 模式运行入口
  - 用于终端观察原始流式执行过程

### 前端

- `frontend_demo/index.html`
  - 通过 import map 直接加载前端依赖
  - 无需构建工具

- `frontend_demo/app.js`
  - 整个 Demo 页面逻辑
  - 负责流式消费 `/api/demo/run`
  - 负责多轮会话状态管理
  - 负责渲染：
    - 顶部状态卡片
    - User Query
    - Action List
    - Workers And Checklists
    - Round Trace
    - Execution Log
    - Final Summary

- `frontend_demo/styles.css`
  - 页面样式与主题

## 总调度逻辑

当前项目的“总调度”不是固定 3 个 worker 的老式模板，而是按 query 临时构建一轮专属运行时图。

一次典型执行流程如下：

1. 前端把用户 query 和历史 `messages` 发给 `/api/demo/run`
2. 后端先执行 `build_agent_bundle(settings, query)`
3. `builder.py` 用模型规划本轮专属 worker，并把名册封装进 supervisor 可调用的 `generate_subagents` 工具
4. 后端把“supervisor + 本轮 worker + backend + middleware”一起交给 `create_deep_agent(...)` 启动
5. supervisor 进入第一轮推理，先调用 `write_todos` 建立主 `Action List`
6. supervisor 调用 `generate_subagents` 获取本轮 worker 名册（含 planner_error）
7. supervisor 根据主任务与名册，调用 `task` 把叶子分片派发给真实 worker（必须使用名册里返回的 id）
8. `demo_session.py` 在看到 `task` 时创建 round，并把 `task -> agent -> round` 绑定起来
9. worker 进入自己的子图后，必须先调用 `write_evidence_todos`
10. worker 再调用框架内置工具或项目工具执行局部任务，并持续更新 evidence checklist
11. checklist 全部满足后，worker 才能向 supervisor 回报
12. collector 根据 worker 回报把状态归类为 `done / blocked / error`
13. 当一轮所有派发任务收敛后，supervisor 决定是否继续下一轮，或直接生成最终回答
14. collector 把真实运行状态实时转换成 NDJSON 快照推给前端

几个关键约束：

- supervisor 的职责只有调度、决策、收敛，不负责代替 worker 做远程落地执行
- 最终总结只能由 supervisor 完成，不能再派一个 summarizer 类 worker
- `blocked` 表示目标条件不满足、权限不足、目标不可达或信息拿不到
- `error` 表示程序、工具、运行环境本身出错

## 子 Agent 逻辑

### 1. 子 Agent 不是固定槽位

当前实现不会默认沿用固定槽位式 worker 命名。

系统会在每次收到 query 时，先规划一组“本轮专属 worker”：

- 名称随任务变化
- 角色随任务变化
- 描述和提示词随任务变化

如果用户通过 `/api/demo/subagents` 注册了长期子 Agent，这些长期 worker 会与“本轮专属 worker”一起进入当次运行名册。

### 2. 生成时机与展示时机不同

这一点很重要：

- 运行前：`builder.py` 会先把本轮 worker 名册准备好
- 运行中：只有当 supervisor 真正调用 `task` 派发到某个 worker 时，collector 才会把它物化到前端状态中

所以前端看到的 worker 不是“候选名册”，而是“本轮真正进入执行链路的 worker”。

### 3. 工具边界

当前项目里：

- supervisor 没有项目自定义的远程执行工具
- worker 才会额外挂载 `ssh_execute`
- framework 默认内置工具仍由 `create_deep_agent` 提供

这样做的目的是强制 supervisor 先派发，再执行，避免它自己越权直接 SSH 到目标机器。

### 4. Checklist 驱动的完成机制

每个 worker 都会挂 [todo_enforcer.py](/mnt/d/pycode/agent/deep_agent_v1/app/agent/todo_enforcer.py) 里的 `EvidenceTodoMiddleware`。

worker 的私有 checklist 规则是：

- 必须先调用 `write_evidence_todos`
- 每项都要有 `content / status / evidence / evidence_type`
- `completed` 必须有强证据
- 如果证据表明“无法执行 / 无法获取 / 缺少工具 / 条件不满足”，该项必须标为 `blocked`
- 只有当所有项都变成 `completed` 或 `blocked` 后，worker 才能结束

### 5. worker 状态语义

前端和 collector 里主要有这几种 worker 状态：

- `pending`：已被 supervisor 派发，但子图还没真正跑起来
- `running`：子图已开始执行
- `done`：局部任务完成，并给出了有效回报
- `blocked`：任务链路正常，但目标条件、权限、环境或外部依赖阻塞了结果
- `error`：程序、工具、runtime、backend 本身出错

## 环境要求

- Python 3.10+
- 可用的 OpenAI-compatible 模型接口

依赖见 [requirements.txt](/mnt/d/pycode/agent/deep_agent_v1/requirements.txt)：

```txt
deepagents>=0.4.9
langchain>=1.2.10
langgraph>=1.1.0
langchain-openai>=1.1.10
paramiko>=3.5.0
python-dotenv>=1.0.1
```

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置

项目启动时会自动读取根目录下的 `.env`。

### 必需环境变量

至少配置以下之一：

- `OPENAI_API_KEY`
- `DASHSCOPE_API_KEY`

### 常用环境变量

```env
# OpenAI-compatible model config
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

# DashScope-compatible model config
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=
DASHSCOPE_MODEL=

# Logging
LOG_LEVEL=INFO
DEEP_AGENT_LOG_FILE=runtime_logs/deep_agent_stream.jsonl

# Backend mode
DEEP_AGENT_BACKEND=filesystem
DEEP_AGENT_DOCKER_CONTAINER=deep-agent-sandbox
DEEP_AGENT_DOCKER_WORKSPACE=/workspace
DEEP_AGENT_DOCKER_TIMEOUT=120

# SSH tool defaults
DEEP_AGENT_SSH_USER=
DEEP_AGENT_SSH_PORT=22
DEEP_AGENT_SSH_CONNECT_TIMEOUT=10
DEEP_AGENT_SSH_TIMEOUT=120
DEEP_AGENT_SSH_PASSWORD=
DEEP_AGENT_SSH_KEY_PATH=
DEEP_AGENT_SSH_ALLOW_AGENT=true
DEEP_AGENT_SSH_LOOK_FOR_KEYS=true
DEEP_AGENT_SSH_STRICT_HOST_KEY=false
```

也支持阿里兼容配置：

```env
DASHSCOPE_API_KEY=your-key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.5-plus
```

### 配置加载逻辑

[config.py](/mnt/d/pycode/agent/deep_agent_v1/app/config.py) 的规则是：

- 所有配置都先从项目根目录 `.env` 加载
- `model` 优先取 `--model`
- 默认取 `OPENAI_MODEL` 或 `DASHSCOPE_MODEL`
- `api_key` 优先读 `OPENAI_API_KEY`，否则读 `DASHSCOPE_API_KEY`
- `base_url` 优先读 `OPENAI_BASE_URL`，否则读 `DASHSCOPE_BASE_URL`
- backend 默认取 `DEEP_AGENT_BACKEND=filesystem`
- SSH 工具默认从 `.env` 读取 `DEEP_AGENT_SSH_*`

如果没有 API Key，启动会直接报错。

### Backend 模式

当前支持两种 backend：

- `filesystem`
  - 文件工具以仓库下的 `workspace/` 目录为沙箱根目录
  - 不提供真正的命令执行沙箱

- `docker`
  - 文件工具仍然锚定仓库下的 `workspace/`
  - `execute` 会通过 `docker exec` 在指定容器中执行

切到 Docker backend 的最小配置示例：

```env
DEEP_AGENT_BACKEND=docker
DEEP_AGENT_DOCKER_CONTAINER=deep-agent-sandbox
DEEP_AGENT_DOCKER_WORKSPACE=/workspace
DEEP_AGENT_DOCKER_TIMEOUT=120
```

对应容器示例：

```bash
docker run -d --rm \
  --name deep-agent-sandbox \
  -v /mnt/d/pycode/agent/deep_agent_v1/workspace:/workspace \
  -w /workspace \
  python:3.13-slim \
  sleep infinity
```

### `execute` 的运行边界

当前项目的 `docker` backend 不是“整个应用都在容器里运行”，而是：

- `serve_demo.py`、`demo_session.py`、前端页面、主调度流程都仍然在宿主机上运行
- 文件工具依然锚定本地 `workspace/` 目录
- 只有 `execute` 会通过 `docker exec` 在容器里运行

这意味着：

- 相对路径默认从容器内的 `DEEP_AGENT_DOCKER_WORKSPACE` 解析
- 只有挂载到 `/workspace` 的文件会与宿主机仓库共享
- 如果命令改动了容器内 `/workspace` 之外的路径，前端文件工具看不到
- 容器里必须有 `bash`
- 宿主机必须能执行 `docker`

如果你需要更强的执行沙箱，建议在启动容器时额外加上：

- `--network none`
- `--cpus`
- `--memory`
- `--pids-limit`
- `--cap-drop ALL`
- `--security-opt no-new-privileges`
- `--read-only`

### SSH 工具配置

项目内置了一个可供 LLM 调用的 `ssh_execute(host_ip, command)` 工具。

这个工具通过 `paramiko` 建立 SSH 连接，并默认读取以下 `.env` 配置：

```env
DEEP_AGENT_SSH_USER=
DEEP_AGENT_SSH_PORT=22
DEEP_AGENT_SSH_CONNECT_TIMEOUT=10
DEEP_AGENT_SSH_TIMEOUT=120
DEEP_AGENT_SSH_PASSWORD=
DEEP_AGENT_SSH_KEY_PATH=
DEEP_AGENT_SSH_ALLOW_AGENT=true
DEEP_AGENT_SSH_LOOK_FOR_KEYS=true
DEEP_AGENT_SSH_STRICT_HOST_KEY=false
```

说明：

- `host_ip` 和 `command` 是工具入参
- 用户名、端口、密钥路径、超时等由 `.env` 提供默认值
- 当前只挂在 worker 上，不挂在 supervisor 上
- 除非目标非常明确，否则应尽量避免复合命令，优先使用单一、聚焦的命令
- 这是一次性远程执行工具，不维护持久会话状态
- 默认适合已经配置好密码、私钥或 ssh-agent 的机器
- 如果要严格校验目标主机密钥，请把 `DEEP_AGENT_SSH_STRICT_HOST_KEY=true`

## 框架内置工具与项目扩展工具

`create_deep_agent` 会给 supervisor / worker 提供一组框架内置工具：

- `write_todos`
  - 维护主 todo 列表
  - 主要由 supervisor 用来拆分用户任务

- 文件系统工具
  - 包括 `ls`、`read_file`、`write_file`、`edit_file`、`glob`、`grep`
  - 当前项目已经把 workspace 根目录固定到仓库下的 `workspace/`

- `execute`
  - 执行 shell 命令
  - 在 `filesystem` backend 下会在宿主机执行，不是安全沙箱
  - 在 `docker` backend 下会通过 `docker exec` 进入容器执行

- `task`
  - 把一个独立分片任务委派给某个 worker
  - worker 完成后把结果回报给 supervisor

这个项目额外注入了以下工具 / 中间件能力：

- `generate_subagents`
  - 不是框架默认工具
  - 由 [subagent_roster.py](/mnt/d/pycode/agent/deep_agent_v1/app/tools/subagent_roster.py) 提供
  - 返回本轮 worker 名册（id/name/role/description），以及本轮规划的 `reasoning/planner_error`
  - 只暴露给 supervisor，且必须在首次 `task` 之前调用
  - supervisor 后续派发 `task` 时，`subagent_type` 必须来自名册里的 id

- `write_evidence_todos`
  - 不是框架默认工具
  - 由 [todo_enforcer.py](/mnt/d/pycode/agent/deep_agent_v1/app/agent/todo_enforcer.py) 注入
  - worker 的严格完成检测基于这套 evidence checklist，而不是普通 `write_todos`

- `ssh_execute(host_ip, command)`
  - 不是框架默认工具
  - 由 [ssh_remote.py](/mnt/d/pycode/agent/deep_agent_v1/app/tools/ssh_remote.py) 提供
  - 适合一次性远程执行聚焦命令，不适合长会话和交互式命令
  - 当前只暴露给 worker，作为“落地执行能力”使用

补充说明：

- supervisor 除了框架内置工具外，还会额外获得 `generate_subagents`（名册工具）；它不挂载远程执行工具
- worker 在框架内置工具之外，会额外获得 `ssh_execute`
- worker 运行时虽然仍然天然带有框架内置 `write_todos`，但本项目的 worker 提示词、前端展示和完成守卫都以 `write_evidence_todos` 为准
- 如果你要观察真正影响 worker 完成态的 checklist，请看 worker 私有 `todo_list`，不要把它和 supervisor 的主 `Action List` 混在一起

## CLI 模式

CLI 模式适合排查真实 stream 和日志。

### 启动

```bash
python3 main.py
```

或者：

```bash
python3 main.py --prompt "请把这个仓库的多 agent 执行链路解释清楚"
```

### 可选参数

`main.py` 最终调用 [config.py](/mnt/d/pycode/agent/deep_agent_v1/app/config.py) 中的参数：

```bash
python3 main.py \
  --prompt "你的问题" \
  --model "gpt-4o-mini" \
  --log-level INFO \
  --log-file runtime_logs/deep_agent_stream.jsonl
```

### CLI 输出内容

CLI 模式会输出：

- 主 agent 的 token 流
- 子 agent 生命周期
- 工具调用和工具返回
- 最终回答
- 已捕获的 subagent 状态摘要
- JSONL 日志文件路径

## Web Demo 模式

Web Demo 是这个仓库的主要使用方式。

### 启动

```bash
python3 serve_demo.py --host 0.0.0.0 --port 8080
```

默认地址：

- `http://127.0.0.1:8080`

### 页面包含什么

- 顶部状态卡片
  - Current round
  - Action steps
  - Completed
  - Active workers
  - Status

- 对话流
  - User Query
  - Action List
  - Workers And Checklists
  - Round Trace
  - Execution Log
  - Final Summary

- 底部输入框
  - Enter 发送
  - Shift+Enter 换行
  - 执行时按钮切换为停止按钮

### 前端特点

- 不依赖 webpack / vite
- 使用浏览器原生 ES Module
- 使用 `react` + `htm`
- 通过 NDJSON 流式更新页面
- 最终回答支持 Markdown 和 Mermaid

## API 说明

### `GET /api/health`

健康检查。

响应示例：

```json
{"ok": true}
```

### `GET /api/demo/meta`

获取当前模型名和长期注册子 Agent 元数据。

注意：

- 这里返回的是“长期注册 worker 名册”
- 不包含“本轮 query 专属动态 worker”
- 本轮动态 worker 只会在 `POST /api/demo/run` 时按 query 生成

### `POST /api/demo/subagents`

动态创建子 Agent。

请求体：

```json
{
  "name": "research_worker",
  "display_name": "Research Worker",
  "role": "负责某个独立维度的调研",
  "description": "用于处理 supervisor 拆分出的独立问题",
  "system_prompt": "你是一个并行 worker..."
}
```

### `POST /api/demo/run`

执行一次真实调度。

请求体：

```json
{
  "query": "派生两个子agent，对比一下python和rust",
  "max_rounds": 12,
  "messages": [
    {"role": "user", "content": "上一轮问题"},
    {"role": "assistant", "content": "上一轮回答"}
  ]
}
```

响应类型：

- `application/x-ndjson`

每一行都是一个事件对象，前端按流式更新状态。

## 状态模型

[demo_session.py](/mnt/d/pycode/agent/deep_agent_v1/app/demo_session.py) 会把真实运行流抽象为以下前端结构：

- `status`
  - `idle`
  - `running`
  - `done`
  - `stopped`

- `tasks`
  - supervisor 的主任务原子列表
  - 每一项都会绑定到对应的 round / worker，避免只靠位置猜测

- `rounds`
  - 每轮派发和收敛情况
  - 记录 dispatch、report、conclusion 和 round 状态

- `agents`
  - 本轮真正进入执行链路的 worker
  - 每个 worker 的状态、当前任务标题、私有 checklist、guard 命中次数和最近一次 guard 信息

- `logs`
  - 执行日志

- `final_summary`
  - supervisor 最终回答

## 子 Agent 与 Checklist 机制

这一节可以把上面的子 agent 逻辑再压缩成一句话：

- worker 名册是按 query 动态准备的
- worker 只有被真实派发后才会出现在前端状态里
- worker 的结束条件不是“口头汇报”，而是“证据型 checklist 满足”

这保证了演示里看到的 worker、任务追踪和 round 收敛之间是同一条真实执行链，而不是静态占位 UI。

## 日志与调试

### JSONL 运行日志

默认日志文件：

- `runtime_logs/deep_agent_stream.jsonl`

当前日志以“结构化事件”为主，不再默认把每个流式 chunk 都原样刷进去。

典型事件包括：

- `session_started / session_finished`
- `main_todos_updated`
- `round_started / round_completed`
- `task_dispatched`
- `agent_created / agent_started / agent_reported`
- `agent_todos_updated`
- `tool_called / tool_result`
- `agent_guard_blocked`

这样更适合排查：

- supervisor 有没有真的派发
- worker 是不是被真正创建了
- checklist 什么时候更新
- round 为什么收敛为 `done / blocked / error`

### CLI 调试

如果你要看更原始的运行过程，优先用：

```bash
python3 main.py --prompt "你的问题"
```

### Web Demo 调试

如果页面表现不对，优先排查：

1. 是否重启了 `serve_demo.py`
2. 是否刷新了浏览器
3. 后端日志文件里是否真的出现了对应结构化事件
4. Execution Log 是否有 worker / tool / round 事件
5. 如果启用了 Docker backend，目标容器是否已经启动

### 一个常见误区

改了 [demo_session.py](/mnt/d/pycode/agent/deep_agent_v1/app/demo_session.py) 或 [prompts.py](/mnt/d/pycode/agent/deep_agent_v1/app/prompts.py) 后，必须重启 `serve_demo.py`，否则前端仍然连的是旧进程。

## 当前实现约束

这个仓库是一个演示型工程，不是生产级 agent 平台。

当前约束包括：

- HTTP 服务使用标准库 `http.server`，不是 FastAPI
- 前端是零构建页面，依赖从 CDN 直接加载
- 动态注册的子 Agent 只保存在进程内，服务重启后不会持久化

## 常见问题

### 1. 为什么前端看到的不是最新改动？

通常是后端没重启。

处理方式：

```bash
python3 serve_demo.py --host 0.0.0.0 --port 8080
```

重启后刷新页面。

### 2. 为什么 `ls` 返回空数组？

旧版本里这通常是 deepagents 文件系统工具看到的是它自己的工作目录视角，不一定等于你当前 shell 所在目录。

当前项目已经把 workspace 根目录固定到仓库下的 `workspace/`；如果你还看到异常结果，优先检查：

- 是否重启了后端
- 当前 backend 是否是你预期的 `filesystem` / `docker`

这不代表仓库本身是空的。

### 3. 为什么 worker 有时没有 checklist？

先看 Execution Log 是否真的出现了 `write_evidence_todos` 或 `agent_todos` 事件。

如果没有，说明这次运行里 worker 还没走到 checklist 阶段。

还要注意一种情况：

- 如果 supervisor 根本没有调用 `task`
- 而是自己直接完成了任务

那么这次运行就不会真正创建 worker，自然也不会有 worker checklist。

另外要区分两层 todo：

- supervisor 的主 `Action List` 来自 `write_todos`
- worker 的私有 checklist 来自 `write_evidence_todos`

前端 worker 面板展示的是后者。

### 4. 最终总结为什么不能再派一个 worker？

这是当前项目的设计约束。

原因是：

- worker 只负责叶子分片
- 最终综合多个 worker 结果属于 supervisor 职责
- 否则会把“调度者”和“最终决策者”角色再外包一次，导致链路失真

### 5. 前端为什么能显示 Markdown 和 Mermaid？

因为 [index.html](/mnt/d/pycode/agent/deep_agent_v1/frontend_demo/index.html) 通过 import map 引入了：

- `marked`
- `dompurify`
- `mermaid`

最终回答会在前端进行安全渲染。

### 6. `execute` 和文件工具是不是都在 Docker 里？

不是。

当前 `docker` backend 模式下：

- agent 主流程仍然在宿主机 Python 进程里运行
- 文件工具锚定当前项目的 `workspace/`
- 只有 `execute` 会通过 `docker exec` 进入容器执行

所以当前架构更准确地说是：

- 宿主机上的 orchestrator
- Docker 容器中的命令执行器

### 7. SSH 工具怎么用？

工具名：

- `ssh_execute(host_ip, command)`

适用场景：

- 远程机器上执行一次性命令
- 已经有可用的 SSH 用户/密钥/密码配置
- 由 worker 承接的远程检查、探测、信息收集任务

不适用场景：

- 交互式命令
- 需要持续会话状态的复杂 shell 操作
- 大量复合命令拼接
- 让 supervisor 直接越过调度逻辑去做远程执行

## 扩展建议

如果你要继续扩展这个项目，推荐从下面几个方向入手：

### 1. 接入真实业务工具

如果你要继续扩展 worker 的能力，可以在 [builder.py](/mnt/d/pycode/agent/deep_agent_v1/app/agent/builder.py) 里给 subagent 显式挂载业务工具，例如：

- 数据库查询
- 文档检索
- Git 仓库分析
- 代码搜索

### 2. 接入更稳定的后端框架

把 [demo_server.py](/mnt/d/pycode/agent/deep_agent_v1/app/demo_server.py) 替换成：

- FastAPI
- SSE / WebSocket
- 更完善的错误码和会话管理

### 3. 增强日志与观测

可以把 JSONL 日志进一步接到：

- ELK
- ClickHouse
- LangSmith
- OpenTelemetry

### 4. 做真正的持久化会话

目前前端多轮对话是通过历史消息回放实现的。

如果要做更强的会话能力，可以增加：

- session id
- 服务端会话存储
- 历史 round 回放
- worker 生命周期归档

## 快速开始

如果你只想最快跑起来：

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 配置 `.env`

```env
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

3. 启动 Web Demo

```bash
python3 serve_demo.py --host 0.0.0.0 --port 8080
```

4. 打开浏览器访问

```text
http://127.0.0.1:8080
```

## 相关入口文件

- CLI 入口：[main.py](/mnt/d/pycode/agent/deep_agent_v1/main.py)
- Web 入口：[serve_demo.py](/mnt/d/pycode/agent/deep_agent_v1/serve_demo.py)
- Agent 构建：[builder.py](/mnt/d/pycode/agent/deep_agent_v1/app/agent/builder.py)
- Session 收集：[demo_session.py](/mnt/d/pycode/agent/deep_agent_v1/app/demo_session.py)
- 前端主逻辑：[app.js](/mnt/d/pycode/agent/deep_agent_v1/frontend_demo/app.js)

## License

当前仓库未单独声明 License。如需开源或分发，建议补充明确许可证。
