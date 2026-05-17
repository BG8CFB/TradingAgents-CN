"""
统一数据读取层

所有下游模块通过本模块读取标准化数据。
内部只从 MongoDB 读取，不直接调用外部 API。
港股/美股无数据时触发 sources/ 编排模块预热缓存。
"""
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd

from .schema.collections import get_collection_name
from .config import get_enabled_sources

logger = logging.getLogger(__name__)


def get_stock_data(market: str, symbol: str, start_date: str, end_date: str) -> str:
    """
    统一的股票行情数据读取接口

    Args:
        market: "CN" / "HK" / "US"
        symbol: 股票代码
        start_date: 开始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD

    Returns:
        str: 格式化的股票数据报告（含技术指标）
    """
    logger.info(f"📖 [Reader] 读取 {market} 行情数据: {symbol} ({start_date} ~ {end_date})")
    start_time = time.time()

    # 1. 从 MongoDB 读取
    data = _read_daily_quotes(market, symbol, start_date, end_date)

    if data is None or data.empty:
        # 2. 港股/美股：触发按需预热
        if market in ("HK", "US"):
            logger.info(f"🔄 [Reader] {market} 无缓存数据，触发按需预热: {symbol}")
            _warm_cache(market, symbol, start_date, end_date)
            data = _read_daily_quotes(market, symbol, start_date, end_date)

        if data is None or data.empty:
            duration = time.time() - start_time
            logger.warning(f"⚠️ [Reader] {market} {symbol} 无数据 ({duration:.2f}s)")
            return f"❌ 未获取到{symbol}的{market}行情数据"

    # 3. 获取股票名称
    stock_name = _get_stock_name(market, symbol)

    # 4. 格式化报告（含技术指标）
    try:
        result = _format_stock_data_response(data, symbol, stock_name, start_date, end_date)
    except Exception as fmt_err:
        logger.warning(f"⚠️ [Reader] 格式化失败，生成简化报告: {fmt_err}")
        result = _format_simple_response(data, symbol, stock_name, start_date, end_date)

    duration = time.time() - start_time
    logger.info(f"✅ [Reader] {market} {symbol} 数据读取完成 ({duration:.2f}s, {len(data)}条)")
    return result


def get_stock_info(market: str, symbol: str) -> Dict[str, Any]:
    """
    统一的股票基本信息读取接口

    Args:
        market: "CN" / "HK" / "US"
        symbol: 股票代码

    Returns:
        Dict: 股票基本信息
    """
    logger.info(f"📖 [Reader] 读取 {market} 股票信息: {symbol}")

    # 1. 从 MongoDB 读取
    doc = _read_basic_info(market, symbol)

    if doc is None:
        # 2. 港股/美股：触发按需预热
        if market in ("HK", "US"):
            logger.info(f"🔄 [Reader] {market} 无缓存信息，触发按需预热: {symbol}")
            _warm_cache(market, symbol, None, None)
            doc = _read_basic_info(market, symbol)

    if doc is None:
        logger.warning(f"⚠️ [Reader] {market} {symbol} 无基本信息")
        return _fallback_info(market, symbol)

    # 构建返回结果
    result = _normalize_info_doc(doc, symbol)

    # 追加快照行情（若存在）
    _attach_market_quote(market, symbol, result)

    return result


def get_news(market: str, symbol: str, start_date: str, end_date: str, limit: int = 50) -> str:
    """
    统一的新闻数据读取接口

    Args:
        market: "CN" / "HK" / "US"
        symbol: 股票代码
        start_date: 开始日期
        end_date: 结束日期
        limit: 最大返回条数

    Returns:
        str: 格式化的新闻报告
    """
    logger.info(f"📖 [Reader] 读取 {market} 新闻: {symbol}")

    collection_name = get_collection_name(market, "news")
    docs = _query_collection(collection_name, {
        "$or": [
            {"symbol": _normalize_symbol(symbol, market)},
            {"code": _normalize_symbol(symbol, market)},
        ]
    }, limit=limit, sort=[("publish_time", -1)])

    if not docs:
        return ""

    result_parts = []
    for doc in docs:
        title = doc.get("title", "")
        content = doc.get("content", "") or doc.get("summary", "")
        source = doc.get("source", "") or doc.get("data_source", "")
        pub_time = doc.get("publish_time", "")
        result_parts.append(f"### {title} ({source}, {pub_time})\n{content}\n")

    return "\n".join(result_parts)


