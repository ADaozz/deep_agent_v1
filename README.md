# deep_agent_v1

一个基于 `create_deep_agent` 的真实多 Agent 协同调度 Demo。

这个项目同时面向两类读者：

- 用户：想先直观看到“一个问题如何被拆解、派发、执行、收敛、生成文件”
- 开发者：想了解这套多 Agent Demo 如何基于真实 `create_deep_agent`、流式事件和前端状态收集搭建起来

项目包含两套入口：

- CLI 运行模式：直接在终端里观察 `create_deep_agent` 的流式执行过程
- Web Demo 模式：通过一个零构建前端页面可视化展示 Supervisor、Action List、Round、Worker checklist、Execution Log 和 Final Summary

这个仓库的重点不是“静态模拟多 agent UI”，而是把真实 `create_deep_agent` 调度过程解析成前端可消费的结构化状态。

## Clone 前建议先看

如果你还没有运行项目，建议先按下面顺序快速浏览：

1. `img/主题1.jpg` 和 `img/主题2.jpg`
   - 先了解首页整体布局、对话结构和主题效果
2. `Supervisor Conversation Runtime.html`
   - 这是一次完整运行流程的导出结果
   - 可以直接看到用户提问、Action List、Worker 协作、Round 收敛、Execution Log、Final Summary、文件卡片的完整链路
3. `img/文件预览md.png` 和 `img/文件预览xlsx.png`
   - 分别展示文本类文件与表格类文件在前端的预览形态

如果你的目标是先判断这个项目值不值得 clone，优先看 `Supervisor Conversation Runtime.html`。它比单张截图更能说明整个系统到底“怎么跑”。

## 主页效果图

下面两张截图来自 `img/`，用于展示 Web Demo 首页的整体布局和主题效果。

![主页效果图（主题1）](img/主题1.jpg)

![主页效果图（主题2）](img/主题2.jpg)

## 文件预览效果图

下面两张截图展示了前端文件卡片点击后的两类文件预览效果。

Markdown / 文本类文件预览：

![Markdown 文件预览效果图](img/文件预览md.png)

Excel / 表格类文件预览：

![Excel 文件预览效果图](img/文件预览xlsx.png)

## 完整测试流程（导出结果）

`Supervisor Conversation Runtime.html` 是一次完整测试流程的导出结果，包含当次会话内的 Action List、Round Trace、Worker checklist、Execution Log、Final Summary 与文件产物展示等信息。

这份导出页不仅是留档文件，更是这个项目最直观的运行说明：

- 对用户：在 clone 之前就能看到系统如何从一个 query 进入真实多 Agent 运行流程
- 对开发者：可以直接观察 supervisor 如何拆分任务、动态生成 worker、派发任务、收敛结果并发布文件
- 对演示场景：它比静态截图更适合展示完整交互链路

- 入口文件：`Supervisor Conversation Runtime.html`
- 资源目录：`Supervisor Conversation Runtime_files/`

本地查看时直接用浏览器打开 `Supervisor Conversation Runtime.html` 即可（需要同目录下的 `_files/` 资源目录同时存在）。

这份导出通常会覆盖以下信息：

- 用户 query 与多轮对话上下文
- supervisor 写出的主任务列表
- 本轮动态 worker 的身份、职责与 checklist
- round dispatch / convergence 过程
- 最近 60 条运行日志
- 最终回答
- 生成文件的前端卡片展示

## 主要能力

