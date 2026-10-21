# QMT 数据源接入 · 交接文档

> 交接日期：2026-10-20
> 分支：`feature/qmt-datasource`（基于 main `ce9f45f7`，**尚未提交**）
> 关联文档：PRD `docs/PRD-QMT数据源接入.md` v1.2 · 技术方案 `docs/技术方案-QMT数据源接入.md` · 部署指南 `docs/deploy/QMT数据源部署指南.md`

---

## 一、一句话现状

M1（日线/合约/交易日历/复权因子）已完成并通过 92 项测试验证，QMT 作为**兜底源**（回退链末位）接入现有数据平台；**M2（分时/tick/缺口补采）尚未开始**，且真实 datadir 联调尚未进行。

---

## 二、已确认的产品口径（不可漂移）

| 编号 | 口径 | 内容 |
|------|------|------|
| D-1 | 部署形态 | 同机：TradingAgents-CN 与国金 QMT 客户端同一台 Windows 机器 |
| D-2 | 源定位 | **兜底源**：所有域回退链末位，既有四源都失败才启用 |
| D-3 | 客户端基线 | 国金证券 QMT 交易端（与参考实现 StockQuant 同基线） |
| D-4 | 配置方式 | datadir 路径支持 Web UI 配置：Mongo `system_configs` 优先、ENV 回退 |
| D-5 | 数据格式 | 必须与项目既有标准 Schema 完全一致；禁止 Parquet/文件湖/QMT 专用表 |
| D-6 | 采集范围 | 新增 tick 与分时（M2）：分时→`intraday_quotes`，tick→新域 `tick_quotes` |
| D-7 | 连接模式 | **仅 datadir 本地直读**，零 `xtquant` 依赖，无 RPC 通道 |

两个由 D-7 派生的边界（已写入 PRD）：
- QMT **不参与**实时快照（datadir 是盘后产物，无盘中实时性），`market_quotes` 能力为 `none`
- QMT **不提供**财务主表（datadir 只有 7004~7007 四张附表），`financial_data` 能力为 `none` ← **PRD 正文尚未修订（见第六节 O-1）**

---

## 三、代码交付清单

### 3.1 新增文件（约 2,400 行实现 + 1,276 行测试）

| 文件 | 行数 | 职责 |
|------|------|------|
| `app/data/sources/cn/qmt/datadir_reader.py` | 1183 | **移植自 StockQuant**：64B K线/144B tick/LevelDB 分红纯 Python 解析 + 四级自检；仅改 3 处（删 `datadir_root()`、加 `self_check()`、加移植说明） |
| `app/data/sources/cn/qmt/provider.py` | 218 | `QmtProvider(BaseProvider)`：async 契约 + `to_thread` + 信号量；支持单票/单日/区间批量日线 |
| `app/data/sources/cn/qmt/adapter.py` | 179 | `QmtAdapter`：手→股、pct_chg 现算、`to_db_doc` 过滤 None |
| `app/data/sources/cn/qmt/health.py` | 228 | 三层探针 + 错误码枚举 + 5s 缓存 + **Mongo 健康落库/告警上报** |
| `app/data/sources/cn/qmt/field_maps.py` | 81 | 字段映射唯一权威（DD-05） |
| `app/data/sources/cn/qmt/config.py` | 72 | Mongo→ENV 配置解析链（仿 `ds_key_utils`） |
| `app/worker/qmt/jobs.py` | 161 | 盘后采集：就绪轮询 → 三域顺序 + 健康闭环 |

### 3.2 修改文件（13 个）

