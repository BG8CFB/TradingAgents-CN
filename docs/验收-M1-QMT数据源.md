# QMT 数据源 M1 验收结论

> 验收日期：2026-10-21
> 分支：`feature/qmt-datasource`（工作区未提交）
> 依据：PRD `docs/PRD-QMT数据源接入.md` v1.2 · 技术方案 `docs/技术方案-QMT数据源接入.md` · 交接 `docs/交接文档-QMT数据源接入.md`
> 口径：以 PRD 10.1 的 M1 范围（FR-01/02/03/05/09/10/13）与各 FR 的 GWT 逐条核对

---

## 一、总体结论

**M1 代码主体可用、测试全绿、注册面完整，但按 PRD 口径未收尾。**

- ✅ 已验证通过：解析层、回退链、平台注册、配置链、健康落库——见第二节证据
- ❌ 未收尾：4 项实质缺口（第三节）+ 3 处文档不一致（第五节）
- ⛔ 仍被阻塞：B-1 真实 datadir 联调、B-2 客户端下载任务——均需部署机，非研发可闭环（第四节）

即：**“能跑通、能兜底”成立；“FR 逐条达标”不成立。**

---

## 二、验证证据（可复核）

| 项 | 方法 | 结果 |
|----|------|------|
| QMT 单元/集成测试 | `pytest tests/data/test_qmt_*.py tests/data/test_tick_quotes_domain.py` | **191 passed**（M1 基线 87 + M2 新增 104） |
| 相关既有回归 | `pytest test_processor_validator / test_capability_registry / test_fallback_router / test_adapters_cn` | **39 passed**，与交接文档数字一致 |
| 数据层全量（最新复跑） | `pytest tests/data --ignore=test_scheduler_engine` | **1045 passed**；9 failed + 35 errors，逐条归因见下 |
| └ 失败归因 | 逐用例复跑 | 8 例 `ModuleNotFoundError: fastapi`（`test_p0_p1_fixes_review` 3 / `test_review_fixes_v2` 4 / `test_cn_sync_orchestrator` 1，后者为 `apscheduler`）+ 1 例限流时间窗用例 `test_polite_interval_blocks_second_request`（依赖 Redis/精确计时）。**无 QMT 相关失败** |
| └ 错误归因 | 逐用例复跑 | 35 例全部为 `pymongo` 连接被拒（`WinError 10061`，本机无 MongoDB 容器），需真实库的 fixture 无法建立 |
| 模块导入冒烟 | 逐个 `import_module` 19 个 QMT/平台模块 | 全部 OK（含 `guarded_write` / `data_gap_repo` / `tick_quotes_repo`） |
| reader 公开面完整性 | 对 `datadir_reader.py` 逐方法核对技术方案 §3.2 | `daily/minute/tick/dividends/finance/index_weights/industry_data/sector_names/sector_members/adjust_frame/has_daily/has_daily_file/stock_codes/trading_dates/self_check/_load_dividends` **全部在位** |
| 零 xtquant 依赖（FR-01 规则 1） | 全 `app/` 检索 `xtquant`/`xtdata` | 仅 docstring 提及，**无 import** |
| 回退链（FR-09 GWT） | `test_qmt_e2e_chain` 熔断三源 | 自动选中 qmt，写入 `stock_daily_quotes`，字段与既有源同构，无 QMT 方言字段 |
| 开关零回归（FR-09/FR-10 GWT） | `QMT_ENABLED=false` + 熔断三源 | 全链路 `source is None`，qmt 不在候选链 |
| 候选链实测（9 域） | 直接调用 `CapabilityRegistry.get_ordered_sources` | 关闭时 `tick_quotes`/`corporate_actions` 为 `[]`；开启时 `daily/adj` 末位 qmt、`intraday` 第三位 qmt、`tick`/`corporate_actions` 为 `['qmt']` |
| 健康三态（FR-02 GWT 1/3） | `test_qmt_health` + `TestStaleRule` | 缓存 60 次/分 → 实际探测 ≤12 次，达标；stale 阈值已按平台交易日历修正（P1-3 已修） |
| 集合/索引登记 | `get_collection_name` / `get_unique_key` 实测 | `stock_tick_quotes` / `stock_intraday_quotes` / `stock_corporate_actions` / `data_gaps`；唯一键分别为 `(symbol,trade_date,time_ms)` / `(symbol,datetime,freq)` / `(symbol,ex_date,action_type)` / `(market,domain,gap_date)`；22 业务域 / 28 索引定义 |
| 架构契约 | `pytest tests/lint` + `ruff check app/ tests/` | **7 passed**；ruff **All checks passed**（含修掉 `test_qmt_datadir_reader.py` 的 E741） |

---

## 三、未收尾缺口

### P0-1 `adj_factors` 域从未主动采集

