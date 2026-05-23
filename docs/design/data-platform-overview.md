# 数据平台总览设计文档

> **版本**: v1.0
> **日期**: 2026-05-21
> **范围**: A 股 / 港股 / 美股 三市场统一数据平台
> **配套文档**:
> - `a-share-data-architecture.md` — A 股数据架构详细设计
> - `hk-stock-data-architecture.md` — 港股数据架构详细设计
> - `us-stock-data-architecture.md` — 美股数据架构详细设计

---

## 目录

1. [平台定位与设计统一性](#1-平台定位与设计统一性)
2. [总体架构](#2-总体架构)
3. [三市场对比与差异点](#3-三市场对比与差异点)
4. [模块化目录规划](#4-模块化目录规划)
5. [跨市场公共组件](#5-跨市场公共组件)
6. [数据库存储规划](#6-数据库存储规划)
7. [配置体系](#7-配置体系)
8. [API 接口规范](#8-api-接口规范)
9. [部署架构](#9-部署架构)
10. [开发与扩展规范](#10-开发与扩展规范)
11. [实施路线图](#11-实施路线图)
12. [附录](#12-附录)

---

## 1. 平台定位与设计统一性

### 1.1 平台定位

构建一套面向 A 股、港股、美股的统一数据平台，作为分析引擎与前端的唯一数据来源。平台特征：

1. **多市场统一**: 三市场共享同一套核心组件，差异通过数据源层与字段标准化层内化
2. **多源容错**: 每个数据域至少配置 2–3 个数据源，具备完整的回退、熔断、重试机制
3. **读写分离**: 消费方只读 MongoDB，处理层负责所有外部 API 调用
4. **按需 + 定时**: 同时支持后端服务的同步刷新与定时增量更新
5. **可观测**: 每一次数据流转、回退、熔断都被记录，便于运维与排查

### 1.2 三市场设计统一性

三市场共享以下设计契约：

| 维度 | 统一标准 |
|------|---------|
| 架构层数 | 消费层 / 读取层 / 处理层 / 数据源层（共 4 层） |
| 数据流 | 三条核心数据流（定时同步 / 内部刷新 / 异步过期感知） |
| 数据源容错 | FallbackRouter + CircuitBreaker + RateLimiter |
| 字段标准 | symbol + market + data_source + updated_at 公共字段 |
| 写入策略 | 全量 upsert 幂等写入，单源活跃 |
| 元数据 | sync_checkpoints / sync_events / source_health 三集合，跨市场共用 |
| 配置体系 | 按 market × domain × source 配置优先级 |
| 调度引擎 | 基于 APScheduler，按市场配置时区与时间表 |
| 通知机制 | 同步事件 + SSE 前端推送 |

差异仅集中在：

- **数据源实现**: A 股（Tushare / AKShare / BaoStock）、港股（**Tushare HK** / AKShare HK / yfinance HK / Tencent HK）、美股（**Tushare US** / yfinance / Finnhub / Alpha Vantage）
- **市场特化字段**: 港股的 `connect_status`、美股的 `pre_market_*` / `post_market_*` 等
- **调度时间**: A 股 / 港股按 CST=HKT，美股按 ET（含夏令时）
- **特有数据域**: 美股、港股的 `corporate_actions` 域；港股的港股通标识与南向持股

**关于 Tushare 的跨市场角色：**

Tushare 是平台中**唯一横跨三市场的数据源**，分别对应 `tushare`（A 股）、`tushare_hk`（港股）、`tushare_us`（美股）。三者：

- 共享同一个 Token 与同一份积分配额
- 各自独立实现 Provider 与 Adapter（接口、字段、单位完全不同）
- 在能力注册表中作为独立条目登记
- 港股 / 美股 Tushare 都受积分门槛制约（港股 ≥ 2000 积分，美股 ≥ 120 积分）
- Tushare HK 与 Tushare US **均不提供公司行为与新闻**，这两个域必须由 AKShare HK / yfinance / Finnhub 等承担

### 1.3 设计原则

1. **实用优先**: 不引入不需要的抽象层，不为"可能的未来需求"预留过度复杂的设计
2. **接口稳定优先**: 公共抽象层（Provider / Adapter / Reader）一旦定义，演进时保持向后兼容
3. **市场可独立演进**: 新增一个市场只需新增 `sources/<market>/` 与 `schema/markets/<market>.py`，无需修改其他市场代码
4. **配置外部化**: 所有市场差异（时区、调度时间、能力矩阵）以配置文件形式存在，非硬编码
5. **故障域隔离**: 一个市场或一个数据源的故障不影响其他市场或数据源

---

## 2. 总体架构

### 2.1 跨市场架构总图

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                              消费层 (Consumer)                           │
│         分析引擎       股票筛选       前端管理页面       数据导出 API       │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │ 只读查询（按 market + domain）
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                            统一读取层 (Reader)                           │
│            标准数据读取 + 新鲜度判定 + 异步刷新通知（市场无关）             │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                  ┌────────────────┼─────────────────┐
                  │ 写入            │                 │ 异步通知
                  ▼                │                 ▼
        ┌──────────────────┐       │       ┌────────────────────────┐
        │     MongoDB      │       │       │   DataRefreshService   │
        │ ┌──────────────┐ │       │       │      (市场无关)         │
        │ │ A股/_hk/_us │ │       │       └─────────┬──────────────┘
        │ │  集合族     │ │       │                 │
        │ ├──────────────┤ │       │                 ▼
        │ │ 共用元数据   │ │       │       ┌────────────────────────┐
        │ │（含 market） │ │◄──────┴──────┤      处理层 (Processor)   │
        │ └──────────────┘ │       写入  │  FallbackRouter             │
        └──────────────────┘             │  CircuitBreaker (市场无关)   │
                                         │  RateLimiter / Validator     │
                                         └─────────┬────────────────────┘
                                                   │
                          ┌────────────────────────┼────────────────────────┐
                          │                        │                        │
                          ▼                        ▼                        ▼
                ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
                │   sources/cn/    │    │   sources/hk/    │    │   sources/us/    │
                │  Tushare         │    │  AKShare HK      │    │  yfinance        │
                │  AKShare         │    │  yfinance HK     │    │  Finnhub         │
                │  BaoStock        │    │  Tencent HK      │    │  Alpha Vantage   │
                └──────────────────┘    └──────────────────┘    └──────────────────┘
```

### 2.2 四层职责

| 层 | 职责 | 市场特化程度 |
|----|------|-------------|
| **消费层** | 业务逻辑（分析、筛选、展示） | 业务侧按市场区分，但仅通过 market 参数请求数据 |
| **读取层** | 标准数据读取 + 新鲜度判定 + 异步通知 | 完全市场无关 |
| **处理层** | 数据源选择、回退、限流、熔断、标准化、写入 | 完全市场无关，仅依赖 schema 与 capability registry |
| **数据源层** | 第三方 API 封装与原始数据返回 | 按市场组织（`sources/cn/` / `sources/hk/` / `sources/us/`） |

### 2.3 三条核心数据流（统一）

**数据流 A — 定时同步**

```text
调度器（按市场时区） → 处理层 → 选择数据源（按市场配置）
  → 拉取 → 标准化 → 写入 MongoDB（按 market 分集合） → 更新检查点
```

**数据流 B — 内部服务调用刷新**

```text
后端服务 → DataRefreshService.refresh(symbol, market, domains)
  → 处理层 → 选择数据源 → 拉取 → 标准化 → 写入 MongoDB
  → 返回刷新结果（fresh / refreshed / partial / timeout / failed）
```

**数据流 C — Reader 过期感知**

```text
消费方请求数据 → Reader 读 MongoDB → 按市场新鲜度规则判定
  ├── 新鲜 → 直接返回（fresh）
  └── 过期 → 立即返回当前数据（stale）
           → 异步通知 DataRefreshService（非阻塞）
```

---

## 3. 三市场对比与差异点

### 3.1 市场基础对比

| 维度 | A 股 | 港股 | 美股 |
|------|------|------|------|
| 时区 | CST（UTC+8） | HKT（UTC+8） | ET（UTC-5/-4，含夏令时） |
| 主货币 | CNY | HKD | USD |
| 涨跌幅限制 | ±10% / 20% / 30% | 无限制 | 无限制（仅熔断） |
| 交易时段 | 09:30–11:30 / 13:00–15:00 | 09:30–12:00 / 13:00–16:00 | 09:30–16:00（盘前 / 盘后另算） |
| 代码格式 | 6 位数字 + 后缀 | 5 位数字 + `.HK` | 字母 ticker + 交易所 |
| 财报频率 | 一 / 三 / 半年 / 年 | 半年 / 年（少数季） | 季 / 年（10-Q / 10-K） |

### 3.2 数据源对比

| 市场 | 主源 | 备源 | 兜底 / 专项源 | 数据源数量 |
|------|------|------|--------------|----------|
| A 股 | Tushare（积分制） | AKShare（免费） | BaoStock（免费） | 3 |
| 港股 | Tushare HK（积分制） | AKShare HK（免费，新闻 / 红股 / 供股唯一源） | yfinance HK（备） + Tencent HK（实时快照） | 4 |
| 美股 | Tushare US（积分制，仅主要美股 + 中概股） | yfinance（全市场） | Finnhub（新闻 / 盘前盘后唯一源） + Alpha Vantage（财务深度） | 4 |

**Tushare 跨市场对照：**

| 接口前缀 | A 股 | 港股 | 美股 |
|---------|------|------|------|
| 基础信息 | stock_basic | hk_basic（≥ 2000 积分） | us_basic（120 试用 / 5000 正式） |
| 交易日历 | trade_cal | hk_tradecal（≥ 2000 积分） | us_tradecal |
| 日线行情 | daily | hk_daily | us_daily |
| 复权行情 | – | hk_daily_adj | us_daily_adj |
| 复权因子 | adj_factor | hk_adjfactor | us_adjfactor |
| 财务三表 | income / balancesheet / cashflow | hk_income / hk_balancesheet / hk_cashflow | us_income / us_balancesheet / us_cashflow |
| 财务指标 | fina_indicator | hk_fina_indicator | us_fina_indicator |
| 实时报价 | realtime_quote | rt_hk_k | – |
| 公司行为 | – | – | – |
| 新闻 | news | – | – |

> 划线（–）表示该市场 Tushare 不支持该域。所有跨市场缺口由其他数据源补齐。

### 3.3 数据域对比

| 数据域 | A 股 | 港股 | 美股 | 说明 |
|--------|------|------|------|------|
| 基本信息 | ✓ | ✓ | ✓ | 三市场通用 |
| 交易日历 | ✓ | ✓ | ✓ | 各市场独立维护 |
| 日线行情 | ✓ | ✓ | ✓ | 美股增 `adj_close` 字段 |
| 每日指标 | ✓ | ✓ | ✓ | 港股 dividend_yield 关键 |
| 复权因子 | ✓ | ✓ | ✓ | 美股本地推导，港股 / A 股数据源直供 |
| 财务三表 | ✓ | ✓ | ✓ | 频率与币种各异 |
| 财务指标 | ✓ | ✓ | ✓ | 字段大体一致 |
| 市场快照 | ✓ | ✓ | ✓ | 美股增盘前盘后字段，港股增准实时来源 |
| 新闻 | ✓ | ✓ | ✓ | 三市场通用 |
| 公司行为 | – | ✓ | ✓ | 港股 / 美股独有 |
| 港股通标识 | – | ✓ | – | 港股独有 |
| 南向持股 | – | ✓ | – | 港股独有 |
| 盘前盘后行情 | – | – | ✓ | 美股可选增强域 |

### 3.4 集合后缀与命名规则

业务集合按市场后缀区分（A 股不加后缀，港股加 `_hk`，美股加 `_us`）：

```text
基本信息：
  stock_basic_info         # A 股（无后缀）
  stock_basic_info_hk      # 港股
  stock_basic_info_us      # 美股

日线行情：
  stock_daily_quotes       # A 股
  stock_daily_quotes_hk    # 港股
  stock_daily_quotes_us    # 美股

财务数据：
  stock_financial_data     # A 股
  stock_financial_data_hk  # 港股
  stock_financial_data_us  # 美股

公司行为（仅港股 / 美股）：
  stock_corporate_actions_hk
  stock_corporate_actions_us

元数据集合（三市场共用）：
  sync_checkpoints         # 含 market 字段
  sync_events              # 含 market 字段
  source_health            # 含 market 字段
```

> **A 股不加后缀的原因**：A 股作为平台的第一个市场，在 `collections.py` 中不使用后缀以保持向后兼容。代码中通过 `market` 参数在 `get_collection_name()` 中自动处理：CN → 无后缀，HK → `_hk`，US → `_us`。

---

## 4. 模块化目录规划

### 4.1 顶层目录原则

数据平台的代码组织遵循**水平分层 + 垂直市场隔离**的双轴设计：

- **水平分层**: `core` / `schema` / `processor` / `storage` / `scheduler` / `monitoring` 是市场无关的基础设施
- **垂直隔离**: `sources/<market>/` 与 `schema/markets/<market>.py` 按市场划分，市场之间完全独立

这样达到的目标：

1. 新增一个市场只影响 `sources/<market>/`、`schema/markets/<market>.py` 与一份调度配置文件，**不修改任何其他代码**
2. 新增一个数据源只影响 `sources/<market>/<source>/`，**不影响处理层与调度层**
3. 修改字段标准化规则只影响 `schema/`，**不影响数据源层**
4. 修改回退或熔断策略只影响 `processor/`，**不影响数据源与业务层**

### 4.2 完整目录结构

```text
app/data/
│
├── core/                              # 核心抽象层（市场无关）
│   ├── interface.py                   # 对外统一接口（market 参数化）
│   ├── reader.py                      # 统一读取层（含新鲜度判定与异步通知）
│   ├── refresh_service.py             # DataRefreshService（按需刷新）
│   ├── domain.py                      # 数据域枚举与定义
│   ├── market.py                      # MarketType 枚举与市场元信息
│   ├── result.py                      # 统一结果对象（fresh / refreshed / failed 等）
│   └── registry/
│       ├── capability.py              # 能力注册表（market × domain × source）
│       ├── priority.py                # 用户优先级配置读取与缓存
│       └── source_metadata.py         # 数据源元信息（限流值、密钥要求等）
│
├── schema/                            # 字段标准定义
│   ├── base/
│   │   ├── types.py                   # 公共类型（Decimal、DateStr、Timestamp）
│   │   ├── markets.py                 # MarketType 枚举（CN / HK / US）
│   │   ├── common_fields.py           # symbol / market / data_source / updated_at
│   │   └── enums.py                   # 公共枚举（list_status、period 等）
│   ├── domains/                       # 各数据域字段定义（公共部分）
│   │   ├── basic_info.py
│   │   ├── trade_calendar.py
│   │   ├── daily_quotes.py
│   │   ├── daily_indicators.py
│   │   ├── adj_factors.py
│   │   ├── corporate_actions.py       # 港股 / 美股共用
│   │   ├── financial_data.py
│   │   ├── market_quotes.py
│   │   ├── stock_news.py
│   │   └── metadata.py                # sync_checkpoints / sync_events / source_health
│   └── markets/                       # 市场特化字段补充
│       ├── cn.py                      # A 股特有字段（exchange、area、market 板块）
│       ├── hk.py                      # 港股特有（connect_status、dual_listed 等）
│       └── us.py                      # 美股特有（pre_market_*、is_adr、cik 等）
│
├── sources/                           # 数据源实现（按市场划分）
│   ├── base/
│   │   ├── provider.py                # BaseProvider 抽象类
│   │   ├── adapter.py                 # BaseAdapter 抽象类
│   │   ├── error_codes.py             # 统一错误码定义
│   │   └── exceptions.py              # 数据源异常类
│   ├── cn/                            # A 股数据源
│   │   ├── tushare/
│   │   │   ├── provider.py
│   │   │   ├── adapter.py
│   │   │   └── api/                   # 各域具体 API 调用封装
│   │   │       ├── stock_basic.py
│   │   │       ├── daily_quotes.py
│   │   │       ├── daily_indicators.py
│   │   │       ├── financial.py
│   │   │       ├── adj_factors.py
│   │   │       ├── trade_calendar.py
│   │   │       └── news.py
│   │   ├── akshare/
│   │   │   ├── provider.py
│   │   │   ├── adapter.py
│   │   │   └── api/
│   │   ├── baostock/
│   │   │   ├── provider.py
│   │   │   ├── adapter.py
│   │   │   └── api/
│   │   └── __init__.py                # 注册到能力注册表
│   ├── hk/                            # 港股数据源
│   │   ├── tushare_hk/                # Tushare 港股：基础/行情/复权/财务
│   │   │   ├── provider.py
│   │   │   ├── adapter.py
│   │   │   └── api/
│   │   │       ├── hk_basic.py
│   │   │       ├── hk_tradecal.py
│   │   │       ├── hk_daily.py
│   │   │       ├── hk_daily_adj.py
│   │   │       ├── hk_adjfactor.py
│   │   │       ├── hk_financials.py
│   │   │       ├── hk_fina_indicator.py
│   │   │       ├── hk_hold.py
│   │   │       └── rt_hk_k.py
│   │   ├── akshare_hk/                # AKShare 港股：公司行为/披露易/港股通
│   │   │   ├── provider.py
│   │   │   ├── adapter.py
│   │   │   └── api/
│   │   ├── yfinance_hk/
│   │   │   ├── provider.py
│   │   │   ├── adapter.py
│   │   │   └── api/
│   │   ├── tencent_hk/
│   │   │   ├── provider.py
│   │   │   ├── adapter.py
│   │   │   └── api/
│   │   └── __init__.py
│   └── us/                            # 美股数据源
│       ├── tushare_us/                # Tushare 美股：仅主要美股 + 中概股
│       │   ├── provider.py
│       │   ├── adapter.py
│       │   └── api/
│       │       ├── us_basic.py
│       │       ├── us_tradecal.py
│       │       ├── us_daily.py
│       │       ├── us_daily_adj.py
│       │       ├── us_adjfactor.py
│       │       ├── us_financials.py
│       │       └── us_fina_indicator.py
│       ├── yfinance/                  # 全市场主源
│       │   ├── provider.py
│       │   ├── adapter.py
│       │   └── api/
│       ├── finnhub/                   # 新闻 / 盘前盘后专用
│       │   ├── provider.py
│       │   ├── adapter.py
│       │   └── api/
│       ├── alpha_vantage/             # 财务深度兜底
│       │   ├── provider.py
│       │   ├── adapter.py
│       │   └── api/
│       └── __init__.py
│
├── processor/                         # 处理层（市场无关）
│   ├── fallback_router.py             # 回退路由器
│   ├── circuit_breaker.py             # 熔断器
│   ├── rate_limiter.py                # 限流器（按数据源配置）
│   ├── retry_policy.py                # 重试策略
│   ├── normalizer.py                  # 字段标准化执行器
│   ├── validator.py                   # 数据校验
│   └── post_processors/               # 后处理器（聚合、推导等）
│       ├── period_aggregator.py       # 日线 → 周/月线聚合
│       └── adj_factor_calculator.py   # 美股复权因子推导
│
├── storage/                           # 存储层
│   ├── mongo/
│   │   ├── client.py                  # Motor 客户端封装
│   │   ├── collections.py             # 集合命名规则与按市场分发
│   │   ├── indexes.py                 # 索引定义与初始化
│   │   └── repositories/              # 各域仓储类（封装查询逻辑）
│   │       ├── basic_info_repo.py
│   │       ├── daily_quotes_repo.py
│   │       ├── daily_indicators_repo.py
│   │       ├── adj_factors_repo.py
│   │       ├── corporate_actions_repo.py
│   │       ├── financial_data_repo.py
│   │       ├── market_quotes_repo.py
│   │       ├── news_repo.py
│   │       ├── trade_calendar_repo.py
│   │       └── metadata_repo.py
│   ├── redis/
│   │   ├── client.py                  # Redis 客户端封装
│   │   ├── locks.py                   # 分布式锁
│   │   ├── counters.py                # 限流计数器
│   │   ├── pubsub.py                  # 异步刷新队列
│   │   └── market_state.py            # 市场状态缓存
│   └── cache/
│       └── memory_cache.py            # 进程内 LRU 缓存（配置、能力表等）
│
├── scheduler/                         # 调度层（市场无关引擎）
│   ├── engine.py                      # 基于 APScheduler 的调度引擎
│   ├── job_registry.py                # 任务注册表
│   ├── checkpoint.py                  # 检查点管理
│   ├── dependencies.py                # 依赖链管理
│   ├── timezone.py                    # 时区换算（含 ET 夏令时）
│   ├── jobs/                          # 任务实现（按市场组织调度配置）
│   │   ├── base/
│   │   │   ├── sync_job.py            # 通用同步任务基类
│   │   │   └── post_processing_job.py
│   │   ├── cn/
│   │   │   └── schedule.yaml          # A 股调度时间表（CST）
│   │   ├── hk/
│   │   │   └── schedule.yaml          # 港股调度时间表（HKT）
│   │   └── us/
│   │       └── schedule.yaml          # 美股调度时间表（ET）
│   └── monitors.py                    # 调度任务执行监控
│
├── monitoring/                        # 监控层
│   ├── source_health.py               # 数据源健康度统计
│   ├── completeness.py                # 完整性检查
│   ├── reconciliation.py              # 多源对账（如公司行为）
│   └── alerts.py                      # 告警分发（日志 / SSE / 邮件）
│
├── config/                            # 平台配置（YAML / JSON）
│   ├── markets.yaml                   # 各市场基础配置（时区、交易时段等）
│   ├── capability_matrix.yaml         # 能力矩阵默认值
│   ├── default_priorities.yaml        # 默认数据源优先级
│   ├── freshness_rules.yaml           # 各数据域新鲜度规则
│   └── source_limits.yaml             # 各数据源限流参数
│
└── README.md                          # 数据平台总体说明
```

### 4.3 目录设计要点解读

#### 4.3.1 为什么 `core/` 与 `processor/` 分离？

- `core/` 是**对外抽象**: 提供统一的 `interface.py`、`reader.py`、`refresh_service.py`，是消费层的入口
- `processor/` 是**内部实现**: 包含数据源选择、回退、限流、校验等具体执行逻辑

消费层只依赖 `core/`，不应直接 import `processor/`。这种分离让处理层可以替换实现（例如从同步改为异步、从单机改为分布式），而消费层无感知。

#### 4.3.2 为什么 `schema/markets/` 单独存在？

`schema/domains/` 定义所有市场共用的字段（如 `daily_quotes` 的 OHLCV），`schema/markets/<market>.py` 定义市场特有的字段补充（如港股 `connect_status`、美股 `pre_market_price`）。

适配器（`sources/<market>/<source>/adapter.py`）合并两部分字段进行标准化输出。这样：

- 公共字段定义集中，三市场必须遵守同一标准
- 市场特化字段独立，新增市场不影响其他市场

#### 4.3.3 为什么 `sources/` 按市场分目录而不是按数据源分目录？

按市场组织的优势：

- 一个数据源通常只服务一个市场（Tushare 只做 A 股，yfinance 同时服务美股与港股但实现路径不同）
- 同一市场内多个数据源共享市场特化逻辑（如港股代码补零、双重上市处理）
- 新增市场是一个独立的目录，认知边界清晰

对于 yfinance 这种跨市场源，分别在 `sources/hk/yfinance_hk/` 和 `sources/us/yfinance/` 实现，**虽然底层 SDK 相同，但适配器与字段映射完全不同**，不应共享代码。

#### 4.3.4 为什么 `storage/` 与 `processor/` 分离？

- `processor/` 关心**数据从哪来、怎么处理**
- `storage/` 关心**数据存哪、怎么读写**

二者通过 `repositories/` 接口解耦。处理层调用仓储写入数据，仓储内部决定写到 MongoDB 哪个集合（按 market 分发）。这样：

- 切换底层数据库（如 PostgreSQL）只改 `storage/`
- 处理层不知道集合名称的拼接规则

#### 4.3.5 为什么 `scheduler/jobs/` 按市场分目录？

调度配置（schedule.yaml）按市场组织：

- A 股 / 港股的时区与 CST 一致，配置简单
- 美股需要处理 ET 夏令时切换，配置较复杂
- 各市场的特有任务（如港股临时停市检测、美股 corporate_actions 推导）都在自己的子目录内

调度引擎（`engine.py`）是统一的，只负责加载并执行任务。

#### 4.3.6 为什么单独有 `config/` 目录？

将以下"易变但不需要代码改动"的内容外部化：

| 配置文件 | 内容 | 修改频率 |
|---------|------|---------|
| `markets.yaml` | 各市场时区、交易时段、假期源 | 低 |
| `capability_matrix.yaml` | 各市场各域支持的数据源 | 中（新增数据源时） |
| `default_priorities.yaml` | 默认优先级 | 低 |
| `freshness_rules.yaml` | 各域新鲜度规则 | 中（业务调整时） |
| `source_limits.yaml` | 各源限流参数 | 中（数据源限流变化时） |

这些配置可以热更新，不需要重启服务。

### 4.4 单一职责约束（强制）

| 模块 | 必须做 | 严格禁止 |
|------|--------|---------|
| `core/reader.py` | 读 MongoDB、判定新鲜度、异步通知 | 不能直接调外部 API、不能写 MongoDB |
| `core/refresh_service.py` | 编排刷新流程、返回结果 | 不能直接调外部 API（必须通过 processor） |
| `processor/fallback_router.py` | 选源、回退、调用 provider | 不能写 MongoDB（通过 repository）、不能做业务逻辑 |
| `sources/<market>/<source>/provider.py` | 调外部 API、返回原始数据 | 不能做字段映射、不能写 MongoDB |
| `sources/<market>/<source>/adapter.py` | 字段映射、单位换算、空值处理 | 不能调外部 API、不能写 MongoDB |
| `storage/mongo/repositories/*.py` | MongoDB 读写封装 | 不能调外部 API、不能做字段映射 |
| `scheduler/engine.py` | 任务调度、依赖管理、检查点推进 | 不能直接调 provider（通过 processor） |

### 4.5 命名约定

| 范畴 | 约定 |
|------|------|
| 数据源编码 | 小写字母 + 下划线，如 `tushare`、`akshare`、`baostock`、`tushare_hk`、`akshare_hk`、`yfinance_hk`、`tencent_hk`、`tushare_us`、`yfinance`、`finnhub`、`alpha_vantage` |
| Tushare 跨市场命名 | A 股用 `tushare`（无后缀以保持向后兼容），港股用 `tushare_hk`，美股用 `tushare_us`；三者共享同一 Token / 配额，但 Provider / Adapter 实现完全独立 |
| 市场编码 | 大写两字母，如 `CN` / `HK` / `US` |
| 数据域编码 | 蛇形小写，如 `basic_info`、`daily_quotes`、`corporate_actions` |
| 集合命名 | 业务集合 A 股无后缀（如 `stock_basic_info`），港股/美股加 `_<market_lower>`（如 `stock_basic_info_hk`）；元数据集合不带后缀 |
| 配置 key | 蛇形小写 |
| 类名 | 大驼峰，Provider/Adapter 后缀，如 `TushareProvider` / `TushareHkProvider` / `TushareUsProvider` |

---

## 5. 跨市场公共组件

本节明确哪些组件是三市场共享的，哪些是市场特化的。

### 5.1 公共组件清单

| 组件 | 路径 | 复用程度 | 说明 |
|------|------|---------|------|
| 统一接口 | `core/interface.py` | 100% | 通过 market 参数化，三市场共用 |
| 统一读取层 | `core/reader.py` | 100% | 内部根据 market 路由到对应集合 |
| 数据刷新服务 | `core/refresh_service.py` | 100% | 三市场共用同一服务，按 market 分发 |
| 能力注册表 | `core/registry/capability.py` | 100% | 注册表内按 market 分类条目 |
| 回退路由器 | `processor/fallback_router.py` | 100% | 完全市场无关 |
| 熔断器 | `processor/circuit_breaker.py` | 100% | 按 source × domain 隔离实例 |
| 限流器 | `processor/rate_limiter.py` | 100% | 按 source 隔离实例 |
| 字段标准化执行器 | `processor/normalizer.py` | 100% | 调用各源 adapter，本身市场无关 |
| MongoDB 客户端 | `storage/mongo/client.py` | 100% | 三市场共用同一连接池 |
| Redis 客户端 | `storage/redis/client.py` | 100% | 三市场共用同一连接池 |
| 仓储类 | `storage/mongo/repositories/*.py` | 100% | 通过 market 参数路由到对应集合 |
| 调度引擎 | `scheduler/engine.py` | 100% | 加载各市场 schedule.yaml |
| 检查点管理 | `scheduler/checkpoint.py` | 100% | 三市场共用 sync_checkpoints 集合 |
| 健康监控 | `monitoring/source_health.py` | 100% | 三市场共用 source_health 集合 |
| 完整性检查 | `monitoring/completeness.py` | 90% | 检查规则按市场略有差异（如港股跳过停市日） |

### 5.2 市场特化组件清单

| 组件 | 路径 | 说明 |
|------|------|------|
| 数据源 Provider | `sources/<market>/<source>/provider.py` | 每个数据源独立实现 |
| 数据源 Adapter | `sources/<market>/<source>/adapter.py` | 字段映射规则按数据源差异化 |
| 市场特化字段 | `schema/markets/<market>.py` | 港股 connect_status、美股 pre_market_* 等 |
| 调度配置 | `scheduler/jobs/<market>/schedule.yaml` | 时区与时间表 |
| 默认优先级 | `config/default_priorities.yaml` 中的 market 段 | 各市场默认优先级 |
| 新鲜度规则 | `config/freshness_rules.yaml` 中的 market 段 | 各市场新鲜度阈值 |

### 5.3 跨市场协作机制

#### 5.3.1 双重上市股票联动

港股 `09988.HK` 与美股 `BABA` 是同一公司在两地上市。系统的处理：

- `stock_basic_info_hk.dual_listed_us_symbol = "BABA"`
- `stock_basic_info_us.dual_listed_hk_symbol = "09988"`（可选反向字段）
- 二者数据**独立同步**，**独立存储**，不做合并写入
- 业务层（分析引擎）按需联动查询

#### 5.3.2 港股通南北水

港股的 `southbound_holding`（南向持股）字段间接关联到 A 股市场，但作为港股的属性记录，不在 A 股侧维护"北向持股"字段（北向持股是另一个独立数据域，本设计未涵盖）。

#### 5.3.3 共用字典与映射

行业分类、币种、交易所代码等公共字典统一在 `schema/base/enums.py` 维护，三市场共享。

#### 5.3.4 Tushare 按市场独立 Token 与配额

Tushare 在三市场（A 股 / 港股 / 美股）有独立的 Provider 实现，**每个市场可以配置不同的 Token，账户配额完全独立**。这一设计支持用户灵活的购买策略（例如只给 A 股付费、其余市场用免费源），也允许用三个独立账户分别购买不同市场的数据。

| 维度 | 处理方式 |
|------|---------|
| Token 配置 | **三个独立配置项**：`TUSHARE_CN_TOKEN` / `TUSHARE_HK_TOKEN` / `TUSHARE_US_TOKEN`；前端在每个市场的配置面板独立填写 |
| 限流配额 | 200 次/分钟（账户级），在 `RateLimiter` 中**按 Token 哈希为 key** 计数：<br>· 不同 Token → 各 Provider 独立配额<br>· 相同 Token（用户在多市场使用同一 Token）→ 自动聚合配额，避免超限 |
| 积分检测 | 启动时分别试探 stock_basic / hk_basic / us_basic，按市场维度独立决定 Tushare CN / HK / US 是否可用；任一市场积分不足不影响其他市场 |
| 失败传染隔离 | Tushare HK Token 失效**不影响** Tushare CN / Tushare US 的可用性；熔断器与 source_health 集合按 `(market, source, domain)` 三元组维护状态 |
| Token 事件 | 401 / Token 过期时仅禁用对应市场的 Tushare 子源，写入 `TUSHARE_TOKEN_INVALID` 事件并附带 `market` 字段 |
| 多 Token 检测 | 启动时对比三市场的 Token 字符串：相同 → `RateLimiter` 注册同一计数器；不同 → 注册独立计数器 |

**典型部署场景：**

| 场景 | A 股 Token | 港股 Token | 美股 Token | 平台行为 |
|------|-----------|-----------|-----------|---------|
| 完全免费用户 | 空 | 空 | 空 | 三市场均使用免费源（AKShare / yfinance / 等），Tushare 在能力注册表中均不可用 |
| 仅 A 股付费 | 已配置 | 空 | 空 | A 股启用 Tushare 主源，港股 / 美股仅使用免费源 |
| 三市场共用一 Token | T1 | T1 | T1 | 三市场 Tushare 均启用，配额按 hash(T1) 聚合（200 次/分钟为整体上限） |
| 三市场各自独立 | T1 | T2 | T3 | 三个 Provider 独立运行，配额各自维护，互不影响 |
| 港股 + 美股付费 | 空 | T2 | T3 | A 股回退到 AKShare/BaoStock，港股 / 美股用各自的 Tushare |

**实现要点（伪机制）：**

```text
启动序列：
  1. 加载三个 Token: TUSHARE_CN_TOKEN, TUSHARE_HK_TOKEN, TUSHARE_US_TOKEN
  2. 对每个非空 Token 调用对应市场的 _basic 接口试探积分
  3. 在 RateLimiter 中：
     - 计算 token_hash = sha256(token)[:8]
     - 三个 Token 哈希一致时 → 注册同一计数器 quota:tushare:<hash>
     - 不同时 → 注册三个独立计数器 quota:tushare_cn:<hash> 等
  4. 在能力注册表中：未配置或积分不足的市场，移除该市场的 Tushare 条目
  5. 在前端配置中：分别展示三市场的 Tushare 状态卡片
```

#### 5.3.5 双层优先级模型与用户自定义

**核心理念**：默认优先级要让"零配置用户开箱即用"，配置了商业化源（Tushare / Finnhub / Alpha Vantage）后又能"自动升级"为最高质量源，用户还可以**完全覆盖**默认顺序。这通过统一的"双层优先级模型"实现，三市场共用同一套机制：

| 层级 | 内容 | 来源 | 刷新频率 |
|------|------|------|---------|
| 1. 静态默认 | YAML 配置中的基线优先级（按数据质量排序） | `config/default_priorities.yaml` | 启动时加载 |
| 2. 动态可用性 | 启动时基于凭据 / 积分 / API Key 检测的实际可用源列表 | 内存（`source_health` 同步） | 每 30 秒刷新 |
| 3. 市场特化约束 | 美股 Tushare 白名单、港股 Tushare 积分阈值等 | 内存（`Tushare US`: 每周；`port`: 每次启动） | 按需 |
| 4. 用户覆盖 | 前端拖拽调整后保存的优先级 | MongoDB `system_configs` | 30 秒缓存 |
| 5. 最终生效 | `静态默认 ∩ 动态可用性 ∩ 市场约束 ∩ 用户覆盖`，按用户指定顺序排序 | 内存（请求时合成） | 每次请求 |

**用户可执行的自定义操作（共用规范）：**

| 操作 | 粒度 | 行为 |
|------|------|------|
| 整体禁用源 | 按市场 × 源 | 该源在所有域都不参与回退路由 |
| **单域禁用源** | **按市场 × 域 × 源** | **该源仅在指定域不参与回退，其他域仍可用（保证"接口级回退"原则）** |
| 调整顺序 | 按市场 × 域 | 拖拽改变各源在该域的优先级 |
| 强制单源 | 按市场 × 域 | 仅保留 1 个源，禁用回退（高级用法） |

**安全约束（三市场统一）：**

- 用户禁用所有源时前端拒绝保存
- 唯一源域不可禁用主源（如港股 `news` 的 AKShare HK、美股 `pre_post_market` 的 Finnhub）
- 能力矩阵 ❌ 的源不会出现在用户可选列表中
- 保存后首次请求失败 ≥ 3 次时自动回滚到上一版配置

**配置生效流程：**

```text
用户在前端调整优先级 → 立即写入 system_configs（保存按钮）
  → ConfigBridge 在内存中按 30 秒 TTL 缓存最新配置
  → 处理层（FallbackRouter）每次请求时调用 ConfigBridge.get_priority(market, domain, symbol?)
  → 不需要重启服务、不影响正在执行的同步任务
```

**默认优先级两档摘要（与各市场文档详细矩阵对应）：**

| 市场 | 配置档（已配 Token / API Key）默认主源 | 零配置档默认主源 | 备注 |
|------|----------------------------------|-----------------|------|
| A 股 | Tushare → AKShare → BaoStock | AKShare → BaoStock | 中文市场 Tushare 数据规范度最高 |
| 港股 | Tushare HK → AKShare HK → yfinance HK → Tencent HK | AKShare HK → yfinance HK → Tencent HK | corporate_actions / news 始终 AKShare HK 主 |
| 美股 | yfinance → Tushare US（白名单内）→ Finnhub → Alpha Vantage | yfinance → Finnhub → Alpha Vantage | yfinance 始终为全市场主源（Tushare US 覆盖度受限） |

### 5.4 抽象类契约

#### 5.4.1 BaseProvider 契约

所有 Provider 必须遵守以下接口契约：

| 方法语义 | 入参 | 出参 | 异常 |
|---------|------|------|------|
| 拉取股票列表 | (limit?) | 原始 DataFrame | DataSourceUnavailable / RateLimited |
| 拉取交易日历 | (start, end) | 原始 DataFrame | DataSourceUnavailable / RateLimited |
| 拉取日线行情 | (symbol, start, end) | 原始 DataFrame | DataSourceUnavailable / RateLimited / SymbolNotFound |
| 拉取每日指标 | (symbol, start, end) | 原始 DataFrame | 同上 |
| 拉取财务数据 | (symbol, period_start, period_end, statement_type) | 原始 DataFrame | 同上 |
| 拉取公司行为 | (symbol, start, end) | 原始 DataFrame | 同上（仅 HK / US 需要） |
| 拉取新闻 | (symbol, start, end) | 原始 DataFrame | 同上 |
| 拉取市场快照 | (symbols?) | 原始 DataFrame | 同上 |

不支持的接口直接抛 `NotImplementedError`，由能力注册表保证不会被误调。

#### 5.4.2 BaseAdapter 契约

所有 Adapter 必须遵守以下接口契约：

| 方法语义 | 入参 | 出参 |
|---------|------|------|
| 标准化股票列表 | 原始 DataFrame | List[StockBasicInfo] |
| 标准化日线行情 | 原始 DataFrame | List[DailyQuote] |
| 标准化每日指标 | 原始 DataFrame | List[DailyIndicator] |
| 标准化财务数据 | 原始 DataFrame | List[FinancialData] |
| 标准化公司行为 | 原始 DataFrame | List[CorporateAction] |
| 标准化新闻 | 原始 DataFrame | List[StockNews] |
| 标准化市场快照 | 原始 DataFrame | List[MarketQuote] |

返回的字典 / 数据类必须包含 `schema/domains/<domain>.py` 与 `schema/markets/<market>.py` 定义的所有字段（不支持的字段写 null）。

---

## 6. 数据库存储规划

### 6.1 MongoDB 集合一览

业务集合按市场后缀区分：

| 数据域 | A 股集合 | 港股集合 | 美股集合 |
|--------|---------|---------|---------|
| 股票基本信息 | stock_basic_info | stock_basic_info_hk | stock_basic_info_us |
| 交易日历 | trade_calendar | trade_calendar_hk | trade_calendar_us |
| 日线行情 | stock_daily_quotes | stock_daily_quotes_hk | stock_daily_quotes_us |
| 每日指标 | stock_daily_indicators | stock_daily_indicators_hk | stock_daily_indicators_us |
| 复权因子 | stock_adj_factors | stock_adj_factors_hk | stock_adj_factors_us |
| 公司行为 | – | stock_corporate_actions_hk | stock_corporate_actions_us |
| 财务数据 | stock_financial_data | stock_financial_data_hk | stock_financial_data_us |
| 市场快照 | market_quotes | market_quotes_hk | market_quotes_us |
| 新闻公告 | stock_news | stock_news_hk | stock_news_us |

元数据集合三市场共用：

| 集合 | 说明 |
|------|------|
| `sync_checkpoints` | 含 `market + domain + source` 唯一键 |
| `sync_events` | 含 `market` 字段，按 market + 时间索引 |
| `source_health` | 含 `market + source + domain` 唯一键 |
| `system_configs` | 用户配置（数据源优先级等），含 `market` 字段 |

### 6.2 索引策略

#### 6.2.1 业务集合索引

| 集合类型 | 主索引（唯一） | 辅助索引 |
|---------|-------------|---------|
| 基本信息类 | symbol | data_source、updated_at |
| 时序类（日线、指标、复权因子） | symbol + trade_date + period | trade_date（用于按日期范围扫描） |
| 财务类 | symbol + report_period + statement_type + report_type | symbol + announce_date |
| 公司行为 | symbol + ex_date + action_type | ex_date（用于按日期扫描） |
| 市场快照 | symbol | last_updated |
| 新闻 | content_hash | symbol + announce_date |
| 交易日历 | exchange + cal_date | cal_date |

#### 6.2.2 元数据集合索引

| 集合 | 主索引（唯一） | 辅助索引 |
|------|-------------|---------|
| sync_checkpoints | market + domain + source | last_sync_time |
| sync_events | _id（自动） | market + created_at、event_type |
| source_health | market + source + domain | updated_at |
| system_configs | config_type + market + domain | updated_at |

### 6.3 集合命名分发逻辑

`storage/mongo/collections.py` 提供统一的集合名计算函数：

```text
get_collection_name(domain, market) → str

示例：
  ("basic_info", "CN") → "stock_basic_info"        # A 股无后缀
  ("daily_quotes", "HK") → "stock_daily_quotes_hk"
  ("corporate_actions", "US") → "stock_corporate_actions_us"
  ("sync_checkpoints", "*")  → "sync_checkpoints"  # 元数据集合无后缀
```

业务代码不直接拼接集合名，必须通过此函数获取。

### 6.4 Redis Key 命名规范

```text
锁:                  lock:{market}:{domain}:{symbol}
限流计数器:          ratelimit:{source}:{minute_window}
熔断器状态:          circuit:{source}:{domain}
熔断器失败计数:      circuit_fail:{source}:{domain}
刷新冷却标记:        cooldown:{market}:{symbol}:{domain}
异步刷新队列:        queue:refresh:{market}
市场状态缓存:        market_state:{market}
配置缓存:            config:priority:{market}:{domain}
```

所有 Key 设置合理 TTL，避免长期占用内存。

### 6.5 容量规划

#### 6.5.1 业务数据规模估算

| 市场 | 股票数 | 日线行情（10 年） | 每日指标（10 年） | 财务数据（10 年） |
|------|--------|------------------|------------------|------------------|
| A 股 | ~5500 | ~1300 万记录 | ~1300 万记录 | ~22 万记录 |
| 港股 | ~3000 | ~700 万记录 | ~700 万记录 | ~6 万记录 |
| 美股 | ~8000 | ~2000 万记录 | ~2000 万记录 | ~32 万记录 |
| **合计** | **~16500** | **~4000 万** | **~4000 万** | **~60 万** |

按此规模，MongoDB 单实例配置 16GB 内存 + 200GB SSD 即可流畅运行。

#### 6.5.2 Redis 容量估算

主要消耗：

- 限流计数器：每数据源 ≈ 60 个 key（按分钟窗口）
- 熔断器状态：每 source × domain ≈ 100 个 key（三市场合计）
- 刷新冷却标记：在线交易日峰值 ≈ 几千个 key（5 分钟 TTL 自动清理）
- 异步刷新队列：长度 < 1000

总计 < 100MB，Redis 单实例 1GB 内存绰绰有余。

---

## 7. 配置体系

### 7.1 配置层级

```text
                    用户配置（最高优先级）
                            ↓
                    数据库 system_configs 集合
                            ↓
                    YAML 配置文件（默认值）
                            ↓
                    代码内置默认值（保底）
```

### 7.2 关键配置文件

#### 7.2.1 `config/markets.yaml`

定义各市场基础元信息：

| 字段 | 说明 |
|------|------|
| code | CN / HK / US |
| name_zh | 市场中文名 |
| timezone | 时区 IANA 名（Asia/Shanghai / Asia/Hong_Kong / America/New_York） |
| currency | 主货币 |
| trading_hours | 交易时段（含午休、盘前盘后） |
| calendar_source | 交易日历优先源 |
| symbol_format | 股票代码格式（regex） |

#### 7.2.2 `config/capability_matrix.yaml`

定义各市场各域支持的数据源（不可被用户配置覆盖，仅用于过滤）：

| 字段 | 说明 |
|------|------|
| market | 市场 |
| domain | 数据域 |
| sources | 支持的数据源列表（带能力等级 full / partial / unique） |

#### 7.2.3 `config/default_priorities.yaml`

定义各市场各域的默认优先级（用户未配置时生效）：

| 字段 | 说明 |
|------|------|
| market | 市场 |
| domain | 数据域 |
| order | 按优先级排序的数据源列表 |

#### 7.2.4 `config/freshness_rules.yaml`

定义各市场各域的新鲜度规则：

| 字段 | 说明 |
|------|------|
| market | 市场 |
| domain | 数据域 |
| rule_type | 规则类型（trading_day_after_close / time_window） |
| threshold | 阈值（如 30 分钟、24 小时、7 天） |
| reference_time | 参考时间（如收盘后 30 分钟） |

#### 7.2.5 `config/source_limits.yaml`

定义各数据源的限流参数：

| 字段 | 说明 |
|------|------|
| source | 数据源编码 |
| rate_per_minute | 每分钟最大调用次数 |
| rate_per_day | 每日最大调用次数（可选） |
| polite_interval_ms | 礼貌间隔毫秒数 |
| circuit_initial_cooldown | 熔断初始冷却（秒） |
| circuit_max_cooldown | 熔断最大冷却（秒） |

### 7.3 用户配置存储（system_configs）

| 字段 | 类型 | 说明 |
|------|------|------|
| config_type | string | 配置类型（`data_source_priority` / `auto_sync_toggle` / `api_key`） |
| market | string | 市场 |
| domain | string | 数据域（仅部分配置有此字段） |
| value | object | 配置内容（JSON） |
| updated_by | string | 更新人 |
| updated_at | datetime | 更新时间 |

**敏感配置（如 API Key）**: 通过环境变量加载，不写入 system_configs 集合。

### 7.4 配置热更新

| 配置类型 | 生效方式 | 缓存策略 |
|---------|---------|---------|
| 用户优先级 | 处理层每次请求时读取 | 内存缓存 30 秒 TTL |
| 自动同步开关 | 调度器每次任务执行前检查 | 内存缓存 30 秒 TTL |
| 调度时间调整 | 需调度器重新加载（手动触发） | – |
| API Key | 重启服务 | – |
| YAML 配置文件 | 重启服务 | – |

---

## 8. API 接口规范

### 8.1 路径前缀约定

所有数据相关 API 必须使用按市场前缀的路径：

```text
A 股: /api/cn/data/...
港股: /api/hk/data/...
美股: /api/us/data/...
跨市场: /api/data/...    # 罕见，仅用于跨市场统计
```

### 8.2 关键端点

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/{market}/data/refresh/{symbol}` | POST | 手动刷新指定股票的数据 |
| `/api/{market}/data/sync/trigger` | POST | 触发指定域的同步任务 |
| `/api/{market}/data/sync/status` | GET | 查询同步任务状态 |
| `/api/{market}/data/sync/events` | GET | 查询同步事件历史 |
| `/api/{market}/data/sources/health` | GET | 查询数据源健康度 |
| `/api/{market}/data/config/priority` | GET / PUT | 获取 / 更新数据源优先级 |
| `/api/{market}/data/calendar` | GET | 查询交易日历 |
| `/api/{market}/data/symbols` | GET | 查询股票列表 |
| `/api/{market}/stocks/{symbol}/quotes` | GET | 查询日线行情 |
| `/api/{market}/stocks/{symbol}/indicators` | GET | 查询每日指标 |
| `/api/{market}/stocks/{symbol}/financials` | GET | 查询财务数据 |
| `/api/{market}/stocks/{symbol}/actions` | GET | 查询公司行为（仅 HK / US） |
| `/api/{market}/stocks/{symbol}/news` | GET | 查询新闻 |

### 8.3 路由组织

按 CLAUDE.md 中的路由约定，路由实现按市场组织：

```text
app/routers/
├── cn/
│   ├── data.py           # /api/cn/data/*
│   ├── stocks.py         # /api/cn/stocks/*
│   └── sync.py           # /api/cn/data/sync/*
├── hk/
│   ├── data.py
│   ├── stocks.py
│   └── sync.py
└── us/
    ├── data.py
    ├── stocks.py
    └── sync.py
```

每个路由文件：

- 必须声明 `prefix="/api/<market>/<domain>"`
- 必须使用英文 Title-Case 的 `tags=[]`
- 禁止直接调用 MongoDB（必须通过 service 层）
- service 层调用 `core/interface.py` 提供的统一接口

---

## 9. 部署架构

### 9.1 进程划分

```text
┌────────────────────┐    ┌────────────────────┐
│   API Server       │    │ Scheduler Worker   │
│   (FastAPI)        │    │  (APScheduler)     │
│                    │    │                    │
│ - HTTP 端点        │    │ - 定时同步任务      │
│ - SSE 推送         │    │ - 完整性检查任务    │
│ - 内部刷新调用     │    │ - 健康监控任务      │
└──────────┬─────────┘    └──────────┬─────────┘
           │                         │
           └────────────┬────────────┘
                        │
            ┌───────────┴────────────┐
            │                        │
            ▼                        ▼
    ┌──────────────┐         ┌──────────────┐
    │   MongoDB    │         │    Redis     │
    │  (持久化)    │         │  (协调层)    │
    └──────────────┘         └──────────────┘
```

### 9.2 多实例部署

| 服务 | 实例数 | 状态 |
|------|--------|------|
| API Server | 多实例（按负载） | 无状态，所有协调通过 Redis |
| Scheduler Worker | 单实例（主备模式） | 通过 Redis 抢主锁，避免重复调度 |
| MongoDB | 单实例 / 副本集 | 数据持久化 |
| Redis | 单实例 | 协调与缓存 |

### 9.3 故障域与降级

| 故障 | 影响 | 降级行为 |
|------|------|---------|
| 单个数据源故障 | 仅影响该源涉及的域 | 自动回退到下一优先级源 |
| 整个市场所有源故障 | 该市场该域不可用 | 返回 stale 数据 + 告警 |
| Redis 故障 | 多实例协调失效 | 降级为单机模式（内存锁、内存计数器） |
| MongoDB 故障 | 整个数据平台不可用 | API 直接返回 503，不尝试调外部源（避免雪崩） |
| Scheduler Worker 故障 | 自动同步停止 | 主备切换，按需刷新仍可工作 |

---

## 10. 开发与扩展规范

### 10.1 新增一个市场

新增市场（如新加坡 SGX）的步骤：

1. 在 `schema/markets/` 下新增 `sg.py`，定义市场特化字段
2. 在 `sources/sg/` 下创建数据源目录，实现 Provider + Adapter
3. 在 `config/markets.yaml` 中添加市场基础信息
4. 在 `config/capability_matrix.yaml` 中添加该市场的能力矩阵
5. 在 `config/default_priorities.yaml` 中添加默认优先级
6. 在 `config/freshness_rules.yaml` 中添加新鲜度规则
7. 在 `scheduler/jobs/sg/schedule.yaml` 中添加调度配置
8. 创建对应的业务集合（带 `_sg` 后缀）

不需要修改：

- `core/`（自动按 market 参数路由）
- `processor/`
- `storage/mongo/repositories/`
- `scheduler/engine.py`

### 10.2 新增一个数据源

新增数据源（如 Polygon.io）的步骤：

1. 在 `sources/<market>/<source_name>/` 下实现 Provider + Adapter
2. 在 `config/capability_matrix.yaml` 中标记该源支持哪些域
3. 在 `config/source_limits.yaml` 中配置限流参数
4. （可选）在 `config/default_priorities.yaml` 中调整优先级
5. 在 `sources/<market>/__init__.py` 中注册到能力注册表

### 10.3 新增一个数据域

新增数据域（如美股期权 IV，假设业务需要）的步骤：

1. 在 `schema/domains/` 下定义该域的字段
2. 在 `storage/mongo/repositories/` 下实现仓储类
3. 在 `storage/mongo/collections.py` 中注册集合命名规则
4. 在所有支持该域的 `sources/<market>/<source>/adapter.py` 中实现标准化方法
5. 在 `config/capability_matrix.yaml` 中标记各源对该域的支持情况
6. 在 `config/freshness_rules.yaml` 中定义新鲜度规则
7. 在 `scheduler/jobs/<market>/schedule.yaml` 中添加调度任务

### 10.4 代码契约（强制）

| 契约 | 说明 |
|------|------|
| 消费层只能 import `core/` | 不能直接 import `processor/`、`sources/`、`storage/` |
| 路由层必须经过 service 层 | 不能直接调用 `core/` 之外的模块 |
| Provider 不能写 MongoDB | 必须由 processor + repository 完成写入 |
| Adapter 不能调外部 API | 只接受 Provider 返回的原始数据 |
| Repository 不能调外部 API | 只读写 MongoDB |
| 业务集合命名必须通过 `get_collection_name` | 不允许字符串拼接 |
| 公共字段必须出现在所有业务集合 | symbol / market / data_source / updated_at |

### 10.5 测试规范

| 层 | 测试目标 |
|----|---------|
| Adapter 单元测试 | 每个数据源 × 每个域至少 1 个映射测试用例 |
| Provider 单元测试 | Mock 外部 API，验证错误处理与异常类型 |
| Processor 单元测试 | 验证 fallback、circuit、rate-limit 行为 |
| Repository 集成测试 | 在测试 MongoDB 上验证 upsert / 查询 |
| Reader 集成测试 | 验证新鲜度判定与异步通知 |
| 端到端测试 | 通过 HTTP API 触发刷新，验证数据落库 |

---

## 11. 实施路线图

整体分为五个阶段，三市场可以**并行推进**（数据源层独立）或**串行落地**（先 A 股稳定后再做港股、美股）。推荐策略为**水平先行**：先把 A 股的全链路打通后，再补齐港股、美股。

### Phase 1: 公共基础设施（市场无关）

目标：搭建市场无关的基础组件，能跑通"假数据 → 标准化 → MongoDB"的最小闭环。

1. 实现 `core/` 抽象层（interface、reader、refresh_service、registry）
2. 实现 `schema/base/` 与 `schema/domains/`
3. 实现 `processor/` 全套（fallback、circuit、rate-limit、normalizer、validator）
4. 实现 `storage/mongo/` 与 `storage/redis/`
5. 实现 `scheduler/engine.py`（不含具体任务）
6. 实现 `monitoring/` 框架
7. 提供 1 个 mock provider 用于联调

### Phase 2: A 股完整落地

目标：A 股全链路打通，作为参照实现。

1. 实现 `sources/cn/` 三个数据源（Tushare / AKShare / BaoStock）
2. 实现 `schema/markets/cn.py`
3. 实现 A 股调度配置（`scheduler/jobs/cn/schedule.yaml`）
4. 实现 A 股相关路由与前端页面
5. A 股数据全量回填、自动调度上线

### Phase 3: 港股扩展

目标：复用 A 股已有模式，最小化改动加入港股。

1. 实现 `sources/hk/` 四个数据源（**Tushare HK** / AKShare HK / yfinance HK / Tencent HK）
2. 实现 `schema/markets/hk.py`（港股通、双重上市等字段）
3. 实现港股调度配置
4. 实现港股 corporate_actions 域（含红股 / 供股，固定 AKShare HK 主源）
5. 实现 Tushare HK 独立 Token 加载（`TUSHARE_HK_TOKEN`）与积分检测
6. 港股相关路由与前端页面（含港股专属 Tushare 配置面板）
7. 临时停市处理通道

### Phase 4: 美股扩展

目标：复用已有模式，加入美股。

1. 实现 `sources/us/` 四个数据源（**Tushare US** / yfinance / Finnhub / Alpha Vantage）
2. 实现 `schema/markets/us.py`（盘前盘后、ADR、公司行为字段）
3. 实现美股调度配置（含 ET 夏令时换算）
4. 实现美股 corporate_actions 域 + 复权因子推导（Tushare 直供 + 本地推导双轨）
5. 实现 Tushare US 独立 Token 加载（`TUSHARE_US_TOKEN`）+ 美股覆盖白名单维护任务
6. 实现 RateLimiter 的 Token 哈希聚合机制（多市场共用 Token 时配额合并）
7. 美股相关路由与前端页面（含美股专属 Tushare 配置面板）
8. Finnhub + Tushare us_basic + yfinance 三源合并的 Universe 维护任务

### Phase 5: 质量与体验完善

目标：数据质量自动闭环、用户体验提升。

1. 三市场完整性检查规则补全
2. 多源公司行为对账（HK / US）
3. 双重上市数据一致性核对
4. 前端总览看板（三市场聚合视图）
5. 数据导出 API
6. 性能压测与调优

---

## 12. 附录

### A. 文档导航

| 主题 | 文档 |
|------|------|
| A 股详细设计 | `a-share-data-architecture.md` |
| 港股详细设计 | `hk-stock-data-architecture.md` |
| 美股详细设计 | `us-stock-data-architecture.md` |
| 总览（本文档） | `data-platform-overview.md` |

### B. 关键术语表

| 术语 | 含义 |
|------|------|
| Market | 市场，三个枚举值：CN（A 股）/ HK（港股）/ US（美股） |
| Domain | 数据域，如 basic_info、daily_quotes、corporate_actions |
| Source | 数据源，如 tushare、akshare、yfinance、finnhub |
| Provider | 数据源 API 调用封装层 |
| Adapter | 字段标准化层，将 Provider 的原始数据映射为统一字段 |
| Reader | 统一读取层，从 MongoDB 读标准数据并判定新鲜度 |
| Processor | 处理层，负责选源、回退、限流、熔断、写入 |
| Repository | 仓储类，封装 MongoDB 读写 |
| Capability Matrix | 能力矩阵，记录各 source 对各 domain 的支持情况 |
| FallbackRouter | 回退路由器，按优先级选择数据源并降级 |
| CircuitBreaker | 熔断器，按 source × domain 隔离故障 |
| RateLimiter | 限流器，按 source 控制调用频率 |
| Checkpoint | 检查点，记录各 market × domain × source 的同步进度 |
| Stale Data | 过期数据，新鲜度判定不通过的数据 |
| Cooldown | 冷却期，按 symbol × domain 限制刷新频率 |

### C. 关键设计决策汇总

| 决策 | 选择 | 理由 |
|------|------|------|
| 架构层数 | 4 层 | 够用即可，不为"可能的需求"预留空层 |
| 市场组织方式 | sources/<market>/ + schema/markets/<market>.py | 市场可独立演进 |
| 集合命名 | A 股无后缀，港股/美股业务集合带 `_<market_lower>` 后缀 | 物理隔离，便于运维与扩展；A 股向后兼容不加后缀 |
| 元数据集合 | 三市场共用，含 market 字段 | 减少集合数量，便于跨市场对比 |
| 回退粒度 | 接口级（source × domain） | 避免一个接口故障拖累整个数据源 |
| 按需刷新模式 | 同步阻塞 + 30 秒超时 | 调用方明确等待，便于业务编排 |
| 公司行为 | 独立成域（HK / US），A 股不需要 | 港股 / 美股的核心特征 |
| 三市场 Tushare | A 股 `tushare`、港股 `tushare_hk`、美股 `tushare_us` **各自独立 Provider + 独立 Token + 独立配额** | 用户可灵活选择哪个市场付费；同一 Token 时 RateLimiter 自动按 Token 哈希聚合配额 |
| Tushare Token 管理 | 三个独立环境变量：`TUSHARE_CN_TOKEN` / `TUSHARE_HK_TOKEN` / `TUSHARE_US_TOKEN` | 支持三市场独立账户、单市场付费、多市场共用同一 Token 三种模式 |
| 默认优先级模型 | 双层模型：静态默认 → 动态可用性 → 用户覆盖 → 最终生效 | 零配置可用 + 配置后自动升级 + 用户完全可覆盖 |
| 默认主源策略 | A 股 / 港股: 配置 Tushare 后前置；美股: yfinance 始终全市场主源 | Tushare US 覆盖度受限（仅白名单内），不能成为全市场默认主源 |
| 用户优先级粒度 | 按市场 × 数据域 × 数据源（支持单域禁用） | 体现"接口级回退"在用户配置层的延伸 |
| 美股按股票分层选源 | 维护 Tushare US 覆盖白名单 | Tushare US 仅覆盖主要美股 + 中概股 |
| 港股公司行为 / 新闻 | 固定使用 AKShare HK | Tushare 不支持港股公司行为与披露易公告 |
| 复权策略 | A 股 / 港股数据源直供，美股 Tushare 直供 + 本地推导兜底 | 各市场情况不同 |
| 配置存储 | YAML（默认）+ MongoDB（用户）+ ENV（敏感） | 分级管理，灵活生效 |
| Redis 角色 | 协调层（锁、计数、状态） | 不存业务数据，可降级 |
| 调度引擎 | APScheduler（单实例） | 简单可靠，主备切换通过 Redis 锁实现 |

### D. 与单市场设计文档的关系

总览文档（本文档）与三份单市场文档的关系：

- **总览文档**: 横向描述三市场共享的架构、目录、组件、协作机制
- **单市场文档**: 纵向描述某一市场的数据源、字段、调度、特殊业务逻辑

实施时：

- **架构师**先读总览文档，了解整体设计与目录规划
- **单市场开发者**重点参考自己负责市场的文档，但需遵守总览中的契约
- **跨市场协调**（如双重上市、共享元数据）按总览文档的规范执行

三份文档保持一致：

- 章节结构对齐（目标 / 架构 / 数据域 / 存储 / 回退 / 刷新 / 调度 / 配置 / 质量 / 前端 / 路线图 / 附录）
- 集合命名、术语、配置 key 完全一致
- 跨市场字段（market、symbol、data_source、updated_at）完全一致



