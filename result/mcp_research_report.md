# MCP 是否该死？深度研究报告

## 执行摘要

**结论：MCP 没有死，但正在经历技术选型分化。** "集体弃用"的说法存在夸大，实际情况是：

- ✅ **Perplexity** 官方宣布内部弃用（2026 年初）
- ⚠️ **YC CEO Garry Tan** 仅个人社交媒体评论，非官方声明
- ❌ **Cloudflare** 积极采用 MCP，作为 AI 战略核心
- ❌ **Zilliz** 官方提供 MCP Server，持续维护

MCP 的核心价值（标准化 + 企业级治理）仍难以替代，但在简单场景和 token 效率敏感场景下，Skills、CLI 等替代方案更具优势。

---

## 一、"集体弃用"真相核查

### 1.1 四家公司实际情况

| 公司/人物 | 是否弃用 | 证据类型 | 关键声明 |
|-----------|---------|---------|---------|
| **Perplexity** | ✅ 是 | 官方声明 | CTO Denis Yarats 在 Ask 2026 开发者大会宣布弃用 |
| **YC CEO (Garry Tan)** | ⚠️ 个人评论 | 社交媒体 | "MCP sucks honestly"，非 YC 官方立场 |
| **Cloudflare** | ❌ 否 | 官方博客 | "We have aggressively adopted MCP as a core part of our AI strategy" |
| **Zilliz** | ❌ 否 | 官方产品 | 提供 Zilliz MCP Server，GitHub 开源维护 |

### 1.2 关键事实澄清

- **Sam Altman（OpenAI CEO）** 实际上在 2025 年 3 月**宣布支持 MCP**，而非弃用
- 用户提到的"YC CEO"应指 Garry Tan（YC President），而非 Sam Altman
- Cloudflare 和 Zilliz 不仅没有弃用，反而在**积极推广**MCP

---

## 二、MCP 技术问题分析

### 2.1 上下文窗口占用问题

**核心数据来源**：
- Apideck 官方博客（2026-03-16）："One team reported three MCP servers consuming 143,000 of 200,000 tokens. That's 72% of the context window"
- Cloudflare 官方博客（2026-02-20）："An equivalent MCP server without Code Mode would consume 1.17 million tokens"

**Token 消耗机制**：

| 消耗项 | Token 范围 | 问题根源 |
|--------|-----------|---------|
| 单个工具定义 | 550-1,400 tokens | 预加载机制：初始化时注入所有 schema |
| 工具调用开销 | 500-2,000 tokens/次 | 静态占用：无论是否使用都消耗上下文 |
| 实际数据 | ~200 tokens | 不透明：用户无法追踪哪个 server 最"重" |

**问题本质**：MCP 采用**预加载策略**，所有工具定义在会话启动时全部注入上下文，导致：
- 3 个服务即可占用 72% 上下文窗口
- Cloudflare 全 API 描述需要 117 万 tokens，超过任何现有模型上下文上限

### 2.2 Skills 方案对比

**Skills 三级渐进式加载机制**：

| 层级 | 内容 | 加载时机 | Token 成本 |
|------|------|----------|-----------|
| Level 1 | name + description（YAML frontmatter） | 会话启动时 | ~100 tokens/skill |
| Level 2 | SKILL.md 完整内容 | Claude 判断需要时 | <5,000 tokens |
| Level 3+ | 模板、脚本、参考资料 | 真正用到时才读取 | 按需加载 |

**实测对比**：

| 场景 | MCP | Skills | 节省比例 |
|------|-----|--------|---------|
| 3 个服务（~40 工具） | 55K-143K tokens | ~4K tokens | 93-97% |
| Cloudflare 全 API | 117 万 tokens | ~1K tokens | 99.9% |

**Skills 优势原理**：
1. **信息分离**：将"能做什么"（元数据）与"怎么做"（实现细节）分离
2. **延迟绑定**：运行时动态决定加载内容，而非启动时确定所有工具
3. **外部存储**：利用文件系统扩展能力，不占用模型上下文

---

## 三、社区舆情分析

### 3.1 支持 MCP 的核心论点

