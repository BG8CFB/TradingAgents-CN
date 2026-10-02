# 选股模块重构设计：三层漏斗 + 全开关成本控制

- 日期：2026-09-14
- 状态：已与用户讨论确认，作为实施基准
- 范围：CN/A 股选股（筛选、评分、推荐、快速研判）

## 1. 背景与问题

现有选股模块是「单日快照过滤器」，用户选不出较好股票的根因：

1. **筛选只有当天截面字段**：`app/data/query/screening_query.py` 四阶段聚合只取每股最新一行的 `pe_ttm / pb / total_mv / turnover_rate / volume_ratio / roe`，无时间维度（动量/趋势/量能变化均缺失）。
2. **技术指标是空壳**：数据库路径 `ma20/rsi14/kdj/macd` 硬编码返回 `None`；前端明确不发送技术条件，技术形态选择器被 `v-if="false"` 隐藏。
3. **传统路径不可用**：`app/services/screening_service.py` 逐股串行读 220 天 K 线再算 pandas，全市场 5000+ 只跑一次需数分钟，这是技术条件被雪藏的根因。
4. **无策略与评分概念**：结果只按单一字段排序（默认市值降序），没有「更好」的度量，无预设策略。
5. **AI 缺席**：4 阶段智能体流水线与筛选模块唯一连接是结果页「分析」按钮；而流水线本身慢且贵（每只股票几十次 LLM 调用），不可能用于全市场。

数据地基已完备（每日调度，`app/data/scheduler/jobs/cn/__init__.py`）：
`daily_quotes`（16:15）、`money_flow`（16:30）、`daily_indicators`（16:45）、`adj_factors`（17:00）、`dragon_tiger`（18:00）、`financial_data`（20:00）。

## 2. 目标与非目标

### 目标

- 用户能通过策略模板一键选出质量可排序的候选股（修复「选不出好股票」根因）
- 定向推荐：筛选页交互查询，秒级、零 token
- 每日推荐：定时任务产出落库推荐，用户浏览零 token
- L1 快速研判：一次 LLM 调用对 Top-N 输出研判（严格开关控制）
- 所有 LLM 消耗默认关闭，用户明确开启才执行

### 非目标（本期出界，留扩展点）

- 港股/美股因子层（CN 验证后复制）
- 回测验证（factor_scores 按日落库，天然为回测留数据基础）
- 自然语言选股入口
- 盘中/分钟级因子（T+1 收盘后批算）

## 3. 总体架构：三层漏斗

```
每日 20:15（financial_data 同步后）
  FactorScoreJob：读标准集合 → 批量算因子 → 写 stock_factor_scores
        │                                          （纯计算，0 token）
        ▼
L0 评分层 ── 筛选页交互：策略模板/自定义条件 → 过滤+评分排序，秒级
        └── 每日推荐 Job：每模板落库 Top-N → screening_recommendations
                    │                        （用户浏览 = 读库，0 token）
                    ▼  ←←← 【开关闸门：默认关】
        L1 快速研判：1 次 LLM 调用，输入 Top-N 因子摘要 → 每只一段研判
                    ▼  ←←← 用户主动点击
        L2 完整 4 阶段智能体分析（现有，不动）
```

分层原则：贵的部分（LLM）按需触发 + 每日限量；便宜的部分（算术）承担 99% 筛选工作量。

## 4. 成本边界：LLM 开关机制（用户核心要求）

| 层 | 触发方式 | 默认状态 |
|---|---|---|
| L0 因子/评分/每日推荐列表 | 定时 + 查询自动 | **永远开，0 token** |
| L1 手动研判 | 筛选结果页「AI 快速研判」按钮，点击后确认框显示预计消耗（≤1 万 token）；**按用户**受独立日配额 `screening.manual_insight_daily_limit`（默认 10 次/日）限制 | 按钮不点不花钱 |
| L1 每日自动研判 | `system_configs` 总开关 `screening.daily_insight_enabled`；定时任务每天至多自然执行 1 次（调度本身即上限，无需计数器）；可配模型 | **默认关** |
| L2 深析 | 现状不变，用户主动点击 | 不变 |

配额语义（明确）：手动与自动是**两个独立计数体系**——自动走调度天然每日 1 次；手动按 `(user_id, 自然日)` 计数，互不挤占。开关配置项统一放 `system_configs` 的 `screening.*` 命名空间。

