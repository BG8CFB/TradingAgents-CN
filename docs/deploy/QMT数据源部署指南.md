# QMT 数据源部署指南

> 对应 PRD：[../PRD-QMT数据源接入.md](../PRD-QMT数据源接入.md) v1.2
> 技术方案：[../技术方案-QMT数据源接入.md](../技术方案-QMT数据源接入.md)

本指南用于在 **Windows 部署机**上启用 TradingAgents-CN 的 QMT 数据源（datadir 本地直读，国金证券 QMT 交易端基线）。QMT 定位为 **A 股兜底源**：仅当 tushare / akshare / baostock 均不可用时接管，默认不参与正常采集。

---

## 一、前置条件（阻塞项）

| 项 | 要求 | 校验方式 |
|----|------|----------|
| 操作系统 | Windows 10/11 x64 | — |
| 客户端 | **国金证券 QMT 交易端**，实盘模式登录（模拟盘不产出行情数据） | 打开客户端确认已登录 |
| 部署形态 | TradingAgents-CN 与 QMT 客户端**同一台机器**（PRD D-1） | — |
| 磁盘 | datadir 所在盘预留 ≥ 50 GB（随下载历史增长） | — |
| 权限 | 运行 TradingAgents-CN 的进程账户对 datadir **有读权限** | 见第四节自检 |

> **注意**：本项目只做**数据读取**，不调用任何交易接口。QMT 客户端由用户自行登录使用；系统不建立客户端会话，因此不存在登录互踢问题。

---

## 二、配置客户端「盘后自续下载任务」（关键步骤）

datadir 是 QMT 客户端下载任务的产物，**未配置该任务则 datadir 不会更新**。

1. 打开国金 QMT 交易端，进入「**数据管理 / 数据下载**」页面（不同版本菜单名可能为「行情下载」「补充数据」）。
2. 选择**全部 A 股**（沪深），勾选需要的数据周期：
   - **日线**（M1 必需）
   - 5 分钟 / 1 分钟（M2 起使用）
   - 分笔（tick，M2 起使用，体积大，按需勾选）
3. 设置**下载时段**：建议收盘后（15:30 之后）自动下载，或设置为「每日自动补充」。
4. 确认下载目录（即 datadir 根路径），典型为：
   ```
   D:\App\国金证券QMT交易端\datadir
   ```
5. 首次运行需手工触发一次全量下载（历史数据量大，耗时数小时），之后由自续任务增量更新。

**验证 datadir 已产出**：进入 datadir 目录，应看到如下结构：

```
datadir/
├── SH/86400/000001.DAT      # 上证指数日线 → 交易日历来源
├── SH/86400/600000.DAT      # 个股日线
├── SZ/86400/000001.DAT
├── SH/300/{code}.DAT        # 5 分钟线（M2）
├── SH/60/{code}.DAT         # 1 分钟线（M2）
├── SH/0/{code}/{YYYYMMDD}.dat  # tick（M2）
├── DividData/*.ldb          # 分红复权（LevelDB）
├── Finance/{SH|SZ}/86400/   # 财务附表
├── Industry/IndustryData.txt
└── Weight/sectorWeightData.txt
```

> 文件名大小写敏感（K 线为 `.DAT`，tick 为 `.dat`），请勿重命名。

---

## 三、配置 TradingAgents-CN

### 3.1 方式 A：Web UI（推荐）

1. 启动系统，进入「**设置 → 数据源管理**」。
2. 点击「添加数据源」，类型选择「**国金 QMT（本地直读）**」。
3. 在「自定义参数」中填写：
   - 键：`datadir`，值：datadir 绝对路径（如 `D:\App\国金证券QMT交易端\datadir`）
4. 点击「**测试连接**」，应返回「QMT datadir 自检通过」（含宇宙数量与最新分区日期）。
5. 保存，并在 `.env` 中将 `QMT_ENABLED` 改为 `true`（见 3.2 说明）。

> Web UI 配置存入 MongoDB `system_configs`，优先级高于环境变量（PRD D-4）。

