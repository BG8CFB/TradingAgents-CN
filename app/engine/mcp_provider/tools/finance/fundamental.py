"""
Fundamental Data Tools Logic
"""
import asyncio
import json
import logging
from app.data.manager import DataSourceManager
from app.utils.stock_utils import StockUtils, StockMarket

logger = logging.getLogger(__name__)

async def get_company_metrics_logic(manager: DataSourceManager, code: str, date: str) -> str:
    """
    Logic for get_company_metrics tool.
    """
    # 1. Identify Market
    market = StockUtils.identify_stock_market(code)

    # Fundamental data currently optimized for A-share in TushareAdapter (daily_basic)
    # If US/HK, Tushare might support it but fields differ.
    # For safe MVP, we might warn if not A-share, or let it try if Tushare handles it.

    try:
        # manager.get_daily_basic_with_fallback
        df, source = await asyncio.to_thread(
            manager.get_daily_basic_with_fallback,
            trade_date=date
        )

        if df is None or df.empty:
             return json.dumps({
                "status": "warning",
                "message": f"No fundamental data found for date {date}."
            }, ensure_ascii=False)

        # Filter for the specific code if dataframe contains multiple
        # Tushare daily_basic returns all stocks for a date usually
        # We need to filter by code.

        # Normalize code for matching (remove suffix if needed, or match ts_code)
        # Tushare returns 'ts_code' like '000001.SZ'

        # Simple fuzzy match or exact match
        target_code = code

        # If df has ts_code
        if 'ts_code' in df.columns:
            # Try exact match
            matched = df[df['ts_code'] == target_code]
            if matched.empty:
                # Try matching without suffix
                prefix = target_code.split('.')[0]
                matched = df[df['ts_code'].str.startswith(prefix)]

            if not matched.empty:
                record = matched.iloc[0].to_dict()
                return json.dumps({
                    "code": code,
                    "date": date,
                    "source": source,
                    "metrics": record
                }, ensure_ascii=False, default=str)

        return json.dumps({
            "status": "warning",
            "message": f"Data available for {date} but code {code} not found in records."
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Error in get_company_metrics_logic: {e}")
        return json.dumps({
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False)
