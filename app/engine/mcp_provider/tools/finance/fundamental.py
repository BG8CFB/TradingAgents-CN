"""
Fundamental Data Tools Logic
"""
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


async def get_company_metrics_logic(reader_mod, code: str, date: str) -> str:
    """
    Logic for get_company_metrics tool.
    """
    try:
        df, source = await asyncio.to_thread(
            reader_mod.get_daily_basic_with_fallback,
            trade_date=date
        )

        if df is None or df.empty:
            return json.dumps({
                "status": "warning",
                "message": f"No fundamental data found for date {date}."
            }, ensure_ascii=False)

        target_code = code

        if 'ts_code' in df.columns:
            matched = df[df['ts_code'] == target_code]
            if matched.empty:
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
