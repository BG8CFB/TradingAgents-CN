# 选股模块三层漏斗重构实施计划（P1+P2）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 spec `docs/superpowers/specs/2026-09-14-screening-factor-funnel-design.md`：L0 因子评分层（0 token）+ 策略模板筛选 + 每日推荐落库 + L1 快速研判（单次 LLM 调用，开关+配额管控）。

**Architecture:** 每日 20:15 `CNFactorScoreJob` 批量计算 19 因子写入 `stock_factor_scores`（纯计算）；策略模板 = YAML 声明式硬条件过滤 + 行业内分位评分排序；每日 20:45 worker 层任务把各模板 Top-30 落库 `screening_recommendations`；L1 研判是 `app/services/` 独立单次 LLM 调用（不经过 engine），手动路径落 `screening_insights` 审计集合并受按用户日配额限制，每日自动路径由 `screening_daily_insight_enabled` 开关（默认关）控制。

**Tech Stack:** FastAPI + Motor(MongoDB) + pandas + APScheduler + Vue3/Element Plus。测试全真 I/O（禁 mock），连 Docker MongoDB `tradingagents_test` 隔离库。

---

## 全局约束与执行纪律（每个任务都必须遵守）

1. **禁止 commit/push**：用户全局规则「用户未要求时不得 commit」优先于 writing-plans 的 frequent-commit 模板。所有任务完成即标记 checkbox，不执行 `git commit`。交付时统一汇报，由用户决定提交。
2. **测试环境**：`conda activate tradingagents`（宿主机 Miniconda，禁 venv）；基础设施 `docker compose -f docker-compose.dev.yml up -d mongodb redis`。Git Bash 里 conda 不可用，统一用绝对路径 `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe`。全量跑 pytest 时必须带 `DOCKER_CONTAINER=true` 环境前缀。
3. **架构红线**：routers 不 import `app.data.storage`/`app.data.sources`（import-linter 强制，`pyproject.toml:110-119` 只禁 routers/engine，**services 允许 import storage.repositories**——本计划据此设计）；routers 不直接调 MongoDB；新代码统一 `symbol`/`data_source`；schema 中立字段；`os.getenv` 只在白名单模块（本计划新代码全部不使用）。
4. **router 响应必须 `ok()` 包装**（`app/core/response.py`），`success+data` 信封。
5. **日志规范**：`logger = logging.getLogger(__name__)`；循环体逐条 DEBUG；ERROR 带 `exc_info=True`。
6. **测试禁 mock**：全部真实 I/O；标记体系 `integration`/`requires_db`/`ai`；AI 真调用测试标 `@pytest.mark.ai`（默认集跳过）。
7. **「⚠ 执行校准」标记**：计划中个别签名/字段名在编写时未能 100% 核实（已在文中标注），执行到该步时先读指定文件对齐，再写代码；若与计划代码冲突，以实际代码为准并在交付汇报中说明。

## 对 spec 的已批准偏差（实施决策，评审时已确认架构合理性）

| # | spec 原文 | 实际做法 | 原因 |
|---|---|---|---|
| 1 | `screening.*` 命名空间键 | 扁平键 `screening_daily_insight_enabled` / `screening_manual_insight_daily_limit` / `screening_insight_model` / `screening_insight_prompt` | 对齐 system_settings 既有扁平键惯例（如 `analyst_model`） |
| 2 | 估值分位「近 3 年」 | 500 交易日（≈2 年）滚动窗口，常量可调 | 全市场 5000 股 × 750 交易日 = 375 万行，内存/时延不划算；500 日已是行业常用估值分位窗口 |
| 3 | 每日推荐 job 在 `app/data/scheduler/jobs/cn/` | 注册在 `app/worker/scheduler_setup.py`（业务层 cron），调 `app/services/screening/strategy_service.py` | 推荐生成是业务逻辑（读 DataInterface + 写业务集合），data 层调度器反向 import services 会破坏分层；worker 层已有 `cn_integrity_check` 同模式先例。因子批算 job（纯数据层）仍在 data scheduler |
| 4 | 趋势因子「复用 app/utils/indicators.py」 | MACD 逐股 numpy EMA 递推（口径一致）自实现 | utils 是整表 DataFrame API，groupby 5000 组逐组构造 DataFrame 开销大；EMA 递推数值口径相同 |
| 5 | —（用户中途补充） | L1 系统提示词内置默认值，可在前端设置页编辑（`screening_insight_prompt` 覆盖） | 用户明确要求「提示词可以在前端的设置里面修改」 |

## 文件结构总览

**新建（后端）**
| 文件 | 职责 |
|---|---|
| `app/data/schema/domains/factor_scores.py` | factor_scores schema 声明 |
| `app/data/storage/mongo/repositories/factor_scores_repo.py` | factor_scores 读写仓储 |
| `app/data/storage/mongo/repositories/screening_recommendations_repo.py` | 每日推荐落库/读取 |
| `app/data/storage/mongo/repositories/screening_insights_repo.py` | 手动研判审计日志（追加+计数） |
| `app/data/factors/__init__.py`、`app/data/factors/engine.py` | L0 因子批量计算引擎（读标准集合→向量化算 19 因子） |
| `app/data/factors/scoring.py` | 行业内分位排名 + 风格评分合成（纯 pandas） |
| `app/data/factors/strategy_config.py` | strategies.yaml 加载（data/services 共用，含 mtime 缓存） |
| `app/data/scheduler/jobs/base/compute_job.py` | 计算型任务基类（区别于 BaseSyncJob） |
| `app/data/scheduler/jobs/cn/factor_score_job.py` | CNFactorScoreJob |
| `app/services/screening/__init__.py` | 服务包 |
| `app/services/screening/strategy_service.py` | 策略运行 + 每日推荐生成 |
| `app/services/screening/insight_service.py` | L1 研判：配额/prompt 覆盖/单次 LLM/落库 |
| `config/screening/strategies.yaml` | 因子分组 + 三风格权重 + 6 策略模板 |

**修改（后端）**
| 文件 | 改动 |
|---|---|
| `app/data/core/domain.py` | 3 个 DataDomain 枚举 + 语义类型 + MARKET_DATA_DOMAINS |
| `app/data/storage/mongo/collections.py` | 3 个集合名映射 |
| `app/data/storage/mongo/index_definitions.py` | 3 组索引 |
| `app/data/storage/mongo/repositories/__init__.py` | 导出 3 个 repo |
| `app/data/core/reader.py` | repo_map + get_data 分支 + latest 排序字段 |
| `app/data/scheduler/jobs/cn/__init__.py` | 注册 CNFactorScoreJob |
| `app/data/scheduler/jobs/cn/schedule.yaml` | factor_scores 条目 |
| `app/worker/scheduler_setup.py` | 每日推荐 cron |
| `app/routers/screening.py` | /strategies、/run 升级、/daily、/insights |

**前端**：`frontend/src/api/screening.ts` 扩展、`frontend/src/views/Screening/index.vue` 三 Tab 改造、`frontend/src/views/ConfigManagement.vue`（或其组件目录）加「选股设置」卡片。

**测试**：`tests/data/factors/`、`tests/data/scheduler/test_factor_score_job.py`、`tests/services/screening/`（strategy/insight/daily）、router 层测试对齐既有模式。

---

### Task 1: 数据域注册三件套 + 三个仓储

**Files:**
- Modify: `app/data/core/domain.py`
- Modify: `app/data/storage/mongo/collections.py`
- Modify: `app/data/storage/mongo/index_definitions.py`
- Modify: `app/data/storage/mongo/repositories/__init__.py`
- Modify: `app/data/core/reader.py`
- Create: `app/data/schema/domains/factor_scores.py`
- Create: `app/data/storage/mongo/repositories/factor_scores_repo.py`
- Create: `app/data/storage/mongo/repositories/screening_recommendations_repo.py`
- Create: `app/data/storage/mongo/repositories/screening_insights_repo.py`
- Test: `tests/data/storage/test_screening_repos.py`

- [ ] **Step 1.1: 写失败的仓储 round-trip 测试**

```python
"""选股新三域仓储真实读写测试（连 tradingagents_test 隔离库）。"""
import pytest

pytestmark = pytest.mark.requires_db

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.data.storage.mongo.repositories.screening_recommendations_repo import (
    ScreeningRecommendationsRepo,
)
from app.data.storage.mongo.repositories.screening_insights_repo import (
    ScreeningInsightsRepo,
)

REPOS = [FactorScoresRepo(), ScreeningRecommendationsRepo(), ScreeningInsightsRepo()]


async def _cleanup():
    db = get_motor_db()
    for domain in ("factor_scores", "screening_recommendations", "screening_insights"):
        await db[get_collection_name(domain, "CN")].delete_many({"symbol": {"$regex": "^TEST"}})
    await db[get_collection_name("screening_insights", "CN")].delete_many(
        {"user_id": "test_user_screening"}
    )


async def test_factor_scores_upsert_and_query(real_mongo_db):
    await _cleanup()
    repo = FactorScoresRepo()
    rows = [
        {"symbol": "TEST001", "trade_date": "2026-09-11", "industry": "银行", "ret_5d": 1.0,
         "score_short_term": 80.0, "data_source": "computed"},
        {"symbol": "TEST001", "trade_date": "2026-09-12", "industry": "银行", "ret_5d": 2.0,
         "score_short_term": 90.0, "data_source": "computed"},
    ]
    n = await repo.upsert_many(rows, market="CN")
    assert n == 2
    # 幂等：同主键 upsert 覆盖不新增
    await repo.upsert_many([rows[1]], market="CN")
    by_date = await repo.get_all_by_date("CN", "2026-09-12")
    assert {r["symbol"] for r in by_date} == {"TEST001"}
    latest = await repo.get_latest_trade_date("CN")
    assert latest == "2026-09-12"
    rng = await repo.get_by_symbol_and_range("TEST001", "CN", "2026-09-11", "2026-09-12")
    assert len(rng) == 2
    await _cleanup()


async def test_recommendations_upsert_latest(real_mongo_db):
    await _cleanup()
    repo = ScreeningRecommendationsRepo()
    doc = {"strategy_id": "test_strategy", "trade_date": "2026-09-12",
           "items": [{"symbol": "TEST001", "score": 88.0}], "insight_status": "none"}
    await repo.upsert_daily(doc, market="CN")
    got = await repo.get_latest_by_strategy("CN", "test_strategy")
    assert got["trade_date"] == "2026-09-12"
    assert got["items"][0]["symbol"] == "TEST001"
    await _cleanup()


async def test_insights_insert_and_quota_count(real_mongo_db):
    await _cleanup()
    repo = ScreeningInsightsRepo()
    await repo.insert_one({"user_id": "test_user_screening", "status": "done",
                           "symbols": ["TEST001"], "insights": {}, "created_at": "2026-09-12T10:00:00"})
    await repo.insert_one({"user_id": "test_user_screening", "status": "failed",
                           "symbols": ["TEST001"], "insights": {}, "created_at": "2026-09-12T11:00:00"})
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    n = await repo.count_today_done("test_user_screening", today)
    assert n == 1  # failed 不计数
    await _cleanup()
```

⚠ 执行校准：`real_mongo_db` fixture 非 autouse（`tests/data/conftest.py:31-52`，负责切换到 tradingagents_test 隔离库并绑定 Motor 事件循环），**每个用 DB 的测试函数必须显式声明该参数**——下文所有测试代码已带；若 fixture 名/行为与计划不符，以 conftest 实际为准调整签名。

- [ ] **Step 1.2: 跑测试确认失败（模块不存在）**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/data/storage/test_screening_repos.py -v`
Expected: FAIL — `ModuleNotFoundError: factor_scores_repo`

- [ ] **Step 1.3: 域注册修改（4 个文件）**

`app/data/core/domain.py` — `DataDomain` 枚举末尾加：

```python
    FACTOR_SCORES = "factor_scores"
    SCREENING_RECOMMENDATIONS = "screening_recommendations"
    SCREENING_INSIGHTS = "screening_insights"
```

`DOMAIN_SEMANTIC_TYPE` 末尾加：

```python
    DataDomain.FACTOR_SCORES: SemanticType.TIMESERIES,
    DataDomain.SCREENING_RECOMMENDATIONS: SemanticType.SNAPSHOT,
    DataDomain.SCREENING_INSIGHTS: SemanticType.EVENT,
```

`MARKET_DATA_DOMAINS` 加 `DataDomain.FACTOR_SCORES,`（非交易日跳过批算，与行情域同语义；recommendations/insights 不加——由上游因子 job 的交易日检查间接保证）。

`app/data/storage/mongo/collections.py` — `_BUSINESS_COLLECTIONS` 末尾加：

```python
    "factor_scores": "stock_factor_scores",
    "screening_recommendations": "screening_recommendations",
    "screening_insights": "screening_insights",
```

`app/data/storage/mongo/index_definitions.py` — `INDEX_DEFINITIONS` 加（注意文件头注释要求覆盖全部业务 domain，`tests/data/test_index_definitions.py` 会做一致性断言）：

```python
    "factor_scores": [
        # 因子日频快照：每股每日一行（计算产物，单版本）
        ([("symbol", 1), ("trade_date", -1)], True),
        ([("trade_date", -1)], False),
    ],
    "screening_recommendations": [
        # 每日推荐：每策略每日一条（job 覆盖写入）
        ([("strategy_id", 1), ("trade_date", -1)], True),
        ([("trade_date", -1)], False),
    ],
    "screening_insights": [
        # 手动研判审计日志：append-only，无业务唯一键
        ([("user_id", 1), ("created_at", -1)], False),
        ([("trade_date", -1)], False),
    ],
```

- [ ] **Step 1.4: schema 声明**

新建 `app/data/schema/domains/factor_scores.py`（⚠ 执行校准：先读同目录 `daily_indicators.py` 对齐 Schema 类基类与导出风格；下面按通用结构写）：

```python
"""factor_scores 域 schema — L0 因子批算结果。

主键：(symbol, trade_date)。中立字段，无数据源方言。
因子字段由 app/data/factors/engine.py 计算写入，值缺失（可选域无数据/
数据不足）时字段置 None，不缺行。
"""

from app.data.schema.base.common_fields import CommonFields

# 引擎写入的全部因子字段（原始值，非分位）——引擎与前端展示共用此清单
FACTOR_FIELDS = [
    # 动量
    "ret_5d", "ret_20d", "ret_60d", "dist_to_60d_high",
    # 趋势
    "bias_ma20", "ma20_slope", "macd_golden_days",
    # 量能
    "turnover_amp", "consecutive_vol_up_days", "volume_ratio",
    # 资金
    "main_inflow_5d", "main_inflow_5d_pct",
    # 估值
    "pe_ttm_percentile", "pb_percentile", "dividend_yield",
    # 质量
    "roe", "gross_margin", "net_profit_yoy", "debt_ratio",
]