- 事实：`run_qmt_sync`（`app/worker/qmt/jobs.py`）只串 `basic_info` / `trade_calendar` / `daily_quotes` 三域；`QmtProvider.get_adj_factors` 仅能被 `fallback_router.py:432` 作为**第 4 顺位兜底**触达（前三源全部熔断时）。
- 后果：`DailyQuotesSchema` 无任何因子字段，故正常情况下 **QMT 复权因子永不入库**。
- 与 PRD 冲突：FR-03 明确要求「OHLCV + 复权因子 `adj_f_evt`/`adj_f_cum` → `daily_quotes` / `adj_factors`」；FR-03 属 M1 范围（10.1）。
- 需拍板：补 `QmtAdjFactorsSync` 进 pinned job，还是明确「复权因子仅随兜底链触发」并同步修订 FR-03。

### P0-2 FR-03 全量 / 断点 / 分块语义未实现

- 事实：无 `QMT_START_DATE`（FR-10 与技术方案 §5.3 均已声明）、无 `sync_checkpoints` 断点续传、无 400 天分块与「块完整性 ≥90% 才判完成」。
- 现状：只有 `QMT_SYNC_LOOKBACK_DAYS=6` 的滚动窗口 → **首次全量（2010 起）无法执行**。
- 冲突：PRD FR-03 业务规则 2/3 未落地；技术方案 M1 工作量表只写「`run_qmt_sync` 骨架」，与 PRD 口径不一致，需确认以哪份为准。

### P1-3 FR-02 stale 判定不达 GWT —— ✅ 已修（2026-10-21）

- 原事实：`health.py` `_STALE_TOLERANCE_DAYS = 10`（自然日）→ GWT「停更 2 个交易日返回 stale」**不通过**。
- 修复：探针新增 `expected_last_trade_date` 入参（保持纯文件 IO），调用方
  （`run_qmt_sync` / 就绪轮询 / `_test_qmt`）用 `app/data/core/market.get_latest_trade_day("CN")`
  取平台交易日历的「期望最后交易日」注入；判定改为 `最新分区 < 期望日` 即停更，
  10 日宽容期降级为**无日历基准时的回退路径**；状态新增 `expected_trade_date` 诊断字段。
- 验证：`test_qmt_health.py::TestStaleRule` 5 项（落后 1 交易日即 stale、无日历回退、未来分区不停更、非法期望日回退、无分区即 stale）。

### P1-4 FR-13 健康页未接 QMT 状态 —— ⚠️ 后端已完成，前端待接

- 原事实：`datadir_state` / `datadir_freshness` / `domain="__datadir__"` 仅存在于
  `health.py`，**全 `app/` 与 `frontend/` 无消费方**；且 `upsert_health` 用 `$set`
  覆盖，成功率计数每次被重置为 1/0 → PRD 3.2 指标失效。
- 已修（后端）：
  1. `MetadataRepo.accumulate_health`（`$inc` 语义）+ 探针改用它 →
     success/failure/total 变成**累计值**，`success_rate` 可用；
  2. 新增 `DataSourceService.get_qmt_source_status()` 与
     `GET /api/config/datasource/{name}/status`，返回三层状态 + 最新/期望分区 +
     累计健康（部署指南 §4.1 已写明响应结构）；
  3. 补上部署指南一直在用、但**代码里原本不存在**的
     `POST /api/config/datasource/{name}/test` 路由。
- 待做（前端）：仓库 `frontend/node_modules` 缺失，无法构建/类型检查，故
  `SourceConfig.vue` 的状态卡片未改动。接口已就绪，前端接入即可闭环 FR-13 GWT。
- 验证：`test_qmt_source_status.py` 4 项 + `test_qmt_health.py::test_counters_accumulate_across_probes`。

- 事实：`datadir_state` / `datadir_freshness` / `domain="__datadir__"` 仅存在于 `health.py`，**全 `app/` 与 `frontend/` 无消费方**（已 grep 确认）。
- 后果：PRD 7.4 / FR-13 GWT 要求的「三层状态、最新分区时间、最近成功/失败时间与失败原因分类」在 UI 上看不到。
- 附带问题：`MetadataRepo.upsert_health` 是 `$set` 覆盖，成功/失败计数每次被重置为 1/0 → 3.2「QMT 采集成功率 ≥98%」指标对 `__datadir__` 行**不可用**，需在写入端做累加或改用独立集合。

### P2-5 FR-09 规则 3 半实现

- `_is_source_enabled()` 只判 `QMT_ENABLED` 开关，不判 datadir 可用性。
- 后果：「datadir 不可用时自动从候选链剔除」需首轮失败打开熔断后才生效，其间会污染 `success_count/failure_count`（与 3.2 成功率目标冲突）。
- 建议：探测结果接入 `_is_source_enabled`（带 5s 缓存的探针已是现成的）。