### 3.2 方式 B：环境变量

编辑项目根目录 `.env`：

```dotenv
QMT_ENABLED=true
QMT_DATADIR=D:\App\国金证券QMT交易端\datadir
QMT_SYNC_ENABLED=true
QMT_DAILY_SYNC_CRON=30 15 * * 1-5
QMT_READINESS_DEADLINE=22:00
QMT_READINESS_POLL_SECONDS=600
QMT_SYNC_LOOKBACK_DAYS=6
QMT_READ_WORKERS=4
```

| 变量 | 默认 | 说明 |
|------|------|------|
| `QMT_ENABLED` | `false` | 总开关。**关闭时 qmt 完全不出现在路由候选链** |
| `QMT_DATADIR` | 空 | datadir 根路径；Web UI 配置优先 |
| `QMT_SYNC_ENABLED` | `true` | 盘后定时采集开关（在总开关之下） |
| `QMT_DAILY_SYNC_CRON` | `30 15 * * 1-5` | 盘后采集触发时间 |
| `QMT_READINESS_DEADLINE` | `22:00` | 等待 datadir 就绪的截止时刻，超时转缺口 |
| `QMT_READINESS_POLL_SECONDS` | `600` | 就绪轮询间隔（秒） |
| `QMT_SYNC_LOOKBACK_DAYS` | `6` | 每轮采集回看的交易日窗口 |
| `QMT_READ_WORKERS` | `4` | datadir 解析并发（磁盘 IO 密集，勿设过大） |
| `QMT_INTRADAY_FREQS` | `5min` | 分时采集频率，逗号分隔（`1min` / `5min`）。datadir 只有 1m/5m 两个周期目录；1m 体量约为 5m 的 5 倍 |
| `QMT_INTRADAY_LOOKBACK_DAYS` | `3` | 分时每轮回看的交易日数（按日分块，控内存峰值） |
| `QMT_TICK_RETENTION_DAYS` | `60` | tick 保留天数；每日 03:30 清理 Job 依据（可被 Web UI 覆盖） |
| `QMT_TICK_DAILY_LIMIT` | `30000000` | tick 单日写入行数阈值（**已按实盘校准**：全市场单日约 2,350 万条 / 3.15 GB） |
| `QMT_GAP_ENABLED` | `true` | 缺口自动补采开关（在 `QMT_ENABLED` 之下） |
| `QMT_GAP_LOOKBACK_DAYS` | `10` | 缺口检测回看的交易日数 |
| `QMT_GAP_MAX_ATTEMPTS` | `3` | 同一缺口自动补采轮次上限，达上限转 `abandoned`（人工介入） |
| `QMT_CROSS_CHECK_THRESHOLD` | `0.005` | 复权因子与既有源不一致率告警阈值（0.5%）；超阈值**保留既有源值** |

---

## 四、自检与验证

### 4.1 连通性自检

Web UI「数据源管理 → QMT → 测试连接」，或直接调用（需管理员）：

```bash
# 按名称测试已保存的数据源配置（等价于 Web UI 的「测试连接」按钮）
curl -X POST http://localhost:8000/api/config/datasource/qmt/test

# 查询 QMT 状态快照（健康页数据源；只读，不改配置）
curl http://localhost:8000/api/config/datasource/qmt/status
```

`status` 返回健康页需要的完整快照：

```json
{
  "state": "ok | not_configured | path_missing | self_check_failed | no_data | stale",
  "ok": true,
  "message": "datadir 就绪（宇宙 5217 只，最新分区 20261020）",
  "datadir": "D:\\App\\国金证券QMT交易端\\datadir",
  "universe_size": 5217,
  "checked_files": 3,
  "rejected_samples": [],
  "latest_trade_date": "20261020",
  "expected_trade_date": "20261020",
  "health": {
    "success_count": 12, "failure_count": 0, "total_calls": 12,
    "success_rate": 1.0, "circuit_state": "closed",
    "last_error": null, "updated_at": "..."
  }
}
```