def get_fundamentals(market: str, symbol: str) -> str:
    """
    统一的基本面数据读取接口

    Args:
        market: "CN" / "HK" / "US"
        symbol: 股票代码

    Returns:
        str: 格式化的基本面报告
    """
    logger.info(f"📖 [Reader] 读取 {market} 基本面: {symbol}")

    collection_name = get_collection_name(market, "financial")
    code = _normalize_symbol(symbol, market)

    docs = _query_collection(collection_name, {
        "$or": [{"symbol": code}, {"code": code}]
    }, limit=5, sort=[("report_period", -1)])

    if not docs:
        return f"❌ 未获取到{symbol}的基本面数据"

    return _format_financial_report(docs, symbol)


# ==================== MongoDB 读取层 ====================

def _read_daily_quotes(market: str, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """从 MongoDB 读取日线行情数据"""
    collection_name = get_collection_name(market, "daily_quotes")
    code = _normalize_symbol(symbol, market)

    query = {
        "$or": [{"symbol": code}, {"code": code}],
        "period": {"$in": ["daily", "day", None]},
    }
    if start_date and end_date:
        query["trade_date"] = {"$gte": start_date.replace("-", ""), "$lte": end_date.replace("-", "")}

    docs = _query_collection(collection_name, query, sort=[("trade_date", 1)])

    if not docs:
        return None

    df = pd.DataFrame(docs)
    # 列名标准化
    col_rename = {
        "trade_date": "date", "pct_chg": "pct_change",
        "volume": "vol", "amount": "turnover",
    }
    df = df.rename(columns={k: v for k, v in col_rename.items() if k in df.columns})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
        df = df.sort_values("date")

    return df


def _read_basic_info(market: str, symbol: str) -> Optional[Dict]:
    """从 MongoDB 读取股票基本信息"""
    collection_name = get_collection_name(market, "basic_info")
    code = _normalize_symbol(symbol, market)

    # 按数据源优先级查询
    sources = get_enabled_sources(market)
    for src in sources:
        doc = _query_one(collection_name, {
            "$and": [
                {"$or": [{"symbol": code}, {"code": code}]},
                {"$or": [{"data_source": src}, {"source": src}]},
            ]
        })
        if doc:
            return doc

    # 无优先级匹配时，不带 source 条件查询
    return _query_one(collection_name, {
        "$or": [{"symbol": code}, {"code": code}]
    })


def _query_collection(collection_name: str, query: Dict, limit: int = 0,
                      sort: Optional[list] = None) -> List[Dict]:
    """查询 MongoDB 集合"""
    try:
        from app.core.database import get_mongo_db_sync
        db = get_mongo_db_sync()
        collection = db[collection_name]

        cursor = collection.find(query, {"_id": 0})
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)

        return list(cursor)
    except Exception as e:
        logger.warning(f"⚠️ MongoDB 查询失败 [{collection_name}]: {e}")
        return []


def _query_one(collection_name: str, query: Dict) -> Optional[Dict]:
    """查询单条 MongoDB 文档"""
    try:
        from app.core.database import get_mongo_db_sync
        db = get_mongo_db_sync()
        return db[collection_name].find_one(query, {"_id": 0})
    except Exception as e:
        logger.warning(f"⚠️ MongoDB 查询失败 [{collection_name}]: {e}")
        return None


# ==================== 按需缓存预热 ====================

def _warm_cache(market: str, symbol: str, start_date: Optional[str], end_date: Optional[str]):
    """
    触发按需缓存预热（仅港股/美股）

    按数据源优先级尝试，第一个成功即停止。
    优先使用 orchestrator 编排模块（走 Provider → Adapter → Schema → MongoDB 管道），
    回退到直接 adapter 调用。
    """
    sources = get_enabled_sources(market)
    for source_name in sources:
        try:
            # 优先尝试 orchestrator
            if _warm_via_orchestrator(market, source_name, symbol, start_date, end_date):
                return
            # 回退到直接 adapter
            _warm_from_source(market, source_name, symbol, start_date, end_date)
            return
        except Exception as e:
            logger.warning(f"⚠️ [预热] {market}/{source_name} 失败: {e}")
            continue

    logger.warning(f"⚠️ [预热] {market} {symbol} 所有数据源预热失败")


