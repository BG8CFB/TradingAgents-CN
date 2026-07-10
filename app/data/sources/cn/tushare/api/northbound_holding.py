"""
Tushare 北向资金数据 API

接口:
- hsgt_top10: 沪深股通十大成交股（北向活跃个股名单）
- moneyflow_hsgt: 沪深港通资金流向（整体北向/南向净流入）

说明: tushare 没有单只 A 股的北向持仓明细接口。
  hk_hold 返回的是港股数据（南向），不是 A 股北向持仓。
  正确做法是用 hsgt_top10 看活跃个股，用 moneyflow_hsgt 看整体方向。

要求: >= 120 积分
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.exceptions import DataNotFoundError, DataSourceUnavailableError
from app.data.sources.base.mappers import (
    is_empty_result,
    map_network_exception,
    map_tushare_code,
)

from .connection import TushareConnection

logger = logging.getLogger(__name__)

_DOMAIN = "northbound_holding"


async def fetch_northbound_holding(
    conn: TushareConnection,
    ts_code: str = None,
    trade_date: str = None,
    start_date: str = None,
    end_date: str = None,
) -> Optional[pd.DataFrame]:
    """获取沪深股通十大成交股（hsgt_top10）

    返回北向资金活跃个股名单，包含成交额、买卖额等信息。
    注：tushare 没有单只 A 股的北向持仓明细接口，
    hk_hold 返回的是港股数据（南向），此函数改用 hsgt_top10。
    """
    if not conn.is_available():
        return None

    # 确定查询日期：优先 trade_date，否则用 end_date 或 start_date
    query_date = None
    if trade_date:
        query_date = str(trade_date).replace("-", "")
    elif end_date:
        query_date = str(end_date).replace("-", "")
    elif start_date:
        query_date = str(start_date).replace("-", "")

    # 如果没有指定日期，默认最近一个交易日
    if not query_date:
        from app.utils.time_utils import get_current_date_compact
        query_date = get_current_date_compact()

    all_dfs = []

    # 分别查沪股通和深股通
    for market_type in ["1", "3"]:
        market_name = "沪股通" if market_type == "1" else "深股通"
        try:
            df = await asyncio.to_thread(
                conn.api.hsgt_top10,
                trade_date=query_date,
                market_type=market_type,
            )
            if not is_empty_result(df):
                df["exchange"] = market_name
                all_dfs.append(df)
        except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
            raise map_network_exception(exc, "tushare", _DOMAIN)
        except Exception as exc:
            error_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)
            mapped = map_tushare_code(error_code, "tushare", _DOMAIN, str(exc))
            if mapped is not None:
                raise mapped
            # 单个市场失败不中断，继续查另一个
            logger.warning(f"Tushare {market_name} top10 失败: {exc}")
            continue

    if not all_dfs:
        logger.debug(f"Tushare 北向资金 top10 为空: date={query_date}")
        raise DataNotFoundError("tushare", _DOMAIN, f"日期 {query_date} 无北向资金数据")

    result = pd.concat(all_dfs, ignore_index=True)

    # 如果指定了 ts_code，过滤该股票
    if ts_code:
        clean_code = ts_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        result = result[result["ts_code"].str.contains(clean_code)]
        if result.empty:
            logger.debug(f"Tushare 北向资金: {ts_code} 不在 top10 名单中")

    logger.info(f"Tushare 北向资金 top10: {len(result)} 条")
    return result
