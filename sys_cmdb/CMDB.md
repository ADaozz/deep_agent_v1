## 2. 业务功能及服务调用链路

### 2.1 模型管理

管理 CMDB 中的配置项类型（CIT）定义，包括模型属性、字段定义、关系映射、模型维度和模型视图的配置。

**服务调用链路：**
- **界面交互**：`ui-ops-cmdb`（模型配置） / `ui-common`（公共组件） ➔ `qz-gateway`（网关） ➔ `ops-cmdb`（核心业务逻辑）
- **底层数据模型**：`ops-cmdb` ➔ `ops-data-model`（获取/保存模型元数据与数据字典）
- **数据持久化**：`ops-cmdb` / `ops-data-model` ➔ `ops-synapplication`（执行底层 MongoDB 读写）

### 2.2 配置项实例管理

管理配置项的实例数据，支持数据的增删改查、批量导入导出（Excel）、数据确认和历史版本追溯。

**服务调用链路：**
- **操作面板**：`ui-ops-cmdb` ➔ `qz-gateway` ➔ `ops-cmdb`（实例管理 / 消费视图操作）
- **批量数据操作**：`ui-ops-cmdb` ➔ `qz-gateway` ➔ `batch-operation`（大批量导入 / 增删改任务分发）
- **入库规则代理**：`ops-cmdb` / `batch-operation` ➔ `ops-synapplication-proxy`（进行数据权限验证与入库规则转换） ➔ `ops-synapplication`（执行真实持久化）
- **历史记录追踪**：`ops-synapplication-proxy` ➔ `update-history`（异步记录数据变更历史及差异比对）
- **字段翻译服务**：`ops-cmdb` / `update-history` ➔ `translation-service`（枚举与关系字段显示值翻译）

### 2.3 数据采集

管理 CMDB 数据的自动采集，包括采集任务的配置、执行、数据老化、入库规则和异常变更处理。

**服务调用链路：**
- **调度配置**：`ui-ops-cmdb` ➔ `qz-gateway` ➔ `ops-cmdb`（修改采集策略与老化机制）
- **定时任务中心**：`ops-cmdb` ➔ `scheduled-proxy`（统一注册/调度 XXL-JOB 或 Quartz 任务）
- **执行引擎与脚本**：`scheduled-proxy` ➔ `ops-synapplication-task`（采集引擎，分发采集指令） ➔ `ansible-proxy`（远端节点命令执行） / `ops-script-repertory`（调用采集脚本逻辑）
- **回写 CMDB**：`ops-synapplication-task` ➔ `ops-synapplication-proxy`（代理入库并转换）

### 2.4 消费视图与数据连接器

提供 CMDB 数据的消费视图配置、第三方系统数据对接、数据转换与推送以及订阅通知功能。

**服务调用链路：**
- **消费参数控制**：`ui-ops-cmdb` ➔ `qz-gateway` ➔ `ops-cmdb`（视图管理、连接器和推送机制配置）
- **标准化 API 网关**：外部第三方系统 ➔ `qz-gateway` ➔ `ops-data-access`（提供受控的 RESTful 数据接口）
- **API 数据获取**：`ops-data-access` ➔ `ops-cmdb`（安全获取实例数据）或 `ops-synapplication-proxy`（代理读取机制）

### 2.5 机柜与拓扑管理

管理数据中心的机柜设备，包括机柜拓扑图、设备位置管理和机柜统计报表。

**服务调用链路：**
- **前端机柜视图**：`ui-ops-cmdb` ➔ `qz-gateway` ➔ `ops-cmdb`（核心机柜管理）
- **图表渲染分析**：`ops-cmdb` ➔ `graphic-analysis`（根据关系拓扑自动生成 DrawIO XML 数据返回前端）
- **设备代理**：`ops-cmdb` ➔ `ops-synapplication-proxy`（代理机柜关联与定位数据） ➔ `ops-synapplication`

### 2.6 流程审批

提供配置项变更的流程审批功能，包括审批流程的创建、审批节点的处理和审批状态追踪。

