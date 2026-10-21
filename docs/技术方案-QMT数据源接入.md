# TradingAgents-CN · QMT 数据源接入 技术方案

> 对应 PRD：[PRD-QMT数据源接入.md](PRD-QMT数据源接入.md) v1.2（口径 D-1 ~ D-7）
> 本文所有接口签名均摘自两个代码库的实际代码（探索时间 2026-10-20），非凭空设计。

## 〇、执行摘要

以 `QmtProvider`/`QmtAdapter` 双类接入既有数据平台：整体移植 StockQuant 的 `QmtDatadirReader`（约 1144 行，纯 numpy+pandas、零项目耦合，移植成本约 90% 代码可直接复制），按平台「新增一个源 + 新增一个标准域」的两套既有清单落地（合计 25 个改动点，逐条列于第五、六节）。M1（日线/合约/回退链/配置/健康）估算 13 人日，M2（分时/tick/财务口径外/调度/缺口）估算 11.5 人日。

**一个必须先拍板的 PRD 修正**（O-1）：datadir 财务直读仅实现 7004~7007 四张表（股本/股东户数/十大股东/流通十大），财务 8 大表（利润/资产负债/现金流）在 StockQuant 走 RPC 下载通道——D-7 移除 RPC 后 **QMT 无法提供财务主表**。建议 PRD FR-07 收窄：`financial_data` 域能力置 `none`，分红/复权/指数/日历保留；扩展 reader 解析其余 table_id 记为开放项。

---

## 一、总体架构

```
Windows 部署机（D-1 同机）
┌─────────────────────────────────────────────────────────────┐
│  国金 QMT 客户端（盘后自续下载任务）                            │
│        │ 产出                                                │
│  {QMT_DATADIR}/  ← 纯文件 IO 直读，零 xtquant 依赖（D-7）      │
│        ▼                                                     │
│  TradingAgents-CN  app/data/sources/cn/qmt/                  │
│  ┌──────────────┐  asyncio.to_thread   ┌──────────────────┐  │
│  │ QmtProvider  │ ───────────────────▶ │ QmtDatadirReader │  │
│  │ (BaseProvider│   信号量并发=4        │ (移植，None=拒读) │  │
│  │  async hooks)│                      └──────────────────┘  │
│  └──────┬───────┘                                            │
│         │ raw DataFrame（xtdata 同形原始列名）                 │
│  ┌──────▼───────┐   field_maps.py（QMT 列 → 标准 Schema 字段）│
│  │ QmtAdapter   │ ──▶ List[XxxSchema] ──▶ to_db_doc()        │
│  └──────────────┘                                            │
└──────────────┬───────────────────────────────────────────────┘
               │  fetch_source 四件套（熔断/限流/重试/健康）+ Normalizer + Validator
┌──────────────▼───────────────────────────────────────────────┐
│  FallbackRouter（qmt 列回退链末位，D-2） → MongoDB 既有集合     │
└──────────────────────────────────────────────────────────────┘
```

**架构决策记录（DD）**

