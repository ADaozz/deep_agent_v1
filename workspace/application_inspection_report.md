# 三台机器 ~/application 目录服务检查报告

**检查时间**: 2026-04-10  
**检查范围**: 10.1.2.13, 10.1.2.11, 10.1.2.14 三台机器的 ~/application 目录

---

## 目录

1. [总体概览](#总体概览)
2. [10.1.2.13 详细检查](#101213-详细检查)
3. [10.1.2.11 详细检查](#101211-详细检查)
4. [10.1.2.14 详细检查](#101214-详细检查)
5. [跨机器共性问题](#跨机器共性问题)
6. [建议与修复方案](#建议与修复方案)

---

## 总体概览

| 机器 IP | 服务数量 | 主要问题 | 严重性 |
|---------|----------|----------|--------|
| 10.1.2.13 | 7 个 | Nacos 连接失败、MongoDB 连接问题、服务间通信异常 | 高 |
| 10.1.2.11 | 6 个 | Nacos 无路由、服务名无法解析、Kafka 重平衡 | 高 |
| 10.1.2.14 | 11 个 | Nacos 连接异常、认证授权失败、服务调用超时 | 高 |

---

## 10.1.2.13 详细检查

### 服务列表（共 7 个）

| 序号 | 服务名称 | 说明 |
|------|----------|------|
| 1 | keyManage | 密钥管理服务 |
| 2 | logs | 日志目录 |
| 3 | ops-cmdb | 运维配置管理服务 |
| 4 | ops-data-access | 运维数据访问服务 |
| 5 | ops-script-repertory | 运维脚本仓库服务 |
| 6 | ops-synapplication-activiti | 运维同步应用工作流服务 |
| 7 | temp | 临时目录 |

### 日志报错详情

#### 1. ops-cmdb 服务

**a) Nacos 连接失败**
```
ERROR - Server check fail, please check server 10.1.2.6, port 9848 is available
java.net.ConnectException: 拒绝连接
```
- **问题**: 无法连接到 Nacos 服务器 10.1.2.6:9848
- **时间**: 2024-11-17

**b) Redis 循环依赖**
```
ERROR - Application run failed
org.springframework.beans.factory.UnsatisfiedDependencyException: 
Error creating bean with name 'citFieldsInfoCache': Circular reference involving containing bean 'redisUtil'
java.lang.NullPointerException
```

**c) MongoDB 连接问题**
```
com.mongodb.MongoSocketOpenException: Exception opening socket
Caused by: java.net.ConnectException: 拒绝连接
com.mongodb.MongoNodeIsRecoveringException: interrupted at shutdown
```

**d) Feign 调用错误**
```
ERROR - ops-data-model executing GET http://ops-data-model/getDataDictByType/message
feign.RetryableException: ops-data-model
Caused by: java.net.UnknownHostException: ops-data-model
```

**e) JSON 解析错误**
```
feign.codec.DecodeException: JSON parse error: 
Unexpected character ('}' (code 125)): was expecting a colon to separate field name and value
```

#### 2. ops-script-repertory 服务

**UnknownHostException**
```
ERROR - ops-data-model executing GET http://ops-data-model/getDataDictByType/message
feign.RetryableException: ops-data-model
Caused by: java.net.UnknownHostException: ops-data-model
```

#### 3. ops-data-access 服务

**调度记录未找到（持续出现）**
```
ERROR - 未找到对应的调度记录，查询条件：{"_id":"..."}
```

---

## 10.1.2.11 详细检查

### 服务列表（共 6 个）

| 序号 | 目录名称 | 说明 |
|------|----------|------|
| 1 | data | 数据目录 |
| 2 | log | 公共日志目录 |
| 3 | message-service | 消息服务 |
| 4 | ops-data-access | 运维数据访问服务 |
| 5 | ops-synapplication-common | 运维同步应用公共模块 |
| 6 | translation-service | 转换服务 |

### 日志报错详情

#### 1. message-service 服务

**a) UnknownHostException - qz-usercenter 无法解析**
```
feign.RetryableException: qz-usercenter: unknown error executing GET http://qz-usercenter/getDataDictByType/message
java.net.UnknownHostException: qz-usercenter: unknown error
```
- **出现时间**: 从 2024-12-31 到 2026-04-10 持续出现
- **规律**: 每天凌晨 00:00 左右定时任务执行时失败

**b) Kafka RebalanceInProgressException**
```
org.apache.kafka.common.errors.RebalanceInProgressException: The group is rebalancing, so a rejoin is needed.
```
- **出现时间**: 2025-01-10

#### 2. ops-data-access 服务

**a) Nacos 服务器连接失败**
```
com.alibaba.nacos.shaded.io.grpc.StatusRuntimeException: UNAVAILABLE: io exception
java.net.NoRouteToHostException: 没有到主机的路由：/10.1.2.6:9848
Server check fail, please check server 10.1.2.6 ,port 9848 is available
```
- **根本原因**: 无法连接到 Nacos 服务器 10.1.2.6:8848/9848
- **出现时间**: 2026-03-30 10:30 左右（服务启动时）
- **影响**: 导致服务启动失败 Application run failed

**b) UnknownHostException - ops-data-model 无法解析**
```
feign.RetryableException: ops-data-model executing GET http://ops-data-model/getDataDictByType/message
java.net.UnknownHostException: ops-data-model
```

**c) 未找到对应的调度记录**
```
ERROR - 未找到对应的调度记录，查询条件：{"_id":"..."}
```

