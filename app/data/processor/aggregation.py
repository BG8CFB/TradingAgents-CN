"""周期聚合 — 将日线数据聚合为周线/月线。"""

import logging
from typing import List, Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)


def aggregate_period(
    data: Union[pd.DataFrame, List[dict]],
    period: str = "daily",
) -> Optional[pd.DataFrame]:
    """将日线数据聚合为指定周期。

    Args:
        data: 日线数据，支持 DataFrame 或 dict 列表
        period: 聚合周期 ("daily" / "weekly" / "monthly")

    Returns:
        聚合后的 DataFrame；输入为空列表时返回空列表以保持兼容
    """
    if data is None:
        return None

    # 兼容 list 输入 — 空列表返回空列表
    if isinstance(data, list):
        if not data:
            return []
        df = pd.DataFrame(data)
    else:
        df = data

    if not isinstance(df, pd.DataFrame) or df.empty:
        if isinstance(data, list):
            return []
        return None

    if period == "daily":
        return df

    if "trade_date" not in df.columns:
        logger.warning("聚合需要 trade_date 列")
        return df

    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date")

    if period == "weekly":
        iso = df["trade_date"].dt.isocalendar()
        df["period_key"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    elif period == "monthly":
        df["period_key"] = df["trade_date"].dt.to_period("M").astype(str)
    else:
        return df

    agg_dict = {}
    if "open" in df.columns:
        agg_dict["open"] = "first"
    if "high" in df.columns:
        agg_dict["high"] = "max"
    if "low" in df.columns:
        agg_dict["low"] = "min"
    if "close" in df.columns:
        agg_dict["close"] = "last"
    if "volume" in df.columns:
        agg_dict["volume"] = "sum"
    if "amount" in df.columns:
        agg_dict["amount"] = "sum"
    if "symbol" in df.columns:
        agg_dict["symbol"] = "first"

    if not agg_dict:
        return df

    result = df.groupby("period_key").agg(agg_dict).reset_index()

    # 添加 trade_date（取每组第一天）
    first_dates = df.groupby("period_key")["trade_date"].first()
    result["trade_date"] = first_dates.values

    result = result.drop(columns=["period_key"])

    # 如果输入是 list，返回 list of dict
    if isinstance(data, list):
        result_list = result.to_dict(orient="records")
        # 转换日期为字符串
        for row in result_list:
            if "trade_date" in row and hasattr(row["trade_date"], "strftime"):
                row["trade_date"] = row["trade_date"].strftime("%Y-%m-%d")
            for key, val in row.items():
                if hasattr(val, "item"):
                    row[key] = val.item()
        return result_list

    return result