| 编号 | 决策 | 理由 |
|------|------|------|
| DD-01 | Provider 业务方法内用 `asyncio.to_thread` 包裹阻塞文件 IO，进程内 `asyncio.Semaphore(4)` 限并发 | 平台 Provider 契约是 `async`；datadir 解析为 CPU/磁盘密集，直接阻塞事件循环会拖垮 API 服务 |
| DD-02 | reader 保持「失败返回 None」契约不变，缺口语义由 Provider 层翻译（记日志 + 返回空帧），由 worker 层登记缺口 | 原契约的语义是「回退 RPC」，目标项目无 RPC；保留 None 契约使移植代码零改动，语义翻译集中在一处 |
| DD-03 | tick 保留期用**定时清理 Job**（按 `trade_date` 分区删除 + `sync_events` 登记），不用 Mongo TTL 索引 | 平台唯一键与时间字段均为字符串；TTL 索引要求 BSON Date 类型，需额外加 `expires_at` 字段，且 TTL 删除不产生 sync_events 记录（PRD FR-06 要求可审计） |
| DD-04 | 复权只存原始价 + datadir 原生 `adj_f_evt`/`adj_f_cum` 因子列，放弃 StockQuant 的「表 A」parquet 因子兜底 | 目标项目复权模型即为「原始价+因子、读取现算」（PRD FR-03 规则 4），datadir 因子槽原生自带；表 A 依赖 StockQuant 内部 parquet 体系 |
| DD-05 | 字段映射表集中在新文件 `field_maps.py`，作为 QMT 列名 → 标准 Schema 字段的**唯一权威**（借鉴 StockQuant FIELD_MAP 单点模式） | 防映射逻辑散落在 provider/adapter 两层造成漂移 |
| DD-06 | 停牌行补齐不做（datadir 无记录即无行），`suspend_flag` 置 0 且 turnover_rate 置空 | StockQuant 的停牌补齐依赖其退市表与交易日历 meta 体系；既有源（tushare）已提供停牌口径，qmt 为兜底源不必复制该语义 |
| DD-07 | datadir 就绪探测内嵌在采集 Job 内轮询（10 分钟间隔、截止 22:00），不注册独立探测定时器 | 避免 worker 队列被空转任务占满；与 PRD FR-11 规则 2 一致 |

## 二、新增/修改文件总览

```
新增  app/data/sources/cn/qmt/
      ├── __init__.py            # 空包标记
      ├── datadir_reader.py      # 移植 StockQuant QmtDatadirReader（唯一大件，~1100 行）
      ├── provider.py            # QmtProvider(BaseProvider)
      ├── adapter.py             # QmtAdapter(BaseAdapter)
      ├── field_maps.py          # DD-05 字段映射唯一权威
      ├── health.py              # QmtHealthProbe 三层检查 + QmtErrorCode 枚举
      └── config.py              # get_qmt_datadir() 等 Mongo→ENV 解析（仿 ds_key_utils）

新增（tick_quotes 新标准域，第六节 15 步清单）
      app/data/schema/domains/tick_quotes.py
      app/data/storage/mongo/repositories/tick_quotes_repo.py

修改  app/data/sources/cn/__init__.py          # 工厂 +2 个 elif 分支
      app/data/config/{capability_matrix,default_priorities,source_limits}.yaml
      app/core/config.py                        # Settings +QMT_* 块（第 358 行 BaoStock 块后）
      app/constants/data_sources.py             # DataSourceCode.QMT + DataSourceInfo
      app/models/config.py                      # DataSourceType 枚举 +QMT（第 177 行）
      app/services/config/data_source_service.py# test_data_source_config +_test_qmt 分支
      app/worker/base_market_sync.py            # _REPO_TABLE +tick_quotes
      app/worker/scheduler_setup.py             # register_jobs +qmt 采集 job
      app/data/processor/normalizer.py          # DOMAIN_METHOD_MAP +2
      app/data/processor/validator.py           # _REQUIRED_FIELDS +tick_quotes
      app/data/core/reader.py                   # repo_map +tick_quotes
      app/data/core/refresh_service.py          # _SUPPORTED_ON_DEMAND_DOMAINS +tick_quotes
      app/data/schema/domains/__init__.py 等    # tick_quotes 登记链

新增  tests/data/test_qmt_datadir_reader.py    # 移植 StockQuant 二进制 fixture 自检用例
      tests/data/test_qmt_adapter.py / test_qmt_provider.py / test_qmt_health.py
```

## 三、QmtDatadirReader 移植设计

### 3.1 移植范围（源自对 StockQuant `src/data/qmt/datadir_reader.py` 的全文分析）

