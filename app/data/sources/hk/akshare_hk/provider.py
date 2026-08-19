"""AKShare HK Provider — 委托 api/ 子模块调用 AKShare 港股 API。"""

import logging

import pandas as pd

from app.data.sources.base.provider import BaseProvider
from app.data.sources.base.exceptions import DataNotFoundError, DataSourceError

logger = logging.getLogger(__name__)


def _filter_by_date(
    df: pd.DataFrame,
    start_date: str,
    end_date: str,
    date_cols: list[str] | None = None,
) -> pd.DataFrame:
    """对 DataFrame 做内存日期过滤。

    AKShare HK 部分底层 API 不支持日期参数，需在 Provider 层按
    公告日期 / 除净日 / date 等列做内存过滤。
    """
    if df is None or df.empty:
        return df
    if not start_date and not end_date:
        return df

    if date_cols is None:
        date_cols = ["公告日期", "除净日", "date", "trade_date", "日期"]

    sd = start_date.replace("-", "") if start_date else ""
    ed = end_date.replace("-", "") if end_date else ""

    date_col = None
    for col in date_cols:
        if col in df.columns:
            date_col = col
            break
    if date_col is None:
        return df

    def _norm(val) -> str:
        s = str(val)[:10].replace("-", "")
        return s

    # 分别计算上下界条件再合并：此前 mask 被两次比较覆盖，
    # 第二次 bool Series 与字符串比较直接抛 TypeError（调用方吞成 None）
    normed = df[date_col].apply(_norm)
    mask = pd.Series(True, index=df.index)
    if sd:
        mask &= normed >= sd
    if ed:
        mask &= normed <= ed
    return df[mask].copy()


def _normalize_hk_symbol(symbol: str) -> str:
    """标准化港股代码为 5 位数字。"""
    return str(symbol).replace(".HK", "").lstrip("0").zfill(5)


class AKShareHKProvider(BaseProvider):
    """AKShare 港股数据源 Provider。"""

    def __init__(self):
        super().__init__(name="akshare_hk", market="HK")

    async def connect(self) -> bool:
        self.connected = True
        return True

    def is_available(self) -> bool:
        try:
            import akshare as ak  # noqa: F401

            return True
        except ImportError:
            return False

    async def get_stock_list(self, **kwargs) -> pd.DataFrame:
        try:
            from app.data.sources.hk.akshare_hk.api.basic_info import fetch_stock_list

            return await fetch_stock_list()
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"AKShare-HK 股票列表失败: {e}")
            return None
        except Exception as e:
            logger.error(f"AKShare-HK 股票列表失败: {e}")
            return None

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        try:
            from app.data.sources.hk.akshare_hk.api.daily_quotes import (
                fetch_daily_quotes,
            )

            return await fetch_daily_quotes(symbol, start_date, end_date)
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"AKShare-HK 行情失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"AKShare-HK 行情失败 {symbol}: {e}")
            return None

    async def get_corporate_actions(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        try:
            from app.data.sources.hk.akshare_hk.api.corporate_actions import (
                fetch_corporate_actions,
            )

            normalized = _normalize_hk_symbol(symbol)
            df = await fetch_corporate_actions(normalized)
            # AKShare stock_hk_ggcgy_em 返回含 "除净日" 列，按 start/end 做内存过滤
            return _filter_by_date(
                df,
                start_date,
                end_date,
                date_cols=["除净日", "公告日期", "date", "日期"],
            )
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"AKShare-HK 公司行为失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.debug(f"AKShare-HK 公司行为失败 {symbol}: {e}")
            return None

    async def get_news(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        # 市场级新闻（symbol=None）：复用 CN 的全球财经快讯（覆盖港股）
        if not symbol:
            from app.data.sources.cn.akshare.api.news import fetch_market_news

            result = await fetch_market_news(limit=100)
            return pd.DataFrame(result) if result else None
        try:
            from app.data.sources.hk.akshare_hk.api.news import fetch_news

            normalized = _normalize_hk_symbol(symbol)
            df = await fetch_news(normalized)
            # AKShare stock_hk_notice_report 返回含 "公告日期" 列，按 start/end 做内存过滤
            return _filter_by_date(
                df,
                start_date,
                end_date,
                date_cols=["公告日期", "除净日", "date", "日期"],
            )
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"AKShare-HK 新闻失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.debug(f"AKShare-HK 新闻失败 {symbol}: {e}")
            return None

    async def get_market_quotes(self, symbols=None, **kwargs) -> pd.DataFrame:
        df = await self.get_stock_list()
        if df is None or df.empty:
            return df
        # 按 symbols 参数做内存过滤（全市场快照 → 指定股票子集）
        if not symbols:
            return df
        normalized_symbols = {_normalize_hk_symbol(s) for s in symbols}
        # 候选列名：symbol / 代码 / 股票代码
        sym_col = None
        for col in ("symbol", "代码", "股票代码"):
            if col in df.columns:
                sym_col = col
                break
        if sym_col is None:
            return df
        return df[
            df[sym_col].apply(
                lambda v: _normalize_hk_symbol(str(v)) in normalized_symbols
            )
        ].copy()