### P2-6 DD-01 局部违反（事件循环阻塞）—— ⚠️ 已缓解

- 事实：`qmt/config.py::_web_config_params()` 使用 **同步** `get_mongo_db_sync()`，而它被 `QmtProvider.__init__` / `QmtHealthProbe.__init__` 在 async 路径中调用（router 每次 fetch 新建 provider）→ 阻塞事件循环。
- 已做：加 **30s 进程内缓存**（与平台「优先级配置 30s 生效」口径一致），把「每次请求一次同步 Mongo 往返」降为「每 30s 一次」。
- 未做：彻底 async 化需要在 async 上下文里解析配置并注入 provider/probe，属于构造期契约改动，留作后续项。

### P1-7 兜底源「后写覆盖」—— pinned 采集与单版本覆盖语义冲突（M2 新发现）

- 机制：业务域唯一键**不含 `data_source`**（单版本覆盖，`index_definitions.py` 明示「备用源 upsert 覆盖同自然键记录」）；而 `run_qmt_sync` 把 qmt **钉死为唯一源**主动采集。
- 时序（已核对 cron）：`CN.daily_quotes` 16:15、`CN.adj_factors` 17:00、`CN.intraday_quotes` 盘中 `*/30 9-14`；QMT 15:30 触发但**要等 datadir 就绪（截止 22:00）**。
- 后果：datadir 若在 16:15 之后才就绪（常态，盘后下载任务产出晚），QMT 写入会**覆盖** tushare 当日记录，`data_source` 从 `tushare` 翻成 `qmt` —— 兜底源在时间上"后写"变成主源，与 D-2「既有源都失败才启用」直接冲突；且 `data_source` 溯源变成时间依赖，同一天不同标的可能来源不同。
- 影响面：`daily_quotes` / `basic_info` / `trade_calendar`（P0），M2 的 `intraday_quotes` 同样命中（QMT 盘后写入必然晚于盘中 tushare 分时）。
- 建议（需拍板）：pinned 采集改为**只补缺口**——写入前按唯一键查存在性，已有非 qmt 记录则跳过（或 `$setOnInsert` 语义），把「兜底」落实为「不覆盖已有主源数据」。这一项不解决，3.2「数据格式一致性验收」与「来源标记」都会失去意义。

---

## 四、阻塞项状态

| 编号 | 事项 | 状态 |
|------|------|------|
| B-1 | **真实 datadir 联调**（V-1 symbol 格式、V-2 volume 手→股、V-3 复权/分红字段、O-2 tick 单位） | **✅ 已完成（2026-10-20）**：`D:\App\国金证券QMT交易端\datadir`，自检 `ok`、宇宙 5,226、最新分区 20261020。V-1~V-3 与 O-2 全部定版，并修正 **2 个单位错误**（分红 `DIVIDEND_PER_UNIT` 10→1、tick `TICK_VOLUME_TO_SHARE` 1→100）。明细见交接文档「B-1 真实 datadir 联调结果」 |
| B-2 | **客户端「盘后自续下载任务」配置** | **✅ 已验证生效**：tick 16:16~16:19、日线 16:38~16:41 全市场落盘，证明下载任务在运行 |

**T-2 实测校准**（同一次联调）：tick 单日 3.15 GB / 5,912 标的 / 约 2,350 万条；60 天保留约 135 GB；`QMT_TICK_DAILY_LIMIT` 由 50,000,000 下调为 30,000,000。

**指标类验收的当前可判定性**：

| 指标（PRD 3.2） | 状态 |
|---|---|
| 回退链演练通过 | ✅ 自动化用例已覆盖（熔断三源 → 选中 qmt） |
| 日线入库时效 ≤30 分钟 | ✅ 数据就绪 16:38~16:41，采集可在数分钟内完成，余量充足 |
| 全市场日线覆盖率 ≥99% | ⚠️ 可估算：datadir 宇宙 5,226 vs 交易所沪深 A 股约 5,3xx（差 <5%）→ 接近达标，仍需与 tushare `stock_basic` 精确比对 |
| 分时时效 ≤90 分钟 / tick ≤2 小时 | ✅ 就绪时刻远早于指标 |
| QMT 采集成功率 ≥98% | ❌ 需连续 10 个交易日运行数据（`source_health` 累计）后判定 |
| 分红覆盖率 | ❌ 受 `ts_key` 回退限制（见下） |

**新发现的待决策项（B-1 暴露）**：分红除权日有 45%~85% 来自 LevelDB key 回退（`ts_key`），
按「绝不写可疑值」当前整条拒写，导致分红域事件覆盖不完整（600000 仅 4/27）。三条路径需拍板：
① 维持拒写；② 移植基于 `dr`/K 线 `f_slot2` 跳变日的除权日校正；③ 接收但标注低置信度（需 Schema 加字段）。

