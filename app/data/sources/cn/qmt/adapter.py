"""QMT Adapter — datadir 原始数据 → 标准 Schema（PRD D-5 格式一致性）。

职责与既有 adapter 一致：字段映射、单位转换（手→股）、change/pct_chg 现算、
空值处理；不读文件、不调 API、不写库。
QMT 数据经本 adapter 后与 tushare 等既有源在库内完全同构（同集合、同
Schema、同字段类型）。
"""

import logging
from typing import Any, List

import pandas as pd

from app.data.schema.base.types import _safe_float, _safe_int, _safe_str
from app.data.schema.domains.adj_factors import AdjFactorsSchema
from app.data.schema.domains.basic_info import StockBasicInfoSchema
from app.data.schema.domains.corporate_actions import CorporateActionsSchema
from app.data.schema.domains.daily_quotes import DailyQuotesSchema
from app.data.schema.domains.intraday_quotes import IntradayQuotesSchema
from app.data.schema.domains.tick_quotes import TickQuotesSchema
from app.data.schema.domains.trade_calendar import TradeCalendarSchema
from app.data.sources.base.adapter import BaseAdapter
from .field_maps import (
    CORPORATE_ACTIONS_TRUST_TS_KEY,
    DIVIDEND_PER_UNIT,
    LOT_TO_SHARE,
    TICK_VOLUME_TO_SHARE,
    ms_to_time_of_day_ms,
    ts_code_to_exchange,
    ts_code_to_symbol,
)

logger = logging.getLogger("adapter.CN.qmt")