| 文件 | 改动 |
|------|------|
| `app/data/sources/cn/__init__.py` | 工厂 +2 个 `elif` 分支 |
| `app/data/config/capability_matrix.yaml` | qmt × 6 域能力（partial/full/none） |
| `app/data/config/default_priorities.yaml` | qmt 追加到 4 个域末位 |
| `app/data/config/source_limits.yaml` | qmt 限流/熔断（冷却 300→1800s） |
| `app/data/core/registry/capability.py` | `_is_source_enabled()` 运行时开关过滤 |
| `app/data/processor/validator.py` | `basic_info` 必填从 `["symbol","name"]` 收窄为 `["symbol"]` |
| `app/core/config.py` | `QMT_*` 11 个 Settings 字段 |
| `app/constants/data_sources.py` | `DataSourceCode.QMT` + 注册信息 |
| `app/models/config.py` | `DataSourceType.QMT` |
| `app/services/config/data_source_service.py` | `_test_qmt` 连通性测试分支 |
| `app/worker/scheduler_setup.py` | 盘后采集 job 注册（`QMT_ENABLED` 门禁） |
| `frontend/src/views/Settings/components/DataSourceConfigDialog.vue` | QMT 类型选项、datadir 提示、隐藏无关字段、自动预填 `datadir` 参数键 |
| `.env.example` | QMT 配置块（11 个变量 + 说明） |

### 3.3 测试（92 项，全部通过）

| 文件 | 数量 | 覆盖 |
|------|------|------|
| `test_qmt_datadir_reader.py` | 35 | 移植的二进制 fixture：头哨兵/status 漂移/ts 单调/半写截断/tick 竞价校准/LevelDB/自检 |
| `test_qmt_adapter.py` | 12 | 单位换算、日期格式、pct_chg、None 过滤 |
| `test_qmt_provider.py` | 16 | 工厂、批量、开关短路、worker 参数契约回归 |
| `test_qmt_health.py` | 13 | 五种状态、缓存、健康落库、告警事件 |
| `test_qmt_registration.py` | 17 | 能力矩阵/优先级/常量/Validator 兼容 |
| `test_qmt_e2e_chain.py` | 5 | 回退演练、入库格式一致性、合并语义、worker 健康闭环 |

---

## 四、验证结论（可直接引用的证据）

```
QMT 测试：           92 passed
既有相关回归：       39 passed（validator / capability / fallback_router / adapters_cn）
静态检查：           ruff F,E9 All checks passed
下拉链路实测：       daily_quotes 候选链 = [tushare, akshare, baostock, qmt]（qmt 末位）
financial_data 链：  [tushare, akshare]（qmt 被 none 过滤）
回退演练：           前三源熔断后自动选中 qmt，返回 1 条记录，字段与既有源同构
入库验证：           6 条写入 stock_daily_quotes，二次运行仍 6 条（幂等）
合并验证：           qmt 的 basic_info 不覆盖既有源 name/industry，补上 exchange
开关验证：           QMT_ENABLED=false 时全链路选不到 qmt
```

> 5 个需要真实 MongoDB 容器的既有用例在本机无法运行（环境限制，与本次改动无关）。

---

## 五、关键实现决策（接手必读）

1. **DD-01 线程池 + 信号量**：Provider 的 async 方法内用 `asyncio.to_thread` 包裹文件 IO，`asyncio.Semaphore(QMT_READ_WORKERS=4)` 限并发。不要改成同步调用——会阻塞事件循环拖垮 API。
2. **DD-02 失败契约**：reader 所有读取方法失败返回 `None`（移植代码零改动）。Provider 层把 None 翻成空 DataFrame（→ router 记 failed 降级），把 **路径级**故障翻成 `DataSourceUnavailableError`（→ 熔断）。
3. **DD-03 tick 保留期**用每日清理 Job，**不用 Mongo TTL 索引**（时间字段是字符串，且 TTL 删除不可审计）。
4. **DD-04 复权**只用 datadir 原生 `adj_f_cum`，不引入 StockQuant 的「表 A」parquet 体系。
5. **DD-05 映射单点**：所有字段映射只在 `field_maps.py` / adapter 内，不要在 provider 里做转换。
6. **区间批量**：worker 用 `get_daily_quotes_batch_range()` 一次性读窗口，**不要**改回按日循环（同一文件会被重复解析 N 次，磁盘放大 N 倍）。
7. **`_QmtPinnedSync.get_sources()` 返回 `["qmt"]`**：采集任务必须钉死单源，否则 tushare 先行、qmt 永远轮不到。
8. **health 落库用 `domain="__datadir__"`**：datadir 是源级状态，不能写进各域，否则污染域成功率统计。
9. **`BaseMarketDomainSync.sync()` 第二参数是 callable**，必须传 `lambda: {...}`（曾误传 dict 导致 TypeError，已有回归测试）。