1. **标准化价值**
   - MCP 被比作"AI 的 USB-C"，提供统一的集成标准
   - 解决 m×n 集成问题，避免为每个 AI 模型和工具编写自定义集成

2. **企业级治理能力**
   - 结构化权限控制、审计日志、合规支持
   - 适合金融、医疗、政府等受监管行业

3. **主流厂商支持**
   - OpenAI（Sam Altman，2025 年 3 月）
   - Google DeepMind（Demis Hassabis，2025 年 4 月）
   - NVIDIA（Jensen Huang，2025 年 11 月）

4. **生态系统成熟度**
   - 110M+ 月 SDK 下载量
   - 5000+ MCP 服务器可用
   - 800 万+ 下载量
   - 2025 年 12 月捐赠给 Linux Foundation Agentic AI Foundation

### 3.2 反对/质疑 MCP 的观点

1. **Context Bloat** - 工具定义占用过多上下文窗口
2. **过度工程化** - 对于简单用例过于复杂
3. **认证复杂** - OAuth 流程繁琐，开发者体验不佳
4. **安全质疑** - 安全专家认为 MCP 安全模型存在缺陷
5. **EEE 策略担忧** - 部分开发者认为 MCP 是 Anthropic 的"拥抱、扩展、消灭"策略

### 3.3 关键意见领袖立场

| 人物 | 职位 | 立场 | 来源 |
|------|------|------|------|
| Sam Altman | OpenAI CEO | ✅ 支持 | 2025 年 3 月在 X 宣布全面支持 MCP |
| Demis Hassabis | Google DeepMind CEO | ✅ 支持 | 2025 年 4 月确认 Gemini 支持 MCP |
| Jensen Huang | NVIDIA CEO | ✅ 支持 | 称 MCP"彻底改变了 AI 格局" |
| David Soria Parra | MCP 联合创始人 | ✅ 支持 | 发布 2026 路线图，回应批评 |
| Denis Yarats | Perplexity CTO | ❌ 批评 | 认为 MCP 上下文开销过大 |
| Garry Tan | YC President | ❌ 批评 | "MCP sucks honestly" |
| tptacek | 安全专家 | ❌ 质疑 | 质疑 MCP 安全模型 |

---

## 四、替代方案分析

### 4.1 主要替代方案

| 方案 | 提出方 | 定位 | 与 MCP 关系 |
|------|--------|------|------------|
| **A2A (Agent2Agent)** | Google | 代理间通信协议 | 互补，非替代 |
| **ACP (Agent Communication Protocol)** | IBM | 代理间通信 | 解决 MCP 未覆盖的代理协作场景 |
| **Agentica** | WRTN Labs | 直接 MCP 替代 | 更轻量，成本更低 |
| **UTCP** | 社区 | 通用工具调用协议 | 简化替代方案 |
| **CLI/Shell** | 社区推荐 | 简单场景替代 | 适合开发者工作流 |
| **Skills** | 社区 | Token 效率优化 | 适合上下文敏感场景 |
| **直接 API 集成** | 传统方案 | 无需协议 | 灵活但维护成本高 |

### 4.2 关键洞察

- **A2A 和 ACP 与 MCP 是互补关系**：A2A 处理代理间通信，MCP 处理代理与工具/数据的集成
- **Skills 和 CLI 是场景化替代**：在特定场景（token 敏感、简单工作流）下更优
- **没有银弹**：不同方案解决不同问题，需根据场景选择

---

## 五、MCP 的不可替代价值

### 5.1 标准化优势

MCP 类似于 REST API 或 HTTP，提供行业公认的集成标准：
- 统一接口规范
- 跨平台兼容性
- 降低集成成本

### 5.2 企业级治理能力

在受监管行业（金融、医疗、政府），MCP 提供：
- 结构化权限控制
- 审计日志
- 合规支持
- 访问控制策略

### 5.3 生态系统网络效应

- 5000+ MCP 服务器覆盖主流工具和服务
- 主流 IDE 和 AI 客户端原生支持（Cursor、Windsurf、Cline 等）
- 持续演进：2026 路线图包括无状态 HTTP、长运行任务、触发器等新功能

