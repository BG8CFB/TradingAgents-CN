"""
Tencent HK 港股准实时行情 API — qt.gtimg.cn 接口封装。

解析 GBK 编码的文本响应，提取实时行情字段。
"""
import asyncio
import logging
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_market_quotes(symbols: List[str]) -> Optional[pd.DataFrame]:
    """获取港股准实时行情快照。

    通过腾讯财经接口 http://qt.gtimg.cn/q= 获取实时行情。
    响应为 GBK 编码的文本，以 ~ 分隔各字段。

    Parameters
    ----------
    symbols : List[str]
        港股代码列表，如 ["00700", "00001"]。
        自动转换为 r_hkXXXXX 格式拼接请求。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，包含 symbol / name / price / last_close / open / volume /
        high / low / bid / ask / update_time 等字段。
    """
    if not symbols:
        return None
    try:
        import urllib.request

        # 构造请求代码列表: r_hk00700,r_hk00001,...
        codes = ",".join([f"r_hk{str(s).zfill(5)}" for s in symbols])
        url = f"http://qt.gtimg.cn/q={codes}"

        def _fetch():
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read().decode("gbk")

        text = await asyncio.to_thread(_fetch)
        records = []

        for line in text.strip().split(";"):
            line = line.strip()
            if not line or "~" not in line:
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

        if not records:
            logger.warning(f"Tencent HK 行情无数据: {len(symbols)} 只")
            return None

        logger.info(f"Tencent HK 行情: {len(records)} 只")
        return pd.DataFrame(records)
    except Exception as e:
        logger.error(f"Tencent HK 获取行情失败: {e}")
        return None
