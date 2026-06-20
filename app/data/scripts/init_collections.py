"""
MongoDB 集合初始化脚本

创建 11 个业务集合 + 索引。
可重复执行（已存在的集合和索引会跳过）。

用法:
    python -m app.data.scripts.init_collections
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 索引定义: {domain → [(索引字段列表, 是否唯一), ...]}
# 必须覆盖 app/data/storage/mongo/collections.py 中 _BUSINESS_COLLECTIONS 全部 18 个 domain
INDEX_DEFINITIONS = {
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
        ([("symbol", 1), ("trade_date", -1), ("period", 1), ("data_source", 1)], True),
        ([("trade_date", -1)], False),
    ],
    "daily_indicators": [
        ([("symbol", 1), ("trade_date", -1), ("data_source", 1)], True),
        ([("trade_date", -1)], False),
    ],
    "adj_factors": [
        ([("symbol", 1), ("trade_date", -1), ("data_source", 1)], True),
    ],
    "corporate_actions": [
        # 公司行为：同一 symbol 同一除权日同一行动类型同一数据源唯一
        ([("symbol", 1), ("ex_date", -1), ("action_type", 1), ("data_source", 1)], True),
        ([("ex_date", -1)], False),
    ],
    "financial_data": [
        # 财务数据：按报告期+报表类型+数据源唯一
        ([("symbol", 1), ("report_period", -1), ("statement_type", 1), ("data_source", 1)], True),
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
        # 互联互通持股：按 symbol + 日期 + 数据源唯一
        ([("symbol", 1), ("trade_date", -1), ("data_source", 1)], True),
    ],
    "southbound_holding": [
        # 南向持股：按 symbol + 日期 + 数据源唯一
        ([("symbol", 1), ("trade_date", -1), ("data_source", 1)], True),
    ],
    "pre_post_market": [
        # 盘前盘后：按 symbol + trade_date + session_type + 数据源唯一
        ([("symbol", 1), ("trade_date", -1), ("session_type", 1), ("data_source", 1)], True),
    ],
    "intraday_quotes": [
        # 分钟线：按 symbol + datetime + freq + 数据源唯一（对齐 IntradayQuotesSchema 字段名）
        ([("symbol", 1), ("datetime", -1), ("freq", 1), ("data_source", 1)], True),
        ([("datetime", -1)], False),
    ],
    "money_flow": [
        # 资金流向：按 symbol + 日期 + 数据源唯一
        ([("symbol", 1), ("trade_date", -1), ("data_source", 1)], True),
    ],
    "margin_trading": [
        # 融资融券：按 symbol + 日期 + 数据源唯一
        ([("symbol", 1), ("trade_date", -1), ("data_source", 1)], True),
    ],
    "dragon_tiger": [
        # 龙虎榜：同一 symbol 同一交易日可能有多个上榜理由（direction 不同），
        # 唯一索引必须包含 direction 才不会丢数据
        ([("symbol", 1), ("trade_date", -1), ("direction", 1), ("data_source", 1)], True),
        ([("trade_date", -1)], False),
    ],
    "block_trade": [
        # 大宗交易：同一 symbol 同一交易日同一买卖方同一数据源唯一
        # （buyer+seller+symbol+trade_date 可区分不同营业部对倒单；
        #  不用浮点 price 做唯一键，避免精度风险）
        ([("symbol", 1), ("trade_date", -1), ("buyer", 1), ("seller", 1), ("data_source", 1)], True),
        ([("trade_date", -1)], False),
    ],
    "tushare_universe": [
        # Tushare 指数成分：按 symbol + trade_date 唯一
        ([("symbol", 1), ("trade_date", -1)], True),
    ],
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


async def init_collections(market: str = "CN") -> None:
    """创建指定市场的全部集合和索引"""
    from app.data.storage.mongo.collections import get_all_collections

    try:
        from app.core.database import get_mongo_db
        db = get_mongo_db()
    except Exception as e:
        logger.error("无法连接 MongoDB: %s", e)
        return

    collection_map = get_all_collections(market)
    logger.info("开始初始化 %s 市场 %d 个集合", market, len(collection_map))

    for data_type, collection_name in collection_map.items():
        collection = db[collection_name]

        # 获取索引定义
        index_specs = INDEX_DEFINITIONS.get(data_type, [])

        for fields, unique in index_specs:
            index_name = "_".join(f"{k}_{v}" for k, v in fields)
            try:
                await collection.create_index(fields, unique=unique)
                logger.info("  索引 %s.%s 创建成功 (unique=%s)", collection_name, index_name, unique)
            except Exception as e:
                logger.warning("  索引 %s.%s 创建失败: %s", collection_name, index_name, e)

    logger.info("集合初始化完成")


async def main():
    for market in ("CN", "HK", "US"):
        await init_collections(market)


if __name__ == "__main__":
    asyncio.run(main())
