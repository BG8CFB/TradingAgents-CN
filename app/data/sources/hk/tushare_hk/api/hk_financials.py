"""
Tushare HK 港股财务数据 API — 多表联合（利润表/资产负债表/现金流量表）。
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


async def fetch_financial_data(
    api,
    ts_code: str,
    statement_type: str = "income",
) -> Optional[pd.DataFrame]:
    """获取港股财务报表数据。

    根据 statement_type 路由到对应的 Tushare HK 接口：
    - income     → api.hk_income()
    - balance    → api.hk_balancesheet()
    - cashflow   → api.hk_cashflow()
    - indicator  → api.hk_fina_indicator()

    Parameters
    ----------
    api : tushare.pro_api
        已初始化的 Tushare pro_api 实例。
    ts_code : str
        Tushare 格式港股代码，如 "0700.HK"。
    statement_type : str
        报表类型: income / balance / cashflow / indicator。

    Returns
    -------
    Optional[pd.DataFrame]
        原始 DataFrame，字段因报表类型不同而异。
    """
    if api is None:
        return None
    try:
        api_method_map = {
            "income": "hk_income",
            "balance": "hk_balancesheet",
            "cashflow": "hk_cashflow",
            "indicator": "hk_fina_indicator",
        }
        method_name = api_method_map.get(statement_type, "hk_income")
        method = getattr(api, method_name, None)
        if method is None:
            logger.error(f"Tushare HK 不支持的财务接口: {method_name}")
            return None

        df = await asyncio.to_thread(lambda: method(ts_code=ts_code))
        if df is not None and not df.empty:
            logger.info(f"Tushare HK 财务数据({statement_type}): {ts_code} {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"Tushare HK 获取财务数据失败: {ts_code} ({statement_type}) - {e}")
        return None
