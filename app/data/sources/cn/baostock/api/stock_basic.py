"""
BaoStock 股票基础信息 API
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

from .connection import baostock_session

logger = logging.getLogger(__name__)


async def fetch_stock_list() -> Optional[pd.DataFrame]:
    """获取 A 股股票列表"""
    try:
        async with baostock_session():
            def _fetch():
                rs = bs.query_stock_basic()
                rows = []
                while rs.error_code == "0" and rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    df = pd.DataFrame(rows, columns=rs.fields)
                    return df[df["type"] == "1"]
                return None

            df = await asyncio.to_thread(_fetch)
            if df is not None and not df.empty:
                # 去掉 sh./sz. 前缀
                if "code" in df.columns:
                    df["code"] = df["code"].str.replace(r"^(sh|sz)\.", "", regex=True)
                logger.info(f"BaoStock 股票列表: {len(df)} 只")
            return df
    except Exception as e:
        logger.error(f"BaoStock 获取股票列表失败: {e}")
        return None
