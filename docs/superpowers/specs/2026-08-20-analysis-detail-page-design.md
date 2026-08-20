# 分析详情页与批量分析展示设计

日期：2026-08-20
状态：已与用户确认方案方向

## 背景与目标

当前 `/analysis/single`（`frontend/src/views/Analysis/SingleAnalysis.vue`，约 3300 行）把表单、进度卡片、结果报告全部堆在同一个页面；提交分析后不跳转路由，进度与过程展示受限于同页布局。批量分析提交后直接跳任务中心表格，缺少聚合视图。

目标：

1. 新增**分析详情页**，作为单次分析运行/回放/历史查看的唯一入口
2. 分析过程以 **Claude Code 式实时上下文流**呈现（工具调用、LLM 输出、压缩、用户消息注入实时可见）
3. `/analysis/single` 瘦身为纯提交表单
4. 新增**批量分析聚合页**，以卡片网格展示各任务状态与结论

核心判断：所需事件基建已全部存在（`app/llm/events.py` 的 EventSink、WS `/api/analysis/ws/task/{id}`、回放 `GET /tasks/{id}/events`、`ProcessPanel.vue`），本设计主要是**前端信息架构与呈现层重构**，后端仅补一个聚合接口。

## 页面结构

### 分析详情页 `/analysis/tasks/:taskId`

入口：

- 单次分析提交成功后 `router.push`
- 任务中心"查看"操作
- 批量页卡片点击
- 历史任务回放

布局（桌面优先，窄屏时左侧栏折叠为顶部摘要）：

```
┌────────────────────────────────────────────────────────────┐
│ 顶栏：返回 | 股票代码+名称 | 状态徽标 | 已耗时 | 操作按钮   │
├──────────────┬─────────────────────────────────────────────┤
│ 左侧栏 280px │ 主区域                                       │
│ 分析配置卡片  │ 阶段化进度条（分析→辩论→风控→交易）           │
│ 股票信息卡片  │ Tab: 实时过程 | 分析报告                      │
└──────────────┴─────────────────────────────────────────────┘
```

- 左侧栏固定 280px，两个卡片：**分析配置**（智能体 chips、辩论轮次、模型、分析日期）、**股票基础信息**（名称/市场/行业/最新价，统一定义列表样式）
- 顶栏操作按钮组右对齐：运行中显示"取消"（`POST /tasks/{id}/cancel`，沿用现有接口）；completed/failed/cancelled 显示下载 md/docx/pdf/json（沿用现有下载实现；cancelled 可能无报告，此时仅显示"重新发起分析"入口）
- 状态机（顶栏徽标 + 页面行为）：`pending/running`（实时流 + 进度条）→ `completed`（自动切"分析报告" tab，可切回 replay）/ `failed`（el-alert 错误 + 失败 agent 红色标记）/ `cancelled`（灰色徽标 + "任务已取消"提示，事件流定格在取消点）
- 分析完成后自动切到"分析报告" tab；用户可切回"实时过程"（replay 模式）

### 单次分析页 `/analysis/single` 瘦身

- 保留表单与提交逻辑；提交成功后写 localStorage 任务缓存（30 分钟有效，供"有进行中任务"恢复提示）并跳转详情页。缓存 key 按用户维度隔离（如 `trading_analysis_task:{user_id}`），避免同浏览器切换账号后出现他人任务的恢复提示
- 进度卡片、结果报告区、ProcessPanel 引用全部迁出

## Claude Code 式实时上下文流

改造 `frontend/src/components/Analysis/ProcessPanel.vue`：从"按 agent 分 tab"改为**单一纵向事件流**：

- 每个 agent 一个可折叠段落：头部 `● 市场分析师 ✓ 完成 · 1m32s`（运行中为转圈动画）；当前运行中的 agent 自动展开，已完成自动折叠为摘要行
- 段落内按事件渲染：
  - `tool_call`/`tool_result` → 折叠行 `⏺ get_stock_data(000001)` + 耗时/错误标记，展开看 input/output（>400 字符截断，沿用现有逻辑）
  - `llm_response` → assistant 气泡（markdown，经 `utils/markdown.ts` 渲染）
  - `compact` → 灰色细提示行"上下文压缩 8.2k → 3.1k tokens"
  - `user_message_injected` → 高亮用户消息气泡