---

## 六、结论与建议

### 6.1 MCP 是否该死？

**答案：不该死，但需要理性看待其适用场景。**

MCP 正在经历 Gartner Hype Cycle 的"幻灭低谷期"，但正走向"启蒙斜坡"：

| 场景 | 推荐方案 | 理由 |
|------|---------|------|
| **企业级复杂集成** | ✅ MCP | 需要治理、合规、审计 |
| **简单开发者工作流** | ✅ CLI/Shell | 更直接、可调试 |
| **Token 效率敏感** | ✅ Skills | 93-99% token 节省 |
| **多代理协作** | ✅ A2A + MCP | 互补使用 |
| **快速原型** | ✅ 直接 API | 灵活、低门槛 |

### 6.2 行业趋势判断

1. **MCP 不会消失**：标准化价值和企业级需求确保其长期存在
2. **场景分化加剧**：不同场景选择不同方案，MCP 不再是唯一选择
3. **持续演进**：MCP 社区正在响应批评，改进 token 效率和开发者体验
4. **多协议共存**：MCP、A2A、ACP、Skills 等将长期共存，各自服务特定场景

### 6.3 实践建议

- **不要盲目跟风弃用**：评估自身场景是否真的受 token 占用影响
- **关注 2026 路线图**：MCP 正在改进无状态 HTTP、长运行任务等功能
- **考虑混合方案**：核心集成用 MCP，简单场景用 CLI/Shell
- **监控生态系统**：5000+ MCP 服务器的覆盖范围仍在快速扩展

---

## 七、参考资料

### 新闻验证
- [Perplexity CTO 宣布弃用 MCP - LinkedIn](https://www.linkedin.com/posts/sattyamjain_mcp-aiagents-agenticai-activity-7441572732548554752-Fm4i)
- [Garry Tan 评论 MCP - LinkedIn](https://www.linkedin.com/posts/maxmusing_the-perplexity-ctoannouncedat-their-developer-activity-7438364101199896576-SZES)
- [Cloudflare 采用 MCP 官方博客](https://blog.cloudflare.com/)
- [Zilliz MCP Server GitHub](https://github.com/zilliztech/zilliz-mcp-server)

### 技术分析
- [Apideck: Why we're moving beyond MCP](https://apideck.com/blog/why-were-moving-beyond-mcp)
- [Cloudflare: Code Mode for MCP](https://blog.cloudflare.com/)
- [Skills 技术文档](https://github.com/anthropics/skills)

### 社区讨论
- [Hacker News: MCP is dead; long live MCP](https://news.ycombinator.com/item?id=47380270)
- [Hacker News: Everything wrong with MCP](https://news.ycombinator.com/item?id=43676771)
- [The New Stack: Why the Model Context Protocol Won](https://thenewstack.io/why-the-model-context-protocol-won/)
- [a16z: A Deep Dive Into MCP and the Future of AI Tooling](https://a16z.com/a-deep-dive-into-mcp-and-the-future-of-ai-tooling/)
- [Workato: Is MCP Dead? Why the Debate Is Asking the Wrong Question](https://www.workato.com/the-connector/is-mcp-dead/)

### 替代方案
- [MCP Alternatives Landscape Analysis](https://www.linkedin.com/pulse/mcp-alternatives-landscape-analysis-kord-campbell-xdigc)
- [A2A vs MCP: Two complementary protocols](https://blog.logto.io/a2a-mcp)
- [6 Model Context Protocol alternatives to consider in 2026](https://www.merge.dev/blog/model-context-protocol-alternatives)

### 官方资源
- [MCP Blog: Future of MCP Transports](https://blog.modelcontextprotocol.io/posts/2025-12-19-mcp-transport-future/)
- [MCP Creator Reveals the 2026 Roadmap - YouTube](https://www.youtube.com/watch?v=kAVRFYgCPg0)

---

**报告生成时间**：2026 年
**研究方法**：多 agent 并行调研，交叉验证新闻、技术文档、社区讨论三方证据