# 三风格合成分
SCORE_FIELDS = ["score_short_term", "score_balanced", "score_value"]

# factor_scores 文档 = CommonFields(symbol, market, data_source, updated_at)
#                   + trade_date + industry + name + FACTOR_FIELDS + SCORE_FIELDS
```

- [ ] **Step 1.5: 三个仓储实现**

`factor_scores_repo.py`：

```python
"""因子分仓储 — L0 批算结果读写。"""

from typing import Dict, List, Optional

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.bulk_utils import batched_bulk_write
from app.data.storage.mongo.repositories.key_spec import build_filter


class FactorScoresRepo:

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        """按 (symbol, trade_date) 幂等覆盖写入；缺唯一键的记录跳过。"""
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("factor_scores", market)]
        ops = []
        for rec in records:
            try:
                filter_doc = build_filter("factor_scores", rec)
            except KeyError:
                continue
            ops.append(UpdateOne(filter_doc, {"$set": rec}, upsert=True))
        if not ops:
            return 0
        return await batched_bulk_write(coll, ops)

    async def get_by_symbol_and_range(
        self, symbol: str, market: str, start_date: str, end_date: str
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("factor_scores", market)]
        cursor = coll.find(
            {"symbol": symbol, "trade_date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0},
        ).sort("trade_date", -1)
        return await cursor.to_list(length=None)

    async def get_latest_trade_date(self, market: str) -> Optional[str]:
        db = get_motor_db()
        coll = db[get_collection_name("factor_scores", market)]
        doc = await coll.find_one({}, {"trade_date": 1, "_id": 0},
                                  sort=[("trade_date", -1)])
        return doc.get("trade_date") if doc else None

    async def get_all_by_date(self, market: str, trade_date: str,
                              projection: Optional[Dict] = None) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("factor_scores", market)]
        cursor = coll.find({"trade_date": trade_date},
                           projection or {"_id": 0})
        return await cursor.to_list(length=None)
```

`screening_recommendations_repo.py`：

```python
"""每日推荐仓储 — 每策略每日一条，job 覆盖写入。"""

from typing import Dict, Optional

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.key_spec import build_filter


class ScreeningRecommendationsRepo:

    async def upsert_daily(self, doc: Dict, market: str) -> None:
        db = get_motor_db()
        coll = db[get_collection_name("screening_recommendations", market)]
        filter_doc = build_filter("screening_recommendations", doc)
        await coll.update_one(filter_doc, {"$set": doc}, upsert=True)

    async def get_latest_by_strategy(self, market: str,
                                     strategy_id: str) -> Optional[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("screening_recommendations", market)]
        return await coll.find_one(
            {"strategy_id": strategy_id}, {"_id": 0},
            sort=[("trade_date", -1)],
        )

    async def get_by_strategy_and_date(self, market: str, strategy_id: str,
                                       trade_date: str) -> Optional[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("screening_recommendations", market)]
        return await coll.find_one(
            {"strategy_id": strategy_id, "trade_date": trade_date}, {"_id": 0}
        )

    async def get_latest_any(self, market: str) -> Optional[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("screening_recommendations", market)]
        return await coll.find_one({}, {"_id": 0}, sort=[("trade_date", -1)])

    async def list_strategies_on_date(self, market: str,
                                      trade_date: str) -> list:
        db = get_motor_db()
        coll = db[get_collection_name("screening_recommendations", market)]
        cursor = coll.find({"trade_date": trade_date}, {"_id": 0})
        return await cursor.to_list(length=None)
```

`screening_insights_repo.py`：

```python
"""手动 L1 研判审计日志仓储 — append-only，无业务唯一键。"""

from typing import Dict

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name


class ScreeningInsightsRepo:

    async def insert_one(self, doc: Dict) -> None:
        db = get_motor_db()
        coll = db[get_collection_name("screening_insights", "CN")]
        await coll.insert_one(doc)

    async def count_today_done(self, user_id: str, date_str: str) -> int:
        """按 (user_id, 自然日) 统计成功研判次数 — 配额计数口径。

        created_at 统一存 app.utils.timezone.now_tz() 的 ISO 字符串，
        其日期部分与调用方传入的本地自然日一致。
        """
        db = get_motor_db()
        coll = db[get_collection_name("screening_insights", "CN")]
        return await coll.count_documents({
            "user_id": user_id,
            "status": "done",
            "created_at": {"$regex": f"^{date_str}"},
        })
```

⚠ 执行校准：`created_at` 存储格式若决定用 BSON date，则 `count_today_done` 改为 `$gte datetime(day_start)` / `$lt datetime(next_day)` 区间查询（对齐 `app/models/operation_log.py` 一类的时间字段惯例）。

`repositories/__init__.py` 追加导出：

```python
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo as FactorScoresRepo
from app.data.storage.mongo.repositories.screening_recommendations_repo import ScreeningRecommendationsRepo as ScreeningRecommendationsRepo
from app.data.storage.mongo.repositories.screening_insights_repo import ScreeningInsightsRepo as ScreeningInsightsRepo
```

- [ ] **Step 1.6: reader 接线**

`app/data/core/reader.py`：
1. `repo_map`（约 :68）加三行：
```python
                "factor_scores": FactorScoresRepo,
                "screening_recommendations": ScreeningRecommendationsRepo,
                "screening_insights": ScreeningInsightsRepo,
```
2. `get_data` 分支：把 `factor_scores` 加进时序组（复用同签名 `get_by_symbol_and_range`）：
```python
        elif domain in ("daily_quotes", "daily_indicators", "adj_factors",
                        "corporate_actions", "factor_scores"):
```
3. ⚠ 执行校准：grep `_LATEST_SORT_FIELDS`（`reader.py:249`，`Dict[str, str]`，值是排序字段名字符串），加 `"factor_scores": "trade_date"`；`screening_recommendations` 同理补 `"trade_date"`（若该注册表只服务 read_latest 系列则同样处理）。

- [ ] **Step 1.7: 跑测试通过 + 域一致性测试**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/data/storage/test_screening_repos.py tests/data/test_index_definitions.py -v`
Expected: 全 PASS（index 一致性测试自动覆盖新域）

- [ ] **Step 1.8: 静态检查**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m ruff check app/data/ && C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m lint_imports`（⚠ lint-imports 若无 `-m` 入口则用绝对路径可执行文件，对齐 memory「Git Bash 里 conda 不可用」）
Expected: 无违规

---

### Task 2: strategies.yaml + 配置加载器

**Files:**
- Create: `config/screening/strategies.yaml`
- Create: `app/data/factors/__init__.py`
- Create: `app/data/factors/strategy_config.py`
- Test: `tests/data/factors/test_strategy_config.py`

- [ ] **Step 2.1: 写失败测试**

```python
"""strategies.yaml 加载与校验测试。"""

from app.data.factors.strategy_config import (
    load_strategy_config, get_factor_groups, get_style_weights, get_strategies,
)


def test_config_loads_and_shape():
    cfg = load_strategy_config()
    # 三套风格权重，权重和为 1
    weights = cfg["score_weights"]
    assert set(weights) == {"short_term", "balanced", "value"}
    for style, w in weights.items():
        assert abs(sum(w.values()) - 1.0) < 1e-6, style
    # 因子分组覆盖 spec 的 6 组
    groups = get_factor_groups()
    assert set(groups) == {"momentum", "trend", "volume", "flow", "valuation", "quality"}
    # 单因子权重上限：组权重/组内因子数 ≤ 40%（spec §8）
    max_factor_weight = max(
        w / len(groups[g]) for w, g in
        ((w, g) for style_w in weights.values() for g, w in style_w.items())
    )
    assert max_factor_weight <= 0.40
    # 6 个策略模板，id 唯一，恰有一个 default
    strategies = get_strategies()
    assert len(strategies) == 6
    ids = [s["id"] for s in strategies]
    assert len(set(ids)) == 6
    assert sum(1 for s in strategies if s.get("default")) == 1
    # 每个模板的 filters 字段都在因子/分组字段范围内
    known = {f for fs in groups.values() for f in fs}
    for s in strategies:
        assert s["style"] in weights
        for cond in s.get("filters", []):
            assert cond["field"] in known, (s["id"], cond["field"])
```

- [ ] **Step 2.2: 跑测试确认失败**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/data/factors/test_strategy_config.py -v`
Expected: FAIL — `ModuleNotFoundError: app.data.factors`

- [ ] **Step 2.3: 写 strategies.yaml**

```yaml
# 选股策略模板与评分权重（L0 唯一事实源）
# 结构：score_weights（三风格 × 六因子组权重）+ factor_groups（组→因子）
#      + strategies（模板 = 硬条件过滤 + 风格评分排序）
# 约束：任一单因子权重（组权重/组内因子数）≤ 40%；组权重和 = 1

score_weights:
  short_term:            # 短线（默认，匹配现有流水线定调）
    momentum: 0.35
    trend: 0.25
    volume: 0.20
    flow: 0.20
  balanced:              # 均衡
    momentum: 0.20
    trend: 0.20
    volume: 0.15
    flow: 0.15
    valuation: 0.15
    quality: 0.15
  value:                 # 价值质量
    valuation: 0.35
    quality: 0.40
    momentum: 0.10
    volume: 0.15

factor_groups:
  momentum: [ret_5d, ret_20d, ret_60d, dist_to_60d_high]
  trend: [bias_ma20, ma20_slope, macd_golden_days]
  volume: [turnover_amp, consecutive_vol_up_days, volume_ratio]
  flow: [main_inflow_5d, main_inflow_5d_pct]
  valuation: [pe_ttm_percentile, pb_percentile, dividend_yield]
  quality: [roe, gross_margin, net_profit_yoy, debt_ratio]

strategies:
  - id: volume_breakout
    name: 放量突破主升初期
    description: 站上 MA20、换手放大、MACD 金叉初期且主力资金净流入，捕捉主升浪起点
    style: short_term
    top_n: 30
    default: true
    filters:
      - {field: bias_ma20, op: ">", value: 0}
      - {field: turnover_amp, op: ">", value: 1.5}
      - {field: macd_golden_days, op: "between", value: [1, 5]}
      - {field: main_inflow_5d, op: ">", value: 0}

  - id: trend_pullback
    name: 强趋势回调买点
    description: 中期趋势向上，短期回调 5%-8% 但未破 MA20，顺势低吸
    style: short_term
    top_n: 30
    filters:
      - {field: ma20_slope, op: ">", value: 0}
      - {field: ret_5d, op: between, value: [-8, 0]}
      - {field: bias_ma20, op: ">", value: 0}

  - id: oversold_rebound
    name: 超跌反弹
    description: 20 日跌超 15% 但主力资金开始净流入，博弈超跌修复
    style: short_term
    top_n: 30
    filters:
      - {field: ret_20d, op: "<", value: -15}
      - {field: main_inflow_5d, op: ">", value: 0}

  - id: high_roe_low_val
    name: 高ROE低估值
    description: ROE>15%、PE 处历史低分位且有股息，经典价值组合
    style: value
    top_n: 30
    filters:
      - {field: roe, op: ">", value: 15}
      - {field: pe_ttm_percentile, op: "<", value: 30}
      - {field: dividend_yield, op: ">", value: 2}

  - id: quality_growth
    name: 质量成长
    description: 毛利率>30%、净利同比>20%、资产负债率<60% 的成长质量股
    style: value
    top_n: 30
    filters:
      - {field: gross_margin, op: ">", value: 30}
      - {field: net_profit_yoy, op: ">", value: 20}
      - {field: debt_ratio, op: "<", value: 60}

  - id: steady_inflow
    name: 资金持续流入
    description: 主力温和流入、换手温和放大、站稳 MA20 的蓄势形态
    style: short_term
    top_n: 30
    filters:
      - {field: main_inflow_5d, op: ">", value: 0}
      - {field: turnover_amp, op: between, value: [1, 2]}
      - {field: bias_ma20, op: ">", value: 0}
```

- [ ] **Step 2.4: 写加载器 `app/data/factors/strategy_config.py`**

```python
"""strategies.yaml 加载 — 数据层（评分）与服务层（策略运行）共用的唯一事实源。

mtime 缓存：热重载环境下改 YAML 后无需重启进程。
"""

import logging
import os
from typing import Dict, List

import yaml

logger = logging.getLogger(__name__)

_CONFIG_NAME = "strategies.yaml"
_SEARCH_DIRS = [
    # 1) 环境变量显式覆盖（测试/自定义部署；_locate 内每次读取，运行期可覆盖）
    "env",
    # 2) 仓库内标准位置（容器内 /app/config/...，宿主机项目根）
    "config/screening/strategies.yaml",
    "/app/config/screening/strategies.yaml",
]

_cache: dict | None = None
_cache_mtime: float | None = None


def _locate() -> str:
    for path in _SEARCH_DIRS:
        if path == "env":
            path = os.environ.get("SCREENING_STRATEGIES_FILE") or ""
        if path and os.path.isfile(path):
            return path
    raise FileNotFoundError(f"未找到选股策略配置 {_CONFIG_NAME}")


def load_strategy_config() -> Dict:
    """读取并缓存 strategies.yaml（mtime 变化时自动重载）。"""
    global _cache, _cache_mtime
    path = _locate()
    mtime = os.path.getmtime(path)
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    _validate(cfg)
    _cache = cfg
    _cache_mtime = mtime
    logger.info("已加载选股策略配置 %s（%d 个模板）", path, len(cfg.get("strategies", [])))
    return cfg


def _validate(cfg: Dict) -> None:
    weights = cfg.get("score_weights") or {}
    groups = cfg.get("factor_groups") or {}
    strategies = cfg.get("strategies") or []
    if not weights or not groups or not strategies:
        raise ValueError("strategies.yaml 缺少 score_weights/factor_groups/strategies")
    for style, w in weights.items():
        if abs(sum(w.values()) - 1.0) > 1e-6:
            raise ValueError(f"风格 {style} 组权重和 != 1: {w}")
        unknown = set(w) - set(groups)
        if unknown:
            raise ValueError(f"风格 {style} 引用未知因子组: {unknown}")
    known_factors = {f for fs in groups.values() for f in fs}
    ids = [s.get("id") for s in strategies]
    if len(set(ids)) != len(ids) or None in ids:
        raise ValueError(f"策略 id 重复或缺失: {ids}")
    if sum(1 for s in strategies if s.get("default")) != 1:
        raise ValueError("必须恰好一个 default: true 的策略模板")
    for s in strategies:
        if s.get("style") not in weights:
            raise ValueError(f"策略 {s['id']} 引用未知风格 {s.get('style')}")
        for cond in s.get("filters", []):
            if cond.get("field") not in known_factors:
                raise ValueError(f"策略 {s['id']} 条件字段 {cond.get('field')} 不在因子清单")


def get_factor_groups() -> Dict[str, List[str]]:
    return load_strategy_config()["factor_groups"]


def get_style_weights() -> Dict[str, Dict[str, float]]:
    return load_strategy_config()["score_weights"]


def get_strategies() -> List[Dict]:
    return load_strategy_config()["strategies"]


def get_default_strategy() -> Dict:
    return next(s for s in get_strategies() if s.get("default"))
```

