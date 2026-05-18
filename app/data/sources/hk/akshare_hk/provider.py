"""
港股 AKShare Provider

包装现有 improved_hk 模块，复用全部 API 调用逻辑。
"""

import asyncio
import logging
from typing import Any, Dict, Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class AKShareHKProvider(BaseProvider):
    """港股 AKShare Provider"""

    def __init__(self):
        super().__init__(name="akshare_hk", market="HK")

    async def connect(self) -> bool:
        self.connected = True
        return True

    def is_available(self) -> bool:
        try:
            import importlib.util
            return importlib.util.find_spec("app.data.providers.hk.improved_hk") is not None
        except (ImportError, ValueError):
            return False

    async def get_stock_list(self) -> Optional[pd.DataFrame]:
        """获取港股全市场股票列表（使用东方财富港股实时行情接口）"""
        try:
            import akshare as ak

            def _fetch():
                return ak.stock_hk_spot_em()

            df = await asyncio.to_thread(_fetch)
            if df is None or df.empty:
                logger.warning("AKShare-HK: stock_hk_spot_em 返回空数据")
                return None

            logger.info(f"AKShare-HK: 获取到 {len(df)} 只港股")
            return df
        except Exception as e:
            logger.error(f"AKShare-HK: 获取港股列表失败: {e}")
            return None

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        from app.data.providers.hk.improved_hk import get_hk_stock_info_akshare
        return get_hk_stock_info_akshare(symbol)

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """获取港股日线行情数据，返回 DataFrame"""
        try:
            import akshare as ak
            from app.data.providers.hk.improved_hk import get_improved_hk_provider

            provider = get_improved_hk_provider()
            normalized_symbol = provider._normalize_hk_symbol(symbol)

            df = ak.stock_hk_daily(symbol=normalized_symbol, adjust="qfq")
            if df is None or df.empty:
                logger.warning(f"⚠️ [AKShare-HK] 返回空数据: {symbol}")
                return None

            # 日期过滤
            df['date'] = pd.to_datetime(df['date'])
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
            df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)]

            if df.empty:
                logger.warning(f"⚠️ [AKShare-HK] 日期范围内无数据: {symbol}")
                return None

            # 添加 pre_close / change / pct_change
            df['pre_close'] = df['close'].shift(1)
            df['change'] = df['close'] - df['pre_close']
            df['pct_change'] = (df['change'] / df['pre_close'] * 100).round(2)

            return df
        except Exception as e:
            logger.error(f"❌ [AKShare-HK] 获取行情失败: {symbol} - {e}")
            return None
