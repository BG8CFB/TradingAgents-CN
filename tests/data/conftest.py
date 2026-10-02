"""数据层测试共享 fixtures。

提供 SimulatedMongoDB 注入、DataInterface 构造、SchedulerEngine 构造等 fixture，
替代 unittest.mock.patch 方案，使用真实的代码路径 + 内存数据库。
"""

import pytest

from test_infra import SimulatedMongoDB


@pytest.fixture(autouse=True)
def _clear_memory_counters():
    """每个测试前后清理模块级 _memory_counters，防跨测试污染。

    SlidingWindowCounter 的内存降级路径使用模块级全局 _memory_counters；
    RateLimiter 内部也有自己的 _memory_counters 实例字段（不共享）。
    本 fixture 只清前者，避免与限流器逻辑耦合。
    """
    from app.data.storage.redis.counters import _memory_counters
    _memory_counters.clear()
    yield
    _memory_counters.clear()


# ============================================================
# 真实 MongoDB（docker 容器）— 索引/upsert 语义验证用
# ============================================================

@pytest.fixture
async def real_mongo_db():
    """连接真实 MongoDB（docker 容器），完成后关闭。

    用于验证索引唯一约束、upsert 覆盖行为等模拟库无法验证的语义。
    """
    import app.core.database as db_module
    from app.data.storage.mongo.client import reset_client

    # 前序测试可能将 SimulatedMongoDB 泄漏进 _motor_db 缓存；
    # 先重置，保证本 fixture 期间 get_motor_db() 绑定真实库与当前事件循环
    reset_client()
    await db_module.db_manager.init_mongodb()
    db_module.mongo_client = db_module.db_manager.mongo_client
    db_module.mongo_db = db_module.db_manager.mongo_db
    yield db_module.get_mongo_db()
    await db_module.db_manager.close_connections()
    db_module.mongo_client = None
    db_module.mongo_db = None
    # Motor 客户端绑定到当前测试的事件循环；pytest-asyncio 每个测试新开循环，
    # 不重置会导致后续测试复用已关闭循环上的客户端（"Event loop is closed"）
    from app.data.storage.mongo.client import reset_client
    reset_client()


# ============================================================
# SimulatedMongoDB 注入 — 直接替换 _motor_db 全局变量
# ============================================================

@pytest.fixture
def sim_db_fresh():
    """创建全新的 SimulatedMongoDB 实例（每个测试独立）。"""
    return SimulatedMongoDB()


@pytest.fixture
def inject_sim_db(sim_db_fresh):
    """将 SimulatedMongoDB 注入到 app.data.storage.mongo.client._motor_db。

    直接替换全局 _motor_db 变量，使所有通过 get_motor_db() 获取数据库的代码
    走内存模拟，而不是连接真实 MongoDB。
    """
    from app.data.storage.mongo import client as mongo_client

    original = mongo_client._motor_db
    mongo_client._motor_db = sim_db_fresh
    yield sim_db_fresh
    mongo_client._motor_db = original


# ============================================================
# MetadataRepo 基于 SimulatedMongoDB
# ============================================================

@pytest.fixture
def metadata_repo(inject_sim_db):
    """创建使用 SimulatedMongoDB 的 MetadataRepo 实例。"""
    from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo
    return MetadataRepo()


# ============================================================
# CheckpointManager 基于 SimulatedMongoDB
# ============================================================

@pytest.fixture
def checkpoint_manager(inject_sim_db):
    """创建使用 SimulatedMongoDB 的 CheckpointManager 实例。"""
    from app.data.scheduler.checkpoint import CheckpointManager
    return CheckpointManager()


# ============================================================
# SchedulerEngine fixture
# ============================================================

@pytest.fixture
def scheduler_engine():
    """创建 SchedulerEngine 实例（不启动调度器）。"""
    from app.data.scheduler.engine import SchedulerEngine
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    # 重置单例，确保每个测试获得独立实例
    SchedulerEngine._instance = None
    scheduler = AsyncIOScheduler(timezone="UTC")
    engine = SchedulerEngine(scheduler=scheduler)
    yield engine
    if engine._scheduler.running:
        engine._scheduler.shutdown(wait=False)
    SchedulerEngine._instance = None


# ============================================================
# FallbackRouter fixture
# ============================================================

@pytest.fixture
def fallback_router():
    """创建使用真实 CapabilityRegistry + PriorityConfig 的 FallbackRouter。"""
    from app.data.processor.fallback_router import FallbackRouter
    from app.data.core.registry.capability import CapabilityRegistry
    from app.data.core.registry.priority import PriorityConfig

    registry = CapabilityRegistry()
    priority = PriorityConfig()
    return FallbackRouter(registry, priority)


# ============================================================
# DataInterface fixture
# ============================================================

@pytest.fixture
def data_interface():
    """创建 DataInterface 实例（使用真实 Reader/Registry/PriorityConfig）。"""
    from app.data.core.interface import DataInterface
    DataInterface.reset_instance()
    di = DataInterface()
    yield di
    DataInterface.reset_instance()


# ============================================================
# 临时 YAML 配置 fixture
# ============================================================

