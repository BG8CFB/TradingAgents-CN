# LLM 模型并发控制机制设计

- **版本**：v1.0
- **日期**：2026-06-14
- **作者**：协作设计（用户 + Claude）
- **状态**：草案，待用户审阅

---

## 1. 背景与目标

### 1.1 业务诉求

当前 TradingAgents-CN 在 LLM 调用层缺乏可配置的并发控制：

- **Stage 1 多分析师**：当前 LangGraph 用 `add_edge` 串行连接，5 个分析师依次跑，单次分析耗时长
- **多任务并发**：多个用户/多个分析任务同时触发时，对同一模型的 LLM 调用数量不可控，容易被上游 API 限流（OpenAI/DeepSeek/DashScope 等）
- **现有 `LLMRateLimiter`**：定义了 per-provider 信号量，但 key 不到 model 级别；`@rate_limited` 装饰器定义后从未被调用

用户期望：

1. 在添加 LLM 模型时**为每个模型设置独立的并发上限**（max_concurrent）
2. 业务逻辑必须清晰：单图内分析师并行 + 多任务跨任务跨阶段共享同一模型资源池
3. 前端可视化运行状态

### 1.2 设计目标

- **粒度**：并发控制到 `(provider, model)` 维度，每个模型一个独立资源池
- **共享性**：同一模型的所有 LLM 调用（无论来自哪个任务、哪个阶段）从同一池取槽位
- **释放语义**：每次 LLM 调用结束立即释放槽位（细粒度，不等到整阶段完成）
- **公平性**：FIFO 队列，先到先得
- **可观察**：前端实时显示每个模型的占用情况与队列状态
- **行业标准**：用 Redis 分布式信号量，支持多 worker 部署
- **不改变业务语义**：辩论/风险讨论的"反驳对方上一轮发言"逻辑保留，仅在每一轮内部并行化

### 1.3 非目标

- 不引入 Celery / 独立 worker 进程（沿用现有 FastAPI + BackgroundTasks）
- 不暴露 RPM/TPM 等高级限流字段（保持代码默认值，未来需要可扩展）
- 不实现任务优先级抢占
- 不重构 Stage 4（Trader/Summary，本身串行）

---

## 2. 核心概念

### 2.1 模型资源池（LLM Resource Pool）

每个 `(provider, model)` 组合对应一个独立的资源池：

- **容量**：`max_concurrent`（用户配置，默认 4）
- **当前占用**：`used`（动态变化）
- **等待队列**：FIFO，存放因槽位不足而临时等待的 LLM 调用请求

### 2.2 槽位（Slot）

资源池中的一个最小占用单位。一次 LLM 调用申请 1 个槽位，调用结束释放。槽位是细粒度的，不是任务级的。

### 2.3 三层并发模型

| 层 | 职责 | 实现 |
|---|---|---|
| L1 任务队列层 | user/global 级粗粒度并发限制 | 现有 `QueueService`（Redis Lua 原子计数） |
| L2 任务执行层 | 单图内部并行执行各阶段 | LangGraph Send API + asyncio |
| L3 LLM 资源池层 | per-(provider, model) 细粒度并发限制 | 新增 `LLMResourcePool`（Redis 分布式信号量） |

---

## 3. 整体架构

```
┌────────────────────────────────────────────────────────────────┐
│                     前端 Vue 3 + Element Plus                  │
│  - 模型管理：每个模型卡片显示 并发 x/y 实时进度条               │
│  - 模型详情页：占用槽位、正在运行任务列表、等待队列             │
│  - 任务详情页：当前任务在两个模型池的占用/等待状态              │
│  - 提交反馈：queued 状态 + 队列位次 + 预计等待时间              │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│              FastAPI 后端                                      │
│                                                                │
│  L1 任务队列层 (现有 QueueService + 改造)                       │
│    - 入队时检查 user/global 并发（现有逻辑）                    │
│    - 不预先扣 LLM 槽位                                          │
│                                                                │
│  L2 任务执行层 (现有 analysis_service.execute_analysis_*)       │
│    - TradingAgentsGraph.propagate(...) 异步执行                 │
│    - LangGraph Send API 并行扇出 Stage 1/2/3                    │
│                                                                │
│  L3 LLM 资源池层 (新增 LLMResourcePool)                         │
│    - 每个 (provider, model) 一个 Redis 信号量                   │
│    - acquire/release 都是原子 Lua 脚本                          │
│    - FIFO 等待队列 + watcher 机制                               │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│              Redis (现有 keys + 新增 keys)                     │
│                                                                │
│  现有：                                                         │
│    qa:ready / qa:processing / qa:user_processing:{user_id}     │
│                                                                │
│  新增：                                                         │
│    qa:llm:slot:{provider}:{model}     槽位容量（数字）          │
│    qa:llm:used:{provider}:{model}     当前占用（计数器）        │
│    qa:llm:queue:{provider}:{model}    FIFO 等待队列（列表）     │
│    qa:llm:waiter:{provider}:{model}:{task_id}:{call_id}        │
│                                          等待者唤醒通道         │
└────────────────────────────────────────────────────────────────┘
```