---

## 六、必须完成或决策的事项

### 阻塞项（不做则功能不可用）

| 编号 | 事项 | 说明 |
|------|------|------|
| B-1 | **真实 datadir 联调** | 全部测试基于合成 fixture。需用国金客户端真实数据跑一次 `run_qmt_sync(force=True)`，核对 V-1（symbol 格式）、V-2（volume 手→股）、V-3（复权因子字段对齐） |
| B-2 | **客户端「盘后自续下载任务」配置** | datadir 不产出则整个源不可用，步骤见部署指南第二节 |

### 待决策

| 编号 | 事项 | 建议 |
|------|------|------|
| O-1 | PRD 正文 FR-07 仍写「财务数据写 `financial_data`」，但实现已按 `none`（datadir 只有 7004~7007） | 修订 PRD FR-07/4.1：明确财务主表不采集，扩展解析记后续版本池 |
| O-2 | tick `volume` 单位（手/股）与 `amount` 精度 | M2 首日用真实 tick 与 tushare 逐笔对账后定版 |
| O-3 | tick 5 档行情存 Mongo 数组 vs 扁平 20 列 | 技术方案取数组（文档体积小 80%） |
| O-4 | 是否提交当前改动 | 13 修改 + 8 新增 + 4 文档，测试全绿 |

### M1 未做（明确不在 M1 范围）

- tick/分时采集（M2）
- 缺口检测与自动补采（FR-12，M2）
- 指数日线、分红/公司行为采集（FR-07，M2；注意 CN 能力矩阵当前**没有** `corporate_actions` 键，需先补）
- tick 保留期清理 Job 与写入量阈值（M2）

---

## 七、M2 开工清单（按依赖顺序）

1. **`tick_quotes` 新标准域**（技术方案第六节 15 步）：schema → domain 枚举 → collections → index_definitions → Repo → Normalizer/Validator → reader → refresh_service → worker → freshness_rules → 测试
2. **分时采集**：`get_intraday_quotes` + `adapt_intraday_quotes`（复用 reader.minute，映射到既有 `intraday_quotes`）
3. **tick 采集**：`get_tick_quotes` + `adapt_tick_quotes`（注意 reader 无竞价行时拒读）
4. **tick 保护**：TTL 清理 Job（DD-03）+ 日写入量阈值暂停
5. **缺口管理**（FR-12）：缺口检测 → 登记 → qmt 优先补 → tushare 兜底 → 3 轮防抖
6. **指数/分红**：`get_corporate_actions` + 指数日线；先在 capability_matrix 补 `CN.corporate_actions`
7. **T-2 实测**：下载任务产出时刻、单日 tick 体积 → 校准 `QMT_TICK_DAILY_LIMIT` 与时效指标

---

## 八、本地开发环境说明

项目测试需要 Python 依赖，本机 anaconda 缺 `pytest-asyncio` 等。已在项目根创建 `.venv`（已在 `.gitignore`）：

```bash
.venv/Scripts/python -m pytest tests/data/test_qmt_*.py -q
```

已安装：numpy / pandas / pyyaml / pydantic-settings / motor / redis / pytest / pytest-asyncio / httpx / requests / ruff。
**注意**：`DEBUG=true` 必须设置（`tests/conftest.py` 会自动设），否则 `app.core.config` 的生产环境保护会抛错。

---

## 九、合规提醒