| 部分 | 处置 | 说明 |
|------|------|------|
| `QmtDatadirReader` 全部公开方法（`daily/minute/tick/stock_codes/trading_dates/has_daily/has_daily_file/dividends/finance/adjust_frame/index_weights/industry_data/sector_names/sector_members/split_code/available`） | **整体复制** | 构造仅收 `datadir: str`，零项目耦合；失败契约「一律返回 None 不抛业务异常」原样保留（DD-02） |
| `_KLINE_DTYPE`（64B）/`_TICK_DTYPE`（144B）结构化 dtype、4 级自检（头哨兵/status 全等+量级/ts 单调/preClose 链告警）、LevelDB 纯 Python 解析 3 函数 | **整体复制** | 文件头 import 期 `assert itemsize` 防写错，保留 |
| 模块函数 `datadir_root()` | **删除重写** | 唯一项目耦合点（lazy import StockQuant Config + 硬编码 `D:\App\...` 路径）；目标项目改由 `qmt/config.py::get_qmt_datadir()` 注入 |
| kline.py 标准化管道（FIELD_MAP 8 条 rename + ms→北京 naive + trade_date 派生） | **翻译到 field_maps.py + adapter.py** | 约 30 行；方向：`volume→vol、preClose→pre_close、suspendFlag→suspend_flag`（StockQuant 产品列名）再映射到**项目** Schema 列名（见 4.2，注意项目 volume 单位是股、QMT 是手） |
| `_ensure_factor_columns`「表 A」兜底、停牌补齐 `_fill_suspended_rows` | **放弃** | DD-04/DD-06 |
| StockQuant 的 15+ 个二进制 fixture 测试（拒读/半写/竞价校准用例） | **随代码移植** | 这是格式正确性的唯一回归保障（`test_datadir_reader.py`/`test_tick_decode`/`test_kline_local_read`/`test_adjust_local`/`test_kline_factor_columns`） |

### 3.2 必须保留的公开面（勿按「只导出读数据方法」裁剪）

`_load_dividends`（被 adjust 引擎跨模块调用的私有方法）、`available`/`has_daily_file`/`stock_codes`（健康探针依赖）、`has_daily`（对账位图）。移植后统一收窄为下表公开 API：

```python
class QmtDatadirReader:
    def __init__(self, datadir: str): ...
    @property
    def available(self) -> bool: ...                 # 根目录 is_dir()
    def self_check(self) -> SelfCheckReport: ...     # 新增聚合：抽 3 只样本股跑四级自检
    def daily(self, ts_code: str, start=None, end=None) -> Optional[pd.DataFrame]   # YYYYMMDD 闭区间
    def minute(self, ts_code: str, period: str, start=None, end=None) -> Optional[pd.DataFrame]  # '1m'/'5m'
    def tick(self, ts_code: str, trade_date: str) -> Optional[pd.DataFrame]         # YYYYMMDD
    def stock_codes(self, markets=("SH","SZ")) -> List[str]     # '000001.SZ' 升序，剔 BJ
    def trading_dates(self) -> Optional[List[str]]
    def has_daily(self, ts_code: str, dates: List[str]) -> np.ndarray
    def has_daily_file(self, ts_code: str) -> bool
    def dividends(self, ts_code: str, with_record_date: bool = False) -> Optional[pd.DataFrame]
    def finance(self, ts_code: str, table_id: int) -> Optional[pd.DataFrame]        # 仅 7004~7007（O-1）
    def index_weights(self, index_code: str) -> Optional[dict]
```

### 3.3 关键二进制事实（实现与评审时对照）

- 64B K 线：`amount` 为 u64 **直存元**（勿 /100）；`volume` u32 单位**手**；价格 ÷1000；`adj_f_evt`@44、`adj_f_cum`@48（f32）；尾哨兵已不校验（两次事故史，勿"修复"回去）；`body % 64` 半写截断容忍。
- 144B tick：`amount` u64 元（勿改回 u32，会回绕）；**无文件头**；时间基校准依赖集合竞价行（`open_int==12`），无竞价行整文件拒读。
- LevelDB 分红：纯 Python SSTable 解析（无 plyvel 依赖）；`ex_u32` 无效时回退 `ts_key` 派生**不可信**（实测 437 条错位），保留 `date_src` 诊断列。
- 依赖仅 `numpy>=1.26,<2.0` + `pandas>=2.2,<3.0`（项目既有依赖范围内，安装成本为零）；文件名大小写敏感（`.DAT` vs `.dat`），代码不得改动。
- 版权：StockQuant 仓库无 LICENSE（默认保留所有权利，属同一用户内部资产，移植无障碍）；移植文件头注明 `# Ported from StockQuant src/data/qmt/datadir_reader.py (2026-10)`。

