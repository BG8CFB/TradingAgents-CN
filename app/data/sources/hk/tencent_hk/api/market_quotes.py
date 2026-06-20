"""
Tencent HK 港股准实时行情 API — qt.gtimg.cn 接口封装。

解析 GBK 编码的文本响应，提取实时行情字段。
"""
import asyncio
import logging
import socket
import urllib.error
import urllib.request
from typing import List, Optional

import pandas as pd

from app.data.sources.base.exceptions import (
    DataFormatError,
    DataNotFoundError,
    DataSourceUnavailableError,
)
from app.data.sources.base.mappers import map_network_exception

logger = logging.getLogger(__name__)

_DOMAIN = "market_quotes"


async def fetch_market_quotes(symbols: List[str]) -> Optional[pd.DataFrame]:
    """获取港股准实时行情快照。

    通过腾讯财经接口 http://qt.gtimg.cn/q= 获取实时行情。
    响应为 GBK 编码的文本，以 ~ 分隔各字段。

    Raises
    ------
    NetworkError
        网络/超时异常（可重试）。
    DataFormatError
        响应解析失败（不可重试）。
    DataNotFoundError
        返回空数据（不可重试）。
    DataSourceUnavailableError
        其他未知异常。

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
    # 参数校验：空列表直接返回（保留原行为，与 if api is None 等模式一致）
    if not symbols:
        return None

    try:
        # 构造请求代码列表: r_hk00700,r_hk00001,...
        codes = ",".join([f"r_hk{str(s).zfill(5)}" for s in symbols])
        url = f"http://qt.gtimg.cn/q={codes}"

        def _fetch():
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read().decode("gbk")

        text = await asyncio.to_thread(_fetch)
    except (
        asyncio.TimeoutError,
        ConnectionError,
        TimeoutError,
        urllib.error.URLError,
        socket.timeout,
    ) as exc:
        # 网络异常：可重试
        # urllib.error.URLError：DNS 失败 / 连接拒绝等网络层错误（不一定有 reason 子类）
        # socket.timeout：底层 socket 超时（URLError 可能包装它，也可能裸抛）
        raise map_network_exception(exc, "tencent_hk", _DOMAIN)
    except Exception as exc:
        # 其他未知异常（含部分 urllib 包装异常）
        raise DataSourceUnavailableError("tencent_hk", _DOMAIN, str(exc))

    # 解析响应文本（保留原结构与逐字段校验）
    # candidates: 满足 ≥50 字段切分的候选行数（用于区分"无响应"与"格式异常"）
    # records: 成功解析的记录
    records = []
    candidates = 0

    for line in text.strip().split(";"):
        line = line.strip()
        if not line or "~" not in line:
            continue
        parts = line.split("~")
        if len(parts) < 50:
            continue
        candidates += 1
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
        except (ValueError, IndexError) as exc:
            # 单条记录字段解析失败：跳过该记录，继续处理后续行
            logger.debug(f"tencent_hk 行情单行解析失败: {exc}")
            continue

    # 所有候选行解析失败：响应存在但格式异常，不可重试
    if candidates > 0 and not records:
        raise DataFormatError(
            "tencent_hk",
            _DOMAIN,
            f"无法解析任何行情记录，候选 {candidates} 行",
        )

    # 无候选或无记录：业务正确但无数据，不可重试
    if not records:
        logger.warning(f"tencent_hk 行情无数据: {len(symbols)} 只")
        raise DataNotFoundError(
            "tencent_hk", _DOMAIN, f"symbols={symbols} 无数据"
        )

    logger.info(f"tencent_hk 行情: {len(records)} 只")
    return pd.DataFrame(records)