QMT 行情授权通常仅限签约用户本人研究使用。当前实现限定为同机、本地、自用场景，**不提供任何数据转发/导出能力**。若未来对外服务化，须先取得行情转发授权并过法务。

---

## 十、M2 进展（2026-10-21 更新）

> M1 验收结论见 `docs/验收-M1-QMT数据源.md`（判定：主体可用、**未收尾**，含 4 项实质缺口）。

### 已完成（第七节清单第 1、2、3、4 步）

| 步骤 | 交付 | 验证 |
|------|------|------|
| 1. `tick_quotes` 新标准域 | `schema/domains/tick_quotes.py`、`repositories/tick_quotes_repo.py`；域枚举/集合 `stock_tick_quotes`/唯一索引 `(symbol, trade_date, time_ms)` + `trade_date` 清理索引；Normalizer/Validator/BaseAdapter/BaseProvider/FallbackRouter 接入；4 个 YAML + 前端标签 | `test_tick_quotes_domain.py` 20 项 |
| 2. 分时采集 | `QmtProvider.get_intraday_quotes` + `get_intraday_quotes_batch_range`、`QmtAdapter.adapt_intraday_quotes`、`field_maps` freq 词表（`1min`/`5min` ↔ `1m`/`5m`）；`QmtIntradayQuotesSync` 接入 pinned job（按日分块，`QMT_INTRADAY_FREQS`/`QMT_INTRADAY_LOOKBACK_DAYS`） | `test_qmt_intraday.py` 17 项 |
| 3. tick 采集 | `QmtProvider.get_tick_quotes` + `read_tick_one`、`QmtAdapter.adapt_tick_quotes`（列级取值，不走 iterrows）、`field_maps.ms_to_time_of_day_ms` + `TICK_VOLUME_TO_SHARE`（O-2 占位）；**`app/worker/qmt/tick_collect.py`** 逐票流式采集 + 覆盖率自检 + 写入量阈值暂停 + 双事件审计 | `test_qmt_tick.py` 13 项 |
| 4. tick 保护 | `app/worker/qmt/tick_cleanup.py`：保留期清理 Job + `sync_events` 审计（DD-03），每日 03:30 注册 | `test_tick_quotes_domain.py` 内 4 项 |
| 5. 缺口管理（FR-12） | `repositories/data_gap_repo.py` + `data_gaps` 元数据集合；`app/worker/qmt/gap_manager.py`：以**库内交易日历**为基准逐日查分区 → 登记 → qmt 优先补 → 日线既有源兜底 → 轮次上限转 `abandoned`；每日 23:10 注册 | `test_qmt_gap_manager.py` 14 项 |
| 6. 分红/复权（FR-07） | `get_corporate_actions(_batch_range)`、`adapt_corporate_actions`（派息/送转/配股拆行 + 每10股→每股）、`QmtCorporateActionsSync`；`get_adj_factors_batch_range` + `QmtAdjFactorsSync`；`app/worker/qmt/guarded_write.py` 实现 FR-07 规则 3「不一致保留既有源值 + 0.5% 告警」；`BaseMarketDomainSync._persist` 新增可覆写入库钩子 | `test_qmt_corporate_actions.py` 21 项 |

**第 6 步的三个必须知悉项**：
1. **`CN.corporate_actions` 在既有源里没有通道**（无任何 CN provider 实现
   `get_corporate_actions`），故该域 **qmt 是唯一源**、优先级 `[qmt]`，不存在回退链。
   连带后果：PRD FR-07 规则 3 的「与 tushare 双源交叉校验」对分红域**无法实现**
   （无对比对象），该规则实际只在 `adj_factors` 上落地。
2. **指数日线未做**：`DailyQuotesSchema` 无 `is_index` 标识，而 CN 唯一键是
   `(symbol, trade_date, period)`——上证指数 `000001.SH` 与平安银行 `000001.SZ`
   会撞同一自然键。需先决策（加 Schema 字段并迁移唯一索引 / 独立指数域），
   属 Schema 治理，不在本轮擅动。
