"""
AKShare 全球指数 API — 通过 index_global_hist_em（东方财富）获取。

作为 tushare index_global 的备用源（partial：仅有 OHLC，无成交量/成交额）。
"""
import asyncio
import logging

import pandas as pd

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import is_empty_result, map_network_exception

logger = logging.getLogger(__name__)
_DOMAIN = "index_global"

# tushare 全球指数代码 -> akshare 东方财富中文名称
_TS_CODE_TO_AK_NAME = {
    "SPX.GI": "标普500",
    "HSI.HI": "恒生指数",
    "N225.GI": "日经225",
    "SX5E.GI": "欧洲斯托克50",
    "FTSE.GI": "英国富时100",
    "IXIC.GI": "纳斯达克",
    "GDAXI.GI": "德国DAX30",
    "FCHI.GI": "法国CAC40",
}

# akshare index_global_hist_em 列名 -> index_global schema 列名
_COLUMN_MAPPER = {
    "日期": "trade_date",
    "代码": "ts_code",
    "名称": "name",
    "今开": "open",
    "最新价": "close",
    "最高": "high",
    "最低": "low",
}


async def fetch_index_global(
    ts_code: str,
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """获取全球指数行情（AKShare 回退源）。

    按 tushare 全球指数代码（如 SPX.GI）映射到东方财富中文名称后拉取历史行情。
    返回列：symbol / trade_date / open / high / low / close（与 tushare 同集合兼容）。
    """
    ak_name = _TS_CODE_TO_AK_NAME.get(ts_code)
    if not ak_name:
        raise DataNotFoundError("akshare", _DOMAIN, f"ts_code={ts_code} 无对应 akshare 全球指数")

    try:
        import akshare as ak

        from app.data.sources.cn.akshare.api.anti_scraping import wait_rate_limit

        def _fetch():
            wait_rate_limit()
            return ak.index_global_hist_em(symbol=ak_name)

        df = await asyncio.to_thread(_fetch)
    except (asyncio.TimeoutError, ConnectionError, TimeoutError) as exc:
        raise map_network_exception(exc, "akshare", _DOMAIN)
    except (KeyError, IndexError, AttributeError, ValueError) as exc:
        raise DataFormatError("akshare", _DOMAIN, f"ts_code={ts_code}: {exc}")
    except Exception as exc:
        raise DataSourceUnavailableError("akshare", _DOMAIN, f"ts_code={ts_code}: {exc}")

    if is_empty_result(df):
        raise DataNotFoundError("akshare", _DOMAIN, f"ts_code={ts_code} 无全球指数数据")

    df = df.rename(columns=_COLUMN_MAPPER)

    # 日期归一化为 YYYYMMDD
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.strftime("%Y%m%d")
        df = df.dropna(subset=["trade_date"])

    # 日期范围过滤（归一化 YYYY-MM-DD / YYYYMMDD）
    def _norm(s: str) -> str:
        return str(s).replace("-", "")

    if start_date:
        df = df[df["trade_date"] >= _norm(start_date)]
    if end_date:
        df = df[df["trade_date"] <= _norm(end_date)]

    if df.empty:
        raise DataNotFoundError("akshare", _DOMAIN, f"ts_code={ts_code} 过滤后无数据")

    # symbol 与 tushare 保持一致（代码部分，如 SPX.GI -> SPX）
    df["symbol"] = df["ts_code"] if "ts_code" in df.columns else str(ts_code).split(".")[0]
    df["data_source"] = "akshare"

    logger.info(f"AKShare 全球指数: {ts_code} {len(df)} 条")
    return df