## 四、QmtProvider / QmtAdapter 设计

### 4.1 QmtProvider（`app/data/sources/cn/qmt/provider.py`）

```python
class QmtProvider(BaseProvider):
    def __init__(self):
        super().__init__(name="qmt", market="CN")
        self._datadir = get_qmt_datadir()          # Mongo config_params → ENV 回退
        self._reader = QmtDatadirReader(self._datadir) if self._datadir else None
        self._sem = asyncio.Semaphore(settings.QMT_READ_WORKERS)

    async def connect(self) -> bool:               # 平台契约：datadir 模式 = 路径探测 + 抽样自检
    def is_available(self) -> bool:                # reader.available and not stale

    # —— 域映射（未列出的一律不覆写，走基类 NotImplementedError）——
    async def get_stock_list(self, **kw) -> pd.DataFrame
        # reader.stock_codes() → DataFrame[symbol]；name/list_date 由 Adapter 层从既有 basic_info 合并（DD-06/FR-05）
    async def get_trade_calendar(self, exchange, start_date, end_date, **kw) -> pd.DataFrame
        # reader.trading_dates()（上证指数日线派生）；入既有日历机制（V-4 落地时核对）
    async def get_daily_quotes(self, symbol, start_date, end_date, **kw) -> pd.DataFrame
        # to_thread(reader.daily, ts_code(symbol), YYYYMMDD(start), YYYYMMDD(end))
    async def get_daily_quotes_batch(self, trade_date: str, **kw) -> pd.DataFrame
        # 全市场按日：for code in stock_codes() 批读单日窗口，Semaphore(4) 并发
    async def get_intraday_quotes(self, symbol, start_date, end_date, freq="5", **kw) -> pd.DataFrame
        # to_thread(reader.minute, ts_code, f"{freq}m", ...)
    async def get_tick_quotes(self, symbol, start_date, end_date, **kw) -> pd.DataFrame      # 新增，基类无此 hook
        # to_thread(reader.tick, ts_code, trade_date)；按日循环
    async def get_adj_factors(self, symbol, start_date, end_date, **kw) -> pd.DataFrame
        # daily() 的 adj_f_evt/adj_f_cum 两列投影
    async def get_corporate_actions(self, symbol, start_date, end_date, **kw) -> pd.DataFrame
        # reader.dividends(ts_code)
```

要点：`raw_fetch` 闭包与 `FallbackRouter.fetch_source(market, domain, source_name, raw_fetch)` 对接（worker 复用同一入口）；所有方法在 reader 返回 None 时返回空 DataFrame 并 `logger.warning`（DD-02，不抛异常→不误触熔断；路径级故障由 `connect/is_available` 报 `DataSourceUnavailableError` 走熔断）。

### 4.2 field_maps.py（DD-05，映射唯一权威）

```python
# QMT 原始列（StockQuant reader 输出，xtdata 同形）→ 项目标准 Schema 字段
DAILY_QUOTES_MAP = {
    "time":       ("trade_date",  ms_to_trade_date),      # ms → 'YYYY-MM-DD'（V-1 以 TushareCNAdapter 输出为准）
    "open": "open", "high": "high", "low": "low", "close": "close",
    "preClose":   ("pre_close",   div1000_nop),           # reader 已 ÷1000，恒等
    "volume":     ("volume",      lot_to_share),          # 手 × 100 → 股（PRD Schema 单位=股）
    "amount":     ("amount",      passthrough),           # 元，直存
    # 不产出：change/pct_chg 由 adapter 按 pre_close 现算；turnover_rate 置 None（datadir 无流通股本）
}
INTRADAY_QUOTES_MAP = { ... "time": ("datetime", ms_to_dt_str), "freq": const_from_period, ... }
TICK_QUOTES_MAP     = { "time": ("time_ms", passthrough_int), "lastPrice": "last_price",
                        "lastClose": "last_close", "volume": ("volume", unit_pending_O2),
                        "amount": "amount", "transactionNum": "transaction_num", ... }
CORPORATE_ACTIONS_MAP / ADJ_FACTORS_MAP = { ... }         # V-3 对齐既有 Schema 后填充
```

