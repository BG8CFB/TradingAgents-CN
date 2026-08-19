"""MongoDB 索引定义唯一事实源（三市场业务集合 + 元数据集合）。

主键语义（架构文档「统一写入原则」）：
- 业务域唯一键一律 **不含 data_source**：回退时备用源 upsert 覆盖同自然键记录，
  主表只保留当前生效版本；多源差异/对账信息写 sync_events 与质量集合。
- 因此读取方拿到的天然是唯一生效数据，无需做源优先级解析。

使用方：
- app/data/scripts/init_collections.py（手动/CI 初始化，三市场）
- app/core/database.py（启动时自动建索引，三市场）
- app/data/storage/mongo/repositories/key_spec.py（域主键注册表，Phase 3）
- tests/data/test_index_definitions.py（一致性断言）

禁止在别处内联定义业务集合索引。
"""

from typing import Dict, List, Tuple

# 索引定义: {domain → [(索引字段列表, 是否唯一), ...]}
# 必须覆盖 app/data/storage/mongo/collections.py 中 _BUSINESS_COLLECTIONS 全部 18 个 domain
INDEX_DEFINITIONS: Dict[str, List[Tuple[List[tuple], bool]]] = {
    "basic_info": [
        ([("symbol", 1)], True),
        ([("data_source", 1)], False),
        ([("updated_at", -1)], False),
    ],
    "trade_calendar": [
        ([("exchange", 1), ("cal_date", 1)], True),
        ([("cal_date", 1)], False),
    ],
    "daily_quotes": [
        # 单版本覆盖：同 symbol 同交易日同周期只保留一份（当前生效源）
        ([("symbol", 1), ("trade_date", -1), ("period", 1)], True),
        ([("trade_date", -1)], False),
    ],
    "daily_indicators": [
        ([("symbol", 1), ("trade_date", -1)], True),
        ([("trade_date", -1)], False),
    ],
    "adj_factors": [
        ([("symbol", 1), ("trade_date", -1)], True),
    ],
    "corporate_actions": [
        # 同一 symbol 同一除权日同一行动类型唯一
        ([("symbol", 1), ("ex_date", -1), ("action_type", 1)], True),
        ([("ex_date", -1)], False),
    ],
    "financial_data": [
        # 财务数据：按报告期+报表类型唯一
        ([("symbol", 1), ("report_period", -1), ("statement_type", 1)], True),
        ([("symbol", 1), ("announce_date", -1)], False),
        ([("report_period", -1)], False),
    ],
    "market_quotes": [
        ([("symbol", 1)], True),
        ([("updated_at", -1)], False),
    ],
    "news": [
        ([("content_hash", 1)], True),
        ([("symbol", 1), ("pub_date", -1)], False),
    ],
    "connect_status": [
        # 互联互通持股：按 symbol + 日期唯一
        ([("symbol", 1), ("trade_date", -1)], True),
    ],
    "southbound_holding": [
        # 南向持股：按 symbol + 日期唯一
        ([("symbol", 1), ("trade_date", -1)], True),
    ],
    "pre_post_market": [
        # 盘前盘后：按 symbol + trade_date + session_type 唯一
        ([("symbol", 1), ("trade_date", -1), ("session_type", 1)], True),
    ],
    "intraday_quotes": [
        # 分钟线：按 symbol + datetime + freq 唯一
        ([("symbol", 1), ("datetime", -1), ("freq", 1)], True),
        ([("datetime", -1)], False),
    ],
    "money_flow": [
        # 资金流向：按 symbol + 日期唯一
        ([("symbol", 1), ("trade_date", -1)], True),
    ],
    "margin_trading": [
        # 融资融券：按 symbol + 日期唯一
        ([("symbol", 1), ("trade_date", -1)], True),
    ],
    "dragon_tiger": [
        # 龙虎榜：同一 symbol 同一交易日可能有多个上榜理由（direction 不同），
        # 唯一索引必须包含 direction 才不会丢数据
        ([("symbol", 1), ("trade_date", -1), ("direction", 1)], True),
        ([("trade_date", -1)], False),
    ],
    "block_trade": [
        # 大宗交易：同一 symbol 同一交易日同一买卖方唯一
        # （buyer+seller+symbol+trade_date 可区分不同营业部对倒单；
        #  不用浮点 price 做唯一键，避免精度风险）
        ([("symbol", 1), ("trade_date", -1), ("buyer", 1), ("seller", 1)], True),
        ([("trade_date", -1)], False),
    ],
    "tushare_universe": [
        # Tushare 指数成分：按 symbol + trade_date 唯一
        ([("symbol", 1), ("trade_date", -1)], True),
    ],
    # === 元数据集合（无市场后缀，三市场共用，market 字段区分） ===
    "sync_checkpoints": [
        ([("market", 1), ("domain", 1), ("source", 1)], True),
        ([("last_sync_time", -1)], False),
    ],
    "sync_events": [
        ([("market", 1), ("created_at", -1)], False),
        ([("event_type", 1)], False),
        ([("domain", 1), ("timestamp", -1)], False),
    ],
    "source_health": [
        ([("market", 1), ("source", 1), ("domain", 1)], True),
        ([("updated_at", -1)], False),
    ],
    "system_configs": [
        # 系统配置：按版本号倒序
        ([("version", -1)], False),
        ([("is_active", 1)], False),
    ],
    "system_secrets": [
        # 安全密钥：name 唯一，强制多 worker 首启只写一条
        ([("name", 1)], True),
    ],
}