- 开关走现有 `system_configs` + 设置页体系（与 LLM 配置同一管理入口），不新造配置机制。
- `/api/screening/insights` 服务端校验**按用户日配额**（手动路径无启用开关，按钮即触发但受配额限制）；每日自动路径的唯一开关是 `screening.daily_insight_enabled`，由 job 内部判定。

## 5. 模块边界：代码位置

| 新组件 | 位置 | 职责 |
|---|---|---|
| 因子定义+计算引擎 | `app/data/factors/`（新子包） | 声明式因子 spec + 批量向量化计算 + 落库；数据层内部读写标准集合 |
| factor_scores schema | `app/data/schema/domains/factor_scores.py` | 主键 `(symbol, trade_date)`，中立字段 |
| 调度任务基类 | `app/data/scheduler/jobs/base/` 新增 `ComputeJob` 基类 | 计算型任务（读标准集合 → 计算 → 写结果集合）。**不复用 `BaseSyncJob`**：其 `execute()` 硬绑 checkpoint → FallbackRouter.fetch → write 的同步模式，且有 `_SUPPORTED_SYNC_DOMAINS` 白名单，计算任务不适用 |
| 调度任务 | `app/data/scheduler/jobs/cn/` 新增 `CNFactorScoreJob(ComputeJob)` | 20:15，depends_on financial_data |
| 域注册 | `app/data/core/domain.py` DataDomain 枚举 + 集合名映射新增 `factor_scores` / `recommendations` / `insights` 条目 | 使新集合可经 `get_collection_name` / DataInterface 访问 |
| 策略模板定义 | `config/screening/strategies.yaml` | 声明式模板（沿用 `config/agents/*.yaml` 模式） |
| 模板解析+评分排序 | `app/services/`（screening 域） | 经 `DataInterface` 读因子，不碰 storage/sources |
| L1 研判服务 | `app/services/`（screening 域） | 走 `app/llm/` 层单次调用 |
| API | 扩展 `app/routers/screening.py`（不加新 router） | `/strategies`、`/run` 升级、`/insights`、`/daily` |
| 前端 | `frontend/src/views/Screening/index.vue` 升级 + 设置页开关 | — |

架构合规：routers 不 import `app.data.storage` / `app.data.sources`（import-linter）；消费方经 `DataInterface`；schema 中立字段（`symbol` / `trade_date`）；新代码统一 `symbol`、`data_source`。

## 6. 数据设计

### 6.1 `stock_factor_scores`（新集合）

- 主键语义：`(symbol, trade_date)`，domain 级显式声明
- 字段：`symbol, trade_date, industry, data_source` + 各因子原始值 + 各风格总分（`score_short_term / score_balanced / score_value`，0-100）
- 日频追加，历史保留（为未来回测留数据）

### 6.2 `screening_recommendations`（新集合）

- 主键语义：`(strategy_id, trade_date)`
- 字段：策略元信息 + Top-N 条目（symbol、名称、总分、关键因子、命中信号）+ `insight_status`（none/pending/done/failed）
- 每日 job 覆盖写入当日记录
- 每日自动 L1 的研判文本写入本集合当日记录的条目级 `insight` 字段（仅每日 job 写入；手动研判不写此处，避免次日 job 覆盖时被冲掉）

### 6.3 `screening_insights`（新集合）

- 定位：手动 L1 研判的追加式（append-only）日志，兼顾回看与 token 消耗审计
- 字段：`created_at, trigger(manual), user_id, trade_date, strategy_id(可空), conditions_digest(自定义条件摘要，可空), symbols[], insights{symbol: 研判文本}, model, tokens_used`
- 查询路径：`/insights` 调用后直接返回结果；本集合主要用于历史回看与审计（列表读取接口为未来扩展，本期只写不读）

## 7. 因子清单（初版）

| 类别 | 因子 | 数据源 |
|---|---|---|
| 动量 | `ret_5d / ret_20d / ret_60d`、`dist_to_60d_high` | daily_quotes + adj_factors（后复权） |
| 趋势 | `bias_ma20`（close/ma20 乖离）、`ma20_slope`、`macd_golden_days`（金叉状态及天数，负值表示死叉） | 同上，复用 `app/utils/indicators.py` |
| 量能 | `turnover_amp`（当日换手/20 日均换手）、`consecutive_vol_up_days`、`volume_ratio` | daily_quotes / daily_indicators |
| 资金 | `main_inflow_5d`（主力净流入 5 日累计）、`main_inflow_5d_pct` | money_flow |
| 估值 | `pe_ttm_percentile`（近 3 年分位）、`pb_percentile`、`dividend_yield` | daily_indicators 历史序列 |
| 质量 | `roe`、`gross_margin`、`net_profit_yoy`、`debt_ratio` | financial_data |