### 4.3 QmtAdapter（`adapter.py`）

按平台契约实现 `adapt_daily_quotes / adapt_intraday_quotes / adapt_basic_info / adapt_adj_factors / adapt_corporate_actions / adapt_tick_quotes`，输入 raw DataFrame → 输出 `List[XxxSchema]`（dataclass，`to_db_doc()` 由 Normalizer 调用）。`market="CN"`、`data_source="qmt"` 固定注入 CommonFields。职责边界与既有 adapter 一致：映射、单位换算（手→股）、`change/pct_chg` 现算、空值处理；不读文件、不写库。

## 五、平台注册（既有源接入清单的逐条落地）

### 5.1 工厂（`app/data/sources/cn/__init__.py`）

```python
elif source_name == "qmt":
    from .qmt.provider import QmtProvider
    return QmtProvider()          # adapter 同构
```

### 5.2 YAML 注册（qmt 全域回退末位，D-2）

```yaml
# capability_matrix.yaml（增量）
CN:
  daily_quotes:    { qmt: partial }     # 缺 turnover_rate；兜底语义足够
  intraday_quotes: { qmt: full }
  tick_quotes:     { qmt: full }        # 新域，唯一源
  basic_info:      { qmt: partial }     # 仅 symbol；名称/上市日靠合并
  corporate_actions: { qmt: full }
  adj_factors:     { qmt: full }
  financial_data:  { qmt: none }        # O-1：datadir 仅 7004~7007，主表不可得
  market_quotes:   { qmt: none }        # D-7 连带：无盘中实时性

# default_priorities.yaml（增量：qmt 追加到每个既有列表末位；tick_quotes 仅 [qmt]）
CN:
  daily_quotes:    [tushare, akshare, baostock, qmt]
  intraday_quotes: [<既有列表…>, qmt]
  tick_quotes:     [qmt]

# source_limits.yaml（增量；本地源无限流语义，冷却针对 datadir 故障）
qmt:
  rate_per_minute: 60                   # 读文件无需网络限流，仅约束批量任务节奏（可调）
  polite_interval_ms: 0
  circuit_initial_cooldown: 300         # datadir 故障多为"未产出/未配置"，短冷却无意义
  circuit_max_cooldown: 1800
  requires_token: false
  retry: { max_retries: 1, backoff_base: 2.0 }   # 本地文件重试意义小，快速失败让位下一域/源
```

### 5.3 常量与配置面

- `app/core/config.py`（第 358 行 BaoStock 块后，照抄既有声明模式，无 alias）：
```python
QMT_ENABLED: bool = Field(default=False, description="启用 QMT 数据源（datadir 本地直读）")
QMT_DATADIR: str = Field(default="", description="国金 QMT datadir 根路径；可被 Web UI 配置覆盖")
QMT_START_DATE: str = Field(default="20100101", description="首次全量起始日")
QMT_READ_WORKERS: int = Field(default=4, description="datadir 解析并发信号量")
QMT_TICK_RETENTION_DAYS: int = Field(default=60, description="tick 保留天数（清理 Job 依据）")
QMT_TICK_DAILY_LIMIT: int = Field(default=50_000_000, description="tick 单日写入行数阈值，超限暂停（估算，T-2 校准）")
QMT_READINESS_DEADLINE: str = Field(default="22:00", description="datadir 就绪等待截止时刻")
QMT_DAILY_SYNC_CRON: str = Field(default="30 15 * * 1-5", description="盘后采集调度（Job 内含就绪轮询）")
QMT_SYNC_ENABLED: bool = Field(default=True, description="QMT 定时采集总开关（QMT_ENABLED 之下的调度开关）")
```
- **Web UI 配置链（D-4）**：`app/models/config.py` 的 `DataSourceType` 枚举加 `QMT = "qmt"`；datadir 路径与保留期存 `DataSourceConfig.config_params`（既有字段，无需改模型）；新增 `app/data/sources/cn/qmt/config.py`：
```python
def get_qmt_datadir() -> str:
    # ① Mongo system_configs → data_source_configs[] 中 type=="qmt" 项的 config_params["datadir"]
    # ② 回退 settings.QMT_DATADIR（经 app.core.env.get_env 顺序）③ 空 = 未配置
def get_qmt_tick_retention_days() -> int: ...   # 同构
```
- `data_source_service.test_data_source_config` 加 `_test_qmt` 分支：实例化 reader → `self_check()` → 返回三层状态（path_missing / self_check_failed(含文件与失败项) / ok+最新分区日期），对应 PRD 7.4 三种错误文案。
- `app/constants/data_sources.py`：`DataSourceCode.QMT = "qmt"` + `DataSourceInfo(name="QMT", display_name="国金 QMT (本地直读)", requires_api_key=False, is_free=True, supported_markets=["a_shares"], features=["日线","分时","tick","分红复权","合约列表"])`。