def _as_list(value: Any) -> List:
    """把 5 档单元格规整为 Python list（兼容 list/tuple/ndarray/None/标量）。

    reader 输出为 ``.tolist()`` 结果，但下游可能经过 parquet/concat 变成
    ndarray 或标量；逐元素清洗前必须先统一容器类型，否则 BSON 写入会因
    numpy 标量（不可序列化）报错。
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if hasattr(value, "tolist"):          # numpy.ndarray
        out = value.tolist()
        return out if isinstance(out, list) else [out]
    # 标量 NaN → 空档位
    try:
        if value != value:                # NaN 自反不等
            return []
    except Exception:  # noqa: BLE001
        return []
    return [value]


def _as_float_list(value: Any) -> List[float]:
    return [f for f in (_safe_float(v) for v in _as_list(value)) if f is not None]


def _as_int_list(value: Any) -> List[int]:
    return [i for i in (_safe_int(v) for v in _as_list(value)) if i is not None]


class QmtAdapter(BaseAdapter):
    """QMT（datadir 本地直读）A 股数据标准化适配器。"""

    def __init__(self, provider=None):
        super().__init__(provider=provider, market="CN", source_name="qmt")

    # ── basic_info ──

    def adapt_basic_info(self, raw: Any) -> List[StockBasicInfoSchema]:
        """datadir 合约列表 → StockBasicInfoSchema。

        datadir 只有代码枚举：name/industry/list_date 置 None（``to_db_doc``
        过滤 None，upsert $set 不含这些键，不覆盖既有源已入库的元数据 ——
        PRD FR-05 规则 2 的合并语义依赖这一点）。
        """
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            ts_code = str(get("ts_code", ""))
            symbol = ts_code_to_symbol(ts_code)
            exchange = ts_code_to_exchange(ts_code)
            results.append(
                StockBasicInfoSchema(
                    symbol=symbol,
                    market="CN",
                    data_source="qmt",
                    full_symbol=f"{symbol}.{exchange}" if exchange else symbol,
                    exchange=exchange,
                    currency="CNY",
                )
            )
        return results

    # ── trade_calendar ──

    def adapt_trade_calendar(self, raw: Any) -> List[TradeCalendarSchema]:
        """datadir 上证指数日线派生日历 → TradeCalendarSchema。

        symbol 沿用既有约定 '__calendar__'（与 TushareCNAdapter 一致）。
        """
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            cal_date = get("cal_date")
            if not cal_date:
                continue
            results.append(
                TradeCalendarSchema(
                    symbol="__calendar__",
                    market="CN",
                    data_source="qmt",
                    exchange=get("exchange", "SSE"),
                    cal_date=str(cal_date),
                    is_open=bool(get("is_open", 1)),
                    pretrade_date=get("pretrade_date"),
                )
            )
        return results

    # ── daily_quotes ──

    def adapt_daily_quotes(self, raw: Any) -> List[DailyQuotesSchema]:
        """datadir K 线帧 → DailyQuotesSchema。

        列契约（provider 已注入 ts_code）：time(ms)/open/high/low/close/
        volume(手)/amount(元)/preClose/adj_f_evt/adj_f_cum。
        单位：volume 手→股 ×100；amount 直存元。
        change/pct_chg 由 close/pre_close 现算（datadir 无独立涨跌列）；
        turnover_rate 置 None（datadir 无流通股本）。
        """
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        # 向量化派生 trade_date（北京时区；日线 time=交易日 00:00）
        trade_dates = pd.to_datetime(df["time"], unit="ms", utc=True).dt.tz_convert(
            "Asia/Shanghai"
        ).dt.strftime("%Y-%m-%d")
        results = []
        for i, (_, row) in enumerate(df.iterrows()):
            get = row.get
            symbol = ts_code_to_symbol(str(get("ts_code", "")))

            volume = _safe_float(get("volume"))
            if volume is not None:
                volume = volume * LOT_TO_SHARE

            close = _safe_float(get("close"))
            pre_close = _safe_float(get("preClose"))
            change = None
            pct_chg = None
            if close is not None and pre_close is not None and pre_close != 0:
                change = round(close - pre_close, 4)
                pct_chg = round((close - pre_close) / pre_close * 100, 4)

            results.append(
                DailyQuotesSchema(
                    symbol=symbol,
                    market="CN",
                    data_source="qmt",
                    trade_date=trade_dates.iloc[i],
                    period="daily",
                    open=_safe_float(get("open")),
                    high=_safe_float(get("high")),
                    low=_safe_float(get("low")),
                    close=close,
                    pre_close=pre_close,
                    change=change,
                    pct_chg=pct_chg,
                    volume=volume,
                    amount=_safe_float(get("amount")),
                    turnover_rate=None,
                )
            )
        return results

    # ── intraday_quotes（M2 / FR-04） ──

    def adapt_intraday_quotes(self, raw: Any) -> List[IntradayQuotesSchema]:
        """datadir 分钟 K 线帧 → IntradayQuotesSchema。

        列契约（provider 已注入 ts_code + freq）：time(ms=bar 时刻)/OHLC/
        volume(手)/amount(元)/preClose。
        单位与日线一致：volume 手→股 ×100；amount 直存元（不 ×1000）。
        pct_chg 按「最新价 vs 昨收」现算（datadir 无独立涨跌列），与日线口径一致；
        唯一键为 (symbol, datetime, freq)，故同股票不同频率互不覆盖。
        """
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        # 向量化派生 datetime（北京时区；分钟线 time 即 bar 结束时刻）
        datetimes = pd.to_datetime(df["time"], unit="ms", utc=True).dt.tz_convert(
            "Asia/Shanghai"
        ).dt.strftime("%Y-%m-%d %H:%M:%S")
        freqs = df["freq"] if "freq" in df.columns else pd.Series([None] * len(df))
        results = []
        for i, (_, row) in enumerate(df.iterrows()):
            get = row.get
            symbol = ts_code_to_symbol(str(get("ts_code", "")))

            volume = _safe_float(get("volume"))
            if volume is not None:
                volume = volume * LOT_TO_SHARE

            close = _safe_float(get("close"))
            pre_close = _safe_float(get("preClose"))
            pct_chg = None
            if close is not None and pre_close is not None and pre_close != 0:
                pct_chg = round((close - pre_close) / pre_close * 100, 4)

            results.append(
                IntradayQuotesSchema(
                    symbol=symbol,
                    market="CN",
                    data_source="qmt",
                    datetime=datetimes.iloc[i],
                    freq=None if pd.isna(freqs.iloc[i]) else str(freqs.iloc[i]),
                    open=_safe_float(get("open")),
                    high=_safe_float(get("high")),
                    low=_safe_float(get("low")),
                    close=close,
                    volume=volume,
                    amount=_safe_float(get("amount")),
                    pct_chg=pct_chg,
                )
            )
        return results

    # ── tick_quotes（M2 / FR-06） ──

    def adapt_tick_quotes(self, raw: Any) -> List[TickQuotesSchema]:
        """datadir 144B tick 帧 → TickQuotesSchema（provider 已注入 ts_code + trade_date）。

        列契约：time(epoch ms，已校准)/lastPrice/amount(元)/volume/lastClose/
        open/high/low/transactionNum/market_phase_status + 5 档 4 列（list）。

        性能：tick 单日可达数万条、全市场千万级，故**不用 ``df.iterrows()``**
        （逐行构造 Series 是主要开销），改为列级 ``tolist()`` 后按下标取值。

        O-2：``volume`` 单位为**手**，按 ``TICK_VOLUME_TO_SHARE``（=100）转股；
        ``volume`` / ``amount`` 是**当日累计值**而非单笔增量（真实 datadir 实测：
        末条累计值与日线 bar 逐值相等），故 Schema 字段名沿用平台惯例但语义为累计。
        """
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        n = len(df)

        times = df["time"].tolist() if "time" in df.columns else [None] * n
        # 时间列：datetime 可读列与当日毫秒唯一键同源派生
        epochs = pd.to_datetime(df["time"], unit="ms", utc=True).dt.tz_convert(
            "Asia/Shanghai"
        )
        datetimes = epochs.dt.strftime("%Y-%m-%d %H:%M:%S").tolist()

        def col(name: str):
            return df[name].tolist() if name in df.columns else [None] * n

        last_price = col("lastPrice")
        amounts = col("amount")
        volumes = col("volume")
        last_close = col("lastClose")
        opens = col("open")
        highs = col("high")
        lows = col("low")
        txns = col("transactionNum")
        phases = col("market_phase_status")
        trade_dates = col("trade_date")
        ts_codes = col("ts_code")

        ask_p, ask_v = col("askPrice"), col("askVol")
        bid_p, bid_v = col("bidPrice"), col("bidVol")

        results = []
        for i in range(n):
            volume = _safe_float(volumes[i])
            if volume is not None:
                volume = volume * TICK_VOLUME_TO_SHARE
            txn = txns[i]
            phase = phases[i]
            results.append(
                TickQuotesSchema(
                    symbol=ts_code_to_symbol(str(ts_codes[i] or "")),
                    market="CN",
                    data_source="qmt",
                    trade_date=_safe_str(trade_dates[i]),
                    time_ms=(
                        ms_to_time_of_day_ms(times[i])
                        if times[i] is not None else None
                    ),
                    datetime=datetimes[i],
                    last_price=_safe_float(last_price[i]),
                    open=_safe_float(opens[i]),
                    high=_safe_float(highs[i]),
                    low=_safe_float(lows[i]),
                    last_close=_safe_float(last_close[i]),
                    volume=volume,
                    amount=_safe_float(amounts[i]),
                    transaction_num=_safe_int(txn),
                    market_phase_status=_safe_int(phase),
                    ask_price=_as_float_list(ask_p[i]),
                    ask_vol=_as_int_list(ask_v[i]),
                    bid_price=_as_float_list(bid_p[i]),
                    bid_vol=_as_int_list(bid_v[i]),
                )
            )
        return results

    # ── corporate_actions（M2 / FR-07） ──

    def adapt_corporate_actions(self, raw: Any) -> List[CorporateActionsSchema]:
        """datadir 分红送配帧 → CorporateActionsSchema（一行一事件，按 action_type 拆分）。

        列契约（provider 已注入 ts_code）：trade_date('YYYYMMDD' 除权日)/
        record_date('YYYYMMDD' 股权登记日)/date_src/interest/stock_bonus/
        stock_gift/allot_num/allot_price/dr。

        单位（V-3 已用真实 datadir 定版）：``interest`` 本身即**每股**现金分红，
        换算系数 ``DIVIDEND_PER_UNIT = 1.0``；送转/配股换算成「每 1 股 → 1+x 股」
        的 ratio 记法（x 同样已是每股口径）。

        唯一键是 ``(symbol, ex_date, action_type)``，故同一次除权若同时含派息+
        送转+配股，会产出 2~3 行 —— 这是设计意图（每种行为独立可查），
        不是重复数据。
        """
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []

        results: List[CorporateActionsSchema] = []
        untrusted = 0
        for _, row in df.iterrows():
            get = row.get
            ex_raw = str(get("trade_date", "") or "")
            if len(ex_raw) != 8 or not ex_raw.isdigit():
                continue
            date_src = str(get("date_src", "") or "")
            if date_src == "ts_key" and not CORPORATE_ACTIONS_TRUST_TS_KEY:
                # 除权日由 LevelDB key 回退派生 → 实测 437 条错位，拒写可疑值
                untrusted += 1
                continue

            symbol = ts_code_to_symbol(str(get("ts_code", "")))
            ex_date = f"{ex_raw[:4]}-{ex_raw[4:6]}-{ex_raw[6:8]}"
            rec_raw = str(get("record_date", "") or "")
            record_date = (
                f"{rec_raw[:4]}-{rec_raw[4:6]}-{rec_raw[6:8]}"
                if len(rec_raw) == 8 and rec_raw.isdigit() else None
            )

            interest = _safe_float(get("interest")) or 0.0
            bonus = _safe_float(get("stock_bonus")) or 0.0
            gift = _safe_float(get("stock_gift")) or 0.0
            allot = _safe_float(get("allot_num")) or 0.0
            allot_price = _safe_float(get("allot_price"))

            common = {
                "symbol": symbol,
                "market": "CN",
                "data_source": "qmt",
                "ex_date": ex_date,
                "record_date": record_date,
                "currency": "CNY",
            }
            if interest > 0:
                results.append(CorporateActionsSchema(
                    **common,
                    action_type="cash_dividend",
                    amount=round(interest / DIVIDEND_PER_UNIT, 6),
                ))
            bonus_shares = (bonus + gift) / DIVIDEND_PER_UNIT
            if bonus_shares > 0:
                results.append(CorporateActionsSchema(
                    **common,
                    action_type="bonus_issue",
                    ratio_from=1.0,
                    ratio_to=round(1.0 + bonus_shares, 6),
                ))
            if allot > 0:
                results.append(CorporateActionsSchema(
                    **common,
                    action_type="rights_issue",
                    ratio_from=1.0,
                    ratio_to=round(1.0 + allot / DIVIDEND_PER_UNIT, 6),
                    rights_price=allot_price,
                ))

        if untrusted:
            logger.warning(
                "分红送配: 跳过 %d 条除权日不可信记录（date_src=ts_key，"
                "PRD「绝不写可疑值」；如部署侧已校正可打开 "
                "CORPORATE_ACTIONS_TRUST_TS_KEY）",
                untrusted,
            )
        return results

    # ── adj_factors ──

    def adapt_adj_factors(self, raw: Any) -> List[AdjFactorsSchema]:
        """datadir K 线因子槽 → AdjFactorsSchema。

        adj_f_cum（累计因子 ≡ Πdr，reader docstring 已实证）语义对应
        tushare adj_factor；adj_f_evt（单次因子）无对应字段不落库；
        fore/back_adj_factor QMT 无对应槽位置 None（V-3）。
        """
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty or "adj_f_cum" not in df.columns:
            return []
        trade_dates = pd.to_datetime(df["time"], unit="ms", utc=True).dt.tz_convert(
            "Asia/Shanghai"
        ).dt.strftime("%Y-%m-%d")
        results = []
        for i, (_, row) in enumerate(df.iterrows()):
            get = row.get
            results.append(
                AdjFactorsSchema(
                    symbol=ts_code_to_symbol(str(get("ts_code", ""))),
                    market="CN",
                    data_source="qmt",
                    trade_date=trade_dates.iloc[i],
                    adj_factor=_safe_float(get("adj_f_cum")),
                    fore_adj_factor=None,
                    back_adj_factor=None,
                )
            )
        return results
