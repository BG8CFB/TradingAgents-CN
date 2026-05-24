"""
股票详情相关API
- 统一响应包: {success, data, message, timestamp}
- 所有端点均需鉴权 (Bearer Token)
- 路径前缀在 main.py 中挂载为 /api，当前路由自身前缀为 /stocks
"""
from typing import Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, status, Query
import logging
import re

from app.routers.auth_db import get_current_user
from app.core.database import get_mongo_db
from app.core.response import ok, safe_error_message
from app.services.unified_stock_service import UnifiedStockService
from app.utils.time_utils import now_config_tz, format_date_compact, format_date_short

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stocks", tags=["Stocks"])


def _zfill_code(code: str) -> str:
    try:
        s = str(code).strip()
        if len(s) == 6 and s.isdigit():
            return s
        return s.zfill(6)
    except Exception:
        return str(code)


def _detect_market_and_code(code: str) -> Tuple[str, str]:
    """
    检测股票代码的市场类型并标准化代码

    Args:
        code: 股票代码

    Returns:
        (market, normalized_code): 市场类型和标准化后的代码
            - CN: A股（6位数字）
            - HK: 港股（4-5位数字或带.HK后缀）
            - US: 美股（字母代码）
    """
    code = code.strip().upper()

    # 港股：带.HK后缀
    if code.endswith('.HK'):
        return ('HK', code[:-3].zfill(5))  # 移除.HK，补齐到5位

    # 美股：纯字母
    if re.match(r'^[A-Z]+$', code):
        return ('US', code)

    # 港股：4-5位数字
    if re.match(r'^\d{4,5}$', code):
        return ('HK', code.zfill(5))  # 补齐到5位

    # A股：6位数字
    if re.match(r'^\d{6}$', code):
        return ('CN', code)

    # 默认当作A股处理
    return ('CN', _zfill_code(code))


@router.get("/{code}/quote", response_model=dict)
async def get_quote(
    code: str,
    force_refresh: bool = Query(False, description="是否强制刷新（跳过缓存）"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取股票实时行情（支持A股/港股/美股）

    自动识别市场类型：
    - 6位数字 → A股
    - 4位数字或.HK → 港股
    - 纯字母 → 美股

    参数：
    - code: 股票代码
    - force_refresh: 是否强制刷新（跳过缓存）

    返回字段（data内，蛇形命名）:
      - code, name, market
      - price(close), change_percent(pct_chg), amount, prev_close(估算)
      - turnover_rate, amplitude（振幅，替代量比）
      - trade_date, updated_at
    """
    # 检测市场类型
    market, normalized_code = _detect_market_and_code(code)

    # 港股和美股：使用新架构 DataInterface
    if market in ['HK', 'US']:
        from app.data.core.interface import DataInterface

        di = DataInterface.get_instance()

        try:
            result = await di.read(market, "market_quotes", symbol=normalized_code)
            quote = result.get("data")
            if not quote:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到行情数据")
            return ok(data=quote)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取{market}股票{code}行情失败: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=safe_error_message(e, "获取行情失败")
            )

    # A股：使用统一服务
    code6 = normalized_code
    db = get_mongo_db()
    service = UnifiedStockService()

    data = await service.get_cn_quote_with_basic_info(code6)
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该股票的任何信息")

    return ok(data)


@router.get("/{code}/fundamentals", response_model=dict)
async def get_fundamentals(
    code: str,
    source: Optional[str] = Query(None, description="数据源 (tushare/akshare/baostock/multi_source)"),
    force_refresh: bool = Query(False, description="是否强制刷新（跳过缓存）"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取基础面快照（支持A股/港股/美股）

    数据来源优先级：
    1. stock_basic_info 集合（基础信息、估值指标）
    2. stock_financial_data 集合（财务指标：ROE、负债率等）

    参数：
    - code: 股票代码
    - source: 数据源（可选），默认按优先级：tushare > multi_source > akshare > baostock
    - force_refresh: 是否强制刷新（跳过缓存）
    """
    # 检测市场类型
    market, normalized_code = _detect_market_and_code(code)

    # 港股和美股：使用新架构 DataInterface
    if market in ['HK', 'US']:
        from app.data.core.interface import DataInterface

        di = DataInterface.get_instance()

        try:
            result = await di.read(market, "basic_info", symbol=normalized_code)
            info = result.get("data")
            if isinstance(info, list):
                info = info[0] if info else None
            if not info:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到基础信息")
            return ok(data=info)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"获取{market}股票{code}基础信息失败: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=safe_error_message(e, "获取基础信息失败")
            )

    # A股：使用统一服务
    code6 = normalized_code
    db = get_mongo_db()
    service = UnifiedStockService()

    if source:
        # 指定数据源时，先检查是否存在
        info = await service.get_cn_fundamentals(code6, source=source)
        if not info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"未找到该股票在数据源 {source} 中的基础信息"
            )
        return ok(data=info)

    data = await service.get_cn_fundamentals(code6)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到该股票的基础信息"
        )

    return ok(data)