**服务调用链路：**
- **流程触发与流转**：`ui-ops-cmdb` ➔ `qz-gateway` ➔ `ops-cmdb`（管理节点进度）
- **工作流数据交互**：`ops-cmdb` ➔ `ops-synapplication-activiti`（专用 MongoDB 流程数据读写）
- **外部流程引擎**：批量任务如 `batch-operation` / `big-data-handle` ➔ `activiti-server`（执行外部统一流程处理）
- **消息与通知**：流转节点 ➔ `message-service`（全站发送待办和提醒通知）

### 2.7 脚本管理与执行

管理运维脚本的创建、版本控制、参数定义和执行调度。

**服务调用链路：**
- **脚本设计器**：`ui-ops-component` / `ui-ops-cmdb` ➔ `qz-gateway` ➔ `ops-script-repertory`（核心组件库与脚本仓库逻辑）
- **调度分配**：`ops-script-repertory` ➔ `scheduled-proxy`（处理脚本自动化与定时运行注册）
- **脚本远行下发**：`ops-script-repertory` ➔ `ansible-proxy`（封装 Ansible 远程调用脚本能力）

### 2.8 全文搜索与作战地图

提供 CMDB 数据的全文搜索能力和可视化作战地图展示。

**服务调用链路：**
- **检索与聚类**：`ui-ops-cmdb` ➔ `qz-gateway` ➔ `qz-elasticsearch`（ES 分词搜索） / `ops-military-map`（宏观数据图表查询）
- **搜索引擎同步**：`qz-elasticsearch` ➔ `ops-cmdb`（定时拉取全量 CMDB 数据更新 ES 索引结构）
- **属性映射**：`ops-military-map` ➔ `ops-cmdb` ➔ `ops-data-model`（构建统计图表时获取模型的元数据标识）

### 2.9 用户与权限管理

管理系统用户、角色权限、组织架构、菜单配置和多租户管理。

**服务调用链路：**
- **网关登录检查**：All Frontend Apps ➔ `qz-gateway`（拦截路由） ➔ `cmdb-sso`（颁发并检验 JWT Token）
- **权限与租户配置**：`ui-master` ➔ `qz-gateway` ➔ `qz-usercenter`（租户/角色/权限 CRUD 管理）
- **身份认证同步**：`cmdb-sso` ➔ `qz-usercenter`（调取完整 LDAP / 用户信息和权限关联以生成令牌）

### 2.10 工作台与报表

提供个人工作门户、待办事项汇聚、日历视图和报表统计。

**服务调用链路：**
- **个性化看板**：`ui-workbench` / `ui-ops-cmdb` ➔ `qz-gateway` ➔ `common-workbench`（用户门户布局配置与代办列表聚合）
- **报表分析层**：`ui-ops-cmdb` ➔ `qz-gateway` ➔ `ops-cmdb`（向页面分发聚合统计报表结果）

### 2.11 移动端

提供 CMDB 数据的移动端查看和操作能力。

**服务调用链路：**
- **H5客户端**：`ui-app`（Vant UI 端） ➔ `qz-gateway`（无线 API 网关拦截）
- **移动端鉴权**：`qz-gateway` ➔ `cmdb-sso`（鉴权校验）
- **移动端业务路由**：`qz-gateway` ➔ `ops-cmdb`（展示移动版适配数据）

---

## 3. 服务清单

### 3.1 后端应用服务（23个）

