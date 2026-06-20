"""
technical-screening skill 的脚本入口

被 BuiltinToolSpec 注册为工具 technical-screening.calc-indicators。
依赖 mplfinance（可选）——缺失时降级为纯数值输出，不崩溃。

设计要点：
- 入口函数 calc_indicators 是同步函数（与 builtin 工具一致）
- 参数与 manifest.yaml 的 inject_args 对齐
- 返回 JSON 可序列化的 dict（simple_agent_template 的 _inject_tool_data 会序列化）
- 不依赖项目内部模块（保持 skill 自包含，便于 Git 分发）
"""
import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _try_import_pandas():
    try:
        import pandas as pd
        return pd
    except ImportError:
        return None


def _try_import_mplfinance():
    try:
        import mplfinance as mpf
        return mpf
    except ImportError:
        return None


def _fetch_daily_quotes(ticker: str, periods: int) -> Dict[str, Any]:
    """
    通过 DataInterface 拉取日线行情。

    DataInterface.read 是 async，但 builtin 工具调用时通过 asyncio.run 或
    已有事件循环调度；此处用 _run_async 包装兼容两种场景。
    延迟导入避免循环依赖，同时让 skill 在无项目环境时也能被 import。
    """
    import asyncio

    async def _do_read():
        from app.data.core.interface import DataInterface
        from datetime import datetime, timedelta

        di = DataInterface.get_instance()
        end_date = datetime.now().strftime("%Y-%m-%d")
        # periods 个交易日约等于 periods * 1.5 个自然日（含周末）
        start_date = (datetime.now() - timedelta(days=int(periods * 1.6))).strftime("%Y-%m-%d")
        return await di.read(
            "CN",
            "daily_quotes",
            symbol=ticker,
            start_date=start_date,
            end_date=end_date,
        )

    try:
        try:
            asyncio.get_running_loop()
            # 已在事件循环中：通过线程池同步等待，避免嵌套 asyncio.run
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    lambda: asyncio.run(_do_read())
                ).result(timeout=30)
        except RuntimeError:
            # 无运行中的事件循环，可直接 asyncio.run
            pass
        return asyncio.run(_do_read())
    except Exception as e:
        logger.warning(f"拉取日线行情失败 {ticker}: {e}")
        return {"error": str(e)}


def _calc_ma(closes, period: int):
    """简单移动平均"""
    if len(closes) < period:
        return [None] * len(closes)
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            window = closes[i - period + 1 : i + 1]
            result.append(round(sum(window) / period, 4))
    return result


def _calc_macd(closes, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD 指标（标准 EMA 实现）"""
    if len(closes) < slow + signal:
        return {"dif": [], "dea": [], "hist": []}

    def ema(data, period):
        multiplier = 2 / (period + 1)
        result = [data[0]]
        for i in range(1, len(data)):
            result.append(data[i] * multiplier + result[-1] * (1 - multiplier))
        return result

    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    dif = [round(f - s, 4) for f, s in zip(ema_fast, ema_slow)]
    dea = ema(dif, signal)
    dea = [round(d, 4) for d in dea]
    hist = [round(2 * (d - e), 4) for d, e in zip(dif, dea)]
    return {"dif": dif, "dea": dea, "hist": hist}


def _calc_rsi(closes, period: int = 14):
    """RSI 指标"""
    if len(closes) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    result = []
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(round(100 - 100 / (1 + rs), 2))
    return result


def calc_indicators(
    ticker: str,
    trade_date: str = "",
    periods: int = 60,
    **kwargs,
) -> str:
    """
    计算指定股票的技术指标。

    Args:
        ticker: 股票代码（如 000001）
        trade_date: 截止日期（YYYY-MM-DD，空表示最新）
        periods: 拉取的交易日数（默认 60）

    Returns:
        JSON 字符串，包含 MA/MACD/RSI 等指标最新值与近期趋势。
        依赖 mplfinance 缺失时自动降级，不包含图表字段。
    """
    periods = int(periods) if isinstance(periods, str) else periods
    if periods < 30:
        periods = 30

    quotes = _fetch_daily_quotes(ticker, periods)
    if "error" in quotes or not quotes.get("data"):
        return json.dumps(
            {
                "ticker": ticker,
                "error": "无法获取行情数据",
                "detail": quotes.get("error", "数据为空"),
            },
            ensure_ascii=False,
        )

    # 提取收盘价序列
    rows = quotes.get("data", [])
    closes = []
    for row in rows:
        close = row.get("close") if isinstance(row, dict) else None
        if close is not None:
            closes.append(float(close))

    if len(closes) < 30:
        return json.dumps(
            {
                "ticker": ticker,
                "error": "数据不足",
                "data_points": len(closes),
                "required": 30,
            },
            ensure_ascii=False,
        )

    # 计算指标
    ma5 = _calc_ma(closes, 5)
    ma20 = _calc_ma(closes, 20)
    ma60 = _calc_ma(closes, 60)
    macd = _calc_macd(closes)
    rsi = _calc_rsi(closes, 14)

    # mplfinance 可用性检测
    mpf = _try_import_mplfinance()
    chart_available = mpf is not None

    result = {
        "ticker": ticker,
        "trade_date": trade_date,
        "data_points": len(closes),
        "latest_close": closes[-1],
        "indicators": {
            "ma5": ma5[-1] if ma5 else None,
            "ma20": ma20[-1] if ma20 else None,
            "ma60": ma60[-1] if ma60 else None,
            "macd": {
                "dif": macd["dif"][-1] if macd["dif"] else None,
                "dea": macd["dea"][-1] if macd["dea"] else None,
                "hist": macd["hist"][-1] if macd["hist"] else None,
            },
            "rsi_14": rsi[-1] if rsi else None,
        },
        "trend": {
            "ma_sequence": _classify_ma_sequence(ma5[-1], ma20[-1], ma60[-1]),
            "macd_signal": _classify_macd_signal(macd),
            "rsi_zone": _classify_rsi_zone(rsi[-1] if rsi else None),
        },
        "chart_available": chart_available,
        "chart_note": "" if chart_available else "mplfinance 未安装，跳过 K 线渲染",
    }

    return json.dumps(result, ensure_ascii=False, default=str)


def _classify_ma_sequence(ma5, ma20, ma60) -> str:
    """根据均线排列判断趋势"""
    if None in (ma5, ma20, ma60):
        return "数据不足"
    if ma5 > ma20 > ma60:
        return "多头排列（强势）"
    if ma5 < ma20 < ma60:
        return "空头排列（弱势）"
    return "纠缠（震荡）"


def _classify_macd_signal(macd) -> str:
    """根据 MACD 最新值判断信号"""
    dif = macd["dif"][-1] if macd["dif"] else None
    dea = macd["dea"][-1] if macd["dea"] else None
    if dif is None or dea is None:
        return "数据不足"
    if dif > dea:
        return "金叉（看涨）"
    return "死叉（看跌）"


def _classify_rsi_zone(rsi) -> str:
    """根据 RSI 判断超买超卖"""
    if rsi is None:
        return "数据不足"
    if rsi > 70:
        return "超买"
    if rsi < 30:
        return "超卖"
    return "中性"