@router.get("/{code}/kline", response_model=dict)
async def get_kline(
    code: str,
    period: str = "day",
    limit: int = 120,
    adj: str = "none",
    force_refresh: bool = Query(False, description="是否强制刷新（跳过缓存）"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取K线数据（支持A股/港股/美股）

    period: day/week/month/5m/15m/30m/60m
    adj: none/qfq/hfq
    force_refresh: 是否强制刷新（跳过缓存）

    🔥 新增功能：当天实时K线数据
    - 交易时间内（09:30-15:00）：从 market_quotes 获取实时数据
    - 收盘后：检查历史数据是否有当天数据，没有则从 market_quotes 获取
    """
    from datetime import timedelta, time as dtime

    valid_periods = {"day","week","month","5m","15m","30m","60m"}
    if period not in valid_periods:
        raise HTTPException(status_code=400, detail=f"不支持的period: {period}")

    # 检测市场类型
    market, normalized_code = _detect_market_and_code(code)

    # 港股和美股：使用新架构 DataInterface
    if market in ['HK', 'US']:
        from app.data.core.interface import DataInterface
        from datetime import timedelta, time as dtime

        di = DataInterface.get_instance()

        try:
            result = await di.read(market, "daily_quotes", symbol=normalized_code)
            kline_data = result.get("data", [])
            return ok(data={
                'code': normalized_code,
                'period': period,
                'items': kline_data,
                'source': result.get("freshness", "unknown")
            })
        except Exception as e:
            logger.error(f"获取{market}股票{code}K线数据失败: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=safe_error_message(e, "获取K线数据失败")
            )

    # A股：使用现有逻辑
    code_padded = normalized_code
    adj_norm = None if adj in (None, "none", "", "null") else adj
    items = None
    source = None

    # 周期映射：前端 -> MongoDB
    period_map = {
        "day": "daily",
        "week": "weekly",
        "month": "monthly",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "60m": "60min"
    }
    mongodb_period = period_map.get(period, "daily")

    # 获取当前时间（配置时区）
    now = now_config_tz()
    today_str_yyyymmdd = format_date_compact(now)  # 格式：20251028（用于查询）
    today_str_formatted = format_date_short(now)  # 格式：2025-10-28（用于返回）

    # 1. 优先从 MongoDB 获取（通过新架构 DataInterface）
    try:
        from app.data.core.interface import DataInterface

        di = DataInterface.get_instance()

        end_date = now.strftime("%Y-%m-%d")
        start_date = (now - timedelta(days=limit * 2)).strftime("%Y-%m-%d")

        logger.info(f"尝试从数据平台获取 K 线数据: {code_padded}, period={period}, limit={limit}")
        result = await di.read("CN", "daily_quotes", symbol=code_padded, start_date=start_date, end_date=end_date)
        data = result.get("data")

        if data and isinstance(data, list):
            for row in data[-limit:]:
                items.append({
                    "time": row.get("trade_date", row.get("date", "")),
                    "open": float(row.get("open", 0)) if row.get("open") else None,
                    "high": float(row.get("high", 0)) if row.get("high") else None,
                    "low": float(row.get("low", 0)) if row.get("low") else None,
                    "close": float(row.get("close", 0)) if row.get("close") else None,
                    "volume": float(row.get("volume", row.get("vol", 0))) if row.get("volume") or row.get("vol") else None,
                    "amount": float(row.get("amount", 0)) if row.get("amount") else None,
                })
            source = "mongodb"
            logger.info(f"从数据平台获取到 {len(items)} 条 K 线数据")
    except Exception as e:
        logger.warning(f"⚠️ MongoDB 获取 K 线失败: {e}")

    # 2. 如果 MongoDB 没有数据，降级到外部 API（带超时保护）
    if not items:
        logger.info("MongoDB 无数据，降级到外部 API")
        try:
            import asyncio
            from app.data.core.interface import DataInterface
            from datetime import datetime, timedelta

            di = DataInterface.get_instance()
            end_date = format_date_compact(now_config_tz())
            start_date = format_date_compact(now_config_tz() - timedelta(days=max(limit * 2, 60)))
            market = "CN"
            result = await asyncio.wait_for(
                di.read(market, "daily_quotes", symbol=code_padded, start_date=start_date, end_date=end_date),
                timeout=10.0
            )
            data = result.get("data")
            if data and isinstance(data, list):
                for row in data:
                    items.append({
                        "date": row.get("trade_date", ""),
                        "open": float(row.get("open", 0)) if row.get("open") else None,
                        "close": float(row.get("close", 0)) if row.get("close") else None,
                        "high": float(row.get("high", 0)) if row.get("high") else None,
                        "low": float(row.get("low", 0)) if row.get("low") else None,
                        "volume": float(row.get("volume", 0)) if row.get("volume") else None,
                        "amount": float(row.get("amount", 0)) if row.get("amount") else None,
                    })
                source = "data_platform"
                logger.info(f"从数据平台获取到 {len(items)} 条 K 线数据")
        except asyncio.TimeoutError:
            logger.error("❌ 外部 API 获取 K 线超时（10秒）")
            raise HTTPException(status_code=504, detail="获取K线数据超时，请稍后重试")
        except Exception as e:
            logger.error(f"❌ 外部 API 获取 K 线失败: {e}")
            raise HTTPException(status_code=500, detail=safe_error_message(e, "获取K线数据失败"))

    # 🔥 3. 检查是否需要添加当天实时数据（仅针对日线）
    if period == "day" and items:
        try:
            # 检查历史数据中是否已有当天的数据（支持两种日期格式）
            has_today_data = any(
                item.get("time") in [today_str_yyyymmdd, today_str_formatted]
                for item in items
            )

            # 判断是否在交易时间内或收盘后缓冲期
            current_time = now.time()
            is_weekday = now.weekday() < 5  # 周一到周五

            # 交易时间：9:30-11:30, 13:00-15:00
            # 收盘后缓冲期：15:00-15:30（确保获取到收盘价）
            is_trading_time = (
                is_weekday and (
                    (dtime(9, 30) <= current_time <= dtime(11, 30)) or
                    (dtime(13, 0) <= current_time <= dtime(15, 30))
                )
            )

            # 🔥 只在交易时间或收盘后缓冲期内才添加实时数据
            # 非交易日（周末、节假日）不添加实时数据
            should_fetch_realtime = is_trading_time

            if should_fetch_realtime:
                logger.info(f"🔥 尝试从 market_quotes 获取当天实时数据: {code_padded} (交易时间: {is_trading_time}, 已有当天数据: {has_today_data})")

                # 使用统一服务获取实时行情原始数据
                db = get_mongo_db()
                stock_service = UnifiedStockService()

                # 查询当天的实时行情
                realtime_quote = await stock_service.get_market_quotes_raw(code_padded)

                if realtime_quote:
                    # 🔥 构造当天的K线数据（使用统一的日期格式 YYYY-MM-DD）
                    today_kline = {
                        "time": today_str_formatted,  # 🔥 使用 YYYY-MM-DD 格式，与历史数据保持一致
                        "open": float(realtime_quote.get("open", 0)),
                        "high": float(realtime_quote.get("high", 0)),
                        "low": float(realtime_quote.get("low", 0)),
                        "close": float(realtime_quote.get("close", 0)),
                        "volume": float(realtime_quote.get("volume", 0)),
                        "amount": float(realtime_quote.get("amount", 0)),
                    }

                    # 如果历史数据中已有当天数据，替换；否则追加
                    if has_today_data:
                        # 替换最后一条数据（假设最后一条是当天的）
                        items[-1] = today_kline
                        logger.info(f"✅ 替换当天K线数据: {code_padded}")
                    else:
                        # 追加到末尾
                        items.append(today_kline)
                        logger.info(f"✅ 追加当天K线数据: {code_padded}")

                    source = f"{source}+market_quotes"
                else:
                    logger.warning(f"⚠️ market_quotes 中未找到当天数据: {code_padded}")
        except Exception as e:
            logger.warning(f"⚠️ 获取当天实时数据失败（忽略）: {e}")

    data = {
        "symbol": code_padded,
        "period": period,
        "limit": limit,
        "adj": adj if adj else "none",
        "source": source,
        "items": items or []
    }
    return ok(data)


@router.get("/{code}/news", response_model=dict)
async def get_news(code: str, days: int = 30, limit: int = 50, include_announcements: bool = True, current_user: dict = Depends(get_current_user)):
    """获取新闻与公告（支持A股、港股、美股）"""
    from app.data.core.interface import DataInterface
    from app.services.news_data_service import get_news_data_service, NewsQueryParams

    # 检测股票类型
    market, normalized_code = _detect_market_and_code(code)

    if market == 'US':
        # 美股：使用 DataInterface
        di = DataInterface.get_instance()
        result = await di.read("US", "news", symbol=normalized_code)
        news_items = result.get("data", [])
        return ok(data={"symbol": normalized_code, "items": news_items or [], "supported": True})
    elif market == 'HK':
        # 港股新闻功能尚未实现
        return ok(
            data={
                "symbol": normalized_code,
                "items": [],
                "supported": False,
            },
            message="港股新闻功能尚未实现，当前仅支持A股和美股新闻"
        )
    else:
        # A股：直接调用同步服务的查询方法（包含智能回退逻辑）
        try:
            logger.info("=" * 80)
            logger.info(f"📰 开始获取新闻: code={code}, normalized_code={normalized_code}, days={days}, limit={limit}")

            # 直接使用 news_data 路由的查询逻辑
            from app.services.news_data_service import get_news_data_service, NewsQueryParams
            from datetime import datetime

            service = await get_news_data_service()

            # 计算时间范围
            hours_back = days * 24

            # 🔥 不设置 start_time 限制，直接查询最新的 N 条新闻
            # 因为数据库中的新闻可能不是最近几天的，而是历史数据
            params = NewsQueryParams(
                symbol=normalized_code,
                limit=limit,
                sort_by="publish_time",
                sort_order=-1
            )

            logger.info(f"🔍 查询参数: symbol={params.symbol}, limit={params.limit} (不限制时间范围)")

            # 1. 先从数据库查询
            logger.info("📊 步骤1: 从数据库查询新闻...")
            news_list = await service.query_news(params)
            logger.info(f"📊 数据库查询结果: 返回 {len(news_list)} 条新闻")

            data_source = "database"

            # 2. 如果数据库没有数据，调用同步服务
            if not news_list:
                logger.info(f"⚠️ 数据库无新闻数据，通过 DataInterface 刷新: {normalized_code}")
                try:
                    from app.data.core.interface import DataInterface
                    di = DataInterface.get_instance()
                    await di.refresh("CN", normalized_code, domains=["news"], force=True)

                    # 重新查询
                    logger.info("🔄 步骤3: 重新从数据库查询...")
                    news_list = await service.query_news(params)
                    logger.info(f"📊 重新查询结果: 返回 {len(news_list)} 条新闻")
                    data_source = "realtime"

                except Exception as e:
                    logger.error(f"❌ 同步服务异常: {e}", exc_info=True)

            # 转换为旧格式（兼容前端）
            logger.info("🔄 步骤4: 转换数据格式...")
            items = []
            for news in news_list:
                # 🔥 将 datetime 对象转换为 ISO 字符串
                publish_time = news.get("publish_time", "")
                if isinstance(publish_time, datetime):
                    publish_time = publish_time.isoformat()

                items.append({
                    "title": news.get("title", ""),
                    "source": news.get("source", ""),
                    "time": publish_time,
                    "url": news.get("url", ""),
                    "type": "news",
                    "content": news.get("content", ""),
                    "summary": news.get("summary", "")
                })

            logger.info(f"✅ 转换完成: {len(items)} 条新闻")

            data = {
                "symbol": normalized_code,
                "days": days,
                "limit": limit,
                "include_announcements": include_announcements,
                "source": data_source,
                "items": items
            }

            logger.info(f"📤 最终返回: source={data_source}, items_count={len(items)}")
            logger.info("=" * 80)
            return ok(data)

        except Exception as e:
            logger.error(f"❌ 获取新闻失败: {e}", exc_info=True)
            data = {
                "symbol": normalized_code,
                "days": days,
                "limit": limit,
                "include_announcements": include_announcements,
                "source": None,
                "items": []
            }
            return ok(data)


@router.get("/search", response_model=dict)
async def search_stocks(
    q: str = Query(..., min_length=1, description="搜索关键词（代码或名称）"),
    market: str = Query("CN", description="市场类型 (CN/HK/US)"),
    limit: int = Query(20, ge=1, le=100, description="返回结果数量"),
    current_user: dict = Depends(get_current_user)
):
    """搜索股票（支持多市场）"""
    market = market.upper()
    if market not in ["CN", "HK", "US"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的市场类型: {market}"
        )

    db = get_mongo_db()
    service = UnifiedStockService()

    try:
        results = await service.search_stocks(market, q, limit)
        return ok(data={
            "stocks": results,
            "total": len(results)
        })
    except Exception as e:
        logger.error(f"搜索股票失败: market={market}, q={q}, error={e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "搜索失败")
        )


@router.get("/{code}/basic-info", response_model=dict)
async def get_basic_info(
    code: str,
    current_user: dict = Depends(get_current_user)
):
    """获取股票基础信息（替代原 /api/stock-data/basic-info/{symbol}）"""
    try:
        from app.data.core.interface import DataInterface
        di = DataInterface.get_instance()
        result = await di.read("CN", "basic_info", symbol=str(code).zfill(6))
        stock_info = result.get("data")

        if not stock_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"未找到股票代码 {code} 的基础信息"
            )
        # 返回第一条记录（如果数据是列表）
        if isinstance(stock_info, list):
            stock_info = stock_info[0] if stock_info else None
        return ok(data=stock_info)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "获取股票基础信息失败")
        )


@router.get("/sync-status/quotes", response_model=dict)
async def get_quotes_sync_status(
    current_user: dict = Depends(get_current_user)
):
    """获取实时行情同步状态（替代原 /api/stock-data/sync-status/quotes）"""
    try:
        from app.services.quotes_ingestion_service import QuotesIngestionService
        service = QuotesIngestionService()
        status_data = await service.get_sync_status()
        return ok(data=status_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_error_message(e, "获取同步状态失败")
        )