| 序号 | 服务名称 | 简要说明 |
|------|---------|---------|
| 1 | ops-cmdb | 基于 Java 的 CMDB 核心微服务，负责 IT 资产模型定义、配置项管理、实例数据 CRUD、数据采集调度、消费视图和机柜管理。 |
| 2 | ops-synapplication | 基于 Java 的数据操作核心微服务，负责 CMDB 实例数据的 MongoDB 读写操作、数据消费和统计。 |
| 3 | ops-synapplication-proxy | 基于 Java 的数据操作代理微服务，在数据操作层之上提供数据验证、入库规则转换、机柜管理等增强功能。 |
| 4 | ops-synapplication-common | 基于 Java 的通用数据操作微服务，与 ops-synapplication 同源，提供多 profile 场景下的 MongoDB 数据读写服务。 |
| 5 | ops-synapplication-task | 基于 Java 的采集任务执行微服务，负责 CMDB 数据采集任务的执行管理和采集数据入库处理。 |
| 6 | ops-synapplication-activiti | 基于 Java 的流程引擎数据操作微服务，负责流程审批相关的 MongoDB 数据读写和流程状态管理。 |
| 7 | ops-data-model | 基于 Java 的数据模型管理微服务，负责 CMDB 模型定义、数据字典管理和模型关系维护。 |
| 8 | ops-data-access | 基于 Java 的数据访问服务，为外部系统提供 CMDB 数据的标准化 RESTful API 接口。 |
| 9 | ops-script-repertory | 基于 Java 的脚本库管理微服务，负责运维脚本的存储、版本管理、执行调度和组件库管理。 |
| 10 | ops-military-map | 基于 Java 的作战地图微服务，提供 CMDB 数据的可视化拓扑展示、全文搜索和定时数据同步。 |
| 11 | batch-operation | 基于 Java 的批量操作微服务，负责 CMDB 配置项的批量数据操作、批量导入导出和批量业务流程处理。 |
| 12 | big-data-handle | 基于 Java 的大数据处理微服务，负责 CMDB 大批量数据的异步处理、数据映射转换和批量入库操作。 |
| 13 | update-history | 基于 Java 的数据变更历史记录微服务，负责记录和管理 CMDB 配置项实例数据的变更历史与版本追溯。 |
| 14 | translation-service | 基于 Java 的数据翻译微服务，负责 CMDB 配置项字段值的显示名翻译和枚举值转换。 |
| 15 | graphic-analysis | 基于 Java 的图形分析微服务，负责 CMDB 配置项关系的图形可视化展示和拓扑分析。 |
| 16 | qz-usercenter | 基于 Java 的用户中心微服务，负责用户管理、角色权限、组织架构、菜单管理和租户管理。 |
| 17 | cmdb-sso | 基于 Java 的单点登录客户端服务，负责 CMDB 系统的统一身份认证和会话管理。 |
| 18 | qz-gateway | 基于 Java 的 API 网关微服务，负责 CMDB 系统的统一路由转发、请求过滤和安全认证。 |
| 19 | common-workbench | 基于 Java 的通用工作台微服务，提供用户工作门户的看板、待办事项和系统通知汇聚功能。 |
| 20 | scheduled-proxy | 基于 Java 的定时任务代理微服务，统一管理和调度 XXL-JOB 定时作业的注册、执行和状态管理。 |
| 21 | ansible-proxy | 基于 Java 的 Ansible 命令执行代理微服务，负责接收远程执行请求并通过 SSH/Ansible 在目标主机上执行命令和脚本。 |
| 22 | message-service | 基于 Java 的消息推送服务，负责 CMDB 系统的站内消息、邮件通知和待办事项管理。 |
| 23 | qz-elasticsearch | 基于 Java 的 Elasticsearch 封装微服务，为 CMDB 系统提供全文搜索和数据索引管理功能。 |

### 3.2 前端 Web 服务（6个）

| 序号 | 服务名称 | 简要说明 |
|------|---------|---------|
| 1 | ui-master | 基于 Vue.js 的 CMDB 系统主门户前端应用，提供登录、系统管理、角色权限、租户管理等基础管理功能界面。 |
| 2 | ui-ops-cmdb | 基于 Vue.js 的 CMDB 核心业务前端应用，提供模型管理、配置项管理、数据采集、消费视图、机柜管理等核心功能界面。 |
| 3 | ui-common | 基于 Vue.js 的公共组件库前端服务，提供 CMDB 系统通用的业务组件和配置中心界面。 |
| 4 | ui-ops-component | 基于 Vue.js 的运维组件库前端服务，提供脚本管理、流程编排、定时任务等运维操作的通用组件。 |
| 5 | ui-workbench | 基于 Vue.js 的工作台前端应用，提供个人工作门户、待办管理、日历视图和系统导航功能界面。 |
| 6 | ui-app | 基于 Vue.js 的 CMDB 移动端应用，提供 CMDB 数据的移动端查看和操作能力。 |