> `health` 的计数是**累计**的（探针写入走 `$inc`），`success_rate` 即 PRD 3.2
> 的「QMT 采集成功率」口径；`expected_trade_date` 来自平台交易日历，
> `latest_trade_date < expected_trade_date` 即判停更（落后 1 个交易日即触发）。

返回的异常状态对应处理方式：

| 返回状态 | 含义 | 处理 |
|----------|------|------|
| `path_missing` | datadir 路径不存在 | 核对客户端安装路径与 `QMT_DATADIR` |
| `self_check_failed` | 抽样文件被四级自检拒读 | 客户端可能升级导致格式漂移；记录样本代码反馈 |
| `stale` | 最新分区落后平台交易日的期望最后交易日（无日历时退回 10 天宽容期） | 检查客户端是否运行、下载任务是否启用 |
| `not_configured` | 未配置路径 | 完成第三节配置 |
| `no_data` | 目录存在但无日线文件 | 首次全量下载尚未完成 |

### 4.2 手动触发一次采集

```bash
python -c "import asyncio; from app.worker.qmt.jobs import run_qmt_sync; print(asyncio.run(run_qmt_sync(force=True)))"
```

预期输出含 `success: True`。域计数 = `3 + N + 1`：3 为 `basic_info` / `trade_calendar` / `daily_quotes`；N 为分时域条目数（`QMT_INTRADAY_FREQS` 频率数 × `QMT_INTRADAY_LOOKBACK_DAYS`，默认 1×3 = 3）；末位 1 为 tick（只采最近一个交易日）。

### 4.3 数据核对
在 MongoDB 中确认数据已入库，且来源标记为 `qmt`：

```javascript
db.stock_daily_quotes.countDocuments({ data_source: "qmt" })
db.stock_daily_quotes.find({ data_source: "qmt" }).sort({ trade_date: -1 }).limit(3)
```

**抽样比对结论（2026-10-20 实盘 datadir 已核对完毕，V-1/V-2/V-3/O-2 全部定版）**：

| 核验项 | 方法 | 结论 |
|---|---|---|
| V-1 symbol/trade_date 格式 | `adapt_daily_quotes` 输出 | `600000` / `2026-10-20`，与既有源同构 ✓ |
| V-2 日线 volume 单位 | `amount ÷ (volume×100)` 应落在当日价格区间 | 600000：9.710 / 9.780 / 9.739（close 9.73/9.78/9.76）✓ **确为「手」×100** |
| V-3 分红单位 | 与公开分红方案对照 | 600000 `interest`=0.320/0.321/0.410/0.420，对应「每 10 股派 3.2/3.21/4.1/4.2 元」→ **字段已是每股**（换算系数 1.0） |
| V-3 `dr` 语义 | 与 `1/(1-dividend/前收)` 对照 | 1.045 / 1.037 / 1.030 与理论值同量级 → 单次复权因子（乘式），与 `adj_f_evt` 同源 |
| O-2 tick volume 单位 | tick 末条累计值 vs 日线当日 | 60,513,300 股 ÷100 = 605,133 手 **完全相等**；amount 589,321,380 **逐值相等** → 单位=手，且为**当日累计值** |

**T-2 实测（同一次 datadir 扫描）**：

| 指标 | 实测值 |
|---|---|
| 全市场单日 tick 体积 | **3.15 GB / 5,912 标的 / 约 2,350 万条**（144B/条） |
| 单票最大 tick 文件 | 0.75 MB / 5,479 条 |
| tick 60 天保留占用 | 约 **135 GB** |
| 分时全历史单票均值 | 5m 0.38~0.76 MB；1m 0.53 MB |
| 下载任务产出时刻 | tick **16:16~16:19**，日线 **16:38~16:41**（全市场约 3~4 分钟写完） |
| 日线最新分区 | 20261020（当日） |

