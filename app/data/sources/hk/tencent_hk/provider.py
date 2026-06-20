"""Tencent HK Provider — 通过腾讯财经接口获取港股准实时行情。

仅用于 market_quotes 域的准实时更新（交易时段每 30 秒）。
"""

import logging

import pandas as pd

from app.data.sources.base.exceptions import DataNotFoundError, DataSourceUnavailableError
from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class TencentHKProvider(BaseProvider):
    """Tencent 港股准实时行情 Provider。"""

    def __init__(self):
        super().__init__(name="tencent_hk", market="HK")

    async def connect(self) -> bool:
        self.connected = True
        return True

    def is_available(self) -> bool:
        return True

    async def get_market_quotes(
        self, symbols=None, **kwargs
    ) -> pd.DataFrame:
        from app.data.sources.hk.tencent_hk.api.market_quotes import fetch_market_quotes

        try:
            return await fetch_market_quotes(list(symbols) if symbols else [])
        except DataNotFoundError:
            return None
        except DataSourceUnavailableError as e:
            logger.debug(f"Tencent HK 行情失败: {e}")
            return None