def _warm_via_orchestrator(market: str, source_name: str, symbol: str,
                          start_date: Optional[str], end_date: Optional[str]) -> bool:
    """通过 orchestrator 编排模块预热缓存，返回是否成功"""
    import asyncio

    orchestrator_map = {
        ("HK", "akshare"): ("app.data.sources.hk.akshare_hk.orchestrator", "AKShareHKOrchestrator"),
        ("HK", "yfinance"): ("app.data.sources.hk.yfinance_hk.orchestrator", "YFinanceHKOrchestrator"),
        ("US", "yfinance"): ("app.data.sources.us.yfinance_us.orchestrator", "YFinanceUSOrchestrator"),
        ("US", "finnhub"): ("app.data.sources.us.finnhub_us.orchestrator", "FinnhubUSOrchestrator"),
    }

    key = (market, source_name)
    if key not in orchestrator_map:
        return False

    module_path, class_name = orchestrator_map[key]

    try:
        from .sources import get_adapter
        adapter = get_adapter(market, source_name)

        import importlib
        module = importlib.import_module(module_path)
        orchestrator_cls = getattr(module, class_name)
        orchestrator = orchestrator_cls(adapter)

        loop = _get_or_create_event_loop()

        # 预热基础信息
        loop.run_until_complete(orchestrator.warm_stock_info(symbol))

        # 预热行情数据
        if start_date and end_date:
            loop.run_until_complete(orchestrator.warm_daily_quotes(symbol, start_date, end_date))

        return True
    except Exception as e:
        logger.debug(f"📊 [orchestrator] {market}/{source_name} 不可用: {e}")
        return False