3. **DividData LevelDB 的二进制解析没有任何自动化测试**（无 fixture）。本轮
   测试只覆盖 Adapter 映射、窗口过滤与保主源写入；真实 .ldb 读取路径需在 B-1
   联调时用实盘 datadir 验证。

**FR-12 的口径选择**（与原方案有出入，需知悉）：
- 检测基准用**库内交易**日历而非 datadir 日历——后者正是可能缺数据的一方，用它当基准会把缺口"检测成正常"；
- 分区级判定（某日有任一条记录即非缺口），覆盖率口径仍归 tick 自检 / domain_health，避免两套语义打架；
- **分时/tick 的既有源兜底未实现**：tushare/akshare 分时是按标的拉取，全市场逐票兜底属独立工作量（PRD T-3 未结）。这两域 qmt 缺分区时记 `fallback_unsupported`，累积轮次后告警转人工。
- 运行 `pytest tests/data/test_qmt_gap_manager.py` 验证；缺口生命周期事件写 `sync_events`（`data_source="qmt_gap"`，action=`registered`/`filled`/`fill_failed`）。

**为什么 tick 不走 `BaseMarketDomainSync`**：基类是「一次 fetch → 全量 normalize →
全量 validate → upsert」，而 tick 单日全市场可达千万级（RK-07 估算 10~50 GB/日），
一次性 materialize 必然打满内存。`tick_collect.py` 改为小批并发（`QMT_READ_WORKERS×2`）
逐批入库并释放，峰值内存只与批大小相关；阈值检查在**批边界**执行。

**顺带修掉的缺陷**：`base_market_sync._REPO_TABLE` 缺 `intraday_quotes` 条目（任何走
`BaseMarketDomainSync` 的分时同步都会在取 Repo 阶段 `ValueError`）；测试基础设施
`SimulatedCursor.to_list` 未应用 `cursor.limit(n)`（与 motor 语义不符）。

**链路实测**：`QMT_ENABLED=false` → `intraday_quotes`/`tick_quotes` 候选链为空；
`QMT_ENABLED=true` → `intraday_quotes` 链末位 `qmt`、`tick_quotes` 链 `[qmt]`；
离线回归 210 项全绿。

### M2 端到端验收证据（2026-10-21）

`tests/data/test_qmt_pipeline_e2e.py`（4 项）用合成 datadir 把已交付的 7 个域
**串成一次 `run_qmt_sync(force=True)`** 跑通，替代技术方案 §8 的「手工验收」：

```
单次调用：success=True，7 域全部尝试
  basic_info        2 条（宇宙：000001.SZ / 600000.SH）
  trade_calendar    3 条（上证指数日线派生）
  daily_quotes      6 条（2 只 × 3 个交易日）
  adj_factors       6 条（同窗口，走保主源写入）
  intraday_quotes   6 条（2 只 × 3 根 5m bar，仅回看 1 日）
  tick_quotes       6 条（2 只 × 3 条，time_ms 为当日毫秒、5 档为 list）
  corporate_actions 0 条（合成 datadir 无 DividData，域被尝试并记 SYNC_FAILED）
```

另三项断言：
- **幂等**：连跑两次，各集合文档数完全一致（唯一键 upsert 语义）；
- **开关零回归**：`QMT_ENABLED=false` → 整体 `skipped`，7 个集合均 0 条；
- **保主源贯穿真实管道**：预置一条 `data_source=tushare` 的复权因子记录，
  跑完整采集后该记录的 `adj_factor` 与 `data_source` **未被改写**，且
  `adj_result["cross_check"]["kept_existing"] >= 1`。

同一轮修掉的两项 M1 遗留：
- **P1-3**：停更判定改为「落后平台交易日历的期望最后交易日即停更」（10 日宽容期降级为无日历回退），`test_qmt_health.py::TestStaleRule` 5 项覆盖；
- **P2-6**：`qmt/config.py` 的同步 Mongo 解析加 30s 进程内缓存，把「每请求一次同步往返」降为「每 30s 一次」（彻底 async 化留待后续）。