#### 3. translation-service 和 ops-synapplication-common

- 未发现明显 ERROR 级别报错

---

## 10.1.2.14 详细检查

### 服务列表（共 11 个）

| 序号 | 服务/目录名 |
|------|-------------|
| 1 | data |
| 2 | log |
| 3 | logs |
| 4 | ops-data-access |
| 5 | ops-data-model |
| 6 | qz-elasticsearch |
| 7 | qz-gateway |
| 8 | qz-usercenter |
| 9 | sso-auth |
| 10 | sso-gateway |
| 11 | sso-resouce |

### 日志报错详情

**总错误数：448,707 条**（包含 error/ERROR/Exception）

#### 1. ops-data-access

```
ERROR - 未找到对应的调度记录，查询条件：{"_id":"..."}
ERROR - Client not connected, current status:UNHEALTHY
ERROR - TimeoutException: Waited 3000 milliseconds
ERROR - Server check fail, please check server 10.1.2.6, port 9848
```

#### 2. ops-data-model

```
NACOS ConnectException httpGet] currentServerAddr:http://10.1.2.5:8848, err : 拒绝连接
Connection refused
```

#### 3. qz-usercenter

```
feign.RetryableException: ops-data-model: unknown error executing POST http://ops-data-model/datadict/getDicts
java.net.UnknownHostException: ops-data-model
initResourceCodeUtil() failed!
getAllMenuCodeByUser() err !
```

#### 4. qz-gateway

```
java.io.IOException: Error while acquiring from reactor.netty
io.netty.channel.unix.Errors$NativeIoException: readAddress(..) failed: Connection reset by peer
500 Server Error for HTTP POST "/qz-usercenter/thirdAuth/login"
```

#### 5. sso-auth

```
InvalidGrantException, Invalid authorization code
error="invalid_token", error_description="Token not valid"
ResourceAccessException: I/O error on POST request for "http://172.10.0.176:8080/sso/logout": 连接超时
java.net.ConnectException: 连接超时
```

---

## 跨机器共性问题

### 1. Nacos 服务注册/配置中心连接异常

| 机器 | Nacos 服务器 | 端口 | 错误类型 |
|------|-------------|------|----------|
| 10.1.2.13 | 10.1.2.6 | 9848 | 拒绝连接 |
| 10.1.2.11 | 10.1.2.6 | 9848 | 无路由到主机 |
| 10.1.2.14 | 10.1.2.5/10.1.2.6 | 8848/9848 | 拒绝连接/超时 |

**影响**: 服务无法注册、配置无法获取、服务发现失败

### 2. 服务间调用失败（UnknownHostException）

| 机器 | 无法解析的服务 |
|------|---------------|
| 10.1.2.13 | ops-data-model |
| 10.1.2.11 | ops-data-model, qz-usercenter |
| 10.1.2.14 | ops-data-model |

**影响**: Feign 远程调用失败，业务功能异常

### 3. ops-data-access 调度记录缺失

三台机器均出现：
```
ERROR - 未找到对应的调度记录，查询条件：{"_id":"..."}
```

**影响**: 调度任务执行异常，数据同步失败

### 4. 网络连接不稳定

- 连接重置（Connection reset by peer）
- 连接超时
- MongoDB 连接被拒绝

---

## 建议与修复方案

### 高优先级

1. **检查 Nacos 服务器状态**
   - 确认 10.1.2.5:8848 和 10.1.2.6:8848/9848 服务是否正常运行
   - 检查防火墙规则是否阻止了连接
   - 验证 Nacos 集群健康状态

2. **修复服务发现配置**
   - 检查各服务的 Nacos 配置是否正确
   - 确认服务注册名称与实际调用名称一致
   - 验证 DNS 或 hosts 解析配置

3. **排查 ops-data-access 数据一致性问题**
   - 检查 MongoDB 数据完整性
   - 确认调度记录写入和查询逻辑
   - 排查是否存在数据同步延迟

### 中优先级

4. **修复 ops-cmdb Redis 循环依赖**
   - 重构 Bean 依赖关系
   - 使用 @Lazy 注解或重新设计缓存结构

5. **优化 Kafka 消费组配置**
   - 调整 rebalance 超时时间
   - 检查消费者组配置一致性

6. **检查 SSO 认证配置**
   - 验证 Token 生成和刷新逻辑
   - 检查授权码有效期配置
   - 确认 172.10.0.176:8080 服务可达性

### 低优先级

7. **日志优化**
   - 统一日志级别和格式
   - 添加更详细的错误上下文信息
   - 配置日志告警阈值

---

## 附录：日志文件位置汇总

### 10.1.2.13
- `~/application/ops-cmdb/logs/ops-cmdb/`
- `~/application/ops-script-repertory/logs/ops-script-repertory/`
- `~/application/ops-data-access/logs/ops-data-access/`
- `~/application/logs/`

### 10.1.2.11
- `~/application/message-service/logs/message-service/`
- `~/application/ops-data-access/logs/ops-data-access/`
- `~/application/log/`

### 10.1.2.14
- `~/application/ops-data-access/logs/ops-data-access/`
- `~/application/ops-data-model/logs/ops-data-model/`
- `~/application/log/qz-usercenter/`
- `~/application/logs/sso-authentication/`
- `~/application/logs/gateway/`

---

**报告生成时间**: 2026-04-10  
**检查工具**: 多 Agent 分布式检查系统