def _get_or_create_event_loop():
    """获取或创建事件循环"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def _warm_from_source(market: str, source_name: str, symbol: str,
                      start_date: Optional[str], end_date: Optional[str]):
    """从指定数据源预热缓存"""
    try:
        from .sources import get_adapter

        adapter = get_adapter(market, source_name)
        if adapter is None:
            logger.debug(f"📊 [预热] {market}/{source_name} adapter 不可用")
            return

        provider = adapter.provider

        # 预热基础信息
        if hasattr(provider, "get_stock_list") or hasattr(provider, "get_stock_basic_info"):
            try:
                raw_info = provider.get_stock_basic_info(symbol)
                if raw_info is not None:
                    schema = adapter.adapt_basic_info(raw_info)
                    if schema:
                        _upsert_to_mongodb(
                            get_collection_name(market, "basic_info"),
                            schema.to_db_doc(),
                            {"symbol": schema.symbol, "data_source": source_name}
                        )
            except Exception as e:
                logger.debug(f"📊 [预热] 基础信息写入失败: {e}")

        # 预热行情数据
        if start_date and end_date and hasattr(provider, "get_daily_quotes"):
            try:
                raw_df = provider.get_daily_quotes(symbol, start_date, end_date)
                if raw_df is not None and not raw_df.empty:
                    schemas = adapter.adapt_daily_quote_batch(raw_df)
                    for schema in schemas:
                        _upsert_to_mongodb(
                            get_collection_name(market, "daily_quotes"),
                            schema.to_db_doc(),
                            {
                                "symbol": schema.symbol,
                                "trade_date": schema.trade_date,
                                "data_source": source_name,
                                "period": "daily",
                            }
                        )
                    logger.info(f"✅ [预热] {market}/{source_name} 行情写入 {len(schemas)} 条")
            except Exception as e:
                logger.debug(f"📊 [预热] 行情写入失败: {e}")

    except ImportError:
        logger.debug(f"📊 [预热] {market}/{source_name} 模块不可用")


def _upsert_to_mongodb(collection_name: str, doc: Dict, filter_query: Dict):
    """Upsert 文档到 MongoDB"""
    try:
        from app.core.database import get_mongo_db_sync
        db = get_mongo_db_sync()
        db[collection_name].update_one(filter_query, {"$set": doc}, upsert=True)
    except Exception as e:
        logger.warning(f"⚠️ MongoDB upsert 失败 [{collection_name}]: {e}")


# ==================== 辅助函数 ====================

def _normalize_symbol(symbol: str, market: str) -> str:
    """标准化股票代码"""
    symbol = str(symbol).strip()
    if market == "CN":
        return symbol.zfill(6)
    elif market == "HK":
        return symbol.replace(".HK", "").replace(".hk", "").zfill(5)
    else:
        return symbol.upper()


def _get_stock_name(market: str, symbol: str) -> str:
    """从 MongoDB 获取股票名称"""
    doc = _read_basic_info(market, symbol)
    if doc:
        return doc.get("name", "") or doc.get("stock_name", "") or f"股票{symbol}"
    return f"股票{symbol}"


def _normalize_info_doc(doc: Dict, symbol: str) -> Dict[str, Any]:
    """标准化信息文档返回格式"""
    # 规范化行业与板块
    board_labels = {"主板", "中小板", "创业板", "科创板"}
    raw_industry = (doc.get("industry") or doc.get("industry_name") or "").strip()
    sec_or_cat = (doc.get("sec") or doc.get("category") or "").strip()
    market_val = (doc.get("market") or "").strip()
    industry_val = raw_industry or sec_or_cat or "未知"
    if raw_industry in board_labels:
        if not market_val:
            market_val = raw_industry
        if sec_or_cat:
            industry_val = sec_or_cat

    return {
        "symbol": doc.get("symbol") or doc.get("code") or symbol,
        "name": doc.get("name") or doc.get("stock_name") or f"股票{symbol}",
        "area": doc.get("area", "未知"),
        "industry": industry_val,
        "market": market_val or doc.get("market", "未知"),
        "list_date": doc.get("list_date", "未知"),
        "source": "mongodb",
    }


def _attach_market_quote(market: str, symbol: str, result: Dict):
    """附加市场快照行情"""
    try:
        collection_name = get_collection_name(market, "market_quotes")
        code = _normalize_symbol(symbol, market)
        doc = _query_one(collection_name, {
            "$or": [{"symbol": code}, {"code": code}]
        })
        if doc:
            result["current_price"] = doc.get("close")
            result["change_pct"] = doc.get("pct_chg") or doc.get("pct_change")
            result["volume"] = doc.get("volume") or doc.get("vol")
    except Exception:
        pass


def _fallback_info(market: str, symbol: str) -> Dict[str, Any]:
    """无数据时的回退信息"""
    labels = {"CN": "A股", "HK": "港股", "US": "美股"}
    currencies = {"CN": "CNY", "HK": "HKD", "US": "USD"}
    exchanges = {"CN": "未知", "HK": "HKG", "US": "US"}
    return {
        "symbol": symbol,
        "name": f"{labels.get(market, '')}{symbol}",
        "currency": currencies.get(market, ""),
        "exchange": exchanges.get(market, ""),
        "source": "fallback",
    }


# ==================== 格式化 ====================

def _format_stock_data_response(data: pd.DataFrame, symbol: str, stock_name: str,
                                start_date: str, end_date: str) -> str:
    """
    格式化股票数据响应（包含技术指标计算）

    复用 data_source_manager.py 中的技术指标计算逻辑。
    """
    original_data_count = len(data)

    # 计算移动平均线
    data["ma5"] = data["close"].rolling(window=5, min_periods=1).mean()
    data["ma10"] = data["close"].rolling(window=10, min_periods=1).mean()
    data["ma20"] = data["close"].rolling(window=20, min_periods=1).mean()
    data["ma60"] = data["close"].rolling(window=60, min_periods=1).mean()

    # RSI（同花顺风格）
    delta = data["close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    for n, com in [(6, 5), (12, 11), (24, 23)]:
        avg_gain = gain.ewm(com=com, adjust=True).mean()
        avg_loss = loss.ewm(com=com, adjust=True).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        data[f"rsi{n}"] = 100 - (100 / (1 + rs))

    # RSI14（国际标准 SMA）
    gain14 = gain.rolling(window=14, min_periods=1).mean()
    loss14 = loss.rolling(window=14, min_periods=1).mean()
    rs14 = gain14 / loss14.replace(0, np.nan)
    data["rsi14"] = 100 - (100 / (1 + rs14))

    # MACD
    ema12 = data["close"].ewm(span=12, adjust=False).mean()
    ema26 = data["close"].ewm(span=26, adjust=False).mean()
    data["macd_dif"] = ema12 - ema26
    data["macd_dea"] = data["macd_dif"].ewm(span=9, adjust=False).mean()
    data["macd"] = (data["macd_dif"] - data["macd_dea"]) * 2

    # 布林带
    data["boll_mid"] = data["close"].rolling(window=20, min_periods=1).mean()
    std = data["close"].rolling(window=20, min_periods=1).std()
    data["boll_upper"] = data["boll_mid"] + 2 * std
    data["boll_lower"] = data["boll_mid"] - 2 * std

    # 展示数据
    display_rows = min(5, len(data))
    latest_data = data.iloc[-1]
    latest_price = latest_data.get("close", 0)
    prev_close = data.iloc[-2].get("close", latest_price) if len(data) > 1 else latest_price
    change = latest_price - prev_close
    change_pct = (change / prev_close * 100) if prev_close != 0 else 0

    result = f"📊 {stock_name}({symbol}) - 技术分析数据\n"
    result += f"数据期间: {start_date} 至 {end_date}\n"
    result += f"数据条数: {original_data_count}条 (展示最近{display_rows}个交易日)\n\n"
    result += f"💰 最新价格: ¥{latest_price:.2f}\n"
    result += f"📈 涨跌额: {change:+.2f} ({change_pct:+.2f}%)\n\n"

    # MA
    for ma_name, ma_label in [("ma5", "MA5"), ("ma10", "MA10"), ("ma20", "MA20"), ("ma60", "MA60")]:
        ma_val = latest_data.get(ma_name, 0)
        arrow = "↑" if latest_price > ma_val else "↓"
        result += f"   {ma_label}: ¥{ma_val:.2f} (价格在{ma_label}{'上方' if latest_price > ma_val else '下方'} {arrow})\n"
    result += "\n"

    # MACD
    result += f"📈 MACD指标:\n"
    result += f"   DIF: {latest_data.get('macd_dif', 0):.3f}\n"
    result += f"   DEA: {latest_data.get('macd_dea', 0):.3f}\n"
    macd_val = latest_data.get("macd", 0)
    result += f"   MACD: {macd_val:.3f} ({'多头 ↑' if macd_val > 0 else '空头 ↓'})\n\n"

    # RSI
    result += f"📉 RSI指标:\n"
    for rsi_name in ["rsi6", "rsi12", "rsi24"]:
        rsi_val = latest_data.get(rsi_name, 0)
        flag = "超买 ⚠️" if rsi_val >= 80 else ("超卖 ⚠️" if rsi_val <= 20 else "")
        result += f"   {rsi_name.upper()}: {rsi_val:.2f} {flag}\n"
    result += "\n"

    # BOLL
    result += f"📊 布林带:\n"
    result += f"   上轨: ¥{latest_data.get('boll_upper', 0):.2f}\n"
    result += f"   中轨: ¥{latest_data.get('boll_mid', 0):.2f}\n"
    result += f"   下轨: ¥{latest_data.get('boll_lower', 0):.2f}\n\n"

    # 历史数据明细表
    result += "## 历史数据明细\n"
    display_data = data.tail(min(300, len(data)))
    cols = [c for c in ["date", "open", "high", "low", "close", "vol", "pct_change"] if c in data.columns]
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    rows = []
    for _, row in display_data.iterrows():
        vals = []
        for c in cols:
            v = row.get(c, "")
            if isinstance(v, (float, int)):
                vals.append(f"{v:.2f}" if c not in ["vol"] else f"{v:.0f}")
            else:
                vals.append(str(v))
        rows.append("| " + " | ".join(vals) + " |")
    result += f"{header}\n{sep}\n" + "\n".join(rows)

    return result


def _format_simple_response(data: pd.DataFrame, symbol: str, stock_name: str,
                           start_date: str, end_date: str) -> str:
    """简化数据报告"""
    latest = data.iloc[-1]
    result = f"📊 {stock_name}({symbol}) - 历史数据\n"
    result += f"数据期间: {start_date} 至 {end_date}\n"
    result += f"数据条数: {len(data)}条\n\n"
    result += f"💰 最新收盘价: ¥{latest.get('close', 0):.2f}\n"
    result += f"📊 最高价: ¥{data['high'].max():.2f}\n"
    result += f"📊 最低价: ¥{data['low'].min():.2f}\n"
    return result


def _format_financial_report(docs: List[Dict], symbol: str) -> str:
    """格式化基本面报告"""
    if not docs:
        return f"❌ 未获取到{symbol}的基本面数据"

    latest = docs[0]
    result = f"# {symbol} 基本面分析报告\n\n"

    # 财务概况
    result += "## 📊 财务概况\n"
    for key, label in [
        ("report_period", "报告期"), ("revenue", "营业收入"),
        ("net_profit", "净利润"), ("total_assets", "总资产"),
        ("total_equity", "股东权益"), ("roe", "ROE"),
        ("roa", "ROA"), ("eps", "每股收益"),
    ]:
        val = latest.get(key, "N/A")
        if isinstance(val, (int, float)):
            val = f"{val:,.2f}"
        result += f"- **{label}**: {val}\n"

    return result


# ==================== Tushare 通用 API 查询（从 manager.py 迁移） ====================

def query_tushare_api(api_name: str, **kwargs) -> Optional[List[Dict]]:
    """
    通用 Tushare API 查询（带降级）

    通过 TushareProvider 的 api 属性直接调用 Tushare 接口，
    支持 30+ 种 API：龙虎榜、大宗交易、资金流向、融资融券等。

    Args:
        api_name: Tushare 接口名（如 "top_inst", "block_trade", "moneyflow_dc"）
        **kwargs: 接口参数

    Returns:
        List[Dict]: 查询结果列表，失败返回 None
    """
    try:
        from app.data.providers.china.tushare import get_tushare_provider
        provider = get_tushare_provider()

        if not provider or not provider.api:
            logger.warning(f"⚠️ Tushare Provider 不可用")
            return None

        df = provider.api.query(api_name, **kwargs)
        if df is not None and not df.empty:
            return df.to_dict(orient="records")
    except Exception as e:
        logger.error(f"❌ Tushare API 查询失败 [{api_name}]: {e}")
    return None


def get_company_performance(ts_code: str, data_type: str, start_date: str, end_date: str,
                            period: str = None, ind_name: str = None, market: str = "cn"):
    """获取公司业绩数据（支持 A 股/港股/美股）"""
    api_map = {
        "cn": {
            "forecast": "forecast", "express": "express", "indicators": "fina_indicator",
            "dividend": "dividend", "mainbz": "fina_mainbz", "holder_number": "stk_holdernumber",
            "holder_trade": "stk_holdertrade", "managers": "stk_managers", "audit": "fina_audit",
            "company_basic": "stock_company", "balance_basic": "balancesheet",
            "balance_all": "balancesheet", "cashflow_basic": "cashflow",
            "cashflow_all": "cashflow", "income_basic": "income", "income_all": "income",
            "share_float": "share_float", "repurchase": "repurchase",
            "top10_holders": "top10_holders", "top10_floatholders": "top10_floatholders",
            "pledge_stat": "pledge_stat", "pledge_detail": "pledge_detail",
        },
        "hk": {"income": "hk_income", "balance": "hk_balancesheet", "cashflow": "hk_cashflow"},
        "us": {"income": "us_income", "balance": "us_balancesheet", "cashflow": "us_cashflow", "indicator": "us_fina_indicator"},
    }
    api_name = api_map.get(market, {}).get(data_type)
    if not api_name:
        return None

    params = {"ts_code": ts_code, "start_date": start_date, "end_date": end_date}
    if period:
        params["period"] = period
    if ind_name:
        params["ind_name"] = ind_name
    return query_tushare_api(api_name, **params)


def get_macro_econ(indicator: str, start_date: str, end_date: str):
    """获取宏观经济数据"""
    api_map = {
        "shibor": "shibor", "lpr": "lpr_data", "gdp": "cn_gdp", "cpi": "cn_cpi",
        "ppi": "cn_ppi", "cn_m": "cn_m", "cn_pmi": "cn_pmi", "cn_sf": "cn_sf",
        "shibor_quote": "shibor_quote", "libor": "libor", "hibor": "hibor",
    }
    api_name = api_map.get(indicator)
    if not api_name:
        return None
    return query_tushare_api(api_name, start_date=start_date, end_date=end_date)


def get_money_flow(start_date: str, end_date: str, query_type: str = None,
                   ts_code: str = None, content_type: str = None,
                   trade_date: str = None):
    """获取资金流向数据"""
    if not query_type:
        if ts_code and ts_code[0].isdigit():
            query_type = "stock"
        else:
            query_type = "market"

    api_map = {"stock": "moneyflow_dc", "market": "moneyflow_mkt_dc", "sector": "moneyflow_ind_dc"}
    api_name = api_map.get(query_type, "moneyflow_dc")

    params = {"start_date": start_date, "end_date": end_date}
    if ts_code:
        params["ts_code"] = ts_code
    if trade_date:
        params["trade_date"] = trade_date
    return query_tushare_api(api_name, **params)


def get_margin_trade(data_type: str, start_date: str, end_date: str = None,
                    ts_code: str = None, exchange: str = None):
    """获取融资融券数据"""
    return query_tushare_api(data_type, start_date=start_date, end_date=end_date,
                            ts_code=ts_code, exchange_id=exchange)


def get_fund_data(ts_code: str, data_type: str, start_date: str = None,
                  end_date: str = None, period: str = None):
    """获取基金数据"""
    api_map = {
        "basic": "fund_basic", "manager": "fund_manager", "nav": "fund_nav",
        "dividend": "fund_div", "portfolio": "fund_portfolio",
    }
    api_name = api_map.get(data_type)
    if not api_name:
        return None

    params = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if period:
        params["period"] = period
    return query_tushare_api(api_name, **params)


def get_fund_manager_by_name(name: str, ann_date: str = None):
    """按名称查询基金经理"""
    params = {"name": name}
    if ann_date:
        params["ann_date"] = ann_date
    return query_tushare_api("fund_manager", **params)


def get_index_data(code: str, start_date: str, end_date: str):
    """获取指数数据"""
    return query_tushare_api("index_daily", ts_code=code, start_date=start_date, end_date=end_date)


def get_csi_index_constituents(index_code: str, start_date: str, end_date: str):
    """获取指数成分股"""
    return query_tushare_api("index_weight", index_code=index_code,
                            start_date=start_date, end_date=end_date)


def get_convertible_bond(data_type: str, ts_code: str = None,
                         start_date: str = None, end_date: str = None):
    """获取可转债数据"""
    api_map = {"info": "cb_basic", "issue": "cb_issue"}
    api_name = api_map.get(data_type, "cb_basic")
    params = {}
    if ts_code:
        params["ts_code"] = ts_code
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return query_tushare_api(api_name, **params)


def get_block_trade(start_date: str, end_date: str, code: str = None):
    """获取大宗交易数据"""
    params = {"start_date": start_date, "end_date": end_date}
    if code:
        params["ts_code"] = code
    return query_tushare_api("block_trade", **params)


def get_dragon_tiger_inst(trade_date: str, ts_code: str = None):
    """获取龙虎榜数据"""
    params = {"trade_date": trade_date}
    if ts_code:
        params["ts_code"] = ts_code
    return query_tushare_api("top_inst", **params)


def get_finance_news(query: str):
    """获取财经新闻"""
    return query_tushare_api("news", src="sina", query=query)


def get_hot_news_7x24(limit: int = 100):
    """获取 7x24 小时新闻"""
    now = datetime.utcnow()
    start = (now - __import__("datetime").timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    end = now.strftime("%Y-%m-%d %H:%M:%S")
    return query_tushare_api("news", src="sina", start_date=start, end_date=end, limit=limit)


def get_stock_data_cross_market(code: str, market_type: str, start_date: str, end_date: str,
                                indicators: str = None):
    """跨市场股票数据查询"""
    if market_type == "cn":
        api_name = "daily"
    elif market_type == "hk":
        api_name = "hk_daily"
    elif market_type == "us":
        api_name = "us_daily"
    else:
        return None
    return query_tushare_api(api_name, ts_code=code, start_date=start_date, end_date=end_date)


def get_stock_data_minutes(market_type: str, code: str, start_datetime: str,
                           end_datetime: str, freq: str):
    """获取分钟级数据"""
    return query_tushare_api("stk_mins", ts_code=code, start_date=start_datetime,
                            end_date=end_datetime, freq=freq)


# ==================== Fallback 查询（从 manager.py 迁移） ====================

def _get_adapters():
    """获取按优先级排序的 A 股数据适配器列表"""
    from app.data.providers.tushare.adapter import TushareAdapter
    from app.services.data_sources.akshare_adapter import AKShareAdapter
    from app.services.data_sources.baostock_adapter import BaoStockAdapter

    adapters = [TushareAdapter(), AKShareAdapter(), BaoStockAdapter()]
    try:
        db = _get_sync_db()
        groupings = list(db.datasource_groupings.find(
            {"market_category_id": "a_shares", "enabled": True},
        ).sort("priority", -1))
        if groupings:
            priority_map = {
                g["data_source_name"].lower(): g.get("priority", 0)
                for g in groupings
                if g.get("data_source_name")
            }
            for a in adapters:
                if a.name in priority_map:
                    a._priority = priority_map[a.name]
    except Exception:
        pass
    adapters.sort(key=lambda x: x.priority)
    return adapters


def _get_sync_db():
    from app.core.database import get_mongo_db_sync
    return get_mongo_db_sync()


def get_available_adapters():
    """返回可用适配器列表（兼容 DataSourceManager 接口）"""
    return [a for a in _get_adapters() if a.is_available()]


def get_all_adapters():
    """返回所有适配器列表（包括不可用的，兼容 DataSourceManager.adapters 接口）"""
    return _get_adapters()


def get_kline_with_fallback(code: str, period: str = "day", limit: int = 120,
                            adj=None):
    """按优先级获取 K 线数据，返回 (items, source)"""
    for adapter in get_available_adapters():
        try:
            items = adapter.get_kline(code=code, period=period, limit=limit, adj=adj)
            if items:
                return items, adapter.name
        except Exception as e:
            logger.debug(f"获取 K 线失败 [{adapter.name}]: {e}")
            continue
    return None, None


def get_daily_basic_with_fallback(trade_date: str, preferred_sources=None):
    """按优先级获取每日基础指标，返回 (df, source)"""
    adapters = get_available_adapters()
    if preferred_sources:
        priority_map = {name: idx for idx, name in enumerate(preferred_sources)}
        preferred = [a for a in adapters if a.name in priority_map]
        others = [a for a in adapters if a.name not in priority_map]
        preferred.sort(key=lambda a: priority_map.get(a.name, 999))
        adapters = preferred + others

    for adapter in adapters:
        try:
            df = adapter.get_daily_basic(trade_date)
            if df is not None and not df.empty:
                return df, adapter.name
        except Exception as e:
            logger.debug(f"获取每日指标失败 [{adapter.name}]: {e}")
            continue
    return None, None


def get_news_with_fallback(code: str, days: int = 2, limit: int = 50,
                           include_announcements: bool = True):
    """按优先级获取新闻/公告，返回 (items, source)"""
    for adapter in get_available_adapters():
        try:
            items = adapter.get_news(code=code, days=days, limit=limit,
                                     include_announcements=include_announcements)
            if items:
                return items, adapter.name
        except Exception as e:
            logger.debug(f"获取新闻失败 [{adapter.name}]: {e}")
            continue
    return None, None


def get_stock_list_with_fallback(preferred_sources=None):
    """按优先级获取股票列表，返回 (df, source)"""
    adapters = get_available_adapters()
    if preferred_sources:
        priority_map = {name: idx for idx, name in enumerate(preferred_sources)}
        preferred = [a for a in adapters if a.name in priority_map]
        others = [a for a in adapters if a.name not in priority_map]
        preferred.sort(key=lambda a: priority_map.get(a.name, 999))
        adapters = preferred + others

    for adapter in adapters:
        try:
            df = adapter.get_stock_list()
            if df is not None and not df.empty:
                return df, adapter.name
        except Exception as e:
            logger.debug(f"获取股票列表失败 [{adapter.name}]: {e}")
            continue
    return None, None


def find_latest_trade_date_with_fallback(preferred_sources=None):
    """按优先级查找最新交易日期，返回 YYYYMMDD 字符串"""
    from datetime import timedelta as _td
    adapters = get_available_adapters()
    if preferred_sources:
        priority_map = {name: idx for idx, name in enumerate(preferred_sources)}
        preferred = [a for a in adapters if a.name in priority_map]
        others = [a for a in adapters if a.name not in priority_map]
        preferred.sort(key=lambda a: priority_map.get(a.name, 999))
        adapters = preferred + others

    for adapter in adapters:
        try:
            trade_date = adapter.find_latest_trade_date()
            if trade_date:
                return trade_date
        except Exception as e:
            logger.debug(f"查找交易日失败 [{adapter.name}]: {e}")
            continue
    return (datetime.utcnow() - _td(days=1)).strftime("%Y%m%d")


def get_realtime_quotes_with_fallback():
    """按优先级获取实时行情，返回 (quotes_dict, source)"""
    for adapter in get_available_adapters():
        try:
            data = adapter.get_realtime_quotes()
            if data:
                return data, adapter.name
        except Exception as e:
            logger.debug(f"获取实时行情失败 [{adapter.name}]: {e}")
            continue
    return None, None