- Supervisor 先调用 `write_todos` 拆分主任务
- Supervisor 在 `write_todos` 之后调用 `generate_subagents` 获取“本轮 worker 名册”，再用 `task` 把独立维度派发给多个子 worker
- 子 worker 通过 `write_evidence_todos` 维护自己的私有 checklist
- 子 worker 只有在 checklist 全部 `completed` / `blocked` 且带 evidence 时才允许结束
- 将“业务受阻”和“系统错误”分开建模，避免把目标不可达误判成程序报错
- 支持真实流式事件订阅：`updates`、`messages`、`custom`
- 支持前端多轮对话
- 支持 PostgreSQL 持久化会话历史、线程级 UI 状态与历史线程切换
- 支持按 query 动态生成专属 worker
- 支持前端提示词中心：预览、编辑、保存、恢复默认
- 支持将 `workspace/` 内文件发布为前端文件卡片，并在会话中预览 / 下载 / 文本类文件保存
- 支持把生成结果直接作为会话内文件卡片展示，便于用户在一次运行结束后立刻查看 Markdown / 文本类 / 表格类产物
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
│   │   ├── subagent_roster.py
│   │   └── workspace_artifacts.py
│   ├── config.py
│   ├── chat_history_store.py
│   ├── demo_server.py
│   ├── demo_session.py
│   ├── logging_utils.py
│   ├── prompts.py
│   ├── workspace_files.py
│   └── runner.py
├── frontend_demo/
│   ├── app.js
│   ├── index.html
│   └── styles.css
├── runtime_logs/
├── docker-compose.yaml
├── img/
├── postgres/
│   ├── docker-compose.yml
│   └── init.sql
├── Supervisor Conversation Runtime.html
├── Supervisor Conversation Runtime_files/
├── main.py
├── requirements.txt
├── serve_demo.py
└── README.md
```

## 项目架构

当前实现可以理解为五层：

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

4. 持久化与会话层
   - [chat_history_store.py](/mnt/d/pycode/agent/deep_agent_v1/app/chat_history_store.py)
   - 负责把会话历史、线程级 UI 状态持久化到 PostgreSQL
   - 支持恢复最近线程、列出历史线程、恢复前端控件状态

5. 交互展示层
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
  - 维护 `tasks / rounds / agents / files / logs / final_summary`
  - 把原始工具调用和 round 收敛过程写成结构化 JSONL 事件
  - 只有当 supervisor 真正 `task` 派发后，才会在 collector 中物化对应 worker
  - 支持把 `publish_workspace_file` 工具结果转成前端文件卡片
  - 当模型漏掉发布工具但在最终答复里写出 `workspace` 路径时，会尝试自动补文件卡片

- `app/demo_server.py`
  - 一个基于 `ThreadingHTTPServer` 的轻量 HTTP 服务
  - 提供前端页面和 API
  - `/api/demo/meta` 返回当前模型名
  - `/api/demo/run` 返回 NDJSON 流式状态快照
  - `/api/demo/history` / `/api/demo/history/threads` / `/api/demo/thread-state` 提供历史线程与 UI 状态持久化
  - `/api/demo/prompts` / `/api/demo/prompts/reset` 提供提示词读取与热更新
  - `/api/demo/workspace-file` 提供 `workspace/` 文件的预览、下载与文本类文件保存

- `app/chat_history_store.py`
  - PostgreSQL 会话持久化层
  - 保存 `thread_id / session_id / payload / error_text`
  - 额外保存线程级 `ui_state`
  - 支持列出历史线程、恢复最近会话

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
  - 使用统一的 `uiState` 对象维护主题、输入框、当前弹窗、当前选中 agent / 文件等前端状态
  - 支持历史会话侧栏、提示词中心、文件卡片与文件预览弹窗
  - 负责渲染：
    - 顶部状态卡片
    - User Query
    - Action List
    - Workers And Checklists
    - Round Trace
    - Execution Log
    - Final Summary
    - Workspace Files

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
15. 如果运行过程中生成了 `workspace/` 内的文件，supervisor 应调用 `publish_workspace_file`，前端会把它渲染为文件卡片
16. 文本类文件可以在前端弹窗里预览、编辑、保存；二进制文件只展示元信息并下载

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

## Docker 目录与统一编排

项目里与容器相关的文件现在分成两部分：

- 根目录 [docker-compose.yaml](/mnt/d/pycode/agent/deep_agent_v1/docker-compose.yaml)
  - 统一编排 `deep-agent-sandbox` 与 `postgresql`
- [postgres/](/mnt/d/pycode/agent/deep_agent_v1/postgres/)
  - `init.sql`：PostgreSQL 初始化脚本
  - `docker-compose.yml`：legacy 配置，仅保留为“单独启动 PostgreSQL”的历史参考；推荐直接使用根目录总 compose

当前推荐的启动方式是使用根目录总 compose：

```bash
docker compose up -d
```

说明：

- [postgres/docker-compose.yml](/mnt/d/pycode/agent/deep_agent_v1/postgres/docker-compose.yml) 是 legacy 配置
- 推荐改用根目录 [docker-compose.yaml](/mnt/d/pycode/agent/deep_agent_v1/docker-compose.yaml)
- 除非你只想单独调试 PostgreSQL，否则不要优先使用 `postgres/docker-compose.yml`

这会同时启动：

- `deep-agent-sandbox`
  - 供 `DEEP_AGENT_BACKEND=docker` 时的 `execute` 使用
  - 将本地 `./workspace` 挂载到容器内 `/workspace`

- `postgresql`
  - 提供聊天历史与 UI 状态持久化
  - 启动时自动执行 [postgres/init.sql](/mnt/d/pycode/agent/deep_agent_v1/postgres/init.sql)
  - 当前 `init.sql` 会初始化 `vector` 扩展

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

# PostgreSQL chat history
DEEP_AGENT_PG_HOST=127.0.0.1
DEEP_AGENT_PG_PORT=5432
DEEP_AGENT_PG_USER=postgresql
DEEP_AGENT_PG_PASSWORD=postgresql
DEEP_AGENT_PG_DATABASE=postgresql

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
- PostgreSQL 会话持久化默认从 `.env` 读取 `DEEP_AGENT_PG_*`

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
docker compose up -d deep-agent-sandbox
```

如果你希望连同 PostgreSQL 一起启动，直接执行：

```bash
docker compose up -d
```

根目录总 compose 的核心内容如下：