### 5.4 调度（worker）

复用既有 `BaseMarketDomainSync`（类属性 `market="CN"` + `domain=...`，`sync(provider_method, provider_kwargs_fn)` 内部已串起 fetch_source → `_get_repo` → `upsert_many` → sync_events/checkpoints）：

```python
class QmtDailyQuotesSync(BaseMarketDomainSync):
    market, domain, description = "CN", "daily_quotes", "QMT 盘后日线同步"
# 同构：QmtIntradayQuotesSync / QmtTickQuotesSync / QmtBasicInfoSync / QmtCorporateActionsSync / QmtAdjFactorsSync
```

入口 `app/worker/qmt/jobs.py::run_qmt_sync(force: bool = False)`：就绪轮询（`QmtHealthProbe.probe()` 每 10 分钟，截止 `QMT_READINESS_DEADLINE`，DD-07）→ 按 PRD FR-11 顺序逐域执行（合约 → 日线 → 复权 → 分时 → tick → 指数/分红），每域独立 try（单域失败不阻断后续域）→ 汇总写 `sync_events`。注册沿用 `scheduler_setup.add_resilient_job`（`max_instances=1, coalesce=True`）。`base_market_sync._REPO_TABLE` 补 `tick_quotes` 条目。

### 5.5 健康监控与错误码

```python
class QmtErrorCode(str, Enum):
    PATH_MISSING / SELF_CHECK_FAILED / TICK_TIMEBASE_UNCALIBRATED /
    NOT_READY_TIMEOUT / VALIDATION_REJECTED / WRITE_LIMIT_PAUSED
class QmtHealthProbe:            # health.py
    def probe(self) -> QmtHealthState     # 三层：路径可读 → 抽样四级自检 → 数据新鲜度(对交易日历)
    # 5s 进程内缓存；结果供 connect/is_available/健康路由/test_qmt 三方复用
```
沿用 `SourceHealthMonitor.record_call(market, source, domain, success, latency_ms, error, circuit_state)` 上报；qmt 特有状态（datadir_freshness、最新分区日期）随 error/描述字段入 `source_health`。

## 六、tick_quotes 新标准域（15 步既有清单逐条落地）

| # | 改动 | 内容 |
|---|------|------|
| 1 | `schema/domains/tick_quotes.py` | 见下方草案 |
| 2 | `schema/domains/__init__.py` | 重导出 `TickQuotesSchema` |
| 3 | `app/data/core/domain.py` | `DataDomain.TICK_QUOTES` |
| 4 | `storage/mongo/collections.py` | `_BUSINESS_COLLECTIONS["tick_quotes"] = "stock_tick_quotes"` |
| 5 | `storage/mongo/index_definitions.py` | 唯一键 `[(symbol,1),(trade_date,-1),(time_ms,1)]`（单版本覆盖语义，与 daily_quotes 同规） |
| 6 | `repositories/tick_quotes_repo.py` | `upsert_many(records, market)` 照抄 DailyQuotesRepo 模式（`build_filter` 自动吃唯一键） |
| 7 | `sources/base/adapter.py` | 加 `adapt_tick_quotes(raw) -> List[TickQuotesSchema]` |
| 8 | `normalizer.py` | `DOMAIN_METHOD_MAP["tick_quotes"] = "adapt_tick_quotes"` |
| 9 | `validator.py` | `_REQUIRED_FIELDS["tick_quotes"] = ["symbol","trade_date","time_ms","last_price"]` |
| 10 | YAML 四件 | 见 5.2 + `freshness_rules.yaml` 加 tick_quotes 规则（time_window 型，收盘后窗口） |
| 11 | `core/reader.py` | `repo_map` + `get_data` 分支 |
| 12 | `core/refresh_service.py` | `_SUPPORTED_ON_DEMAND_DOMAINS` + `tick_quotes`；`_INCREMENTAL_DOMAINS["tick_quotes"] = ("trade_date", 5)`（按需刷新仅回看 5 日，控体量） |
| 13 | `worker/base_market_sync.py` | `_REPO_TABLE` 加条目 |
| 14 | 定时任务 | `QmtTickQuotesSync`（M2）+ **TTL 清理 Job**（DD-03：每日删除 `trade_date < today - retention` 分区，`sync_events` 记录清理量） |
| 15 | 测试 | `tests/data/test_schema_domains.py` / `test_index_definitions.py` 一致性断言自动覆盖 |