@pytest.fixture
def sample_schedule_yaml(tmp_path):
    """创建包含 cron 调度配置的临时 YAML 文件。"""
    import yaml
    config = {
        "daily_quotes": {
            "cron": "15 16 * * 1-5",
            "timezone": "Asia/Shanghai",
            "mode": "incremental",
        },
        "basic_info": {
            "cron": "0 9 * * *",
            "timezone": "Asia/Shanghai",
            "mode": "full",
        },
    }
    path = tmp_path / "schedule.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)
    return str(path)


@pytest.fixture
def sample_schedule_yaml_no_cron(tmp_path):
    """创建不含 cron 字段的 YAML。"""
    import yaml
    config = {
        "daily_quotes": {
            "timezone": "Asia/Shanghai",
            "mode": "incremental",
        },
    }
    path = tmp_path / "schedule_no_cron.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)
    return str(path)


@pytest.fixture
def sample_schedule_yaml_empty(tmp_path):
    """创建空的 YAML 文件。"""
    path = tmp_path / "schedule_empty.yaml"
    path.write_text("", encoding="utf-8")
    return str(path)


# ============================================================
# 因子引擎种子数据（真实 MongoDB）— factors/scheduler 测试共用
# ============================================================

SEED_FACTOR_SYMBOLS = ["TESTF001", "TESTF002"]


def _factor_trade_dates(n: int, end) -> list:
    """生成 n 个连续工作日（周末跳过），升序 YYYY-MM-DD 字符串列表。"""
    from datetime import timedelta
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return sorted(f"{x:%Y-%m-%d}" for x in days)


async def _seed_factor_stocks(db, symbols_cfg: dict, dates: list):
    """按配置向 5 个标准域种股票种子数据（字段名对齐 schema 中立口径）。

    symbols_cfg: {symbol: {name, industry, close[130], turnover[130],
    volume, amount, pe, pb, dv, vr, inflow, np_prev, np_cur, roe, gm, dr}}
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
        vol = cfg["volume"] if isinstance(cfg["volume"], list) \
            else [cfg["volume"]] * len(dates)
        q_docs = [{
            "symbol": sym, "trade_date": d, "period": "daily",
            "close": c, "volume": v, "amount": cfg["amount"],
            "turnover_rate": t, "pct_chg": 0.0,
            "data_source": "test",
        } for d, c, v, t in zip(dates[-120:], cfg["close"][-120:],
                                vol[-120:], cfg["turnover"][-120:])]
        await q_coll.insert_many(q_docs)
        # indicators 覆盖全部唯一交易日（估值分位窗口数据驱动，不足 500 不影响）
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
                    "symbol": sym, "report_period": rp,
                    "statement_type": "indicator",
                    "net_profit": np_, "roe": cfg["roe"],
                    "gross_margin": cfg["gm"], "debt_ratio": cfg["dr"],
                    "data_source": "test",
                }}, upsert=True)


async def _cleanup_factor_seeds(db, symbols):
    """清理因子种子涉及的 6 个域中该批 symbol 的数据。"""
    from app.data.storage.mongo.collections import get_collection_name
    for domain in ("daily_quotes", "daily_indicators", "basic_info",
                   "money_flow", "financial_data", "factor_scores"):
        await db[get_collection_name(domain, "CN")].delete_many(
            {"symbol": {"$in": list(symbols)}})


def _default_factor_seed_cfg() -> dict:
    """TESTF001（银行线性递增）/ TESTF002（医药线性递减）标准种子配置。"""
    up = [10.0 + 0.1 * i for i in range(130)]
    down = [30.0 - 0.1 * i for i in range(130)]
    return {
        "TESTF001": {
            "name": "正常股", "industry": "银行",
            "close": up, "turnover": [2.0] * 129 + [4.0],
            # volume 尾日 2 倍：turnover_amp 已改成交量口径（股本常数，
            # 放大倍数与换手率口径等价），与 turnover 尾日 4/2=2 同构
            "volume": [1_000_000] * 129 + [2_000_000],
            "amount": 50_000_000,
            "pe": 20.0, "pb": 1.5, "dv": 3.0, "vr": 1.8,
            "inflow": 10_000_000.0, "np_prev": 100.0, "np_cur": 130.0,
            "roe": 18.0, "gm": 35.0, "dr": 45.0,
        },
        "TESTF002": {
            "name": "正常股B", "industry": "医药",
            "close": down, "turnover": [1.0] * 130,
            "volume": 500_000, "amount": 10_000_000,
            "pe": 50.0, "pb": 5.0, "dv": 0.5, "vr": 0.6,
            "inflow": -2_000_000.0, "np_prev": 50.0, "np_cur": 40.0,
            "roe": 5.0, "gm": 15.0, "dr": 70.0,
        },
    }


@pytest.fixture
async def seed_factor_inputs(real_mongo_db):
    """种 2 只 TESTF 股票全输入数据，teardown 清理。

    供 tests/data/** 下因子引擎、调度 job、仓储层联动的测试复用。
    """
    from datetime import date
    dates = _factor_trade_dates(130, date(2026, 9, 11))
    await _cleanup_factor_seeds(real_mongo_db, SEED_FACTOR_SYMBOLS)
    await _seed_factor_stocks(real_mongo_db, _default_factor_seed_cfg(), dates)
    yield {
        "db": real_mongo_db, "dates": dates,
        "symbols": list(SEED_FACTOR_SYMBOLS),
        "cfg": _default_factor_seed_cfg(),
    }
    await _cleanup_factor_seeds(real_mongo_db, SEED_FACTOR_SYMBOLS)