⚠ 执行校准：`os.environ.get(...)` 出现在配置加载定位逻辑里——lint 实测匹配模式只查 `os.getenv(`，`os.environ.get` 不触发白名单约束；若跑 `tests/lint/test_env_access_conventions.py` 仍报，则删除 env 覆盖入口（`_SEARCH_DIRS` 去掉 `"env"` 项），仅保留两个固定路径探测。

`app/data/factors/__init__.py`：

```python
"""L0 因子层 — 批量计算引擎、评分合成、策略配置。"""
```

- [ ] **Step 2.5: 跑测试通过**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/data/factors/test_strategy_config.py -v`
Expected: PASS

---

### Task 3: 评分合成 scoring.py（纯 pandas，无 IO）

**Files:**
- Create: `app/data/factors/scoring.py`
- Test: `tests/data/factors/test_scoring.py`

- [ ] **Step 3.1: 写失败测试**

```python
"""行业内分位排名 + 风格评分合成测试（构造已知数据验证）。"""
import math

import pandas as pd

from app.data.factors.scoring import rank_factors_by_industry, compute_style_scores

GROUPS = {
    "momentum": ["ret_5d", "ret_20d"],
    "valuation": ["pe_ttm_percentile"],
}
FACTORS = [f for fs in GROUPS.values() for f in fs]
WEIGHTS = {
    "short_term": {"momentum": 1.0},
    "value": {"valuation": 1.0},
}


def _df():
    # 两行业各 2 股：银行内 ret_5d 高者得高分；pe 分位低者得高分（lower_better）
    return pd.DataFrame([
        {"symbol": "TEST001", "industry": "银行", "ret_5d": 5.0, "ret_20d": 10.0,
         "pe_ttm_percentile": 80.0},
        {"symbol": "TEST002", "industry": "银行", "ret_5d": 1.0, "ret_20d": 4.0,
         "pe_ttm_percentile": 20.0},
        {"symbol": "TEST003", "industry": "医药", "ret_5d": -2.0, "ret_20d": -5.0,
         "pe_ttm_percentile": 50.0},
        {"symbol": "TEST004", "industry": "医药", "ret_5d": 2.0, "ret_20d": 1.0,
         "pe_ttm_percentile": 50.0},
    ])


def test_industry_rank_direction():
    ranked = rank_factors_by_industry(_df(), FACTORS)
    by_sym = ranked.set_index("symbol")
    # 同行业内 ret_5d 高者 rank 高
    assert by_sym.loc["TEST001", "ret_5d_rank"] > by_sym.loc["TEST002", "ret_5d_rank"]
    # pe 分位 lower_better：TEST002(20) 应高于 TEST001(80)
    assert by_sym.loc["TEST002", "pe_ttm_percentile_rank"] > by_sym.loc["TEST001", "pe_ttm_percentile_rank"]
    # 行业内 rank 范围 (0, 100]
    assert 0 < by_sym["ret_5d_rank"].min() <= 100


def test_style_scores_weighted():
    df = rank_factors_by_industry(_df(), FACTORS)
    scored = compute_style_scores(df, GROUPS, WEIGHTS)
    by_sym = scored.set_index("symbol")
    # short_term = momentum 组内 ret_5d/ret_20d 均分加权，TEST001 在银行内两项都最高 → 100
    assert math.isclose(by_sym.loc["TEST001", "score_short_term"], 100.0, abs_tol=1e-6)
    # value = pe 分位单因子（lower_better）：2 股行业内 rank(pct)∈{50,100}，
    # 反转后最优股 = 100-50 = 50（两股行业反转上限即 50）
    assert math.isclose(by_sym.loc["TEST002", "score_value"], 50.0, abs_tol=1e-6)
    assert math.isclose(by_sym.loc["TEST001", "score_value"], 0.0, abs_tol=1e-6)


def test_missing_factor_renormalize():
    df = _df()
    df.loc[df["symbol"] == "TEST001", "ret_20d"] = None  # TEST001 缺 ret_20d
    scored = compute_style_scores(rank_factors_by_industry(df, FACTORS), GROUPS, WEIGHTS)
    by_sym = scored.set_index("symbol")
    # 可用因子归一：TEST001 的 short_term 只剩 ret_5d（行业内最高→100），归一后仍 100
    assert math.isclose(by_sym.loc["TEST001", "score_short_term"], 100.0, abs_tol=1e-6)
    # TEST002 的 ret_5d 是银行内最低（rank 非零）→ 缺失归一后分数为有限正值
    assert by_sym.loc["TEST002", "score_short_term"] > 0


def test_coverage_below_threshold_no_score():
    df = _df()
    # TEST003 两个动量因子都缺 → short_term 覆盖 0% < 30% → 不评分
    df.loc[df["symbol"] == "TEST003", ["ret_5d", "ret_20d"]] = None
    scored = compute_style_scores(rank_factors_by_industry(df, FACTORS), GROUPS, WEIGHTS)
    assert pd.isna(scored.set_index("symbol").loc["TEST003", "score_short_term"])
```

- [ ] **Step 3.2: 跑测试确认失败**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/data/factors/test_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: app.data.factors.scoring`

- [ ] **Step 3.3: 实现 scoring.py**

```python
"""因子行业内分位排名与风格评分合成（纯 pandas，无 IO）。

评分口径（spec §8）：
1. 每因子在行业内 percentile rank（消除行业偏差）
2. lower_better 因子反转（rank → 100-rank），统一为越大越好
3. 风格评分 = Σ(组权重 × 组内可用因子平均分)，按可用因子归一
4. 因子覆盖 < 30% 的股票该风格不评分（score=None）
"""

from typing import Dict, List

import numpy as np
import pandas as pd

# 值越小越好的因子（行业内 rank 后反转）
LOWER_BETTER_FACTORS = {
    "pe_ttm_percentile", "pb_percentile", "debt_ratio", "dist_to_60d_high",
}

MIN_COVERAGE_RATIO = 0.30


def rank_factors_by_industry(df: pd.DataFrame,
                             factor_fields: List[str]) -> pd.DataFrame:
    """每因子行业内 pct rank ×100；lower_better 反转。产出 <f>_rank 列。"""
    out = df.copy()
    grouped = out.groupby("industry", group_keys=False)
    for f in factor_fields:
        if f not in out.columns:
            out[f] = np.nan
        rank = grouped[f].rank(pct=True) * 100.0
        if f in LOWER_BETTER_FACTORS:
            rank = 100.0 - rank
        out[f"{f}_rank"] = rank
    return out


def compute_style_scores(df: pd.DataFrame,
                         factor_groups: Dict[str, List[str]],
                         style_weights: Dict[str, Dict[str, float]]) -> pd.DataFrame:
    """对 rank 后的 DataFrame 追加 score_<style> 列（0-100，覆盖不足为 NaN）。"""
    out = df.copy()
    all_factors = [f for fs in factor_groups.values() for f in fs]
    rank_cols = {f: f"{f}_rank" for f in all_factors}

    for style, groups_w in style_weights.items():
        style_factors = [f for g, w in groups_w.items() if w > 0
                         for f in factor_groups[g]]
        # 覆盖率：该风格涉及因子中非 NaN 的比例
        avail = out[[rank_cols[f] for f in style_factors]].notna()
        coverage = avail.mean(axis=1)
        score = pd.Series(np.nan, index=out.index, dtype=float)
        eligible = coverage >= MIN_COVERAGE_RATIO
        if eligible.any():
            # 每因子加权分：组权重在组内均分；行级按可用因子归一
            weighted_sum = pd.Series(0.0, index=out.index)
            weight_sum = pd.Series(0.0, index=out.index)
            for group, gw in groups_w.items():
                if gw <= 0:
                    continue
                members = factor_groups[group]
                fw = gw / len(members)  # 组内均分
                for f in members:
                    rc = out[rank_cols[f]]
                    valid = rc.notna()
                    weighted_sum = weighted_sum + rc.fillna(0.0) * fw * valid
                    weight_sum = weight_sum + fw * valid
            norm = weighted_sum / weight_sum.replace(0.0, np.nan)
            score = norm.where(eligible)
        out[f"score_{style}"] = score
    return out
```

- [ ] **Step 3.4: 跑测试通过**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/data/factors/test_scoring.py -v`
Expected: PASS（4 个用例）

---

### Task 4: 因子计算引擎 engine.py

**Files:**
- Create: `app/data/factors/engine.py`
- Test: `tests/data/factors/test_factor_engine.py`

**设计要点（读数路径全部在数据层内部：get_motor_db + get_collection_name）：**
- 交易日窗口从 `daily_quotes` distinct trade_date 取（数据驱动，避免日历/数据错位）
- 流式游标读取（`async for`）控内存；indicators 窗口 500 交易日只投影 4 列
- 行情/指标行数 < 60 的股票剔除（等价实现「上市<60 日 + 长期停牌」过滤；ST 按 basic_info name 过滤）
- MACD 金叉天数：逐股 numpy EMA 递推（口径同 utils/indicators，避免 5000 次 DataFrame 构造）

- [ ] **Step 4.1: 写失败测试（手算对比）**

```python
"""因子引擎数值正确性测试：种子数据 → 计算 → 与独立手算对比。"""
import math

import pytest

pytestmark = pytest.mark.requires_db

from datetime import date, timedelta

from app.data.factors.engine import FactorScoreEngine

# ── 种子数据构造 ────────────────────────────────────────────────

def _trade_dates(n: int, end: date) -> list:
    """生成 n 个连续工作日（周五跳过）。"""
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return sorted(f"{x:%Y-%m-%d}" for x in days)


async def _seed(db, symbols_cfg: dict, dates: list):
    """按配置种 3 域种子数据。

    symbols_cfg: {symbol: {"close": [..130 个递增/递减序列..],
                            "turnover": [..], "pe": [..], "name": ...}}
    """
    from app.data.storage.mongo.collections import get_collection_name

    q_coll = db[get_collection_name("daily_quotes", "CN")]
    i_coll = db[get_collection_name("daily_indicators", "CN")]
    b_coll = db[get_collection_name("basic_info", "CN")]
    m_coll = db[get_collection_name("money_flow", "CN")]
    f_coll = db[get_collection_name("financial_data", "CN")]

    for sym, cfg in symbols_cfg.items():
        await b_coll.update_one(
            {"symbol": sym}, {"$set": {
                "symbol": sym, "market": "CN", "name": cfg["name"],
                "industry": cfg["industry"], "data_source": "test",
            }}, upsert=True)
        q_docs = [{
            "symbol": sym, "trade_date": d, "period": "daily",
            "close": c, "vol": cfg["vol"], "amount": cfg["amount"],
            "turnover_rate": t, "pct_chg": 0.0,
            "data_source": "test",
        } for d, c, t in zip(dates[-120:], cfg["close"][-120:],
                             cfg["turnover"][-120:])]
        await q_coll.insert_many(q_docs)
        # indicators 覆盖全部 130 个唯一交易日（引擎取库内可得窗口，不足 500 不影响）；
        # pe 全窗口恒定 → pe_ttm_percentile = 100
        i_docs = [{
            "symbol": sym, "trade_date": d, "pe_ttm": cfg["pe"], "pb": cfg["pb"],
            "dividend_yield": cfg["dv"], "volume_ratio": cfg["vr"],
            "data_source": "test",
        } for d in dates]
        await i_coll.insert_many(i_docs)
        for d in dates[-5:]:
            await m_coll.insert_one({
                "symbol": sym, "trade_date": d,
                "main_net_inflow": cfg["inflow"], "data_source": "test",
            })
        for rp, np_ in [("2025-06-30", cfg["np_prev"]), ("2026-06-30", cfg["np_cur"])]:
            await f_coll.update_one(
                {"symbol": sym, "report_period": rp},
                {"$set": {
                    "symbol": sym, "report_period": rp, "statement_type": "合并报表",
                    "net_profit": np_, "roe": cfg["roe"],
                    "gross_margin": cfg["gm"], "debt_ratio": cfg["dr"],
                    "data_source": "test",
                }}, upsert=True)


async def _cleanup(db, symbols):
    from app.data.storage.mongo.collections import get_collection_name
    for domain in ("daily_quotes", "daily_indicators", "basic_info",
                   "money_flow", "financial_data", "factor_scores"):
        await db[get_collection_name(domain, "CN")].delete_many(
            {"symbol": {"$in": symbols}})


