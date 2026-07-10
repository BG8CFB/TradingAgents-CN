"""
AKShare 行业资金流 API — 通过 stock_fund_flow_industry（同花顺）获取。

作为 tushare moneyflow_ind_dc 的备用源。akshare 仅提供即时快照（无历史日期），
本函数以传入的 trade_date（或当日）标注数据日期，按行业维度产出资金流。
"""
import asyncio
import logging
from datetime import date

import pandas as pd

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import is_empty_result, map_network_exception

logger = logging.getLogger(__name__)
_DOMAIN = "moneyflow_ind_dc"

# 两种返回形态（同花顺接口在不同时间返回的列不同），统一重命名为标准列名
_COLUMN_MAPPER = {
    "行业": "industry",
    "行业指数": "index",
    "行业-涨跌幅": "pct_chg",
    "阶段涨跌幅": "pct_chg",
    "流入资金": "inflow",
    "流出资金": "outflow",
    "净额": "net_amount",
    "公司家数": "count",
    "领涨股": "leader",
    "领涨股-涨跌幅": "leader_pct",
    "当前价": "price",
}


def _norm_date(s: str) -> str:
    if not s:
        return None
    return str(s).replace("-", "")[:8]


async def fetch_moneyflow_ind_dc(
    trade_date: str = None,
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """获取行业资金流（AKShare 回退源，即时快照）。"""
    td = _norm_date(trade_date) or date.today().strftime("%Y%m%d")

    try:
        import akshare as ak

        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        def _fetch():
            wait_rate_limit()
            return ak.stock_fund_flow_industry(symbol="即时")

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"{exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"{exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, "无行业资金流")

    df = df.rename(columns=_COLUMN_MAPPER)

    df["trade_date"] = td
    # 同花顺接口无股票代码维度，以行业名称作为 symbol
    if "industry" in df.columns:
        df["symbol"] = df["industry"].astype(str)
        df["ts_code"] = df["industry"].astype(str)
    df["data_source"] = "akshare"

    logger.info(f"AKShare 行业资金流: {td} {len(df)} 条")
    return df