---

## 4. 数据模型扩展

### 4.1 LLMConfig 新增字段

在 `app/models/config.py` 的 `LLMConfig` 模型中新增：

- `max_concurrent`：整数，范围 1-200，默认 4
- 含义：该模型允许的最大并发 LLM 调用数
- 用户可在添加/编辑模型时配置

### 4.2 数据迁移

- 旧数据无 `max_concurrent` 字段时，Pydantic 默认值自动补全为 4
- 无需显式迁移脚本
- 启动时（lifespan）调用 `LLMResourcePool.sync_configurations_from_db()` 把数据库中所有 LLMConfig 的 `max_concurrent` 同步到 Redis

### 4.3 AnalysisStatus 状态扩展

新增 `QUEUED` 枚举值，语义："任务已入队等待执行"。

```
PENDING → QUEUED → PROCESSING → COMPLETED / FAILED / CANCELLED
```

---

## 5. 核心组件：LLMResourcePool

### 5.1 职责

- 维护每个 `(provider, model)` 的资源池状态
- 提供 acquire/release 接口（原子操作）
- 提供 usage 查询接口（用于前端展示）
- 提供 capacity 更新接口（用于配置变更同步）
- 提供槽位清理接口（用于异常恢复）

### 5.2 Redis 键命名约定

- 槽位容量：`qa:llm:slot:{provider}:{model}`
- 当前占用：`qa:llm:used:{provider}:{model}`
- FIFO 队列：`qa:llm:queue:{provider}:{model}`
- 等待唤醒通道：`qa:llm:waiter:{provider}:{model}:{task_id}:{call_id}`

### 5.3 acquire 语义

- 输入：(provider, model, task_id, call_id, timeout)
- 行为（整个流程必须在**单一 Lua 脚本**中原子完成，不能跨脚本分步执行）：
  1. INCR `used_key`，记为 new_used
  2. 若 new_used ≤ GET `slot_key`：
     - SADD `holders_key` `{task_id}:{call_id}`（记录持有者，用于取消时反查）
     - 返回成功
  3. 否则：
     - DECR `used_key`（回滚上面的 INCR）
     - RPUSH `queue_key` `{task_id}:{call_id}`（入 FIFO 队列）
     - SET `waiter_key:{task_id}:{call_id}` 1 EX 300（设置 5 分钟 TTL 防泄漏）
     - 调用方在 Lua 脚本返回后用 BLPOP `waiter_key:{task_id}:{call_id}` 阻塞等待唤醒
- 超时：BLPOP 等待超过 timeout（默认 300 秒）后返回失败，并清理 `waiter_key` 与 `queue_key` 中对应条目
- 关键：acquire 阶段（INCR/比较/回滚/入队）必须在同一 Lua 脚本内；BLPOP 是脚本之外的阻塞调用，但配合 watcher TTL 不会破坏原子性

### 5.4 release 语义

- 输入：(provider, model, task_id, call_id)
- 行为（同样是单一 Lua 脚本）：
  1. SREM `holders_key` `{task_id}:{call_id}`（移除持有者记录）
  2. DECR `used_key`
  3. LRANGE `queue_key` 0 0 取队首
     - 若有等待者：LPOP `queue_key` 移除队首，解析出 `{woken_task_id}:{woken_call_id}`，LPUSH `waiter_key:{woken_task_id}:{woken_call_id}` 1（唤醒那个 BLPOP）
  4. 若无等待者：直接返回
- 关键：释放是渐进的，每个 LLM 调用结束立即触发，不等待整阶段