async def test_factor_values_match_hand_calc(real_mongo_db):
    db = real_mongo_db
    symbols = ["TESTF001", "TESTF002", "TESTF003"]
    dates = _trade_dates(130, date(2026, 9, 11))
    await _cleanup(db, symbols)

    # TESTF001：线性递增 close 10→~22.9（斜率 0.1），TESTF002：递减
    up = [10.0 + 0.1 * i for i in range(130)]
    down = [30.0 - 0.1 * i for i in range(130)]
    symbols_cfg = {
        "TESTF001": {
            "name": "正常股", "industry": "银行",
            "close": up, "turnover": [2.0] * 129 + [4.0],
            "vol": 1_000_000, "amount": 50_000_000,
            "pe": 20.0, "pb": 1.5, "dv": 3.0, "vr": 1.8,
            "inflow": 10_000_000.0, "np_prev": 100.0, "np_cur": 130.0,
            "roe": 18.0, "gm": 35.0, "dr": 45.0,
        },
        "TESTF002": {
            "name": "正常股B", "industry": "医药",
            "close": down, "turnover": [1.0] * 130,
            "vol": 500_000, "amount": 10_000_000,
            "pe": 50.0, "pb": 5.0, "dv": 0.5, "vr": 0.6,
            "inflow": -2_000_000.0, "np_prev": 50.0, "np_cur": 40.0,
            "roe": 5.0, "gm": 15.0, "dr": 70.0,
        },
    }
    # ST 股（含 "ST" 子串应被剔除）先清残留再种，用于验证过滤生效
    await _cleanup(db, ["TESTF003"])
    await _seed(db, {
        "TESTF003": {
            "name": "ST测试", "industry": "电子",
            "close": [20.0] * 130, "turnover": [1.0] * 130,
            "vol": 800_000, "amount": 20_000_000,
            "pe": 40.0, "pb": 3.0, "dv": 0.0, "vr": 1.0,
            "inflow": 0.0, "np_prev": 10.0, "np_cur": 8.0,
            "roe": 2.0, "gm": 8.0, "dr": 80.0,
        },
    }, dates)
    await _seed(db, symbols_cfg, dates)

    engine = FactorScoreEngine()
    df = await engine.compute_factors("CN")
    got = df.set_index("symbol")
    assert "TESTF003" not in got.index, "ST 股应被引擎剔除"

    # ── 手算断言（TESTF001）──
    c = up
    # ret_5d：后复权无除权时 = close[-1]/close[-6]-1
    assert math.isclose(got.loc["TESTF001", "ret_5d"], (c[-1] / c[-6] - 1) * 100, rel_tol=1e-6)
    assert math.isclose(got.loc["TESTF001", "ret_20d"], (c[-1] / c[-21] - 1) * 100, rel_tol=1e-6)
    assert math.isclose(got.loc["TESTF001", "ret_60d"], (c[-1] / c[-61] - 1) * 100, rel_tol=1e-6)
    # dist_to_60d_high = (60日最高/现价 - 1)×100 = 0（最后一天即最高）
    assert math.isclose(got.loc["TESTF001", "dist_to_60d_high"], 0.0, abs_tol=1e-9)
    # bias_ma20 = (close/ma20-1)×100
    ma20 = sum(c[-20:]) / 20
    assert math.isclose(got.loc["TESTF001", "bias_ma20"], (c[-1] / ma20 - 1) * 100, rel_tol=1e-6)
    # ma20_slope = (ma20[-1]/ma20[-5]-1)×100
    ma20_prev = sum(c[-25:-5]) / 20
    assert math.isclose(got.loc["TESTF001", "ma20_slope"], (ma20 / ma20_prev - 1) * 100, rel_tol=1e-6)
    # turnover_amp = 当日换手 / 前 20 日均换手 = 4/2 = 2
    assert math.isclose(got.loc["TESTF001", "turnover_amp"], 2.0, rel_tol=1e-6)
    # 递增序列 → consecutive_vol_up_days 用 vol 常量时无连续放量 → 0
    assert got.loc["TESTF001", "consecutive_vol_up_days"] == 0
    # 财务直取 + yoy
    assert math.isclose(got.loc["TESTF001", "net_profit_yoy"], 30.0, rel_tol=1e-6)
    assert got.loc["TESTF001", "roe"] == 18.0
    # 资金：5 日累计 = 5×1000万
    assert math.isclose(got.loc["TESTF001", "main_inflow_5d"], 50_000_000.0, rel_tol=1e-6)
    # main_inflow_5d_pct = 5×1000万 / (5×5000万) ×100 = 20
    assert math.isclose(got.loc["TESTF001", "main_inflow_5d_pct"], 20.0, rel_tol=1e-6)
    # 估值：pe 恒为 20 → 分位 = 100（当前值不小于窗口内所有值；lower_better 前的原始分位）
    assert got.loc["TESTF001", "pe_ttm_percentile"] == 100.0
    assert got.loc["TESTF001", "dividend_yield"] == 3.0
    assert got.loc["TESTF001", "volume_ratio"] == 1.8
    # 三风格分已生成
    for col in ("score_short_term", "score_balanced", "score_value"):
        assert not math.isnan(got.loc["TESTF001", col])
    # 两行业各 1 股 → 单股行业内 rank 恒 100 → 所有风格满分（因子齐全时）
    assert math.isclose(got.loc["TESTF001", "score_short_term"], 100.0, abs_tol=1e-6)

    # macd_golden_days：全程上行 → dif>dea 持续，值应为正
    assert got.loc["TESTF001", "macd_golden_days"] > 0
    assert got.loc["TESTF002", "macd_golden_days"] < 0

    await _cleanup(db, symbols)
```

⚠ 执行校准（写种子前必须先核对真实字段名）：
- 读 `app/data/schema/domains/daily_quotes.py`、`daily_indicators.py`、`money_flow.py`、`financial_data.py`、`basic_info.py`，对齐字段名（`main_net_inflow`/`turnover_rate`/`vol`/`report_period`/`statement_type` 等以 schema 为准）；`daily_quotes` 若必填 `period` 字段，种子补 `"period": "daily"`。
- financial_data 的最新期判断：引擎按 `report_period` 降序取最新一行 + 上年同期对比。若 schema 用 `fiscal_year`+`report_type` 表达同期，测试种子同步调整。
- `real_mongo_db` fixture 的返回值（db 句柄）与库名对齐 `tests/data/conftest.py`。

- [ ] **Step 4.2: 跑测试确认失败**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/data/factors/test_factor_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: app.data.factors.engine`

- [ ] **Step 4.3: 实现 engine.py**

```python
"""L0 因子计算引擎 — 读标准集合，批量向量化计算 19 因子并落库 stock_factor_scores。

设计约束（spec §7）：
- 全市场批量向量化（groupby + 滚动窗口），禁止逐股串行读库
- ST / 行情数据不足 60 日的股票剔除（数据不足同时覆盖「上市<60日」与「长期停牌」）
- 可选域（money_flow 等）当日缺失时对应因子置 NaN，不阻塞
- 交易日窗口从 daily_quotes distinct trade_date 取（数据驱动，避免日历错位）
- 流式游标读取控内存；indicators 只投影 4 列

对外入口：
- compute_factors(market) -> DataFrame   纯读+算（测试/诊断用）
- compute_and_store(market) -> dict      算+落库（调度入口）
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.data.factors.scoring import compute_style_scores, rank_factors_by_industry
from app.data.factors.strategy_config import get_factor_groups, get_style_weights
from app.data.schema.domains.factor_scores import FACTOR_FIELDS
from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    """EMA 递推（口径同 app/utils/indicators）。"""
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def _macd_golden_days(close: np.ndarray) -> float:
    """金叉状态天数：dif>dea 时为最近一次死叉以来的天数（正），反之为负。"""
    if len(close) < 35:  # EMA26+DEA9 预热不足，不可判
        return np.nan
    dif = _ema(close, 12) - _ema(close, 26)
    dea = _ema(dif, 9)
    above = dif[-1] > dea[-1]
    days = 0
    for i in range(len(close) - 1, -1, -1):
        if above and dif[i] <= dea[i]:
            break
        if not above and dif[i] >= dea[i]:
            break
        days += 1
    return float(days) if above else -float(days)


class FactorScoreEngine:
    QUOTE_WINDOW_TRADE_DAYS = 120      # 动量/趋势/量能窗口
    PERCENTILE_WINDOW_TRADE_DAYS = 500 # 估值分位窗口
    FLOW_WINDOW_TRADE_DAYS = 5         # 资金窗口
    MIN_QUOTE_ROWS = 60                # 数据不足剔除线

    async def compute_and_store(self, market: str = "CN") -> Dict:
        df = await self.compute_factors(market)
        if df.empty:
            return {"status": "skipped", "reason": "no_data", "rows": 0}
        records = self._to_records(df, market)
        written = await FactorScoresRepo().upsert_many(records, market=market)
        return {
            "status": "ok",
            "trade_date": str(df["trade_date"].iloc[0]),
            "symbols": int(len(records)),
            "written": int(written),
        }

    # ── 读取 ────────────────────────────────────────────────

    async def _recent_trade_dates(self, market: str, coll_name: str,
                                  n: int) -> List[str]:
        db = get_motor_db()
        distinct = await db[coll_name].distinct("trade_date")
        return sorted([d for d in distinct if d], reverse=True)[:n]

    async def _stream_find(self, market: str, domain: str, query: Dict,
                           projection: Dict) -> pd.DataFrame:
        """流式拉取为列式 DataFrame（避免 to_list 全量 dict 峰值内存）。"""
        db = get_motor_db()
        coll = db[get_collection_name(domain, market)]
        cols: Dict[str, list] = {}
        async for doc in coll.find(query, projection):
            for k, v in doc.items():
                if k == "_id":
                    continue
                cols.setdefault(k, []).append(v)
        return pd.DataFrame(cols)

    async def compute_factors(self, market: str = "CN") -> pd.DataFrame:
        quote_dates = await self._recent_trade_dates(
            market, get_collection_name("daily_quotes", market),
            self.QUOTE_WINDOW_TRADE_DAYS)
        if not quote_dates:
            logger.warning("daily_quotes 无数据，因子计算跳过")
            return pd.DataFrame()
        trade_date = quote_dates[0]
        quote_min = quote_dates[-1]

        # 基础信息（行业/名称/ST 过滤）
        basic = await self._stream_find(market, "basic_info", {}, {
            "symbol": 1, "name": 1, "industry": 1})
        if basic.empty:
            return pd.DataFrame()
        basic = basic[~basic["name"].astype(str).str.contains("ST", na=False)]

        # 行情窗口（复权因子 join）
        quotes = await self._stream_find(market, "daily_quotes", {
            "trade_date": {"$gte": quote_min},
            "period": {"$in": [None, "daily"]},
        }, {"symbol": 1, "trade_date": 1, "close": 1, "vol": 1,
            "amount": 1, "turnover_rate": 1})
        adj = await self._stream_find(market, "adj_factors", {
            "trade_date": {"$gte": quote_min}},
            {"symbol": 1, "trade_date": 1, "adj_factor": 1})
        if not adj.empty:
            quotes = quotes.merge(adj, on=["symbol", "trade_date"], how="left")
            quotes["close_adj"] = quotes["close"] * quotes["adj_factor"].fillna(1.0)
        else:
            quotes["close_adj"] = quotes["close"]

        quotes = quotes[quotes["symbol"].isin(set(basic["symbol"]))]
        quotes = quotes.sort_values(["symbol", "trade_date"])
        counts = quotes.groupby("symbol")["trade_date"].transform("count")
        quotes = quotes[counts >= self.MIN_QUOTE_ROWS]

        df = self._compute_momentum_trend_volume(quotes)
        df = df.merge(basic[["symbol", "name", "industry"]], on="symbol", how="left")

        # 估值分位 + 量比 + 股息（可选窗口数据不足时 NaN）
        df = df.join(self._compute_valuation(market, trade_date))
        # 资金（可选域）
        df = df.join(self._compute_flow(market, quote_dates))
        # 质量财务
        df = df.join(await self._compute_quality(market))

        # 评分
        df = rank_factors_by_industry(df, FACTOR_FIELDS)
        df = compute_style_scores(df, get_factor_groups(), get_style_weights())
        df["trade_date"] = trade_date
        return df

    # ── 因子计算（向量化） ─────────────────────────────────

    def _compute_momentum_trend_volume(self, q: pd.DataFrame) -> pd.DataFrame:
        g = q.sort_values(["symbol", "trade_date"]).groupby("symbol", sort=False)
        last = g.tail(1).set_index("symbol")

        def _ret(col: str, k: int) -> pd.Series:
            # k 日收益 = 末值 / k 个交易日前值 - 1（iloc[-(k+1)] 即 T-k 日）
            return (g[col].last() / g[col].apply(
                lambda s, _k=k: s.iloc[-(_k + 1)] if len(s) >= _k + 1 else np.nan)
                - 1.0) * 100.0

        out = pd.DataFrame(index=last.index)
        out["ret_5d"] = _ret("close_adj", 5)
        out["ret_20d"] = _ret("close_adj", 20)
        out["ret_60d"] = _ret("close_adj", 60)
        # 60 日新高距离（正=低于高点）
        high60 = g["close_adj"].apply(lambda s: s.tail(60).max())
        out["dist_to_60d_high"] = (high60 / last["close_adj"] - 1.0) * 100.0
        # 趋势
        ma20 = g["close_adj"].apply(lambda s: s.tail(20).mean())
        ma20_prev5 = g["close_adj"].apply(lambda s: s.tail(25).head(20).mean())
        out["bias_ma20"] = (last["close_adj"] / ma20 - 1.0) * 100.0
        out["ma20_slope"] = (ma20 / ma20_prev5 - 1.0) * 100.0
        out["macd_golden_days"] = pd.Series({
            sym: _macd_golden_days(grp["close_adj"].to_numpy(dtype=float))
            for sym, grp in g
        })
        # 量能
        tr = g["turnover_rate"]
        out["turnover_amp"] = tr.last() / tr.apply(lambda s: s.tail(21).head(20).mean())
        out["consecutive_vol_up_days"] = g["vol"].apply(
            lambda s: _consecutive_up_days(s.to_numpy(dtype=float)))
        return out

    async def _compute_valuation(self, market: str, trade_date: str) -> pd.DataFrame:
        dates = await self._recent_trade_dates(
            market, get_collection_name("daily_indicators", market),
            self.PERCENTILE_WINDOW_TRADE_DAYS)
        if not dates:
            return pd.DataFrame({
                "pe_ttm_percentile": pd.Series(dtype=float),
                "pb_percentile": pd.Series(dtype=float),
                "dividend_yield": pd.Series(dtype=float),
                "volume_ratio": pd.Series(dtype=float),
            })
        ind = await self._stream_find(market, "daily_indicators", {
            "trade_date": {"$gte": dates[-1]}},
            {"symbol": 1, "trade_date": 1, "pe_ttm": 1, "pb": 1,
             "dividend_yield": 1, "volume_ratio": 1})
        if ind.empty:
            return pd.DataFrame(columns=["pe_ttm_percentile", "pb_percentile",
                                         "dividend_yield", "volume_ratio"])
        g = ind.sort_values(["symbol", "trade_date"]).groupby("symbol", sort=False)

        def _pct_rank(series: pd.Series) -> float:
            cur = series.iloc[-1]
            valid = series.dropna()
            if pd.isna(cur) or valid.empty:
                return np.nan
            return float((valid <= cur).sum() / len(valid) * 100.0)

        out = pd.DataFrame(index=g.size().index)
        out["pe_ttm_percentile"] = g["pe_ttm"].apply(_pct_rank)
        out["pb_percentile"] = g["pb"].apply(_pct_rank)
        last = g.tail(1).set_index("symbol")
        out["dividend_yield"] = last["dividend_yield"]
        out["volume_ratio"] = last["volume_ratio"]
        return out

    async def _compute_flow(self, market: str, quote_dates: List[str]) -> pd.DataFrame:
        recent = quote_dates[: self.FLOW_WINDOW_TRADE_DAYS]
        mf = await self._stream_find(market, "money_flow", {
            "trade_date": {"$in": recent}},
            {"symbol": 1, "trade_date": 1, "main_net_inflow": 1})
        if mf.empty:
            return pd.DataFrame(columns=["main_inflow_5d", "main_inflow_5d_pct"])
        amt = await self._stream_find(market, "daily_quotes", {
            "trade_date": {"$in": recent}},
            {"symbol": 1, "amount": 1})
        amt_sum = amt.groupby("symbol")["amount"].sum()
        g = mf.groupby("symbol")["main_net_inflow"]
        out = pd.DataFrame(index=g.sum().index)
        out["main_inflow_5d"] = g.sum()
        out["main_inflow_5d_pct"] = (g.sum() / amt_sum * 100.0).dropna()
        return out

    async def _compute_quality(self, market: str) -> pd.DataFrame:
        fin = await self._stream_find(market, "financial_data", {}, {
            "symbol": 1, "report_period": 1, "net_profit": 1, "roe": 1,
            "gross_margin": 1, "debt_ratio": 1})
        if fin.empty:
            return pd.DataFrame(columns=["roe", "gross_margin", "net_profit_yoy",
                                         "debt_ratio"])
        rows = []
        for sym, grp in fin.groupby("symbol"):
            g = grp.sort_values("report_period")
            cur = g.iloc[-1]
            # 上年同期：report_period 去掉年份后相同的最早前一报告期（YYYY-MM-DD）
            rp = str(cur["report_period"])
            same_period_prev = None
            try:
                mmdd = rp[4:]
                prev_year = int(rp[:4]) - 1
                cand = g[g["report_period"].astype(str).str.endswith(mmdd)
                         & (g["report_period"].astype(str).str[:4].astype(int)
                            == prev_year)]
                if not cand.empty:
                    same_period_prev = cand.iloc[-1]
            except (ValueError, IndexError):
                pass
            yoy = np.nan
            if same_period_prev is not None:
                np_prev = same_period_prev.get("net_profit")
                np_cur = cur.get("net_profit")
                if np_prev and np_cur and np_prev > 0 and np_cur > 0:
                    yoy = (np_cur / np_prev - 1.0) * 100.0
            rows.append({
                "symbol": sym,
                "roe": cur.get("roe"),
                "gross_margin": cur.get("gross_margin"),
                "debt_ratio": cur.get("debt_ratio"),
                "net_profit_yoy": yoy,
            })
        return pd.DataFrame(rows).set_index("symbol")

    # ── 落库记录 ────────────────────────────────────────────

    def _to_records(self, df: pd.DataFrame, market: str) -> List[Dict]:
        now = now_tz().isoformat()
        keep = (["symbol", "trade_date", "name", "industry"]
                + FACTOR_FIELDS
                + [f"score_{s}" for s in ("short_term", "balanced", "value")])
        recs = []
        for row in df[keep].to_dict("records"):
            rec = {k: (None if pd.isna(v) else
                       (v.item() if isinstance(v, np.generic) else v))
                   for k, v in row.items() if pd.notna(v) or k in FACTOR_FIELDS}
            rec["market"] = market
            rec["data_source"] = "computed"
            rec["updated_at"] = now
            recs.append(rec)
        return recs


def _consecutive_up_days(vol: np.ndarray) -> int:
    """末位起连续放量天数（vol[i] > vol[i-1] 计一天；首日缩量即 0）。"""
    days = 0
    for i in range(len(vol) - 1, 0, -1):
        if vol[i] > vol[i - 1]:
            days += 1
        else:
            break
    return days
```