> 对比 PRD RK-07 的「10~50 GB/日」估算，实测 **3.15 GB/日低一个量级**，磁盘风险等级应下调；
> `QMT_TICK_DAILY_LIMIT` 已按实测定为 30,000,000（实测 2,350 万 + 28% 余量）。
> 产出时刻早于 22:00 截止约 5 小时，分时（≤90 分钟）/tick（≤2 小时）时效指标有余量。

---

## 五、调度与时间线

```
交易日 15:30  调度触发（QMT_DAILY_SYNC_CRON）
   ↓
就绪轮询：每 10 分钟探测 datadir，直到 22:00
   ↓ 就绪
合约列表 → 交易日历 → 日线（最近 6 个交易日区间批量）
   ↓
分时（最近 3 个交易日**逐日**分块，1m/5m）
   ↓
tick（最近 1 个交易日，**逐票流式**：读→标准化→校验→入库；受日写入量阈值约束）
   ↓
分红送配（DividData LevelDB；窗口 [-30 天, +60 天]，覆盖已公告未除权事件）
   ↓
写入既有 MongoDB 集合（与 tushare 等同集合、同 Schema）

每日 03:30   tick 保留期清理（QMT_TICK_CLEANUP_CRON 固定）
   ↓
删除 trade_date < 今日 − QMT_TICK_RETENTION_DAYS 的 tick 分区
   ↓
sync_events 记录清理量（data_source=qmt_tick_cleanup，含 cutoff/retention）

每日 23:10   缺口管理（FR-12，排在就绪截止之后，确保当日采集已定型）
   ↓
以库内交易日历为基准，逐日检查 daily_quotes / intraday_quotes / tick_quotes 分区
   ↓
缺失 → 登记 data_gaps → qmt 优先补采 → 日线缺可采则既有源兜底
   ↓
失败按轮次累积；达 QMT_GAP_MAX_ATTEMPTS（默认 3）转 abandoned 并告警，不再自动补
```

- datadir 在 22:00 前未就绪：任务结束，写 `sync_events` 告警，当日数据由既有源或后续补采承接
- 单域失败不阻断后续域
- tick 日写入量超 `QMT_TICK_DAILY_LIMIT`：**只暂停 tick**，其余域照常；`sync_events` 记 `qmt_tick_limit_pause`
- 重复运行幂等（按 `symbol + trade_date + period` / `symbol + trade_date + time_ms` upsert）

---

## 六、回滚

```dotenv
QMT_ENABLED=false
```

重启服务即完成回滚：qmt 从所有路由候选链移除，既有四源链路不受影响。已入库的 qmt 数据带 `data_source="qmt"` 标记，保留无害；如需清除：

```javascript
db.stock_daily_quotes.deleteMany({ data_source: "qmt" })
```

---

## 七、常见问题

**Q1：datadir 有文件但健康检查报 `stale`？**
检查 QMT 客户端是否在收盘后执行了下载任务。也可先手工在客户端触发一次「补充数据」，再看 datadir 中最新 `.DAT` 文件的修改时间。

**Q2：报 `self_check_failed`？**
datadir 二进制格式为逆向成果，客户端升级可能改变格式。系统会整文件拒读（不写错误值），此时应暂停使用 QMT 源并记录被拒样本，交由研发适配。

**Q3：QMT_ENABLED=true 但数据仍来自 tushare？**
这是预期行为——qmt 是**兜底源**（回退链末位）。只有前三源失败时才会使用 qmt。如需调整优先级，修改 `app/data/config/default_priorities.yaml` 或通过优先级配置接口覆盖（30 秒生效）。

**Q4：能否用在 Linux/Docker 部署？**
datadir 直读本身是纯文件 IO、跨平台；但 datadir 必须由 Windows 上的 QMT 客户端产出。当前仅支持同机部署（PRD D-1）；将 datadir 通过共享目录同步到 Linux 服务器的分离部署属于 M3 评估项。

---

## 合规提示

QMT 行情数据经券商/迅投授权，通常**仅限签约用户本人研究使用**。本系统不提供数据转发、批量导出或对外服务能力。如计划以 SaaS 形式向第三方提供数据，须先取得行情转发授权并咨询法务。
