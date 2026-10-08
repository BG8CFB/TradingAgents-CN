"""L0 因子计算引擎 — 读标准集合，批量向量化计算 19 因子并落库 stock_factor_scores。

设计约束（spec §7）：
- 全市场批量向量化（groupby + 滚动窗口），禁止逐股串行读库
- ST / 行情数据不足 60 日的股票剔除（数据不足同时覆盖「上市<60日」与「长期停牌」）
- 可选域（money_flow 等）当日缺失时对应因子置 NaN，不阻塞
- 交易日窗口从 daily_quotes distinct trade_date 取（数据驱动，避免日历错位）
- 流式游标读取控内存；indicators 只投影 4 列

对外入口：
- compute_factors(market) -> DataFrame   纯读+算（测试/诊断用）
- compute_and_store(market) -> dict      算+落库（调度入口）
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.data.factors.scoring import compute_style_scores, rank_factors_by_industry
from app.data.factors.strategy_config import get_factor_groups, get_style_weights
from app.data.schema.domains.factor_scores import FACTOR_FIELDS
from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    """EMA 递推（口径同 app/utils/indicators）。"""
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def _macd_golden_days(close: np.ndarray) -> float:
    """金叉状态天数：dif>dea 时为最近一次死叉以来的天数（正），反之为负。"""
    if len(close) < 35:  # EMA26+DEA9 预热不足，不可判
        return np.nan
    dif = _ema(close, 12) - _ema(close, 26)
    dea = _ema(dif, 9)
    above = dif[-1] > dea[-1]
    days = 0
    for i in range(len(close) - 1, -1, -1):
        if above and dif[i] <= dea[i]:
            break
        if not above and dif[i] >= dea[i]:
            break
        days += 1
    return float(days) if above else -float(days)


def _consecutive_up_days(vol: np.ndarray) -> int:
    """末位起连续放量天数（vol[i] > vol[i-1] 计一天；首日缩量即 0）。"""
    days = 0
    for i in range(len(vol) - 1, 0, -1):
        if vol[i] > vol[i - 1]:
            days += 1
        else:
            break
    return days


class FactorScoreEngine:
    QUOTE_WINDOW_TRADE_DAYS = 120      # 动量/趋势/量能窗口
    PERCENTILE_WINDOW_TRADE_DAYS = 500 # 估值分位窗口
    MIN_PERCENTILE_ROWS = 120         # 少于约半年有效样本，不发布历史分位
    FLOW_WINDOW_TRADE_DAYS = 5         # 资金窗口
    MIN_QUOTE_ROWS = 60                # 数据不足剔除线

    async def compute_and_store(self, market: str = "CN") -> Dict:
        df = await self.compute_factors(market)
        if df.empty and not df.attrs.get("complete_snapshot"):
            return {"status": "skipped", "reason": "no_data", "rows": 0}
        trade_date = (str(df["trade_date"].iloc[0]) if not df.empty
                      else df.attrs["trade_date"])
        records = self._to_records(df, market) if not df.empty else []
        stored = await FactorScoresRepo().replace_complete_date(
            records, market=market, trade_date=trade_date)
        return {
            "status": "ok",
            "trade_date": trade_date,
            "symbols": int(len(records)),
            "written": int(stored["written"]),
            "removed": int(stored["removed"]),
        }

    # ── 读取 ────────────────────────────────────────────────

    async def _recent_trade_dates(self, market: str, coll_name: str,
                                  n: int, as_of: Optional[str] = None) -> List[str]:
        db = get_motor_db()
        query = {"trade_date": {"$lte": as_of or now_tz().date().isoformat()}}
        if coll_name == get_collection_name("daily_quotes", market):
            query["period"] = {"$in": [None, "daily"]}
        distinct = await db[coll_name].distinct("trade_date", query)
        return sorted([d for d in distinct if d], reverse=True)[:n]

    async def _stream_find(self, market: str, domain: str, query: Dict,
                           projection: Dict,
                           ensure_cols: Optional[List[str]] = None) -> pd.DataFrame:
        """流式拉取为 DataFrame；ensure_cols 中的列不存在时补 NaN。

        真实库可选域（daily_indicators/financial_data 等）文档字段不齐是
        常态——DataFrame 按出现过的键建列，全库缺失的键不会成列，下游
        取列会 KeyError（曾因 dividend_yield 整列缺失崩过批算）。
        """
        db = get_motor_db()
        coll = db[get_collection_name(domain, market)]
        rows: List[Dict] = []
        async for doc in coll.find(query, projection):
            doc.pop("_id", None)
            rows.append(doc)
        df = pd.DataFrame(rows)
        if ensure_cols and not df.empty:
            for c in ensure_cols:
                if c not in df.columns:
                    df[c] = np.nan
        return df

    async def compute_factors(self, market: str = "CN") -> pd.DataFrame:
        quote_dates = await self._recent_trade_dates(
            market, get_collection_name("daily_quotes", market),
            self.QUOTE_WINDOW_TRADE_DAYS)
        if not quote_dates:
            logger.warning("daily_quotes 无数据，因子计算跳过")
            return pd.DataFrame()
        trade_date = quote_dates[0]
        quote_min = quote_dates[-1]

        # 基础信息（行业/名称/ST 过滤）
        basic = await self._stream_find(market, "basic_info", {}, {
            "symbol": 1, "name": 1, "industry": 1},
            ensure_cols=["symbol", "name", "industry"])
        if basic.empty:
            return pd.DataFrame()
        basic = basic[~basic["name"].astype(str).str.contains("ST", na=False)]

        # 行情窗口（复权因子 join）
        quotes = await self._stream_find(market, "daily_quotes", {
            "trade_date": {"$gte": quote_min, "$lte": trade_date},
            "period": {"$in": [None, "daily"]},
        }, {"symbol": 1, "trade_date": 1, "close": 1, "volume": 1,
            "amount": 1},
            ensure_cols=["symbol", "trade_date", "close", "volume",
                         "amount"])
        if quotes.empty:
            return pd.DataFrame()
        adj = await self._stream_find(market, "adj_factors", {
            "trade_date": {"$gte": quote_min, "$lte": trade_date}},
            {"symbol": 1, "trade_date": 1, "adj_factor": 1},
            ensure_cols=["symbol", "trade_date", "adj_factor"])
        if not adj.empty:
            quotes = quotes.merge(adj, on=["symbol", "trade_date"], how="left")
            quotes["close_adj"] = quotes["close"] * quotes["adj_factor"].fillna(1.0)
        else:
            quotes["close_adj"] = quotes["close"]

        quotes = quotes[quotes["symbol"].isin(set(basic["symbol"]))]
        quotes = quotes.sort_values(["symbol", "trade_date"])
        counts = quotes.groupby("symbol")["trade_date"].transform("nunique")
        latest = quotes.groupby("symbol")["trade_date"].transform("max")
        quotes = quotes[(counts >= self.MIN_QUOTE_ROWS) & (latest == trade_date)]
        if quotes.empty:
            empty = pd.DataFrame()
            empty.attrs.update(complete_snapshot=True, trade_date=trade_date)
            return empty

        df = self._compute_momentum_trend_volume(quotes)
        df = df.merge(basic[["symbol", "name", "industry"]], on="symbol", how="left")
        df = df.set_index("symbol")

        # 估值分位 + 量比 + 股息（可选窗口数据不足时 NaN）
        df = df.join(await self._compute_valuation(market, trade_date))
        # 资金（可选域）
        df = df.join(await self._compute_flow(market, quote_dates))
        # 质量财务
        df = df.join(await self._compute_quality(market, trade_date))

        # 评分（rank 需 industry 列；join 后 symbol 回列供落库）
        df = rank_factors_by_industry(df, FACTOR_FIELDS)
        df = compute_style_scores(df, get_factor_groups(), get_style_weights())
        df = df.reset_index()
        df["trade_date"] = trade_date
        return df

    # ── 因子计算（向量化） ─────────────────────────────────

    def _compute_momentum_trend_volume(self, q: pd.DataFrame) -> pd.DataFrame:
        g = q.sort_values(["symbol", "trade_date"]).groupby("symbol", sort=False)
        last = g.tail(1).set_index("symbol")

        def _ret(col: str, k: int) -> pd.Series:
            # k 日收益 = 末值 / k 个交易日前值 - 1（iloc[-(k+1)] 即 T-k 日）
            return (g[col].last() / g[col].apply(
                lambda s, _k=k: s.iloc[-(_k + 1)] if len(s) >= _k + 1 else np.nan)
                - 1.0) * 100.0

        out = pd.DataFrame(index=last.index)
        out["ret_5d"] = _ret("close_adj", 5)
        out["ret_20d"] = _ret("close_adj", 20)
        out["ret_60d"] = _ret("close_adj", 60)
        # 60 日新高距离（正=低于高点）
        high60 = g["close_adj"].apply(lambda s: s.tail(60).max())
        out["dist_to_60d_high"] = (high60 / last["close_adj"] - 1.0) * 100.0
        # 趋势
        ma20 = g["close_adj"].apply(lambda s: s.tail(20).mean())
        ma20_prev5 = g["close_adj"].apply(lambda s: s.tail(25).head(20).mean())
        out["bias_ma20"] = (last["close_adj"] / ma20 - 1.0) * 100.0
        out["ma20_slope"] = (ma20 / ma20_prev5 - 1.0) * 100.0
        out["macd_golden_days"] = pd.Series({
            sym: _macd_golden_days(grp["close_adj"].to_numpy(dtype=float))
            for sym, grp in g
        })
        # 量能：放大倍数用成交量口径——单股内换手率=成交量/流通股本，
        # 股本为常数，二者放大倍数数学等价；turnover_rate 在当前同步
        # 链路缺失（daily_quotes 不落该字段），volume 口径不依赖它
        vol = g["volume"]
        out["turnover_amp"] = vol.last() / vol.apply(
            lambda s: s.tail(21).head(20).mean())
        out["consecutive_vol_up_days"] = g["volume"].apply(
            lambda s: _consecutive_up_days(s.to_numpy(dtype=float)))
        return out

    async def _compute_valuation(self, market: str, trade_date: str) -> pd.DataFrame:
        dates = await self._recent_trade_dates(
            market, get_collection_name("daily_indicators", market),
            self.PERCENTILE_WINDOW_TRADE_DAYS, as_of=trade_date)
        cols = ["pe_ttm_percentile", "pb_percentile", "dividend_yield", "volume_ratio"]
        if not dates:
            return pd.DataFrame(columns=cols)
        ind = await self._stream_find(market, "daily_indicators", {
            "trade_date": {"$gte": dates[-1], "$lte": trade_date}},
            {"symbol": 1, "trade_date": 1, "pe_ttm": 1, "pb": 1,
             "dividend_yield": 1, "volume_ratio": 1},
            ensure_cols=["symbol", "trade_date", "pe_ttm", "pb",
                         "dividend_yield", "volume_ratio"])
        if ind.empty:
            return pd.DataFrame(columns=cols)
        return self._valuation_from_frame(ind, trade_date)

    def _valuation_from_frame(self, ind: pd.DataFrame, trade_date: str) -> pd.DataFrame:
        """只发布行情当日指标；缺少历史样本不能用单点的 100 分位替代。"""
        ind = ind[ind["trade_date"] <= trade_date].copy()
        for col in ("pe_ttm", "pb", "dividend_yield", "volume_ratio"):
            ind[col] = pd.to_numeric(ind[col], errors="coerce").replace(
                [np.inf, -np.inf], np.nan)
        ind = ind.drop_duplicates(["symbol", "trade_date"], keep="last")
        g = ind.sort_values(["symbol", "trade_date"]).groupby("symbol", sort=False)

        def _pct_rank(series: pd.Series) -> float:
            """当前值在窗口内的分位（0-100，值越小分位越低）。"""
            cur = series.iloc[-1]
            valid = series.dropna()
            if pd.isna(cur) or len(valid) < self.MIN_PERCENTILE_ROWS:
                return np.nan
            return float((valid <= cur).sum() / len(valid) * 100.0)

        out = pd.DataFrame(index=g.size().index)
        out["pe_ttm_percentile"] = g["pe_ttm"].apply(_pct_rank)
        out["pb_percentile"] = g["pb"].apply(_pct_rank)
        last = g.tail(1).set_index("symbol")
        out["dividend_yield"] = last["dividend_yield"]
        out["volume_ratio"] = last["volume_ratio"]
        out["_pe_history_days"] = g["pe_ttm"].count()
        out["_pb_history_days"] = g["pb"].count()
        out["_indicators_trade_date"] = last["trade_date"]
        stale = last["trade_date"] != trade_date
        out.loc[stale, ["pe_ttm_percentile", "pb_percentile",
                        "dividend_yield", "volume_ratio"]] = np.nan
        return out

    async def _compute_flow(self, market: str, quote_dates: List[str]) -> pd.DataFrame:
        recent = quote_dates[: self.FLOW_WINDOW_TRADE_DAYS]
        mf = await self._stream_find(market, "money_flow", {
            "trade_date": {"$in": recent}},
            {"symbol": 1, "trade_date": 1, "main_net_inflow": 1},
            ensure_cols=["symbol", "trade_date", "main_net_inflow"])
        if mf.empty:
            return pd.DataFrame(columns=["main_inflow_5d", "main_inflow_5d_pct"])
        amt = await self._stream_find(market, "daily_quotes", {
            "trade_date": {"$in": recent},
            "period": {"$in": [None, "daily"]}},
            {"symbol": 1, "trade_date": 1, "amount": 1},
            ensure_cols=["symbol", "trade_date", "amount"])
        return self._flow_from_frames(mf, amt, recent)

    def _flow_from_frames(self, mf: pd.DataFrame, amt: pd.DataFrame,
                          recent: List[str]) -> pd.DataFrame:
        """五日必须逐日齐全；重复记录不补天数，缺值不能被 sum 变成零。"""
        def daily_values(frame, field):
            if frame.empty:
                return pd.Series(dtype=float)
            frame = frame[frame["trade_date"].isin(recent)].copy()
            frame[field] = pd.to_numeric(frame[field], errors="coerce").replace(
                [np.inf, -np.inf], np.nan)
            # 同一日重复且冲突的数据也不可拼成可靠的累计值。
            return frame.groupby(["symbol", "trade_date"])[field].agg(
                lambda s: s.dropna().iloc[0] if s.nunique() == 1 else np.nan)

        flows = daily_values(mf, "main_net_inflow")
        amounts = daily_values(amt, "amount")
        if flows.empty:
            return pd.DataFrame(columns=["main_inflow_5d", "main_inflow_5d_pct"])
        grouped = flows.groupby(level="symbol")
        counts = grouped.count()
        complete = counts.eq(self.FLOW_WINDOW_TRADE_DAYS) & (
            len(set(recent)) == self.FLOW_WINDOW_TRADE_DAYS)
        inflow = grouped.sum(min_count=self.FLOW_WINDOW_TRADE_DAYS).where(complete)
        out = pd.DataFrame({"main_inflow_5d": inflow, "_money_flow_days": counts})
        if amounts.empty:
            out["main_inflow_5d_pct"] = np.nan
        else:
            amount_group = amounts.groupby(level="symbol")
            total = amount_group.sum(min_count=self.FLOW_WINDOW_TRADE_DAYS)
            total = total.where(amount_group.count().eq(self.FLOW_WINDOW_TRADE_DAYS)
                                & total.gt(0))
            out["main_inflow_5d_pct"] = inflow / total * 100.0
        return out

    async def _compute_quality(self, market: str, trade_date: str) -> pd.DataFrame:
        cols = ["symbol", "report_period", "statement_type", "report_type",
                "announce_date", "data_source", "net_profit", "roe",
                "gross_margin", "debt_ratio"]
        fin = await self._stream_find(market, "financial_data", {
            "report_period": {"$lte": trade_date},
            "announce_date": {"$lte": trade_date}},
            {col: 1 for col in cols}, ensure_cols=cols)
        if fin.empty:
            return pd.DataFrame(columns=["roe", "gross_margin", "net_profit_yoy",
                                         "debt_ratio"])
        return self._quality_from_frame(fin, trade_date)

    def _quality_from_frame(self, fin: pd.DataFrame, trade_date: str) -> pd.DataFrame:
        """同股、同报告期/类型非空合并；公告日期未知不能证明当时已披露。"""
        fin = fin.copy()
        for col in ("report_period", "announce_date"):
            fin[col] = pd.to_datetime(fin[col], errors="coerce").dt.normalize()
        for col in ("net_profit", "roe", "gross_margin", "debt_ratio"):
            fin[col] = pd.to_numeric(fin[col], errors="coerce").replace(
                [np.inf, -np.inf], np.nan)
        for col in ("statement_type", "data_source", "report_type"):
            fin[col] = fin[col].fillna("")
        cutoff = pd.Timestamp(trade_date)
        eligible = (fin["report_period"].notna() & fin["announce_date"].notna()
                    & fin["report_period"].le(cutoff)
                    & fin["announce_date"].le(cutoff)
                    & fin["announce_date"].ge(fin["report_period"])
                    & fin["statement_type"].isin(
                        ["income", "balance", "cashflow", "indicator"]))
        rows = []
        for sym, raw_group in fin.groupby("symbol", sort=False):
            row = {"symbol": sym, "roe": np.nan, "gross_margin": np.nan,
                   "debt_ratio": np.nan, "net_profit_yoy": np.nan,
                   "_financial_status": "no_disclosed_data",
                   "_net_profit_yoy_method": "unavailable"}
            g = raw_group[eligible.loc[raw_group.index]].sort_values(
                ["report_period", "announce_date", "statement_type"], kind="stable")
            if g.empty:
                rows.append(row)
                continue
            latest = g.iloc[-1]
            period = latest["report_period"]
            current = g[g["report_period"].eq(period)
                        & g["report_type"].eq(latest["report_type"])]
            for field in ("roe", "gross_margin", "debt_ratio"):
                available = current[field].dropna()
                if not available.empty:
                    row[field] = available.iloc[-1]
            row.update({"_financial_status": "disclosed",
                        "_financial_report_period": period.date().isoformat(),
                        "_financial_announce_date": current["announce_date"].max().date().isoformat()})
            profits = current[current["net_profit"].notna()]
            if not profits.empty:
                profit = profits.iloc[-1]
                # 标准 net_profit 的来源口径尚未细分；不跨数据源/报表类型拼同比。
                previous = g[g["report_period"].eq(period - pd.DateOffset(years=1))
                             & g["data_source"].eq(profit["data_source"])
                             & g["statement_type"].eq(profit["statement_type"])
                             & g["report_type"].eq(profit["report_type"])
                             & g["net_profit"].notna()]
                if profit["data_source"] and not previous.empty:
                    prior = previous.iloc[-1]["net_profit"]
                    if prior > 0:
                        row["net_profit_yoy"] = (profit["net_profit"] / prior - 1.0) * 100.0
                        row["_net_profit_yoy_method"] = "derived_same_source_statement_period"
            rows.append(row)
        return pd.DataFrame(rows).set_index("symbol")

    # ── 落库记录 ────────────────────────────────────────────

    def _to_records(self, df: pd.DataFrame, market: str) -> List[Dict]:
        now = now_tz().isoformat()
        keep = (["symbol", "trade_date", "name", "industry"]
                + FACTOR_FIELDS
                + [f"score_{s}" for s in ("short_term", "balanced", "value")])
        recs = []
        quality_cols = [col for col in df.columns if col.startswith("_")]
        for row in df[keep + quality_cols].to_dict("records"):
            quality = {key[1:]: (value.item() if isinstance(value, np.generic) else value)
                       for key, value in row.items()
                       if key in quality_cols and pd.notna(value)}
            quality.update({"as_of": row["trade_date"],
                            "money_flow_required_days": self.FLOW_WINDOW_TRADE_DAYS,
                            "valuation_minimum_history_days": self.MIN_PERCENTILE_ROWS,
                            "valuation_window_trade_days": self.PERCENTILE_WINDOW_TRADE_DAYS})
            quality.setdefault("financial_status", "no_disclosed_data")
            quality.setdefault("net_profit_yoy_method", "unavailable")
            quality.setdefault("money_flow_days", 0)
            rec = {k: (None if pd.isna(v) else
                       (v.item() if isinstance(v, np.generic) else v))
                   for k, v in row.items()
                   if k not in quality_cols and (
                       pd.notna(v) or k in FACTOR_FIELDS or k.startswith("score_"))}
            rec["data_quality"] = quality
            rec["market"] = market
            rec["data_source"] = "computed"
            rec["updated_at"] = now
            recs.append(rec)
        return recs