**实现说明**：`compute_factors` 里 `_compute_valuation`/`_compute_flow`/`_compute_quality` 三者相互独立，可串行 await（夜间时窗足够），也可 `asyncio.gather` 并发（可选优化）。

⚠ 执行校准：
- `daily_quotes` 查询的 `period` 过滤：先确认 schema 中 period 字段的实际取值（`"daily"`/None/缺省），对齐真实数据形状。
- `adj_factors` 无数据的环境（种子测试）：merge 走 how="left" + fillna(1.0) 路径已覆盖。
- `pandas` 版本兼容：`groupby.apply` 返回 DataFrame 的行为在 2.x 有 FutureWarning（include_groups），必要时对子列先 `droplevel`/传 `include_groups=False`；以 conda env 实际版本运行结果为准。

- [ ] **Step 4.4: 跑测试通过**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/data/factors/test_factor_engine.py -v`
Expected: PASS（手算断言全部命中；若有小数值偏差，核对窗口口径后修引擎或修断言——**不得改断言迁就实现**，先确认哪边口径对）

---

### Task 5: ComputeJob 基类 + CNFactorScoreJob + 调度接线

**Files:**
- Create: `app/data/scheduler/jobs/base/compute_job.py`
- Create: `app/data/scheduler/jobs/cn/factor_score_job.py`
- Modify: `app/data/scheduler/jobs/cn/__init__.py`
- Modify: `app/data/scheduler/jobs/cn/schedule.yaml`
- Test: `tests/data/scheduler/test_factor_score_job.py`

- [ ] **Step 5.1: 写失败测试**

```python
"""CNFactorScoreJob 集成测试：种子数据 → execute → factor_scores 落库。"""
import pytest

pytestmark = pytest.mark.requires_db

from app.data.scheduler.jobs.cn.factor_score_job import CNFactorScoreJob
from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name


async def test_factor_score_job_writes_output(real_mongo_db,
                                              seed_factor_inputs):
    """seed_factor_inputs fixture 来自顶层 tests/conftest.py 的共享种子助手。"""
    db = get_motor_db()
    coll = db[get_collection_name("factor_scores", "CN")]
    await coll.delete_many({"symbol": {"$regex": "^TESTF"}})

    job = CNFactorScoreJob()
    job.force_sync = True  # 跳过交易日检查（测试可能落在周末）
    result = await job.execute()

    assert result["status"] == "ok"
    docs = await coll.find({"symbol": {"$regex": "^TESTF"}}).to_list(None)
    assert len(docs) >= 2
    doc = docs[0]
    assert doc["trade_date"]
    assert "score_short_term" in doc and "ret_5d" in doc
    assert doc["data_source"] == "computed"

    await coll.delete_many({"symbol": {"$regex": "^TESTF"}})
```

⚠ 执行校准：`seed_factor_inputs` fixture 抽取 Task 4 测试里的 `_trade_dates/_seed/_cleanup` 到**顶层 `tests/conftest.py`**（不能放 `tests/data/factors/conftest.py`——pytest conftest 只对所在目录树可见，而 `tests/data/scheduler/` 与 `tests/services/screening/` 的用例都要用它）。fixture 名 `seed_factor_inputs`，内部种 2 只 TESTF 股票并 teardown 清理。

- [ ] **Step 5.2: 跑测试确认失败**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/data/scheduler/test_factor_score_job.py -v`
Expected: FAIL — 模块不存在

- [ ] **Step 5.3: 实现 ComputeJob 基类**

`app/data/scheduler/jobs/base/compute_job.py`：

```python
"""计算型任务基类 — 读库内标准域 → 批量计算 → 写结果域。

与 BaseSyncJob 的区别：不走 FallbackRouter/checkpoint 的外部数据同步流程，
输入全部来自库内标准集合。保留两件事以复用现有调度链路：
1. engine 的属性注入约定（sync_mode/preferred_source/dependencies/force_sync）
2. 非交易日跳过 + sync_events 终态事件（SchedulerMonitor/手动触发依赖）
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional

from app.data.scheduler.jobs.base.sync_job import _is_trading_day_or_skip  # ⚠ 校准

logger = logging.getLogger(__name__)


class ComputeJob(ABC):
    market: str = "CN"
    domain: str = ""

    # engine 注入属性（计算任务仅消费 force_sync；其余接收不使用）
    sync_mode: str = "incremental"
    preferred_source: Optional[str] = None
    dependencies: list = []
    force_sync: bool = False

    async def execute(self) -> Dict:
        from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

        await MetadataRepo().insert_event({
            "event_type": "SYNC_START", "market": self.market, "domain": self.domain,
        })
        # 非交易日跳过（手动 force 触发不跳）
        if not self.force_sync and await self._should_skip_non_trading_day():
            await MetadataRepo().insert_event({
                "event_type": "SYNC_SKIPPED", "market": self.market,
                "domain": self.domain, "reason": "non_trading_day",
            })
            return {"status": "skipped", "reason": "non_trading_day"}

        try:
            result = await self.compute()
            await MetadataRepo().insert_event({
                "event_type": "SYNC_SUCCESS", "market": self.market,
                "domain": self.domain, "result": result,
            })
            return result
        except Exception as e:
            # re-raise：调度引擎的 except 分支据此触发 monitor 失败回调（M14 语义）
            logger.error("计算任务失败 %s/%s: %s", self.market, self.domain, e,
                         exc_info=True)
            await MetadataRepo().insert_event({
                "event_type": "SYNC_FAILED", "market": self.market,
                "domain": self.domain, "error": str(e),
            })
            raise

    async def _should_skip_non_trading_day(self) -> bool:
        from app.data.core.market import is_trading_day
        from app.utils.timezone import now_tz
        # is_trading_day 是 async（app/data/core/market.py:31），必须 await
        return not await is_trading_day(self.market, now_tz().strftime("%Y-%m-%d"))

    @abstractmethod
    async def compute(self) -> Dict:
        """执行计算并返回摘要 dict。"""
```

⚠ 执行校准（写基类前先读 `app/data/scheduler/jobs/base/sync_job.py`）：
- 交易日判断直接复用 BaseSyncJob 的私有实现方式（把其 `_is_trading_day` 的实现原样内联或 import，取真实可行路径；上面的 `_is_trading_day_or_skip` import 是占位）。
- `MetadataRepo().insert_event` 的事件字段形状对齐 sync_job.py 的实际调用（字段名/必填项）。
- `is_trading_day` 的真实签名与所在模块以 `app/data/core/market.py` 为准；`market.py:31` 的 `target_date: Optional[date]` 是 date 类型注解——若实现要求 date 对象，把调用改为 `is_trading_day(self.market, now_tz().date())`（接受 str 则维持现状）。

- [ ] **Step 5.4: 实现 CNFactorScoreJob + 注册**

`app/data/scheduler/jobs/cn/factor_score_job.py`：

```python
"""A 股 L0 因子批算任务 — 每交易日收盘数据齐备后跑全市场因子计算。"""

from app.data.factors.engine import FactorScoreEngine
from app.data.scheduler.jobs.base.compute_job import ComputeJob


class CNFactorScoreJob(ComputeJob):
    market = "CN"
    domain = "factor_scores"

    async def compute(self) -> dict:
        return await FactorScoreEngine().compute_and_store("CN")
```

`app/data/scheduler/jobs/cn/__init__.py`：import 区加 `CNFactorScoreJob`，`_CN_JOBS` 列表加 `CNFactorScoreJob`（对齐既有条目写法）。

`schedule.yaml` 加（timezone/格式对齐文件内既有条目）：

```yaml
factor_scores:
  cron: "15 20 * * 1-5"
  timezone: "Asia/Shanghai"
  depends_on: [financial_data]
```

⚠ 执行校准：确认 schedule.yaml 既有条目的 timezone 字段写法（可能统一在文件头或每条目），保持一致；确认 `depends_on: [financial_data]` 的递归依赖不会在 financial_data 已跑过的当日重复全量同步（engine 的 checkpoint 增量语义会快速跳过——只确认行为存在即可，不必改）。

- [ ] **Step 5.5: 跑测试通过 + 调度注册不破坏既有测试**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/data/scheduler/test_factor_score_job.py tests/data/scheduler/ -v`
Expected: PASS（含既有调度测试无回归）

---

### Task 6: StrategyService（策略运行 + 每日推荐生成）

**Files:**
- Create: `app/services/screening/__init__.py`
- Create: `app/services/screening/strategy_service.py`
- Test: `tests/services/screening/test_strategy_service.py`

- [ ] **Step 6.1: 写失败测试**

```python
"""策略模板过滤/排序与每日推荐落库测试。"""
import pytest

pytestmark = pytest.mark.requires_db

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.services.screening.strategy_service import StrategyService


async def _seed_factors():
    """3 只股 × 同一 trade_date，量纲设计使 volume_breakout 只命中 2 只。"""
    await _cleanup()
    rows = [
        # 命中全部硬条件 + short_term 分最高
        {"symbol": "TESTS001", "trade_date": "2026-09-11", "name": "甲", "industry": "银行",
         "bias_ma20": 3.0, "turnover_amp": 2.0, "macd_golden_days": 3, "main_inflow_5d": 1e8,
         "score_short_term": 95.0, "score_balanced": 80.0, "score_value": 40.0, "ret_5d": 5.0},
        # 命中全部硬条件 + 分数次高
        {"symbol": "TESTS002", "trade_date": "2026-09-11", "name": "乙", "industry": "医药",
         "bias_ma20": 1.0, "turnover_amp": 1.6, "macd_golden_days": 2, "main_inflow_5d": 5e7,
         "score_short_term": 88.0, "score_balanced": 70.0, "score_value": 50.0, "ret_5d": 2.0},
        # 不命中：bias_ma20 < 0
        {"symbol": "TESTS003", "trade_date": "2026-09-11", "name": "丙", "industry": "电子",
         "bias_ma20": -1.0, "turnover_amp": 3.0, "macd_golden_days": 4, "main_inflow_5d": 2e8,
         "score_short_term": 99.0, "score_balanced": 90.0, "score_value": 60.0, "ret_5d": 8.0},
    ]
    await FactorScoresRepo().upsert_many(rows, market="CN")


async def _cleanup():
    db = get_motor_db()
    for d in ("factor_scores", "screening_recommendations"):
        await db[get_collection_name(d, "CN")].delete_many(
            {"symbol": {"$regex": "^TESTS"}} if d == "factor_scores"
            else {"strategy_id": {"$regex": "^(test|volume_breakout|trend_pullback|oversold_rebound|high_roe_low_val|quality_growth|steady_inflow)$"}})


async def test_list_strategies():  # 只读 YAML，不触 DB，无需 real_mongo_db
    strategies = await StrategyService().list_strategies()
    assert len(strategies) == 6
    default = [s for s in strategies if s["is_default"]]
    assert len(default) == 1 and default[0]["id"] == "volume_breakout"
    s0 = strategies[0]
    assert {"id", "name", "description", "style", "top_n", "is_default",
            "filters"} <= set(s0)


async def test_run_strategy_filters_and_sorts(real_mongo_db):
    await _seed_factors()
    result = await StrategyService().run_strategy("volume_breakout")
    assert result["total"] == 2
    assert [i["symbol"] for i in result["items"]] == ["TESTS001", "TESTS002"]
    item = result["items"][0]
    assert item["score"] == 95.0
    assert item["signals"]  # 命中信号非空
    assert result["as_of"] == "2026-09-11"
    await _cleanup()


async def test_run_strategy_extra_industry_filter(real_mongo_db):
    await _seed_factors()
    result = await StrategyService().run_strategy(
        "volume_breakout", extra_conditions=[{"field": "industry", "op": "==", "value": "银行"}])
    assert result["total"] == 1
    assert result["items"][0]["symbol"] == "TESTS001"
    await _cleanup()


async def test_generate_daily_recommendations_persists(real_mongo_db):
    await _seed_factors()
    summary = await StrategyService().generate_daily_recommendations()
    assert summary["strategies_written"] == 6
    db = get_motor_db()
    coll = db[get_collection_name("screening_recommendations", "CN")]
    doc = await coll.find_one({"strategy_id": "volume_breakout"})
    assert doc and doc["trade_date"] == "2026-09-11"
    assert doc["insight_status"] == "none"
    assert len(doc["items"]) == 2
    # 幂等：重跑不产生重复文档
    await StrategyService().generate_daily_recommendations()
    cnt = await coll.count_documents({"strategy_id": "volume_breakout"})
    assert cnt == 1
    await _cleanup()