```python
@dataclass
class TickQuotesSchema(CommonFields):
    trade_date: str                    # 'YYYY-MM-DD'，分区/唯一键
    time_ms: int                       # 当日毫秒时刻（校准后），唯一键之一
    datetime: Optional[str] = None     # 'YYYY-MM-DD HH:MM:SS' 冗余可读列
    last_price: Optional[float] = None
    open: Optional[float] = None       # 当日快照 OHLC（datadir tick 语义）
    high: Optional[float] = None
    low: Optional[float] = None
    last_close: Optional[float] = None
    volume: Optional[float] = None     # 单位待 O-2 抽样验证（手/股）
    amount: Optional[float] = None     # 元
    transaction_num: Optional[int] = None
    market_phase_status: Optional[int] = None   # 集合竞价段=12
    ask_price: Optional[List[float]] = None     # 5 档，Mongo 数组（DD 评审项：扁平 20 列 vs 数组，
    ask_vol:  Optional[List[int]] = None        #   取数组：与 reader 输出同形、文档数减 80%）
    bid_price: Optional[List[float]] = None
    bid_vol:  Optional[List[int]] = None
```

## 七、数据语义对齐（风险最集中处，实现前逐项核对）

| 编号 | 事项 | 处理 |
|------|------|------|
| V-1 | symbol / trade_date 的**字符串格式**（`000001.SZ` vs `000001`；`20261020` vs `2026-10-20`） | 以既有 `TushareCNAdapter` 输出为唯一基准，field_maps 翻译函数照抄其格式化逻辑；`StockUtils.identify_stock_market` 正则 `\d{6}` 表明 CN symbol 为 6 位裸码 |
| V-2 | QMT `volume` 单位手 vs Schema 单位股 | adapter ×100；用 000001 某交易日与 tushare volume 精确比对验证 |
| V-3 | `adj_factors` / `corporate_actions` 域的既有字段集未在本次探查中提取 | 实现第一步：读 `schema/domains/adj_factors.py`、`corporate_actions.py`，回填 field_maps；`dr`（每 10 股股利?) 与项目字段语义对齐需人工核对 |
| V-4 | 交易日历的既有存储机制（域 or `market.py` 工具内嵌） | 实现时核对 `app/data/core/market.py`；原则：不新建日历域，对接既有机制 |
| O-2 | tick volume 单位、`amount` 精度 | M2 首日用国金 datadir 实盘数据抽样 vs tushare/东财逐笔对账 |
| O-5 | 指数日线覆盖：datadir 周期目录下非 6 位纯数字文件（000016/000300 等）是否齐全 | M2 抽样验证 `SH/86400/` 目录；宽基 8 只缺哪些记入缺口，不阻塞 |

## 八、测试方案

沿用项目测试规约：pytest（`asyncio_mode="auto"`）、**禁用 unittest.mock**、DB 用 `tests/data/conftest.py` 的 `inject_sim_db`（SimulatedMongoDB 替换 `_motor_db`）。