### 5.5 holders 集合与取消时的反查

为支持"取消任务时找到该 task 持有的所有槽位"，新增：

- 持有者集合：`qa:llm:holders:{provider}:{model}`（Redis SET，元素格式 `{task_id}:{call_id}`）

取消任务时（见 7.4）：扫描所有 `holders_key`，SMEMBERS 后过滤出属于该 task_id 的所有 `{call_id}`，逐个执行 release 流程。这避免了"used 是计数器无法反查"的问题。

每次 acquire 成功 SADD、release 时 SREM，集合内容与 used 计数始终保持同步。

### 5.5 Lua 脚本的原子性

所有 acquire/release/查询操作都用单 Lua 脚本完成。Redis 单线程执行 Lua 保证原子性，多 worker 间不会出现竞态。

### 5.7 防泄漏机制

- 每次 acquire 给 `waiter_key` 设置 5 分钟 TTL
- 任务正常结束时清理所有该 task_id 持有的槽位
- Worker 启动时扫描 `qa:llm:used:*`，把"占用但已无对应任务"的槽位回收
- Visibility timeout 5 分钟未唤醒自动失败

---

## 6. LangGraph 拓扑改造

### 5.8 与现有 LLMRateLimiter 的协同

**接入顺序**（在 `_invoke_llm` 内）：

1. **先**调用 `LLMResourcePool.acquire(provider, model, task_id, call_id)`：获得跨进程的并发槽位
2. **再**调用现有 `LLMRateLimiter.rate_limited_call(provider, ...)`：获得进程内的 RPM/TPM 限流补充
3. 调用底层 `llm.ainvoke(...)`
4. finally 中先 release LLMRateLimiter，再 release LLMResourcePool

**为什么保留 LLMRateLimiter**：
- LLMResourcePool 只控**并发数**，不控**调用频率**（每分钟请求数）
- LLMRateLimiter 保留作为 RPM/TPM 的滑动窗口限流，防止短时间内 burst 调用击穿上游 API 配额
- 两者职责互补，不冲突

**未来优化**：当 LLMResourcePool 落地稳定后，可以把 LLMRateLimiter 的功能合并进 LLMResourcePool（同一类内同时维护并发槽 + RPM 滑动窗口），届时下线 LLMRateLimiter。本次不做此重构。

### 6.1 Stage 1：分析师并行扇出

**改造前**：N 个分析师节点用 `add_edge` 串行连接。

**改造后**：用 LangGraph Send API 扇出：

- 新增 `Stage1Fanout` 占位节点与 `Stage1Reduce` 聚合节点
- `Stage1Fanout` 的 conditional_edges 路由函数返回 N 个 `Send`，每个指向一个分析师节点
- 所有分析师节点连到 `Stage1Reduce`
- `Stage1Reduce` 连到下一阶段入口

**LangGraph 行为**：Send 出去的节点并行执行。由于底层已接入 LLMResourcePool，槽位不足时部分节点会阻塞在 `acquire()`，待其他节点释放后被唤醒。

**效果**：5 个分析师，模型并发=4 → 4 个并行启动 + 1 个等待，谁先完成释放槽位，第 5 个立即顶上。

### 6.2 Stage 2：辩论同轮内并行

**业务语义保留**：每个发言者仍然反驳"对方上一轮的报告"。只是同一轮内的两个发言不再串行等待。

**改造前**：Bull ↔ Bear 用 `latest_speaker` 在 conditional_edges 中交替路由，本质串行。

**改造后**：

- 新增 `DebateFanout` 与 `DebateReduce` 节点
- `DebateFanout` 的路由函数判断当前轮次：
  - 若已达最大轮次：返回 `"Research Manager"`
  - 否则：返回 `[Send("Bull Researcher", state), Send("Bear Researcher", state)]`
- 两个发言者都连到 `DebateReduce`
- `DebateReduce` 再连回 `DebateFanout`（继续下一轮）或 `Research Manager`（结束）

**关键不变量**：每个发言者读取 state 中"对方上一轮的报告"。同一轮的两个发言并行执行，但下一轮开始前必须等本轮两个发言都完成（LangGraph 自动保证 reduce 节点等待所有上游）。

**state 快照隔离要求（实施时必须验证）**：