```

- [ ] **Step 6.2: 跑测试确认失败**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/services/screening/test_strategy_service.py -v`
Expected: FAIL — 模块不存在

- [ ] **Step 6.3: 实现 strategy_service.py**

```python
"""选股策略运行服务 — L0 消费层（读 factor_scores，过滤+排序+落库推荐）。

边界：只经 DataInterface/repo 读标准库，不直连数据源；
LLM 相关（L1）在 insight_service，本服务不触 LLM（自动研判由
generate_daily_recommendations 的调用方（worker job）串联，见 Task 8/9）。
"""

import logging
from typing import Any, Dict, List, Optional

from app.data.core.interface import DataInterface
from app.data.factors.strategy_config import get_strategies
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.data.storage.mongo.repositories.screening_recommendations_repo import (
    ScreeningRecommendationsRepo,
)
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)

_OPS = {
    ">": lambda v, t: v is not None and v > t,
    ">=": lambda v, t: v is not None and v >= t,
    "<": lambda v, t: v is not None and v < t,
    "<=": lambda v, t: v is not None and v <= t,
    "==": lambda v, t: v is not None and v == t,
    "!=": lambda v, t: v is not None and v != t,
    "between": lambda v, t: v is not None and t[0] <= v <= t[1],
}

# 策略结果条目里回传给前端的因子子集（控制响应体大小）
_KEY_FACTORS = [
    "ret_5d", "ret_20d", "bias_ma20", "ma20_slope", "macd_golden_days",
    "turnover_amp", "main_inflow_5d_pct", "pe_ttm_percentile", "roe",
    "net_profit_yoy",
]


class StrategyService:

    async def list_strategies(self) -> List[Dict[str, Any]]:
        strategies = []
        for s in get_strategies():
            strategies.append({
                "id": s["id"], "name": s["name"], "description": s.get("description", ""),
                "style": s["style"], "top_n": s.get("top_n", 30),
                "is_default": bool(s.get("default")), "filters": s.get("filters", []),
            })
        return strategies

    async def _load_latest_factors(self) -> tuple:
        trade_date = await FactorScoresRepo().get_latest_trade_date("CN")
        if not trade_date:
            return []
        result = await DataInterface.get_instance().screen(
            "CN", "factor_scores", filters={"trade_date": trade_date}, limit=0)
        items = result.get("items", [])
        return items, trade_date

    async def run_strategy(self, strategy_id: str,
                           extra_conditions: Optional[List[Dict]] = None,
                           limit: Optional[int] = None) -> Dict[str, Any]:
        strategy = next((s for s in get_strategies() if s["id"] == strategy_id), None)
        if not strategy:
            raise ValueError(f"未知策略模板: {strategy_id}")
        loaded = await self._load_latest_factors()
        if not loaded:
            return {"total": 0, "items": [], "as_of": None, "strategy": strategy_id}
        items, trade_date = loaded

        passed = [r for r in items if self._match(r, strategy.get("filters", []))
                  and self._match(r, extra_conditions or [])]

        style = strategy["style"]
        passed.sort(key=lambda r: (r.get(f"score_{style}") is not None,
                                   r.get(f"score_{style}") or 0.0), reverse=True)
        top_n = limit or strategy.get("top_n", 30)
        top = passed[:top_n]

        return {
            "total": len(passed),
            "items": [self._to_item(r, strategy) for r in top],
            "as_of": trade_date,
            "strategy": strategy_id,
            "style": style,
        }

    async def generate_daily_recommendations(self) -> Dict[str, Any]:
        """对全部模板跑 Top-N 并落库当日推荐（幂等覆盖）。"""
        written = 0
        for s in get_strategies():
            try:
                result = await self.run_strategy(s["id"])
                if not result["as_of"]:
                    logger.warning("factor_scores 无数据，跳过 %s", s["id"])
                    continue
                await ScreeningRecommendationsRepo().upsert_daily({
                    "strategy_id": s["id"],
                    "trade_date": result["as_of"],
                    "strategy_name": s["name"],
                    "style": s["style"],
                    "total": result["total"],
                    "items": result["items"],
                    "insight_status": "none",
                    "generated_at": now_tz().isoformat(),
                    "data_source": "computed",
                }, market="CN")
                written += 1
            except Exception as e:
                # 单模板失败不阻塞其余模板（spec §13 降级）
                logger.error("每日推荐生成失败 %s: %s", s["id"], e, exc_info=True)
        logger.info("每日推荐生成完成：%d/%d 个模板", written, len(get_strategies()))
        return {"strategies_written": written}

    # ── 内部 ────────────────────────────────────────────────

    @staticmethod
    def _match(record: Dict, conditions: List[Dict]) -> bool:
        for cond in conditions:
            field, op, target = cond.get("field"), cond.get("op"), cond.get("value")
            fn = _OPS.get(op)
            if fn is None:
                logger.warning("未知操作符 %s，条件忽略: %s", op, cond)
                continue
            if not fn(record.get(field), target):
                return False
        return True

    @staticmethod
    def _to_item(r: Dict, strategy: Dict) -> Dict:
        factors = {k: r.get(k) for k in _KEY_FACTORS if r.get(k) is not None}
        signals = [
            f"{c['field']} {c['op']} {c['value']}"
            for c in strategy.get("filters", []) if r.get(c["field"]) is not None
        ]
        style = strategy["style"]
        return {
            "symbol": r.get("symbol"),
            "code": r.get("symbol"),  # 前端既有列用 code（兼容）
            "name": r.get("name"),
            "industry": r.get("industry"),
            "score": r.get(f"score_{style}"),
            "score_short_term": r.get("score_short_term"),
            "score_balanced": r.get("score_balanced"),
            "score_value": r.get("score_value"),
            "factors": factors,
            "signals": signals,
        }
```

`app/services/screening/__init__.py`：

```python
"""选股域服务（策略运行 / L1 研判）。"""
```

- [ ] **Step 6.4: 跑测试通过**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/services/screening/test_strategy_service.py -v`
Expected: PASS（4 个用例）

---

### Task 7: Router /strategies + /run 升级

**Files:**
- Modify: `app/routers/screening.py`
- Test: `tests/routers/test_screening_strategies_api.py`

- [ ] **Step 7.1: 写失败测试**

⚠ 执行校准：先看 `tests/` 下既有 router 测试的客户端构造方式（httpx AsyncClient + app lifespan 或 TestClient），完全复用其模式与 fixture；下面以「服务层直测 + 路由薄封装」思路写，若项目有标准 router 测试基建则改为端到端调用。

```python
"""/api/screening/strategies 与 /run 策略路径测试。"""
import pytest

pytestmark = pytest.mark.requires_db

from app.services.screening.strategy_service import StrategyService
# ⚠ 若 tests/routers 既有基建支持端到端，则改为 HTTP 调用并断言 success 信封


async def test_strategies_listing_shape():
    strategies = await StrategyService().list_strategies()
    assert strategies and strategies[0]["id"]

async def test_run_via_strategy_path():
    # 种子 → StrategyService.run_strategy（等价于 router 策略分支的全部逻辑）
    ...  # 复用因子种子/清理助手（统一放顶层 tests/conftest.py，见 Task 5 校准）
```

router 响应信封断言（若有 HTTP 基建）：`resp.json()["success"] is True` 且数据在 `resp.json()["data"]`（router-response-must-wrap 项目规则）。

- [ ] **Step 7.2: 修改 router**

`app/routers/screening.py` 在现有 import 基础上追加：

```python
from app.services.screening.strategy_service import StrategyService
```

`ScreeningRequest` 追加字段：

```python
    strategy_id: Optional[str] = Field(None, description="策略模板 id；传入时走 L0 因子策略路径")
```

`run_screening` 头部插入策略分支（原逻辑完全不动）：

```python
        if req.strategy_id:
            svc = StrategyService()
            # 复用现有条件转换：自定义叠加条件（行业/市值等）走同一 DSL
            extra = _convert_legacy_conditions_to_new_format(req.conditions)
            extra = [{"field": c.field, "op": c.operator, "value": c.value}
                     for c in extra]
            result = await svc.run_strategy(req.strategy_id,
                                            extra_conditions=extra or None,
                                            limit=req.limit)
            return ok({
                "total": result["total"],
                "items": result["items"],
                "as_of": result["as_of"],
                "strategy": result["strategy"],
                "style": result["style"],
            })
```

新增端点（放在 /industries 之前）：

```python
@router.get("/strategies")
async def list_strategies(user: dict = Depends(get_current_user)):
    """策略模板列表（YAML 驱动，0 token）。"""
    try:
        return ok({"strategies": await StrategyService().list_strategies()})
    except Exception as e:
        logger.error("[list_strategies] 失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500,
                            detail=safe_error_message(e, "获取策略列表失败"))
```

注意：strategy 分支里 `_convert_legacy_conditions_to_new_format` 返回 `ScreeningCondition` 对象（`operator` 属性），转 dict 时键名用 `op`（服务层 `_OPS` 的键）。额外校验：叠加条件 field 若不在 factor 字段+`industry` 白名单内则忽略（防止任意字段过滤），在 router 分支加：

```python
            allowed = set(FACTOR_FIELDS) | {"industry"}
            extra = [c for c in extra if c["field"] in allowed]
```

（`FACTOR_FIELDS` 从 `app.data.schema.domains.factor_scores` import。）

- [ ] **Step 7.3: 跑测试 + lint**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/routers/test_screening_strategies_api.py tests/lint/test_router_conventions.py -v`
Expected: PASS（router 约定测试：prefix/tags/无 Mongo 直连均合规）

---

### Task 8: 每日推荐 worker 接线 + GET /daily

**Files:**
- Modify: `app/worker/scheduler_setup.py`
- Modify: `app/routers/screening.py`
- Test: `tests/services/screening/test_daily_endpoint.py`

- [ ] **Step 8.1: 写失败测试**

```python
"""GET /daily 读取落库推荐（含数据截至标注，经服务层）。"""
import pytest

pytestmark = pytest.mark.requires_db

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.screening_recommendations_repo import (
    ScreeningRecommendationsRepo,
)
from app.services.screening.strategy_service import StrategyService


async def test_daily_read_seeded(real_mongo_db):
    db = get_motor_db()
    coll = db[get_collection_name("screening_recommendations", "CN")]
    await coll.delete_many({"strategy_id": "test_daily"})
    await ScreeningRecommendationsRepo().upsert_daily({
        "strategy_id": "test_daily", "trade_date": "2026-09-11",
        "strategy_name": "测试", "style": "short_term", "total": 1,
        "items": [{"symbol": "TESTD001", "name": "x", "score": 90.0,
                   "factors": {}, "signals": [], "insight": None}],
        "insight_status": "none",
    }, market="CN")

    result = await StrategyService().get_daily("test_daily")
    assert result["trade_date"] == "2026-09-11"
    assert result["strategies"][0]["items"][0]["symbol"] == "TESTD001"

    result_all = await StrategyService().get_daily()
    assert any(s["strategy_id"] == "test_daily" for s in result_all["strategies"])

    await coll.delete_many({"strategy_id": "test_daily"})
```

（若 Task 7 决定采用 HTTP 端到端基建，本测试同样改为调 `GET /api/screening/daily?strategy_id=test_daily` 并断言 success 信封。）

- [ ] **Step 8.2: router 加 /daily（经服务层，router 不新增 storage import）**

`strategy_service.py` 追加读方法：

```python
    async def get_daily(self, strategy_id: Optional[str] = None) -> Dict[str, Any]:
        """读最新交易日落库推荐（router /daily 委托此方法，避免 routers 触 storage）。"""
        repo = ScreeningRecommendationsRepo()
        if strategy_id:
            docs = [d for d in [await repo.get_latest_by_strategy("CN", strategy_id)] if d]
        else:
            latest = await repo.get_latest_any("CN")
            docs = await repo.list_strategies_on_date("CN", latest["trade_date"]) if latest else []
        trade_date = docs[0]["trade_date"] if docs else None
        return {
            "trade_date": trade_date,
            "strategies": [
                {"strategy_id": d["strategy_id"], "strategy_name": d.get("strategy_name"),
                 "style": d.get("style"), "total": d.get("total"),
                 "items": d.get("items", []), "insight_status": d.get("insight_status"),
                 "generated_at": d.get("generated_at")}
                for d in docs
            ],
        }
```

`app/routers/screening.py` 追加端点：

```python
@router.get("/daily")
async def get_daily_recommendations(
    strategy_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """每日推荐（读落库结果，0 token）。返回最新交易日全部/指定策略。"""
    try:
        return ok(await StrategyService().get_daily(strategy_id))
    except Exception as e:
        logger.error("[get_daily_recommendations] 失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500,
                            detail=safe_error_message(e, "获取每日推荐失败"))
```

（Step 8.1 测试改为调 `StrategyService().get_daily()` 断言结构，不直触 repo。）

- [ ] **Step 8.3: worker 注册每日推荐**

`app/worker/scheduler_setup.py` 的 `register_jobs` 内（`cn_integrity_check` 注册之后）追加：

```python
    # ── 选股每日推荐（20:15 factor_scores 批算完成后）──
    add_resilient_job(
        scheduler, _run_screening_daily_recommendations,
        CronTrigger(hour=20, minute=45, timezone=tz),
        id="screening_daily_recommendations",
        name="选股每日推荐生成",
    )
    logger.info("选股每日推荐任务已注册: 每交易日 20:45")
```

模块级函数（放在 `register_jobs` 外，与 `_run_cn_integrity_check` 同区）：

```python
async def _run_screening_daily_recommendations():
    """每日推荐生成（幂等覆盖；失败只记日志不重试——次日自然覆盖）。

    自动 L1 研判的串联在 Task 9（insight_service 落地后）追加到本函数尾部。
    """
    try:
        from app.services.screening.strategy_service import StrategyService
        summary = await StrategyService().generate_daily_recommendations()
        logger.info("选股每日推荐完成: %s", summary)
    except Exception as e:
        logger.error("选股每日推荐生成失败: %s", e, exc_info=True)
```

⚠ 执行校准：`_run_cn_integrity_check` 的定义位置与写法（async def + 全 try/except 包裹）对齐后放置；cron 分钟避开整点/半点拥堵可取 `minute=47`（保持与 factor_scores 20:15 至少 30 分钟间隔）。

- [ ] **Step 8.4: 跑测试通过**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/services/screening/test_daily_endpoint.py -v`
Expected: PASS

---

### Task 9: InsightService（L1 研判：配额 + prompt 覆盖 + 单次 LLM + 落库）+ POST /insights

**Files:**
- Create: `app/services/screening/insight_service.py`
- Modify: `app/routers/screening.py`
- Test: `tests/services/screening/test_insight_service.py`（非 AI：配额/设置合并/落库路径）
- Test: `tests/services/screening/test_insight_service_ai.py`（AI 标记，真调用）

- [ ] **Step 9.1: 写失败测试（非 AI 部分）**

```python
"""L1 研判服务非 AI 路径测试：设置合并 / 配额边界 / 失败审计。"""
import pytest