### B-1 真实 datadir 联调结果（2026-10-20，`D:\App\国金证券QMT交易端\datadir`）

**结论：四级自检通过，V-1/V-2/V-3/O-2 全部定版；发现并修正 2 个单位错误。**

```
健康探针：code=ok  universe=5,226（SH 2,320 + SZ 2,906，无 BJ）
          checked_files=3  rejected=[]  latest_trade_date=20261020
交易日历：8,745 行（1990-12-19 ~ 2026-10-20）
日线：600000 6,409 行 / 000001 8,520 行 / 300750 2,027 行；列齐 13 个
分时：5m 48 bar/日（09:35~15:00）；1m 241 bar/日（09:30~15:00，含开盘竞价 bar）
tick：600000 4,994 条/日，首条 09:15:00.000（竞价锚定），末条 15:30:09
分红：600000 27 条（ex_u32 可信 4 / ts_key 回退 23）
财务：7004/7005/7006/7007 可读（150/96/1301/900 行）；7001 不支持 → 与 O-1 的 none 一致
指数：000300 6,012 行 / 000001 8,745 行 / 000905 5,291 行 → 可读
```

**两处单位错误（B-1 的核心产出）**：

| 项 | 原假设 | 实测 | 修正 |
|---|---|---|---|
| 分红 `interest` | 每 10 股，÷10 | **已是每股**（600000 = 0.320/0.321/0.410/0.420，对应「每 10 股派 3.2/3.21/4.1/4.2 元」） | `DIVIDEND_PER_UNIT` 10.0 → **1.0**（否则分红缩小 10 倍） |
| tick `volume` | 单位未知，占位 1.0 | **手**，且为**当日累计值**（tick 末条 60,513,300 股 ÷100 = 605,133 手 == 日线 volume；amount 589,321,380 逐值相等） | `TICK_VOLUME_TO_SHARE` 1.0 → **100.0** |

**T-2 实测校准**：单日全市场 tick **3.15 GB / 5,912 标的 / 约 2,350 万条**（较 PRD RK-07 的 10~50 GB/日低一个量级）；60 天保留约 135 GB；下载任务产出时刻 **tick 16:16~16:19、日线 16:38~16:41**（早于 22:00 截止约 5 小时）。`QMT_TICK_DAILY_LIMIT` 已按此从 50,000,000 下调为 **30,000,000**。

**仍待决策**：分红有 **85%/77%/45%** 的除权日来自 `ts_key` 回退（600000/000001/300750），当前策略按「绝不写可疑值」整条拒写 → 分红域实际只落 4/8/6 条事件。三条路径需拍板：维持拒写 / 移植 `dr` 跳变日校正逻辑 / 接收并标注低置信度（需 Schema 加字段）。

### 待办（按依赖顺序）

6b. **指数日线**：先决策唯一键冲突（见上文第 2 项）
7. **T-2 实测校准**：下载任务产出时刻、单日 tick 体积 → `QMT_TICK_DAILY_LIMIT`；**O-2 tick volume 单位对账** → 回填 `TICK_VOLUME_TO_SHARE`；**V-3 分红单位对账** → 回填 `DIVIDEND_PER_UNIT`

### M1 遗留（M2 推进中可一并修）

- P1-3 stale 判定（`_STALE_TOLERANCE_DAYS=10` → 应按平台交易日历的最后已收盘交易日）
- P1-4 健康页未接 `__datadir__` 状态；`upsert_health` 用 `$set` 导致成功率计数无效
- P0-1 `adj_factors` 是否纳入 pinned job —— **待拍板**（涉及 D-2 兜底源与单版本覆盖的语义冲突）
- P0-2 FR-03 全量/断点/分块（工作量最大）

---

> 本方案为产品设计参考，具体实施请结合公司合规与法务要求确认。