字段说明：除 `net_profit_yoy` 外均为存储字段直取；`net_profit_yoy` 为**派生计算**——按 `report_period` 取本期与上年同期的 `net_profit` 计算同比（financial_data 保留多期历史，`_fetch_latest_roe` 的按期分组聚合已验证此点）。

计算约束：

- 全市场批量向量化计算（按 symbol 分组 + pandas 滚动窗口），禁止逐股串行读库（吸取传统筛选路径教训）
- 统一过滤：剔除 ST、上市 <60 日、长期停牌（交易日历判断）
- 可选域（money_flow/dragon_tiger）当日缺失时对应因子置空，不阻塞 job

## 8. 评分合成

1. 每因子在**行业内**做 percentile rank（消除行业偏差，行业惯例底线，非可选优化）
2. 风格权重合成（三套 preset，写死在 strategies.yaml 顶层）：
   - `short_term`（默认，匹配现有流水线短线定调）：动量 35% + 趋势 25% + 量能 20% + 资金 20%
   - `balanced`：四类均衡 + 质量/估值微权
   - `value`：估值 35% + 质量 40% + 动量 10% + 量价 15%
3. 因子缺失时按可用因子加权归一；覆盖 <30% 因子的股票不参与评分（`score_* = None`）
4. 合成分散是多因子底线：任何单一因子权重不超过 40%（2025 下半年市值因子拥挤回撤的行业教训）

## 9. 策略模板（初版 6 个）

模板 = 硬条件过滤 + 评分排序，声明式 YAML：

| 模板 | 硬条件 | 排序 |
|---|---|---|
| 放量突破主升初期（默认） | `bias_ma20 > 0` 且 `turnover_amp > 1.5` 且 `macd_golden_days` ∈ (0,5] 且 `main_inflow_5d > 0` | short_term 分 |
| 强趋势回调买点 | 趋势向上 且 `ret_5d` ∈ [-8%, 0] 且 close ≥ ma20 | short_term 分 |
| 超跌反弹 | `ret_20d < -15%` 且 `main_inflow_5d > 0` | short_term 分 |
| 高ROE低估值 | `roe > 15` 且 `pe_ttm_percentile < 30` 且 `dividend_yield > 2` | value 分 |
| 质量成长 | `gross_margin > 30` 且 `net_profit_yoy > 20` 且 `debt_ratio < 60` | value 分 |
| 资金持续流入 | `main_inflow_5d > 0` 且 `turnover_amp` ∈ (1, 2) 且 `bias_ma20 > 0` | short_term 分 |

每模板输出 Top 30（可配）；模板支持叠加用户自定义硬条件（如行业、市值区间）。

## 10. L1 快速研判服务（独立单次对话 AI，不调用工作流）

| | L1 快速研判 | L2 完整分析 |
|---|---|---|
| 执行机制 | `app/services/` 新服务函数，经 `app/llm/providers` 获取客户端，发 **1 次** LLM 调用 | 现有 `TradingAgentsGraph.propagate` |
| 经过 engine/orchestrator | **完全不经过**；不创建分析任务、不占 `analysis_tasks`、不进辩论/风控 | 经过 |
| 输入 | Top-N（默认 20，可调 10-30）结构化因子摘要表，每只约 100-150 token | 工作流自行取数 |
| Prompt | 新「量化研究员」系统提示词：每只输出 2-3 句（核心逻辑/主要风险/适配场景），结构化 JSON 返回，禁止给出买卖指令 | 现有各 agent prompt |
| 成本 | 1 次调用 ≤1 万 token，十几秒 | 每只股票几十次调用 |
| 模型 | 默认复用系统 analyst 配置；开关处可单独指定便宜模型 | 现有 analyst/debate 配置 |

流程：触发 → `ScreeningInsightService.generate(symbols)` → 服务端按 `symbols + 最新可用 trade_date` 从 `stock_factor_scores` 重取因子摘要（**不信任前端传入的因子值**，前端只传 symbol 列表）→ `app/llm/providers` 取客户端 → 1 次 chat → JSON 解析 → 返回结果并落库。

