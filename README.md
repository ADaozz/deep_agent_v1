# deep_agent_v1

一个基于 `create_deep_agent` 的真实多 Agent 协同调度 Demo。

项目包含两套入口：

- CLI 运行模式：直接在终端里观察 `create_deep_agent` 的流式执行过程
- Web Demo 模式：通过一个零构建前端页面可视化展示 Supervisor、Action List、Round、Worker checklist、Execution Log 和 Final Summary

这个仓库的重点不是“静态模拟多 agent UI”，而是把真实 `create_deep_agent` 调度过程解析成前端可消费的结构化状态。

## 主要能力

- Supervisor 先调用 `write_todos` 拆分主任务
- 使用 `task` 把独立维度派发给多个子 worker
- 子 worker 通过 `write_evidence_todos` 维护自己的私有 checklist
- 子 worker 只有在 checklist 全部完成且带 evidence 时才允许结束
- 支持真实流式事件订阅：`updates`、`messages`、`custom`
- 支持前端多轮对话
- 支持动态新增子 Agent
- 支持 Markdown / Mermaid 格式的最终回答渲染
- 落盘 JSONL 运行日志，便于后续排查和审计

## 项目结构

```text
deep_agent_v1/
├── app/
│   ├── agent/
│   │   ├── builder.py
│   │   └── todo_enforcer.py
│   ├── streaming/
│   │   └── stream_logger.py
│   ├── tools/
│   │   └── mock_tools.py
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
├── main.py
├── requirements.txt
├── serve_demo.py
└── README.md
```

## 核心模块说明

### 后端

- `app/agent/builder.py`
  - 创建 `create_deep_agent`
  - 组装默认 worker 和动态 worker
  - 构建 supervisor system prompt

- `app/agent/todo_enforcer.py`
  - 子 worker 的 checklist 运行时守卫
  - 强制每个私有 todo 带 evidence
  - 防止 worker 在未完成 checklist 时提前结束

- `app/prompts.py`
  - supervisor 与 worker 的提示词
  - 约束“最终总结只能由 supervisor 完成”
  - 约束动态 worker 只能处理叶子分片任务

- `app/demo_session.py`
  - Web Demo 的核心执行与状态收集器
  - 把真实 stream chunk 转成前端可视状态
  - 负责抽取：
    - 主 Action List
    - Round Trace
    - Worker 面板状态
    - Worker todo_list
    - Execution Log
    - Final Summary

- `app/demo_server.py`
  - 一个基于 `ThreadingHTTPServer` 的轻量 HTTP 服务
  - 提供前端页面和 API

- `app/runner.py`
  - CLI 模式运行入口
  - 用于终端观察原始流式执行过程

- `app/tools/mock_tools.py`
  - 演示型工具
  - 包含一个 mock 内部知识库查询工具和一个架构检查工具

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

## 运行原理

一次典型执行流程如下：

1. 用户在前端输入问题
2. 前端调用 `POST /api/demo/run`
3. 后端调用真实 `create_deep_agent`
4. Supervisor 先执行 `write_todos`
5. Supervisor 用 `task` 派发若干 worker
6. worker 执行 `write_evidence_todos`，建立自己的 checklist
7. worker 调用工具完成本地任务，并逐项补充 evidence
8. checklist 全部完成后，worker 才允许回报 supervisor
9. supervisor 收敛各 worker 结果
10. supervisor 自己完成最终总结与最终回答
11. 后端把整个过程流式转换为结构化 NDJSON 事件
12. 前端实时更新各面板

## 环境要求

- Python 3.10+
- 可用的 OpenAI-compatible 模型接口

依赖见 [requirements.txt](/mnt/d/pycode/agent/deep_agent_v1/requirements.txt)：

```txt
deepagents>=0.4.9
langchain>=1.2.10
langgraph>=1.1.0
langchain-openai>=1.1.10
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
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

LOG_LEVEL=INFO
DEEP_AGENT_LOG_FILE=runtime_logs/deep_agent_stream.jsonl
```

也支持阿里兼容配置：

