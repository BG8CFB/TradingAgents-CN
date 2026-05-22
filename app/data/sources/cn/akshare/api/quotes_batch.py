"""
AKShare 批量行情 API（三级回退：EM 直接 → 腾讯批量 → ak API）
"""
import asyncio
import logging
from typing import Dict, List, Optional, Any


logger = logging.getLogger(__name__)


async def fetch_batch_quotes(codes: List[str]) -> Optional[Dict[str, Dict[str, Any]]]:
    """批量获取实时行情（三级回退）"""
    for strategy_name, strategy_fn in [
        ("em_direct", _fetch_em_spot_direct),
        ("tencent_batch", _fetch_tencent_batch),
        ("ak_api", _fetch_ak_spot),
    ]:
        try:
            result = await strategy_fn(codes)
            if result:
                logger.info(f"AKShare 批量行情: {strategy_name} 返回 {len(result)} 只")
                return result
        except Exception as e:
            logger.debug(f"AKShare 批量行情 {strategy_name} 失败: {e}")
            continue

    logger.error("AKShare 批量行情: 所有策略失败")
    return None


async def _fetch_em_spot_direct(codes: List[str]) -> Optional[Dict[str, Dict[str, Any]]]:
    """策略 1: 东方财富直接 HTTP"""
    try:
        from app.utils.anti_scraping import fetch_em_spot_direct
        data = await asyncio.to_thread(fetch_em_spot_direct)
        if not data:
            return None
        result = {}
        for code in codes:
            code6 = str(code).zfill(6)
            if code6 in data:
                result[code6] = data[code6]
        return result if result else None
    except ImportError:
        return None


async def _fetch_tencent_batch(codes: List[str]) -> Optional[Dict[str, Dict[str, Any]]]:
    """策略 2: 腾讯批量接口"""
    try:
        from app.utils.anti_scraping import fetch_tencent_spot_batch
        data = await asyncio.to_thread(fetch_tencent_spot_batch, codes)
        return data
    except (ImportError, Exception):
        return None


async def _fetch_ak_spot(codes: List[str]) -> Optional[Dict[str, Dict[str, Any]]]:
    """策略 3: AKShare API"""
    try:
        import akshare as ak

        def _fetch():
            return ak.stock_zh_a_spot_em()

        df = await asyncio.to_thread(_fetch)
        if df is None or df.empty:
            return None

        result = {}
        code_set = {str(c).zfill(6) for c in codes}
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).zfill(6)
            if code in code_set:
                result[code] = row.to_dict()
        return result if result else None
    except Exception:
        return None