- 底部消息输入框保留（复用 `stores/analysisProcess.ts` 的 `sendAgentMessage`，仅运行中可用）
- 滚动策略：自动滚底；用户上滚即暂停，显示"回到底部"悬浮按钮
- 性能：仅渲染最近 500 条事件，更早的折叠为"加载更早事件"
- `text_delta` 仅实时通道做流式渲染；回放模式用 `llm_response` 全量

事件分页协议（后端配合改动）：现有 `GET /tasks/{id}/events` 仅支持 `after_seq` 升序、limit≤500，无法取"最近 500 条"或向前翻页。扩展该接口增加 `before_seq` + `order=desc` 参数：`order=desc` 按 seq 降序返回，`before_seq` 取该 seq 之前的一段。前端首拉 `order=desc&limit=500` 得到最近 500 条（本地再反转为升序），"加载更早事件"携带当前最小 seq 作为 `before_seq` 继续向前翻。

## 批量分析页 `/analysis/batches/:batchId`

- 顶部汇总卡：进度环（完成/总数）+ 状态计数（运行中/排队/成功/失败）+ 批量操作（全部下载）
- 任务卡片网格（el-row/el-col 响应式）：每卡 = 代码+名称 / 状态徽标 / 进度条或最终决策（买入/卖出 tag）/ 耗时；底部两个等宽按钮 `查看详情` `下载报告`
- 状态刷新策略：**轮询 `GET /api/analysis/batches/{batch_id}` 兜底**（间隔 5s，批量全部终态后停止），这是主通道，不依赖通知推送能力；如后续通知 WS 扩展了含 `task_id`/状态变化的 payload，可叠加为加速通道（非本期必需，现有通知仅在任务完成时推送且 payload 不含 task_id，不足以支撑全生命周期刷新）
- 任务中心列表视角保持不变，批量页是聚合视图

## 后端改动（最小化）

- 新增 `GET /api/analysis/tasks/{id}/overview`：一次返回任务参数 + 股票基础信息。股票信息走 `DataInterface.get_instance()`，router 不直连 MongoDB / `app.data.sources`（架构约束）
- 扩展 `GET /api/analysis/tasks/{id}/events`：新增 `order=desc` 与 `before_seq` 参数（向后兼容，默认行为不变），支撑"最近 500 条 + 向前翻页"
- 批量页刷新复用现有 `GET /batches/{id}` 轮询，不新增推送
- 事件流、WS、`report_titles` 全部复用，不改动

## 错误处理与状态恢复

- 任务失败：详情页顶部 el-alert 展示错误信息；时间线中失败 agent 红色标记
- WS 断连：沿用指数退避重连（最多 10 次）；期间顶部显示"连接中断，重连中…"提示条，并回退轮询 `GET /tasks/{id}/status` 保证进度不丢
- 页面刷新 / 直接访问 URL：先拉 status；running → 连 WS + 回放补齐历史事件（**循环分页拉全量**：`order=desc&limit=500` 起步，`before_seq` 向前翻直到取完，记录当前最大 seq 与 WS 增量续接；渲染层仍只保留最近 500 条）；completed/failed → 纯回放

## 硬性约束遵循

- 智能体中文显示名一律来自 `report_titles` 或 `agentDisplayNames.ts`，禁止前端硬编码
- 路由规范：新后端接口 `prefix="/api/analysis"`（已有域）、英文 Title-Case tags
- overview 接口测试：integration 层、真实 I/O、无 mock
- 输出安全：markdown 渲染必须走现有 `renderMarkdown`（DOMPurify 消毒）

## 验证计划

- 后端：`python -m pytest tests/ -m "integration and not ai" -q`（含 overview 新测试、events 接口 desc/before_seq 分页专项测试）；`ruff check`、`lint-imports`
- 前端：`npm run type-check`、`npm run lint`；浏览器实际打开详情页（running 回放、completed、failed、cancelled 四态）与批量页，检查桌面/窄屏视口、按钮对齐、长文本溢出；批量页验证轮询在全部终态后停止