```yaml
services:
  deep-agent-sandbox:
    image: python:3.13-slim
    container_name: deep-agent-sandbox
    working_dir: /workspace
    command: sleep infinity
    restart: unless-stopped
    volumes:
      - ./workspace:/workspace

  postgresql:
    image: pgvector/pgvector:pg17
    container_name: postgresql
    environment:
      POSTGRES_USER: postgresql
      POSTGRES_PASSWORD: postgresql
      POSTGRES_DB: postgresql
    ports:
      - "5432:5432"
    restart: unless-stopped
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./postgres/init.sql:/docker-entrypoint-initdb.d/init.sql:ro

volumes:
  pg_data:
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

- `publish_workspace_file(relative_path, title="")`
  - 不是框架默认工具
  - 由 [workspace_artifacts.py](/mnt/d/pycode/agent/deep_agent_v1/app/tools/workspace_artifacts.py) 提供
  - 只暴露给 supervisor
  - 用于把 `workspace/` 下已存在的文件发布成前端会话里的文件卡片
  - 适合 markdown、txt、py、json、csv、xlsx 等结果文件

补充说明：

- supervisor 除了框架内置工具外，还会额外获得 `generate_subagents`（名册工具）；它不挂载远程执行工具
- supervisor 还会额外挂载 `publish_workspace_file`，用于发布结果文件卡片
- worker 在框架内置工具之外，会额外获得 `ssh_execute`
- worker 运行时虽然仍然天然带有框架内置 `write_todos`，但本项目的 worker 提示词、前端展示和完成守卫都以 `write_evidence_todos` 为准
- 如果你要观察真正影响 worker 完成态的 checklist，请看 worker 私有 `todo_list`，不要把它和 supervisor 的主 `Action List` 混在一起

## Web Demo 扩展能力

### 1. 历史会话与 UI 状态持久化

- 聊天历史会持久化到 PostgreSQL
- 每个线程除了会话内容，还会保存线程级 `ui_state`
- `ui_state` 当前覆盖：
  - 当前主题
  - 输入框内容
  - 当前选中的提示词模块
  - 当前提示词编辑草稿
  - 当前选中的 agent / 文件
- 前端支持从历史线程列表切换线程，并恢复对应 UI 状态
- 历史线程支持删除，并带页面内二次确认弹窗
- 删除当前线程时，会自动切换到最近一条剩余线程，或创建一个新的空线程
- 历史 / 提示词 / 文件弹窗属于临时 UI 状态，刷新页面后不会自动恢复为打开状态

### 2. 提示词管理中心

左侧“提示词”按钮打开后，可以直接在前端：

- 预览当前核心提示词
- 编辑提示词
- 保存提示词
- 恢复默认提示词

当前支持管理的提示词包括：

- 默认用户提示词
- 运行时 worker 规划器提示词
- supervisor 系统提示词
- worker evidence todo 守卫提示词

提示词保存是“进程内热更新”：

- 不需要重启 `serve_demo.py`
- 对后续新任务立即生效
- 但服务重启后仍会回到代码中的默认值

### 3. 文件产物卡片

如果 supervisor 在 `workspace/` 中生成了结果文件，并调用 `publish_workspace_file`，前端会在会话底部渲染文件卡片。

当前文件卡片能力：

- 支持多个文件并排展示
- 支持点击卡片打开文件弹窗
- 支持下载原始文件

当前文件弹窗能力：

- Markdown / 纯文本 / 代码文本：预览、编辑、保存、下载
- 图片 / PDF：预览、下载
- Excel / 其他二进制文件：显示文件信息并下载，不做错误的文本预览

另外，collector 还提供一个兜底：

- 如果模型漏掉了 `publish_workspace_file`
- 但在最终答复里写出了 `workspace/...` 或 `/workspace/...` 路径
- 系统会尝试自动把它补成文件卡片

### 4. 运行态交互

当前 Web Demo 还包含一组运行态交互约束：

- 对话执行过程中，底部输入框会自动收起，只保留停止按钮
- 执行过程中左侧“历史会话”和“提示词管理”按钮会被禁用
- 执行过程中如果直接点击“新会话”，会先中断当前流式运行，再切换到新的线程
- 已完成状态的 round / worker 面板默认自动收起
- `Execution Log` 默认收起，避免长日志干扰主对话流
- `Execution Log` 前端仅展示最近 60 条事件

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
  - Execution Log（前端仅展示最近 60 条）
  - Final Summary

- 底部输入框
  - Enter 发送
  - Shift+Enter 换行
  - 执行时输入框自动收起，仅保留停止按钮

- 左侧菜单
  - 历史会话
  - 提示词管理
  - 执行中禁用，避免打断当前运行态

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

获取当前模型名。

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

### `DELETE /api/demo/history?thread_id=...`

删除指定历史线程。

行为说明：

- 会同时删除该线程下的会话历史与线程级 `ui_state`
- 删除前会弹出页面内二次确认弹窗
- 如果删除的是当前线程，前端会自动切换到最近一条剩余线程
- 如果已经没有剩余线程，前端会自动创建一个新的空线程

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
