"""
Tushare US 美股财务数据 API（利润表/资产负债表/现金流量表）
"""
import asyncio
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _to_us_ts_code(symbol: str) -> str:
    """将普通 ticker 转换为 Tushare US ts_code 格式。

    AAPL → AAPL.O (NASDAQ 默认)
    """
    symbol = symbol.upper().strip()
    if "." in symbol:
        return symbol
    return f"{symbol}.O"


async def fetch_financial_data(
    api,
    ts_code: str,
    statement_type: str = "income",
) -> Optional[pd.DataFrame]:
    """获取美股财务报表数据。

    根据 statement_type 调用不同的 Tushare US 财务接口：
    - "income" → api.us_income()（利润表）
    - "balance" → api.us_balancesheet()（资产负债表）
    - "cashflow" → api.us_cashflow()（现金流量表）

    Args:
        api: tushare pro_api 实例
        ts_code: 股票代码，如 "AAPL" 或 "AAPL.O"
        statement_type: 报表类型 ("income"/"balance"/"cashflow")

    Returns:
        财务数据 DataFrame，失败返回 None
    """
    if api is None:
        return None
    us_code = _to_us_ts_code(ts_code)

    api_method_map = {
        "income": "us_income",
        "balance": "us_balancesheet",
        "cashflow": "us_cashflow",
    }
    method_name = api_method_map.get(statement_type, "us_income")

    try:
        method = getattr(api, method_name, None)
        if method is None:
            logger.error(f"Tushare US 不支持的方法: {method_name}")
            return None
        df = await asyncio.to_thread(method, ts_code=us_code)
        if df is not None and not df.empty:
            logger.info(
                f"Tushare US 财务数据 ({statement_type}): {us_code} {len(df)} 条"
            )
        return df
    except Exception as e:
        logger.debug(f"Tushare US 获取财务数据失败 {ts_code} ({statement_type}): {e}")
        return None