pytestmark = pytest.mark.requires_db

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.screening_insights_repo import (
    ScreeningInsightsRepo,
)
from app.services.screening.insight_service import (
    ScreeningInsightService, QuotaExceededError, DEFAULT_INSIGHT_SYSTEM_PROMPT,
)


async def _cleanup():
    db = get_motor_db()
    await db[get_collection_name("screening_insights", "CN")].delete_many(
        {"user_id": "test_quota_user"})


async def test_settings_defaults_and_override(real_mongo_db):
    svc = ScreeningInsightService()
    settings = await svc.get_settings()
    assert settings["daily_enabled"] is False          # 默认关（用户核心要求）
    assert settings["manual_daily_limit"] == 10
    assert settings["prompt"] == DEFAULT_INSIGHT_SYSTEM_PROMPT


async def test_quota_boundary(real_mongo_db):
    await _cleanup()
    svc = ScreeningInsightService()
    repo = ScreeningInsightsRepo()
    from app.utils.timezone import now_tz
    today = now_tz().strftime("%Y-%m-%d")  # 与 quota_remaining 的「今日」同口径
    # 已用 1 次（写一条 done 记录）
    await repo.insert_one({"user_id": "test_quota_user", "status": "done",
                           "created_at": f"{today}T09:00:00", "symbols": [],
                           "insights": {}})
    remaining = await svc.quota_remaining("test_quota_user")
    assert remaining == 9
    # failed 不占配额
    await repo.insert_one({"user_id": "test_quota_user", "status": "failed",
                           "created_at": f"{today}T10:00:00", "symbols": [],
                           "insights": {}})
    assert await svc.quota_remaining("test_quota_user") == 9
    await _cleanup()


async def test_generate_manual_records_audit_even_on_failure(real_mongo_db):
    """LLM 失败：落 status=failed 审计记录且不扣配额，异常向上抛。

    全真 I/O 禁 mock —— 本用例不 patch LLM，而是传入不存在的 symbol 让
    服务在调 LLM 前走「因子取不到」真实失败分支。
    """
    await _cleanup()
    svc = ScreeningInsightService()
    with pytest.raises(Exception):
        await svc.generate_manual(symbols=["TESTNOSUCH"], user_id="test_quota_user")
    db = get_motor_db()
    coll = db[get_collection_name("screening_insights", "CN")]
    doc = await coll.find_one({"user_id": "test_quota_user", "status": "failed"})
    assert doc is not None  # 审计记录存在
    assert await svc.quota_remaining("test_quota_user") == 10  # 未扣配额
    await _cleanup()
```

（`quota_remaining` 的「今日」口径用 `now_tz().strftime("%Y-%m-%d")` 动态取当天，测试 seed 的 `today` 同样动态生成。）

AI 真调用测试 `test_insight_service_ai.py`：

```python
"""L1 研判真实 LLM 调用测试（标记 ai，默认集跳过；需配置好 analyst 模型）。"""
import pytest

pytestmark = [pytest.mark.ai, pytest.mark.requires_db]

from app.services.screening.insight_service import ScreeningInsightService


async def test_generate_manual_real_call(real_mongo_db, seed_factor_inputs):
    svc = ScreeningInsightService()
    result = await svc.generate_manual(symbols=["TESTF001"], user_id="test_ai_user")
    assert result["insights"], "应返回每 symbol 一段研判"
    text = result["insights"]["TESTF001"]
    assert isinstance(text, str) and len(text) >= 20
    assert result["quota_remaining"] >= 0
```

- [ ] **Step 9.2: 跑测试确认失败**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/services/screening/test_insight_service.py -v`
Expected: FAIL — 模块不存在

- [ ] **Step 9.3: 实现 insight_service.py**