落库去向（两条路径分开，避免覆盖冲突）：
- **手动触发**：追加写入 `screening_insights`（6.3 节），不触碰 `screening_recommendations`（该集合由每日 job 按日覆盖，手动写入会在次日被冲掉）
- **每日自动触发**（开关开启时）：由每日 job 写入当日 `screening_recommendations` 条目级 `insight` 字段

失败降级：L0 结果完整保留，不自动重试。自动路径置 `insight_status = failed`（该字段在 `screening_recommendations` 上）；手动路径直接向 API 调用方返回错误信息（不扣配额），同时向 `screening_insights` 写入一条 `status=failed` 审计记录。

边界：纯新增服务，不改 engine、不改工作流、不改 analysis_tasks。

## 11. API 设计（扩展现有 screening router）

```
GET  /api/screening/strategies   # 模板列表（YAML 驱动，含名称/描述/参数摘要）
POST /api/screening/run          # 升级：支持 strategy_id 或混合自定义条件；结果带总分与因子明细
GET  /api/screening/daily        # 每日推荐（读落库结果 + 数据截至日期标注）
POST /api/screening/insights     # L1 手动研判：入参 symbols[]；服务端校验按用户日配额，重取因子后单次调用
```

- 响应统一 `success + data` 包装（router-response-must-wrap 项目规则）
- 路由规范：`prefix="/api/screening"`、Title-Case tags（现有 router 已合规）

## 12. 前端设计

- 筛选页改造：
  - 顶部新增「策略模板」区（6 个模板卡片，一键运行）
  - 保留自定义条件区（现有表单）
  - 结果表新增：总分列（按所选风格）、关键因子列、命中信号标签
  - 「AI 快速研判」按钮：点击弹确认框（显示预计 token）→ 调 `/insights` → 研判文本展示在行内展开区
  - 「今日精选」Tab（页内 Tab 而非独立页）：展示每日推荐落库结果 + 数据截至日期
- 设置页：screening 开关区（每日自动 L1 总开关、研判模型选择、手动日配额）
- L2 打通：结果行「分析」按钮保持现有跳转逻辑

## 13. 错误处理与降级

| 场景 | 行为 |
|---|---|
| 因子 job 失败/数据滞后 | 现有 monitoring 告警；查询降级到最近可用日期，前端标注「数据截至 X 日」 |
| 次新股/数据不足 | 因子置空，评分按可用因子归一；覆盖 <30% 不评分 |
| 可选域（money_flow 等）缺失 | 对应因子置空，不阻塞 |
| L1 调用失败 | L0 保留，`insight_status=failed`，不重试烧钱 |
| 手动 L1 超按用户日配额 | 拒绝并返回剩余额度提示（自动 L1 不占用手动配额，见第 4 节配额语义） |

## 14. 测试策略（全真 I/O，禁 mock，遵循项目规则）

- 因子数值正确性：样本股（3-5 只）与独立 pandas 手工计算对比
- 评分逻辑：构造已知因子值验证行业内 rank + 权重合成 + 缺失归一
- 策略模板解析与过滤：YAML 加载 + 条件求值
- API 集成测试连真实 Mongo（tradingagents_test 隔离库）
- `CNFactorScoreJob` 集成测试：真实集合输入 → factor_scores 落库断言
- `/insights` 配额边界集成测试：同一用户当日超限被拒、失败不扣配额
- L1 研判测试标记 `ai`（默认测试集跳过）

## 15. 分期交付

- **P1（0 LLM）**：因子层 + 评分 + 策略模板 + `/run` 升级 + 筛选页模板/评分列
- **P2**：L1 研判服务（手动路径 + 落库）+ 开关与配额 + 每日推荐 job（含可选自动 L1）+ 「今日精选」Tab；新增结果行沿用现有「分析」按钮跳转逻辑，无 engine 改动

每期独立可验证；P1 上线后选股质量根因即修复。

## 16. 未来扩展（明确不在本期）

- 回测验证：基于 factor_scores 历史序列评估模板胜率/赔率
- 自然语言选股：一句话 → LLM 解析为结构化条件 + 模板参数
- 港股/美股因子复制
- 盘中因子（依赖 intraday_quotes 域）