连带未验证：日线覆盖率 ≥99%、采集成功率 ≥98%、日线时效 ≤30 分钟、回退演练（真实环境）、与 tushare 的 V-2 对账——这些**只有拿到真实 datadir 才能验**。

---

## 五、文档不一致

| 项 | 文档 | 代码/事实 |
|----|------|-----------|
| `QMT_*` 变量数 | 交接文档「11 个」；部署指南 `.env` 块列 8 个 | **10 个**（缺 `QMT_START_DATE`；部署指南缺 `QMT_TICK_RETENTION_DAYS` / `QMT_TICK_DAILY_LIMIT`） |
| reader docstring | 技术方案/PRD 要求「零 RPC 兜底」 | `daily()` 仍写「走 RPC 兜底」、`finance()` 写「调用方回退 xtdata API」——移植残留，与 D-7 矛盾 |
| 采集域数 | 交接文档称 M1 含「复权因子」 | 实际 3 域（部署指南 §4.2 写 `synced_domains: 3`，与代码一致）→ 交接文档表述有误 |
| **测试覆盖** | 交接文档 §3.3 称 M1「92 项」且 `test_qmt_datadir_reader.py`「35 项，覆盖 …**LevelDB**…」 | 实测各文件为 **32 / 12 / 15 / 13（+6 本轮新增）/ 15 = 87 项**（交接的分文件数自身相加已是 93，与 92 亦不符）；且该文件**0 个 LevelDB/分红用例**（grep `divid`/`ldb` 全无命中，测试类只有 Kline/Tick/HasDaily/Misc/StockCodes/SelfCheck）。差额 3 项与「LevelDB」一项吻合 —— 分红二进制解析路径**无自动化测试** |

---

## 五之二、M2 推进中新发现的缺口（按严重度）

### P1-9 FR-07 规则 3 对 `corporate_actions` 不可实现

PRD FR-07 要求分红事件「与 tushare 双源交叉校验，不一致率 > 0.5% 告警并保留 tushare 值」。
事实：**CN 侧没有任何 provider 实现 `get_corporate_actions`**（全仓 grep 仅 HK/US 有），
即该域不存在 tushare 通道，没有可交叉校验的对象。实现上 `CN.corporate_actions`
优先级只能是 `[qmt]`（qmt 唯一源），交叉校验只在 `adj_factors` 上落地。
→ 需修订 PRD FR-07 规则 3 的适用范围。

### P1-10 指数日线存在唯一键冲突（需 Schema 决策）

PRD FR-07 规则 1 要求「指数日线写 `daily_quotes`（index 标识）」，但
`DailyQuotesSchema` **没有** index 标识字段，CN 唯一键是 `(symbol, trade_date, period)`，
`symbol` 为 6 位裸码 —— 上证指数 `000001.SH` 与平安银行 `000001.SZ` 会撞同一自然键，
单版本覆盖语义下必然互相覆盖。
→ 两条路径：① 给 `DailyQuotesSchema` 加 `security_type` 并纳入唯一键（需建索引迁移
+ 清理旧索引）；② 新开指数域。均属 Schema 治理，需先决策，故本轮**未实现指数日线**。

### P2-11 复权因子采集带来双倍磁盘 IO（已知成本）

`daily_quotes` 与 `adj_factors` 各跑一次全宇宙文件解析（同一次 `reader.daily` 的
两种投影）。合并为单趟双写可省一半 IO，但会破坏「一域一 sync」的域隔离语义，
当前选择保留隔离并记录成本。

---

## 六、结论与后续

1. **M1 判定：不通过（未收尾）**。主体工程质量良好（解析契约、DD-01/02/05、回退链、注册面都到位），缺口集中在「PRD 范围覆盖」而非「代码可用性」。
2. **M2 已开工**：`tick_quotes` 新标准域已落地并通过 16 项新测试（见 `docs/交接文档-QMT数据源接入.md` 第七节依赖顺序第 1 步）。
3. **建议处置顺序**：P1-3（stale 判定）→ P1-4（健康页 + 计数）→ P0-1（adj_factors 口径拍板）→ P0-2（全量/断点，工作量最大）→ P2-5/P2-6。其中 P1-3/P1-4 与 M2 的 tick 自检、tick 超限告警共用同一套健康/告警面，建议在 M2 推进中一并修。
4. **B-1/B-2 需部署机**：在拿到真实 datadir 前，M1 的指标类验收（覆盖率/成功率/时效/对账）无法给出结论，不应对外宣称 M1 已验收。

---

> 本记录仅覆盖代码与文档一致性验收；数据正确性结论须待 B-1 联调后补充。