# 历史遗留的唯一键（含 data_source，多源并存语义，已废弃）。
# 用于启动/脚本时清理旧 unique 索引——键不同 MongoDB 视为不同索引，
# 不主动删除会与新 unique 索引并存造成插入冲突。
_LEGACY_UNIQUE_WITH_SOURCE: Dict[str, List[tuple]] = {
    "daily_quotes": [("symbol", 1), ("trade_date", -1), ("period", 1), ("data_source", 1)],
    "daily_indicators": [("symbol", 1), ("trade_date", -1), ("data_source", 1)],
    "adj_factors": [("symbol", 1), ("trade_date", -1), ("data_source", 1)],
    "corporate_actions": [
        ("symbol", 1), ("ex_date", -1), ("action_type", 1), ("data_source", 1),
    ],
    "financial_data": [
        ("symbol", 1), ("report_period", -1), ("statement_type", 1), ("data_source", 1),
    ],
    "connect_status": [("symbol", 1), ("trade_date", -1), ("data_source", 1)],
    "southbound_holding": [("symbol", 1), ("trade_date", -1), ("data_source", 1)],
    "pre_post_market": [
        ("symbol", 1), ("trade_date", -1), ("session_type", 1), ("data_source", 1),
    ],
    "intraday_quotes": [("symbol", 1), ("datetime", -1), ("freq", 1), ("data_source", 1)],
    "money_flow": [("symbol", 1), ("trade_date", -1), ("data_source", 1)],
    "margin_trading": [("symbol", 1), ("trade_date", -1), ("data_source", 1)],
    "dragon_tiger": [("symbol", 1), ("trade_date", -1), ("direction", 1), ("data_source", 1)],
    "block_trade": [
        ("symbol", 1), ("trade_date", -1), ("buyer", 1), ("seller", 1), ("data_source", 1),
    ],
    # basic_info 旧版启动索引（database.py 历史内联定义）
    "basic_info": [("symbol", 1), ("data_source", 1)],
}

# 其他历史自定义命名的废弃索引（domain → 显式索引名列表）
_LEGACY_NAMED_INDEXES: Dict[str, List[str]] = {
    # database.py 旧启动逻辑用自定义名建的索引，与默认命名规则不一致
    "market_quotes": ["symbol_unique", "last_price_idx", "updated_at_idx"],
}


def default_index_name(fields: List[tuple]) -> str:
    """按 MongoDB 默认命名规则生成索引名（field_1_dir_-1_...）。"""
    return "_".join(f"{k}_{v}" for k, v in fields)


def get_legacy_index_names() -> Dict[str, List[str]]:
    """返回需要清理的旧版含 data_source 唯一索引名（按 domain）。"""
    result = {
        domain: [default_index_name(fields)] if len(fields) else []
        for domain, fields in _LEGACY_UNIQUE_WITH_SOURCE.items()
    }
    for domain, names in _LEGACY_NAMED_INDEXES.items():
        result.setdefault(domain, []).extend(names)
    return result


def get_unique_key(domain: str) -> List[str]:
    """返回指定业务域的唯一键字段列表（不含 data_source）。

    Raises:
        KeyError: domain 无索引定义。
    """
    for fields, unique in INDEX_DEFINITIONS[domain]:
        if unique:
            return [k for k, _ in fields]
    raise KeyError(f"domain {domain} 未定义唯一索引")