- Send 出去的两个发言节点读取的"对方上一轮报告"必须是本轮开始前的**不可变快照**
- 在 Send 路由函数中显式构造快照：把当前 state 中 `bull_reports` / `bear_reports` 列表深拷贝后作为 Send payload 传入
- 两个节点不能直接读写全局 state 的同一个列表字段（否则会出现并发写入冲突，对应 [LangGraph Forum 的 merge message issues](https://forum.langchain.com/t/seeking-help-with-some-merge-message-issues-when-langgraph-is-called-in-parallel/3007)）
- 节点输出由 `DebateReduce` 聚合：把本轮 Bull 输出 append 到 `bull_reports`、Bear 输出 append 到 `bear_reports`，再交给下一轮路由函数读取
- 实施时必须新增单元测试：模拟 Bull 与 Bear 同时写入，验证最终 state 中报告数量正确（不丢失、不重复）

### 6.3 Stage 3：风险讨论同轮内并行

同理：

- `RiskFanout` 路由函数判断轮次：
  - 达到上限：返回 `"Risk Judge"`
  - 否则：返回 `[Send("Risky", state), Send("Safe", state), Send("Neutral", state)]`
- 三个发言者并行执行
- `RiskReduce` 聚合后路由回 `RiskFanout` 或 `Risk Judge`

### 6.4 各阶段最大并发 LLM 调用数

| 阶段 | 同一任务内最大 LLM 并发 | 占用的模型池 |
|---|---|---|
| Stage 1 | N（取决于分析师配置数） | analyst_model 池 |
| Stage 2 同轮 | 2（Bull + Bear） | debate_model 池 |
| Stage 3 同轮 | 3（Risky + Safe + Neutral） | debate_model 池 |
| Stage 4 | 1（Trader / Summary） | debate_model 池 |

### 6.5 跨任务跨阶段槽位占用模型

- **同一任务同一时刻只在一个阶段**（Stage 1 完成后才进 Stage 2）
- **每个阶段在该阶段 LLM 调用发起时按细粒度扣对应模型池槽位**
- **不同任务可能各自处在不同阶段**，每个任务当前阶段的占用总和 = 该模型池当前 used 数
- 当 used < max_concurrent 时新调用立即获得槽位；否则进入该模型池的 FIFO 队列等待

---

## 7. 任务队列调度

### 7.1 入队逻辑

`QueueService.enqueue_task`：

1. 检查 user 并发上限（现有，默认 3）
2. 检查 global 并发上限（现有，统一为合理值，需修复 keys.py:22 与 config.py 的不一致）
3. **不预先扣 LLM 槽位**（槽位在 LLM 调用时细粒度扣）
4. 任务状态置为 `QUEUED`
5. 推入 `qa:ready` 队列
6. 立即返回 task_id 给前端

### 7.2 出队逻辑

`QueueService.dequeue_task`：

1. 从 `qa:ready` 原子取出任务（现有 Lua 脚本）
2. 任务状态置为 `PROCESSING`
3. 交给 worker 执行 `execute_analysis_background`

### 7.3 任务进度透明化

通过现有 SSE/WebSocket/Redis PubSub 通道推送新事件类型：

- `slot_waiting`：包含 stage、model、队列位次、预计等待时间
- `slot_acquired`：包含 stage、model
- `stage_progress`：包含 stage、completed/total

前端接收后实时更新任务详情页的"资源占用"区块。

### 7.4 任务取消

`POST /api/analysis/{task_id}/cancel`：

1. 现有取消逻辑（置 CANCELLED 状态）
2. **新增清理**：
   - 从 `qa:ready` 移除（若在队列中）
   - 清理该 task_id 的所有 `qa:llm:waiter:*` 等待键
   - 释放该 task_id 已占用的 LLM 槽位（扫描 `qa:llm:used:*` 找到该 task 持有的）
   - 唤醒受影响的等待者

### 7.5 异常恢复

- 任务异常终止：`execute_analysis_background` 的 finally 块调用 `llm_pool.cleanup_task_slots(task_id)`
- Worker 进程崩溃：启动时 `LLMResourcePool.cleanup_leaked_slots()` 扫描所有 used_key，与活跃任务列表对比，回收泄漏
- Watchdog：每个 acquire 的 waiter_key 设置 5 分钟 TTL，防止永久等待

### 7.6 端到端时序示例

**场景 A**：analyst=DeepSeek (4并发)，5 个分析师，1 个任务

- t=0s：用户提交任务 #1，立即返回 task_id, status=QUEUED
- t=0s+：Worker 取出，进入 PROCESSING，Stage 1 扇出 5 个分析师
  - 4 个 acquire 成功（4/4），1 个进入等待队列
- t=12s：Market Analyst 完成 → 释放 1 槽 → 队首等待者被唤醒
- ...
- t=45s：Stage 1 全部完成 → 进入 Stage 2（debate 池）
- t=80s：Stage 2 完成 → 进入 Stage 3
- t=120s：DONE

**场景 B**：t=10s 时提交任务 #2，此时任务 #1 仍占满 analyst 池

- t=10s：任务 #2 入队，Worker 取出，Stage 1 扇出 5 个分析师
- 全部 acquire 失败 → 全部进入 analyst 池等待队列（5 个等待者）
- t=12s：任务 #1 释放 1 槽 → 任务 #2 队首分析师被唤醒 → 占用 1 槽
- 按 FIFO 顺序逐步释放与唤醒

---

## 8. 前端设计

### 8.1 模型添加/编辑表单

在 `frontend/src/views/Settings/components/LLMConfigDialog.vue` 的"高级设置"折叠面板中新增：

- **最大并发数 (max_concurrent)** 输入框
  - 类型：数字输入
  - 默认值：4
  - 范围：1-200
  - 校验：必填、整数、范围内
  - 帮助文本：「该模型允许同时进行的 LLM 调用数。设置过高可能被上游 API 限流。范围 1-200，默认 4」
  - 修改提示：保存时弹窗"此修改对正在运行的任务无效，新任务将使用新值"

不暴露 RPM/TPM 等高级字段（保持代码默认值）。

### 8.2 模型列表 — 实时并发状态

每个模型卡片显示：

- 模型名称、provider、是否启用（现有信息）
- **新增：并发占用进度条**
  - 显示格式：`2/4` 配合可视化进度条
  - 颜色：< 50% 绿色，50-80% 黄色，> 80% 红色
- 当前正在运行任务数
- 当前等待队列长度
- 「详情」「编辑」「删除」按钮

数据通过 `GET /api/llm/usage` 拉取，30 秒轮询一次（或 SSE 推送，未来优化）。

### 8.3 模型详情页（新增）

路由：`/settings/llm/:provider/:model`

内容：

- **基本信息**：provider、model、max_concurrent（带「修改」按钮）
- **实时状态**：槽位占用进度条、队列长度
- **正在运行的任务列表**：task_id、股票代码、当前阶段、阶段进度
- **等待队列**：task_id、股票代码、队列位次、预计等待时间

### 8.4 任务详情页 — 资源占用区块

在现有任务详情页新增"资源占用"区块：

- **analyst_model**：占用 X 槽 / 共 Y 槽，状态（已获得/等待中）
- **debate_model**：占用 X 槽 / 共 Y 槽，状态（已获得/等待中）、队列位次、预计等待时间

通过现有 SSE 通道接收 `slot_waiting` / `slot_acquired` 事件实时更新。

### 8.5 提交任务的反馈

任务提交后立即返回 task_id，前端跳转到任务详情页：

- 模型当前未满载：显示「任务已提交，预计 ~5 秒后开始执行」
- 模型当前满载：显示「任务已提交，等待资源，分析师模型 X 当前满载 (4/4)，你的任务在队列第 N 位，预计等待 ~30 秒」

---

## 9. API 端点

### 9.1 新增端点

- `GET /api/llm/usage`：返回所有模型的实时占用列表，用于列表页
- `GET /api/llm/usage/{provider}/{model}`：返回单个模型的详细占用 + 正在运行任务列表 + 等待队列，用于详情页

### 9.2 现有端点扩展

- `POST /api/llm`：接受 `max_concurrent` 字段
- `PUT /api/llm/{id}`：接受 `max_concurrent` 字段
- `DELETE /api/llm/{id}`：拒绝删除当前有任务在使用的模型，返回 409 + 提示

### 9.3 配置变更同步

修改 max_concurrent 时：

1. 写入 MongoDB（现有逻辑）
2. 调用 `LLMResourcePool.update_capacity(provider, model, new_value)` 同步 Redis
3. 若新值 > 旧值，唤醒队列中等待的任务（按 FIFO）

---

## 10. 启动流程

`app/main.py` 的 lifespan 新增初始化：

1. 从数据库加载所有 `LLMConfig`
2. 把每个模型的 `max_concurrent` 同步到 Redis（`SET qa:llm:slot:{provider}:{model}`）
3. 扫描清理可能的泄漏槽位（重启前未释放的，与活跃任务列表对比）

退出时无需特殊清理（Redis 状态持久化，下次启动复用）。

---

## 11. 错误处理与降级

| 错误场景 | 处理 |
|---|---|
| Redis 连接失败 | 资源池降级为进程内 `asyncio.Semaphore`（带警告日志），多 worker 部署时上限可能被突破 |
| Lua 脚本执行失败 | 调用方重试 3 次，仍失败则任务标记为 FAILED |
| 任务超时未释放槽位 | waiter_key TTL 5 分钟自动回收 + watchdog 检查 |
| LLM 调用异常 | `_invoke_llm` 的 finally 块确保释放槽位 |
| Worker 进程崩溃 | 启动时扫描清理 + visibility timeout |
| 删除有任务使用的模型 | API 返回 409 拒绝删除 |
| 修改正在使用的模型配置 | 接受修改，但提示"对正在运行的任务无效" |

---

## 12. 测试策略

### 12.1 单元测试

- `LLMResourcePool` 的 Lua 脚本逻辑（用 fakeredis 模拟）
- Stage 1 Send API 扇出（构造一个最小 LangGraph，验证并行执行）
- `LLMConfig.max_concurrent` 字段验证
- FIFO 队列顺序的正确性

### 12.2 集成测试（连真实 Redis + MongoDB）

- 端到端：2 个并发任务，验证 FIFO 与槽位释放顺序
- 异常恢复：手动 kill 任务，验证槽位被回收
- 配置变更：运行中修改 max_concurrent，验证新任务生效
- 取消任务：取消正在等待槽位的任务，验证等待队列清理

### 12.3 回归测试

- 单分析师配置：扇出只有 1 个节点，等价于原来串行（向后兼容）
- 关闭 Stage 2/3：路径走 trader → summary，无并发变化
- 单 worker 部署：验证基础功能正常

### 12.4 压力测试（手动）

- 同时提交 10 个任务，验证 deepseek 4 并发上限不被突破（监控 used_key 最大值）
- 单任务内部 5 分析师，验证最多 4 个并发槽位被占

### 12.5 测试规则

遵循 CLAUDE.md：

- 全部测试在 Miniconda conda env `tradingagents` 内运行
- 连真实 Docker 容器化的 MongoDB + Redis（不引入 fakeredis 或任何 Redis 模拟器，所有 Lua 脚本测试在真实 Redis 上验证）
- 严禁任何业务 mock（包括 unittest.mock、pytest-mock、MagicMock、patch）
- 临时脚本放 `.ai_temp/tests/`，完成后删除

---

## 13. 涉及的文件清单

### 13.1 后端新建

- `app/services/llm_resource_pool.py`：LLMResourcePool 类与 Lua 脚本
- `app/routers/config/llm_usage.py`（或扩展现有 llm.py）：usage 端点
- 相关单元测试与集成测试

### 13.2 后端改造

- `app/models/config.py`：LLMConfig 增加 `max_concurrent` 字段
- `app/models/analysis.py`：AnalysisStatus 增加 `QUEUED` 枚举
- `app/engine/graph/setup.py`：Stage 1/2/3 拓扑改为 Send API 扇出
- `app/engine/agents/analysts/simple_agent_template.py`：把硬编码的 `llm_provider="default"` 改为传入真实 (provider, model)
- `app/engine/agents/executors/agent_executor.py`：`_invoke_llm` 接入 LLMResourcePool
- `app/services/queue_service.py`：状态机扩展 + 取消时清理槽位
- `app/services/queue/keys.py`：修复 GLOBAL_CONCURRENT_LIMIT 不一致
- `app/services/analysis_service.py`：finally 块清理槽位
- `app/main.py`：lifespan 初始化资源池
- `app/utils/llm_rate_limiter.py`：与 LLMResourcePool 协同（或保留作为进程内补充）

### 13.3 前端新建

- `frontend/src/views/Settings/LLMDetails.vue`：模型详情页

### 13.4 前端改造

- `frontend/src/views/Settings/components/LLMConfigDialog.vue`：表单加 max_concurrent 字段
- `frontend/src/views/Settings/ConfigManagement.vue` 或模型列表组件：显示并发进度条
- 现有任务详情组件：新增"资源占用"区块
- 提交任务后的反馈 UI
- `frontend/src/api/config.ts`：新增 usage API 调用

---

## 14. 行业标准参考

本设计参考了主流 LLM 平台的并发控制模式：

- **Dify**：基于 Celery + Redis 的分布式任务调度，per-queue 并发控制
- **FastGPT**：通过 OneAPI 网关实现按 channel（模型）的限流
- **LangGraph Send API**：动态扇出并行的官方推荐机制
- **Redis 分布式信号量**：多副本 LLM 推理服务的行业标准（多 worker 部署时进程内信号量失效）
- **三层并发漏斗**：接入层 → 调度层 → 模型层，主流 LLM 推理平台通用模式

参考资料：

- LangGraph Send API: https://forum.langchain.com/t/best-practices-for-parallel-nodes-fanouts/1900
- Redis LLMOps Guide: https://redis.io/blog/large-language-model-operations-guide/
- Token & Rate Limits in LLM Inference: https://www.typedef.ai/resources/handle-token-limits-rate-limits-large-scale-llm-inference
- Upstash Redis in LLM Apps: https://upstash.com/blog/redis-in-llms

---

## 15. 风险与权衡

| 风险 | 影响 | 缓解 |
|---|---|---|
| Stage 1/2/3 拓扑改造回归风险 | 可能影响分析质量 | 充分回归测试 + 单分析师配置等价于原串行 |
| LangGraph Send API 状态合并 | 已知社区有坑（merge message issues） | 在 Stage1Reduce 等聚合节点显式合并 state |
| Redis 单点故障 | 全局并发控制失效 | 降级为进程内 Semaphore + 警告日志 |
| Lua 脚本性能 | 高并发时 Redis 单线程瓶颈 | 实测在 100+ QPS 下仍可接受，未来可分片 |
| 槽位泄漏 | 长期运行后 used 计数偏高 | TTL + 启动扫描 + watchdog |
| 修改 max_concurrent 不影响运行中任务 | 用户体验有歧义 | UI 明确提示 |

---

## 16. 后续扩展（YAGNI）

本次不做，但架构预留扩展空间：

- **RPM/TPM 限流**：在 LLMConfig 增加 rpm/tpm 字段，资源池扩展滑动窗口计数
- **任务优先级抢占**：高优先级任务可以抢占低优先级任务的槽位
- **多模型负载均衡**：同一角色配置多个模型，资源池自动路由到空闲的
- **成本控制**：累计 token 用量达到阈值自动停用模型
- **按用户配额**：不同用户对不同模型有不同的并发上限

---

## 17. 开放问题（已采纳的答案）

1. **`GLOBAL_CONCURRENT_LIMIT` 不一致**：当前 `queue/keys.py` 中为 3、`core/config.py` 默认为 50。**采纳**：统一为 `core/config.py` 的 50，并删除 `queue/keys.py:22` 的硬编码常量，改为从 settings 读取。理由：global 并发限制是粗粒度上限（任务级），LLM 级细粒度并发由 LLMResourcePool 负责，50 是合理默认。

2. **删除模型时若有任务在使用**：**采纳** 409 拒绝方案，前端显示"模型 X 当前有 N 个任务正在使用，无法删除。请等待任务完成或先停用模型"。

3. **修改 max_concurrent 后动态生效**：**采纳**"允许动态生效，唤醒等待者"。理由：用户调小后若无动态生效机制，正在运行的任务可能卡死或破坏 FIFO 公平性。

---

## 18. 验收标准

- 用户可在添加/编辑模型时配置 `max_concurrent`（默认 4）
- 提交任务时若目标模型满载，任务自动排队并返回 `QUEUED` 状态
- 前端模型列表实时显示每个模型的 x/y 占用
- 模型详情页可查看正在运行任务列表与等待队列
- 任务详情页可查看该任务在两个模型池的占用情况
- Stage 1 多分析师在同一任务内并行执行
- Stage 2/3 同轮内的多个发言者并行执行（语义不变）
- 跨任务跨阶段，同一模型的并发上限不被突破
- 取消任务时正确清理所有占用的槽位与等待键
- Worker 重启后能识别并回收泄漏的槽位