```env
DASHSCOPE_API_KEY=your-key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen-plus
```

### 配置加载逻辑

[config.py](/mnt/d/pycode/agent/deep_agent_v1/app/config.py) 的规则是：

- `model` 优先取 `--model`
- 默认取 `OPENAI_MODEL` 或 `DASHSCOPE_MODEL`
- `api_key` 优先读 `OPENAI_API_KEY`，否则读 `DASHSCOPE_API_KEY`
- `base_url` 优先读 `OPENAI_BASE_URL`，否则读 `DASHSCOPE_BASE_URL`

如果没有 API Key，启动会直接报错。

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

获取当前可用子 Agent 元数据。

用于前端初始化 worker 列表。

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

- `rounds`
  - 每轮派发和收敛情况

- `agents`
  - 每个 worker 的状态
  - 当前任务标题
  - 私有 checklist
  - guard 命中次数
  - 最近一次 guard 信息

- `logs`
  - 执行日志

- `final_summary`
  - supervisor 最终回答

## 子 Agent 与 Checklist 机制

### 默认 worker

默认内置三个通用 worker：

- `worker_alpha`
- `worker_beta`
- `worker_gamma`

它们没有固定业务语义，只负责承接 supervisor 拆分出来的独立维度任务。

### 动态 worker

当默认 3 个 worker 不够覆盖问题维度时，系统会尝试动态派生额外 worker。

但当前提示词已经明确限制：

- 动态 worker 只能处理叶子分片任务
- 不允许生成总结型、综合型、最终回答型 worker
- 最终总结必须由 supervisor 自己完成

### 为什么要有 checklist 守卫

子 worker 不允许“凭口头说完成”就结束。

在 [todo_enforcer.py](/mnt/d/pycode/agent/deep_agent_v1/app/agent/todo_enforcer.py) 中：

- worker 必须先写私有 todo
- 每项 todo 都要有 evidence
- checklist 未完成时会被 runtime guard 拦截

这保证了演示时能看到：

- checklist 是真的
- worker 的完成检测是严格的
- Execution Log 和 Worker 面板能互相对上

## 日志与调试

### JSONL 运行日志

默认日志文件：

- `runtime_logs/deep_agent_stream.jsonl`

里面会记录每个 stream chunk 的摘要，便于调试。

### CLI 调试

如果你要看更原始的运行过程，优先用：

```bash
python3 main.py --prompt "你的问题"
```

### Web Demo 调试

如果页面表现不对，优先排查：

1. 是否重启了 `serve_demo.py`
2. 是否刷新了浏览器
3. 后端日志文件里是否真的出现了对应 chunk
4. Execution Log 是否有 worker / tool / round 事件

### 一个常见误区

改了 [demo_session.py](/mnt/d/pycode/agent/deep_agent_v1/app/demo_session.py) 或 [prompts.py](/mnt/d/pycode/agent/deep_agent_v1/app/prompts.py) 后，必须重启 `serve_demo.py`，否则前端仍然连的是旧进程。

## 当前实现约束

这个仓库是一个演示型工程，不是生产级 agent 平台。

当前约束包括：

- HTTP 服务使用标准库 `http.server`，不是 FastAPI
- 前端是零构建页面，依赖从 CDN 直接加载
- `query_internal_kb` 是 mock 工具，不是真实知识库
- `inspect_architecture` 是基于当前仓库文件生成的实时摘要，不是外部搜索
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

这通常是 deepagents 文件系统工具看到的是它自己的工作目录视角，不一定等于你当前 shell 所在目录。

这不代表仓库本身是空的。

### 3. 为什么 worker 有时没有 checklist？

先看 Execution Log 是否真的出现了 `write_evidence_todos` 或 `agent_todos` 事件。

如果没有，说明这次运行里 worker 还没走到 checklist 阶段。

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

## 扩展建议

如果你要继续扩展这个项目，推荐从下面几个方向入手：

### 1. 接入真实业务工具

替换 [mock_tools.py](/mnt/d/pycode/agent/deep_agent_v1/app/tools/mock_tools.py) 中的 mock 能力：

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
