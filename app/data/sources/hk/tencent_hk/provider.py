"""Tencent HK Provider — 通过腾讯财经接口获取港股准实时行情。

仅用于 market_quotes 域的准实时更新（交易时段每 30 秒）。
"""

import asyncio
import logging

import pandas as pd

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
        try:
            import urllib.request

            if not symbols:
                return None

            # 腾讯行情接口
            codes = ",".join([f"r_hk{str(s).zfill(5)}" for s in symbols])
            url = f"http://qt.gtimg.cn/q={codes}"

            def _fetch():
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.read().decode("gbk")

            text = await asyncio.to_thread(_fetch)
            records = []
            for line in text.strip().split(";"):
                if not line.strip() or "~" not in line:
                    continue
                parts = line.split("~")
                if len(parts) < 50:
                    continue
                try:
                    records.append({
                        "symbol": parts[2] if len(parts) > 2 else "",
                        "name": parts[1] if len(parts) > 1 else "",
                        "price": float(parts[3]) if parts[3] else None,
                        "last_close": float(parts[4]) if parts[4] else None,
                        "open": float(parts[5]) if parts[5] else None,
                        "volume": float(parts[6]) if parts[6] else None,
                        "high": float(parts[33]) if len(parts) > 33 and parts[33] else None,
                        "low": float(parts[34]) if len(parts) > 34 and parts[34] else None,
                        "bid": float(parts[9]) if len(parts) > 9 and parts[9] else None,
                        "ask": float(parts[10]) if len(parts) > 10 and parts[10] else None,
                        "update_time": parts[30] if len(parts) > 30 else "",
                    })
                except (ValueError, IndexError):
                    continue

            return pd.DataFrame(records) if records else None
        except Exception as e:
            logger.debug(f"Tencent HK 行情失败: {e}")
            return None