| 层 | 文件 | 关键用例（移植 + 新写） |
|----|------|--------------------------|
| reader | `test_qmt_datadir_reader.py` | 移植 StockQuant 二进制 fixture：64B/144B 构造、头哨兵拒读、status 漂移拒读、ts 倒序拒读、半写截断容忍、tick 无竞价行拒读、LevelDB 分红解析、`adjust_frame` 乘式复权 |
| adapter | `test_qmt_adapter.py` | 构造真实原始列 DataFrame → 断言 `volume==raw*100`、`trade_date` 格式、`data_source=="qmt"`、pct_chg 现算 |
| provider | `test_qmt_provider.py` | tmp_path 伪造 datadir 目录树；None→空帧契约；Semaphore 并发上限；`is_available` 三态 |
| 路由 | `test_fallback_router.py`（增补） | qmt 末位兜底选中；`QMT_ENABLED=false` 不入候选链；Validator 拒写路径 |
| 新域 | `test_schema_domains.py`/`test_index_definitions.py`（增补） | tick_quotes 唯一键/Repo/collection 一致性 |
| 验收 | 手工 | 回退演练（熔断 tushare）；与 tushare 逐域抽样对账（V-2/O-2） |

## 九、里程碑与工作量估算（人日，含联调不含 code review 排期等待）

**M1（P0：直读层 + 日线 + 合约 + 回退链 + 配置 + 健康）≈ 13 人日**

| 任务 | 估时 |
|------|------|
| datadir_reader 移植 + 解耦（去 datadir_root/Config、self_check 聚合） | 2 |
| 二进制 fixture 测试移植并通过 | 2 |
| field_maps + QmtAdapter（daily/basic_info，V-1~V-3 核对） | 2 |
| QmtProvider（connect/is_available/daily/stock_list/calendar + to_thread/Semaphore） | 1.5 |
| 工厂分支 + 3 个 YAML + 常量注册 | 0.5 |
| Settings + config.py 解析链 + DataSourceType/_test_qmt（Web UI 后端） | 1.5 |
| health.py 三层探针 + SourceHealthMonitor 对接 | 1 |
| worker QmtDailyQuotesSync + run_qmt_sync 骨架（就绪轮询） | 1 |
| provider/adapter/router 测试 + 回退演练 + 对账联调 | 1.5 |

**M2（P1：分时 + tick + 分红复权 + 调度完善 + 缺口）≈ 11.5 人日**

| 任务 | 估时 |
|------|------|
| tick_quotes 新域 15 步 + freshness_rules | 2 |
| adapter 分时/tick + field_maps 补全（V-3 回填、O-2 验证） | 1.5 |
| reader minute/tick 时间基校准验证（国金实盘数据） | 1.5 |
| 调度完善：就绪截止/逐域隔离/TTL 清理 Job/超限暂停 | 1.5 |
| 缺口管理（FR-12：detect→登记→qmt 优先补→tushare 兜底→3 轮防抖） | 1.5 |
| 指数/分红/复权域接入 + 双源交叉校验告警 | 1 |
| 测试补全 + T-2 实测校准（产出时刻、tick 体积、阈值定版） | 2.5 |

**M3（另立项）**：分离部署代理、板块 Schema 评审、盘中准实时性评估。

## 十、开放项与 PRD 修订建议

| 编号 | 内容 | 动作 |
|------|------|------|
| O-1 | **PRD FR-07 收窄**：`financial_data` 域 qmt 能力 `none`（datadir 仅 7004~7007；主表曾依赖 RPC 下载） | 请确认后修订 PRD 4.1/FR-07/能力矩阵；「扩展 reader 解析其余 table_id」记后续版本池 |
| O-2 | tick volume 单位（手/股）与 amount 精度 | M2 首日抽样对账定版 field_maps |
| O-3 | tick 5 档存 Mongo 数组 vs 扁平 20 列 | 方案取数组（本文第六节）；评审可推翻 |
| V-1~V-4 | 见第七节 | 实现第一步逐项核对，核对结论回填 field_maps.py 注释 |
| T-2 | 国金下载任务产出时刻 + 单日 tick 体积 | M2 开发前实测，校准 `QMT_TICK_DAILY_LIMIT`/时效指标 |

> 合规声明：本方案为产品设计参考，具体实施请结合公司合规与法务要求确认。