```python
"""L1 快速研判服务 — 独立单次 LLM 调用（不经过 engine/工作流）。

成本边界（spec §4/§10）：
- 手动路径：按钮触发，按 (user_id, 自然日) 配额限制，失败不扣配额但落审计
- 每日自动路径：system_settings 开关 screening_daily_insight_enabled（默认关），
  调度天然每日至多 1 次，写 screening_recommendations 条目级 insight
- 前端只传 symbols；服务端按 symbols+最新 trade_date 从 factor_scores 重取因子，
  不信任前端传入的因子值
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.data.core.interface import DataInterface
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.data.storage.mongo.repositories.screening_insights_repo import (
    ScreeningInsightsRepo,
)
from app.data.storage.mongo.repositories.screening_recommendations_repo import (
    ScreeningRecommendationsRepo,
)
from app.llm.core.types import Message, Role
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)

DEFAULT_INSIGHT_SYSTEM_PROMPT = """你是一名严谨的量化研究员。用户给你一批通过多因子策略
初筛的候选股票及其关键因子数据。请对每一只股票输出 2-3 句中文研判：
第 1 句概括核心逻辑（因子数据支持的选股理由）；第 2 句指出主要风险；
第 3 句（可选）说明适合什么投资风格/场景。

要求：
- 只基于给出的因子数据做客观解读，不编造数据里没有的信息
- 禁止给出任何买卖指令、目标价或仓位建议
- 输出必须是合法 JSON：{"insights": {"<symbol>": "<研判文本>", ...}}，
  每只入参 symbol 都要有对应键，不要输出 JSON 以外的任何内容"""

SETTING_DAILY_ENABLED = "screening_daily_insight_enabled"
SETTING_MANUAL_LIMIT = "screening_manual_insight_daily_limit"
SETTING_MODEL = "screening_insight_model"
SETTING_PROMPT = "screening_insight_prompt"

DEFAULT_MANUAL_LIMIT = 10
MAX_SYMBOLS_PER_CALL = 30
_INSIGHT_FACTORS = [
    "ret_5d", "ret_20d", "bias_ma20", "macd_golden_days", "turnover_amp",
    "main_inflow_5d_pct", "pe_ttm_percentile", "dividend_yield",
    "roe", "net_profit_yoy", "debt_ratio",
]


class QuotaExceededError(Exception):
    """手动研判超出当日配额。"""


class ScreeningInsightService:

    # ── 设置 ────────────────────────────────────────────────

    async def get_settings(self) -> Dict[str, Any]:
        from app.services.config import get_config_service  # ⚠ 校准：门面导出名
        try:
            stored = await get_config_service().get_system_settings() or {}
        except Exception as e:
            logger.warning("读取 system_settings 失败，用默认值: %s", e)
            stored = {}
        return {
            "daily_enabled": bool(stored.get(SETTING_DAILY_ENABLED, False)),
            "manual_daily_limit": int(stored.get(SETTING_MANUAL_LIMIT,
                                                 DEFAULT_MANUAL_LIMIT)),
            "model": stored.get(SETTING_MODEL) or None,
            "prompt": stored.get(SETTING_PROMPT) or DEFAULT_INSIGHT_SYSTEM_PROMPT,
        }

    async def quota_remaining(self, user_id: str) -> int:
        settings = await self.get_settings()
        today = now_tz().strftime("%Y-%m-%d")
        used = await ScreeningInsightsRepo().count_today_done(user_id, today)
        return max(0, settings["manual_daily_limit"] - used)

    # ── 手动路径 ────────────────────────────────────────────

    async def generate_manual(self, symbols: List[str], user_id: str,
                              strategy_id: Optional[str] = None,
                              conditions_digest: Optional[str] = None) -> Dict[str, Any]:
        symbols = [s for s in symbols if s][:MAX_SYMBOLS_PER_CALL]
        if not symbols:
            raise ValueError("symbols 不能为空")

        remaining = await self.quota_remaining(user_id)
        if remaining <= 0:
            raise QuotaExceededError("今日手动研判配额已用完")

        settings = await self.get_settings()
        audit = {
            "created_at": now_tz().isoformat(),
            "trigger": "manual", "user_id": user_id,
            "trade_date": None, "strategy_id": strategy_id,
            "conditions_digest": conditions_digest,
            "symbols": symbols, "insights": {},
            "model": settings["model"] or "analyst_default",
            "tokens_used": None, "status": "pending",
        }
        try:
            rows, trade_date = await self._fetch_factor_rows(symbols)
            if not rows:
                raise ValueError("factor_scores 中无这些 symbol 的最新因子数据")
            prompt = self._build_prompt(rows)
            text, usage = await self._call_llm(prompt, settings)
            insights = self._parse_json_insights(text, symbols)
            audit.update({
                "trade_date": trade_date, "insights": insights,
                "tokens_used": usage, "status": "done",
            })
            await ScreeningInsightsRepo().insert_one(audit)
            return {
                "insights": insights, "trade_date": trade_date,
                "quota_remaining": remaining - 1,
            }
        except QuotaExceededError:
            raise
        except Exception as e:
            # 失败审计：不扣配额（count 只数 done），向上抛给 API 层报错
            audit["status"] = "failed"
            audit["error"] = str(e)[:500]
            try:
                await ScreeningInsightsRepo().insert_one(audit)
            except Exception as log_err:
                logger.error("研判失败审计落库异常: %s", log_err, exc_info=True)
            raise

    # ── 每日自动路径（开关控制） ─────────────────────────────

    async def run_daily_auto_if_enabled(self) -> Optional[Dict[str, Any]]:
        """开关开启时对默认策略 Top-20 生成研判并写回当日推荐记录。

        开关关闭返回 None（调用方以此区分「未启用」与「执行结果」）。
        """
        settings = await self.get_settings()
        if not settings["daily_enabled"]:
            return None
        repo = ScreeningRecommendationsRepo()
        from app.data.factors.strategy_config import get_default_strategy
        default_id = get_default_strategy()["id"]
        doc = await repo.get_latest_by_strategy("CN", default_id)
        if not doc or not doc.get("items"):
            return {"status": "skipped", "reason": "no_recommendations"}
        symbols = [it["symbol"] for it in doc["items"][:20]]
        try:
            rows, _ = await self._fetch_factor_rows(symbols)
            prompt = self._build_prompt(rows)
            text, usage = await self._call_llm(prompt, settings)
            insights = self._parse_json_insights(text, symbols)
            for it in doc["items"]:
                if it["symbol"] in insights:
                    it["insight"] = insights[it["symbol"]]
            await repo.upsert_daily({
                **doc, "insight_status": "done",
                "insight_generated_at": now_tz().isoformat(),
            }, market="CN")
            return {"status": "done", "symbols": len(insights),
                    "tokens_used": usage}
        except Exception as e:
            # 失败：列表保留，标记 failed，不重试（spec §13）
            logger.error("每日自动研判失败: %s", e, exc_info=True)
            await repo.upsert_daily({**doc, "insight_status": "failed"},
                                    market="CN")
            return {"status": "failed", "error": str(e)[:200]}

    # ── 内部 ────────────────────────────────────────────────

    async def _fetch_factor_rows(self, symbols: List[str]):
        trade_date = await FactorScoresRepo().get_latest_trade_date("CN")
        if not trade_date:
            return [], None
        result = await DataInterface.get_instance().screen(
            "CN", "factor_scores",
            filters={"trade_date": trade_date, "symbol": {"$in": symbols}},
            limit=0)
        return result.get("items", []), trade_date

    @staticmethod
    def _build_prompt(rows: List[Dict]) -> str:
        lines = ["以下是通过多因子策略初筛的候选股因子摘要（数据截至最新交易日）："]
        for r in rows:
            parts = [f"股票 {r.get('symbol')} {r.get('name') or ''} "
                     f"行业:{r.get('industry') or '未知'} "
                     f"短线分:{r.get('score_short_term')} "
                     f"均衡分:{r.get('score_balanced')} "
                     f"价值分:{r.get('score_value')}"]
            kv = [f"{k}={r.get(k)}" for k in _INSIGHT_FACTORS
                  if r.get(k) is not None]
            parts.append("关键因子: " + ", ".join(kv))
            lines.append("- " + " ".join(parts))
        lines.append("请按系统指令对每只股票输出研判，返回 JSON。")
        return "\n".join(lines)

    async def _call_llm(self, prompt: str, settings: Dict[str, Any]):
        """单次 chat 调用：优先设置指定模型，否则 analyst 默认客户端。"""
        from app.llm.providers import get_engine_clients, resolve_task_override_bundle
        from app.llm.retry import with_retry

        client = None
        model_name = settings.get("model")
        if model_name:
            try:
                bundle = await resolve_task_override_bundle(model_name)
                client = bundle.primary
            except Exception as e:
                logger.warning("研判模型 %s 解析失败，回落 analyst 默认: %s",
                               model_name, e)
        if client is None:
            clients = await get_engine_clients()
            bundle = clients.get("analyst")
            if bundle is None:
                raise RuntimeError("未配置任何 LLM 模型（请先在设置页配置）")
            client = bundle.primary

        resp = await with_retry(
            lambda: client.chat(
                [Message(role=Role.USER, content=prompt)],
                system=settings["prompt"],
                tools=None,
                max_tokens=4000,
            ),
            max_retries=2,
        )
        text = resp.text() or ""
        usage = getattr(resp, "usage", None)
        tokens = None
        if usage is not None:
            tokens = (getattr(usage, "input_tokens", 0)
                      or getattr(usage, "prompt_tokens", 0)) + \
                     (getattr(usage, "output_tokens", 0)
                      or getattr(usage, "completion_tokens", 0))
        return text, tokens

    @staticmethod
    def _parse_json_insights(text: str, symbols: List[str]) -> Dict[str, str]:
        """解析 LLM JSON 输出（容忍 ```json 围栏）；缺失 symbol 补提示文本。"""
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        payload = {}
        if m:
            try:
                data = json.loads(m.group(0))
                payload = data.get("insights", data)
            except json.JSONDecodeError:
                logger.warning("研判 JSON 解析失败，回退原文按行拆分")
        if not payload:
            # 降级：整段文本作为所有 symbol 的统一研判
            payload = {s: cleaned for s in symbols}
        return {s: str(payload.get(s, "（模型未返回该股研判）")) for s in symbols}
```

⚠ 执行校准：
- `from app.services.config import get_config_service`：读 `app/services/config/__init__.py:99-102` 确认门面对象的实际获取方式（可能是模块级单例函数或类导出）。
- `resolve_task_override_bundle(model)` 签名（`app/llm/providers.py:378`）——参数可能还需 provider/role；对齐后调整调用，返回对象的 primary 客户端属性名以 `EngineClientBundle` 定义为准（`providers.py:56`）。
- `resp.usage` 的字段名读 `app/llm/core/` 的 ChatResponse 定义；没有 usage 就保持 None（审计字段尽力而为）。

- [ ] **Step 9.4: router 加 /insights**

```python
class InsightRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1, max_length=30,
                               description="待研判 symbol 列表（服务端重取因子）")
    strategy_id: Optional[str] = None
    conditions_digest: Optional[str] = Field(None, max_length=200)


@router.post("/insights")
async def generate_insights(req: InsightRequest,
                            user: dict = Depends(get_current_user)):
    """L1 手动快速研判：1 次 LLM 调用，按用户日配额限流。"""
    try:
        from app.services.screening.insight_service import (
            ScreeningInsightService, QuotaExceededError,
        )
        svc = ScreeningInsightService()
        result = await svc.generate_manual(
            symbols=req.symbols, user_id=str(user.get("id") or user.get("username")),
            strategy_id=req.strategy_id,
            conditions_digest=req.conditions_digest,
        )
        return ok(result)
    except QuotaExceededError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("[generate_insights] 失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500,
                            detail=safe_error_message(e, "AI 快速研判失败"))
```

- [ ] **Step 9.5: 跑非 AI 测试通过**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/services/screening/ -v -m "not ai"`
Expected: PASS

- [ ] **Step 9.6: AI 测试（有模型配置时验证一次）**

Run: `C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/services/screening/test_insight_service_ai.py -v -m ai`
Expected: PASS（若本机无可用模型配置，记录跳过原因，交付时说明）

- [ ] **Step 9.7: 自动研判串联到每日 worker job（补 Task 8 的 `_run_screening_daily_recommendations`）**

insight_service 落地后，在 `app/worker/scheduler_setup.py` 的 `_run_screening_daily_recommendations` try 块尾部（推荐生成 log 之后）追加：

```python
        # 自动 L1 研判（默认关）：由 insight 服务内部读开关判定，未启用返回 None
        try:
            from app.services.screening.insight_service import ScreeningInsightService
            auto = await ScreeningInsightService().run_daily_auto_if_enabled()
            if auto is not None:
                logger.info("选股每日自动研判完成: %s", auto)
        except Exception as e:
            logger.error("选股每日自动研判失败（不影响推荐列表）: %s", e, exc_info=True)
```

验证：`C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/worker/ -q`（若存在 worker 相关测试目录）+ `ruff check app/worker/`。

---

### Task 10: 前端 API 扩展

**Files:**
- Modify: `frontend/src/api/screening.ts`

- [ ] **Step 10.1: 扩展类型与方法**（追加到现有文件；`ScreeningRunReq` 加 `strategy_id?: string | null`）

```typescript
// ── 策略模板（L0）──
export interface StrategyFilter { field: string; op: string; value: any }
export interface StrategyInfo {
  id: string
  name: string
  description: string
  style: 'short_term' | 'balanced' | 'value'
  top_n: number
  is_default: boolean
  filters: StrategyFilter[]
}
export interface StrategyRunItem {
  symbol: string
  code: string
  name?: string
  industry?: string
  score?: number | null
  score_short_term?: number | null
  score_balanced?: number | null
  score_value?: number | null
  factors: Record<string, number>
  signals: string[]
  insight?: string | null
}
export interface StrategyRunResp {
  total: number
  items: StrategyRunItem[]
  as_of: string | null
  strategy: string
  style: string
}
export interface DailyRecommendation {
  strategy_id: string
  strategy_name: string
  style: string
  total: number
  insight_status: 'none' | 'pending' | 'done' | 'failed'
  generated_at?: string
  items: StrategyRunItem[]
}
export interface DailyResp { trade_date: string | null; strategies: DailyRecommendation[] }
export interface InsightReq {
  symbols: string[]
  strategy_id?: string | null
  conditions_digest?: string | null
}
export interface InsightResp {
  insights: Record<string, string>
  trade_date: string | null
  quota_remaining: number
}

// ScreeningRunReq 追加字段
// strategy_id?: string | null
```

方法（并入现有 `screeningApi` 对象）：

```typescript
  getStrategies: () =>
    ApiClient.get<{ strategies: StrategyInfo[] }>('/api/screening/strategies'),
  getDaily: (strategyId?: string) =>
    ApiClient.get<DailyResp>('/api/screening/daily',
      { params: strategyId ? { strategy_id: strategyId } : {} }),
  postInsights: (payload: InsightReq) =>
    ApiClient.post<InsightResp>('/api/screening/insights', payload,
      { timeout: 180000 }),
```

⚠ 执行校准：`ApiClient.get` 是否支持第二参 `{ params }`——对齐 `frontend/src/api/request.ts` 与既有带参 GET 的写法（如 `stocks.ts`）。

- [ ] **Step 10.2: 类型检查**

Run: `cd frontend && npm run type-check`
Expected: 无错误

---

### Task 11: 筛选页三 Tab 改造

**Files:**
- Modify: `frontend/src/views/Screening/index.vue`

- [ ] **Step 11.1: 结构改造**

页面顶部包 `el-tabs`（v-model `activeTab`），三个 pane：
1. **策略选股**（name `strategy`）：模板卡片网格（el-row/el-col，每卡片：name、description、风格 tag、筛选条件 chips、「运行」按钮；default 模板加「默认」角标）+ 运行结果区（表格：排名/代码/名称/行业/总分（el-progress 或彩色 el-tag）/关键因子（el-tooltip 列表）/命中信号/操作（「AI 研判」+「分析」跳转保留现有路由逻辑））+ 行内研判展开（el-table type="expand" 或 expandable row 显示 insight 文本）
2. **自定义筛选**（name `custom`）：现有整块表单+结果表原样移入（逻辑零改动）
3. **今日精选**（name `daily`）：策略下拉（来自 getDaily 的 strategies 或 getStrategies）+ 表格（同策略结果列 + insight 列，insight_status 标签）+ 「数据截至 {trade_date}」标注 + 手动刷新按钮

- [ ] **Step 11.2: 策略 Tab 核心逻辑（script setup 追加）**

```typescript
const strategies = ref<StrategyInfo[]>([])
const strategyResult = ref<StrategyRunResp | null>(null)
const runningStrategy = ref(false)
const insightLoading = ref(false)
const rowInsights = ref<Record<string, string>>({})
const quotaRemaining = ref<number | null>(null)

const loadStrategies = async () => {
  try {
    const res = await screeningApi.getStrategies()
    strategies.value = res.strategies || []
  } catch (e) {
    ElMessage.error('策略模板加载失败')
  }
}

const runStrategy = async (s: StrategyInfo) => {
  runningStrategy.value = true
  strategyResult.value = null
  rowInsights.value = {}
  try {
    strategyResult.value = await screeningApi.run({
      market: 'CN', conditions: {}, strategy_id: s.id, limit: s.top_n,
    })
    if (strategyResult.value.total === 0) {
      ElMessage.info(`「${s.name}」今日无命中股票（数据截至 ${strategyResult.value.as_of ?? '无'}）`)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '策略运行失败')
  } finally {
    runningStrategy.value = false
  }
}

const runInsight = async (symbols: string[], strategyId?: string) => {
  if (symbols.length === 0) return
  try {
    await ElMessageBox.confirm(
      `将对 ${symbols.length} 只股票发起 1 次 AI 快速研判（预计消耗约 ${Math.min(symbols.length * 400 + 2000, 10000)} token）。今日剩余额度以服务端为准。`,
      'AI 快速研判', { confirmButtonText: '开始研判', cancelButtonText: '取消', type: 'info' },
    )
  } catch { return }
  insightLoading.value = true
  try {
    const res = await screeningApi.postInsights({
      symbols, strategy_id: strategyId ?? null,
      conditions_digest: strategyId ? `strategy:${strategyId}` : 'custom',
    })
    rowInsights.value = { ...rowInsights.value, ...res.insights }
    quotaRemaining.value = res.quota_remaining
    ElMessage.success(`研判完成，今日剩余额度 ${res.quota_remaining} 次`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '研判失败')
  } finally {
    insightLoading.value = false
  }
}
```

（AI 研判按钮入口：结果表上方「AI 研判当前列表」= 当前页 symbols；行级按钮传单 symbol。`ElMessage/ElMessageBox` 显式 import——项目 AutoImport 只覆盖模板组件。）

- [ ] **Step 11.3: 今日精选 Tab**

```typescript
const daily = ref<DailyResp | null>(null)
const dailyLoading = ref(false)
const selectedDailyStrategy = ref<string>('')

const loadDaily = async () => {
  dailyLoading.value = true
  try {
    daily.value = await screeningApi.getDaily()
    const first = daily.value.strategies.find(s => s.items.length > 0)
    selectedDailyStrategy.value = first?.strategy_id
      || daily.value.strategies[0]?.strategy_id || ''
  } catch {
    ElMessage.error('每日推荐加载失败')
  } finally {
    dailyLoading.value = false
  }
}
```

onMounted 同时调 `loadStrategies()` 与 `loadDaily()`（daily 失败不阻塞主页面——首次上线时推荐尚未生成，显示空态文案「每日推荐将在因子批算完成后生成（交易日 20:45 后）」）。

- [ ] **Step 11.4: 验证**

Run: `cd frontend && npm run type-check && npm run lint`
Expected: 通过（chrome-devtools MCP 本机不可用——按项目 memory 约定，浏览器核查改用 curl 验证后端 API + 声明未做浏览器核查；前端视觉以 type-check/lint + 代码审查兜底）

---

### Task 12: 设置页「选股设置」区

**Files:**
- Modify: `frontend/src/views/ConfigManagement.vue`（⚠ 执行时先读文件，确认是单文件还是 components/ 子组件结构，按既有分区模式插入）

- [ ] **Step 12.1: 选股设置卡片**（读取用 configApi.getSystemSettings，保存用 updateSystemSettings 只提交本区 4 个键）

模板结构：

```vue
<el-card class="box-card" shadow="never">
  <template #header>
    <span>选股设置</span>
  </template>
  <el-form label-width="160px">
    <el-form-item label="每日自动 AI 研判">
      <el-switch v-model="screeningForm.dailyEnabled" />
      <div class="form-tip">开启后每个交易日在每日推荐生成后自动对默认策略 Top-20
        执行 1 次 AI 快速研判（消耗 token）；默认关闭</div>
    </el-form-item>
    <el-form-item label="手动研判日配额">
      <el-input-number v-model="screeningForm.manualLimit" :min="1" :max="200" />
      <div class="form-tip">每个用户每日可手动发起的 AI 快速研判次数</div>
    </el-form-item>
    <el-form-item label="研判模型">
      <el-select v-model="screeningForm.model" clearable placeholder="默认使用分析主力模型">
        <el-option v-for="m in llmModelOptions" :key="m" :label="m" :value="m" />
      </el-select>
      <div class="form-tip">可指定更便宜的模型执行快速研判</div>
    </el-form-item>
    <el-form-item label="研判提示词">
      <el-input v-model="screeningForm.prompt" type="textarea" :rows="8"
                placeholder="留空使用内置默认提示词" />
      <div class="form-tip">AI 快速研判的系统提示词，可按需调整风格与输出格式；
        清空保存即恢复默认</div>
    </el-form-item>
    <el-form-item>
      <el-button type="primary" :loading="screeningSaving" @click="saveScreeningSettings">
        保存选股设置
      </el-button>
    </el-form-item>
  </el-form>
</el-card>
```

逻辑：

```typescript
const screeningForm = reactive({ dailyEnabled: false, manualLimit: 10,
                                 model: '' as string, prompt: '' })
const screeningSaving = ref(false)

const loadScreeningSettings = async () => {
  try {
    const s = await configApi.getSystemSettings()
    screeningForm.dailyEnabled = !!s.screening_daily_insight_enabled
    screeningForm.manualLimit = Number(s.screening_manual_insight_daily_limit ?? 10)
    screeningForm.model = s.screening_insight_model || ''
    screeningForm.prompt = s.screening_insight_prompt || ''
  } catch { /* 设置加载失败保持默认展示 */ }
}

const saveScreeningSettings = async () => {
  screeningSaving.value = true
  try {
    await configApi.updateSystemSettings({
      screening_daily_insight_enabled: screeningForm.dailyEnabled,
      screening_manual_insight_daily_limit: screeningForm.manualLimit,
      screening_insight_model: screeningForm.model || null,
      screening_insight_prompt: screeningForm.prompt.trim() || null,
    })
    ElMessage.success('选股设置已保存')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    screeningSaving.value = false
  }
}
```

（`llmModelOptions` 复用该页已有的 LLM 模型列表数据源；`null` 值语义 = 删除自定义回落默认——`update_system_settings` 对 null 的处理若不支持删除键，改为存空字符串、服务端 `or None` 兜底，两边口径一致即可。）

- [ ] **Step 12.2: 验证**

Run: `cd frontend && npm run type-check && npm run lint`
Expected: 通过

---

### Task 13: 全量验证与收尾

- [ ] **Step 13.1: 后端静态检查**

```bash
C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m ruff check app/ tests/
C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m lint_imports   # ⚠ 若无 -m 入口，用 env Scripts/ 下绝对路径
```
Expected: 0 违规（新增代码不引入禁用 import）

- [ ] **Step 13.2: 后端测试分层**

```bash
docker compose -f docker-compose.dev.yml up -d mongodb redis
# unit 层
C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/ -m "not integration and not slow and not ai" -q
# integration 层（含新测试）
C:/Users/li_ao/miniconda3/envs/tradingagents/python.exe -m pytest tests/ -m "integration and not ai" -q
```
Expected: 新增测试全 PASS；存量失败对照 memory 已知清单（`pytest-full-run-quirks`：5 个存量/环境失败），不得新增失败。若跑全套，加 `DOCKER_CONTAINER=true` 前缀。

- [ ] **Step 13.3: 前端**

```bash
cd frontend && npm run type-check && npm run lint
```

- [ ] **Step 13.4: 冒烟（真实环境，可选但推荐）**

```bash
docker compose -f docker-compose.dev.yml up --build -d
# 容器内手动触发因子批算 + 推荐：
curl -X POST "http://localhost:8000/api/sync/run" -H "Authorization: Bearer <token>" \
  -d '{"market":"CN","domain":"factor_scores"}'   # ⚠ 端点对齐现有手动同步 API 路径
curl "http://localhost:8000/api/screening/strategies" -H "Authorization: Bearer <token>"
curl "http://localhost:8000/api/screening/daily" -H "Authorization: Bearer <token>"
```
Expected: strategies 返回 6 模板；daily 在批算+推荐完成后返回数据。浏览器核查按项目 memory 约定声明未做（chrome-devtools MCP 本机不可用），以 curl 冒烟替代。

- [ ] **Step 13.5: 收尾清单**

- `.ai_temp/` 临时脚本（若有）确认删除
- 不执行 git commit（用户未要求）
- 交付汇报：完成项 / 验证结果（跑过什么、通过与否、未跑原因）/ 遗留风险与用户决策点
