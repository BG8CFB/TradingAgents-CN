"""QMT Provider — datadir 本地直读（PRD D-7：纯文件 IO，零 xtquant 依赖）。

平台契约对齐：
- BaseProvider 业务方法均为 async → 阻塞文件 IO 经 ``asyncio.to_thread``
  卸载到线程池，``asyncio.Semaphore(QMT_READ_WORKERS)`` 限并发（DD-01）；
- ``FallbackRouter`` 不调用 ``connect()``，直接 raw_fetch → 原始方法必须
  惰性自持：datadir 未配置/路径不存在抛 ``DataSourceUnavailableError``
  （计入熔断快速降级到既有源）；单文件缺失/拒读返回空 DataFrame。
- reader 返回 None（拒读/缺文件）→ 空帧：router 记「failed」转下一源，
  worker 侧由 sync_events/checkpoints 记缺口（DD-02 语义翻译点）。

M1 覆盖域：basic_info（stock_list）/ trade_calendar / daily_quotes（含
按交易日批量）/ adj_factors。
M2 新增域：intraday_quotes（1m/5m，FR-04）/ tick_quotes（144B 逐笔，FR-06）。
"""

import asyncio
import logging
from typing import List, Optional

import pandas as pd

from app.core.config import settings
from app.data.sources.base.exceptions import DataSourceUnavailableError
from app.data.sources.base.provider import BaseProvider

from .config import get_qmt_datadir
from .datadir_reader import QmtDatadirReader
from .field_maps import (
    bare_to_ts_code,
    freq_to_reader_period,
    iso_to_yyyymmdd,
)

logger = logging.getLogger("sources.CN.qmt.provider")


class QmtProvider(BaseProvider):
    """QMT（datadir 本地直读）A 股数据源。"""

    def __init__(self):
        super().__init__(name="qmt", market="CN")
        self._datadir = get_qmt_datadir()
        self._reader: Optional[QmtDatadirReader] = (
            QmtDatadirReader(self._datadir) if self._datadir else None
        )
        self._sem = asyncio.Semaphore(max(1, int(settings.QMT_READ_WORKERS)))

    # ── 平台契约方法 ──

    async def connect(self) -> bool:
        """datadir 模式的「连接」= 开关 + 路径探测 + 抽样四级自检（FR-01）。"""
        if not settings.QMT_ENABLED:
            self.connected = False
            return False
        if self._reader is None or not self._reader.available:
            self.connected = False
            return False
        report = await asyncio.to_thread(self._reader.self_check)
        self.connected = bool(report.ok)
        if not self.connected:
            self.logger.warning(
                "QMT datadir 自检未通过: universe=%d rejected=%s latest=%s",
                report.universe_size,
                report.rejected_samples,
                report.latest_trade_date,
            )
        return self.connected

    def is_available(self) -> bool:
        """开关打开且 datadir 路径存在（连接态由 connect/探针细化）。"""
        return bool(
            settings.QMT_ENABLED
            and self._reader is not None
            and self._reader.available
        )

    # ── basic_info ──

    async def get_stock_list(self, **kwargs) -> pd.DataFrame:
        """本机有日线文件的沪深 A 股合约列表（宇宙下界，见 reader.stock_codes）。"""
        codes = await self._run_reader("basic_info", self._reader.stock_codes)
        if not codes:
            return pd.DataFrame(columns=["ts_code"])
        return pd.DataFrame({"ts_code": codes})

    # ── trade_calendar ──

    async def get_trade_calendar(
        self, exchange: str = "SSE", start_date: str = "", end_date: str = "",
        **kwargs,
    ) -> pd.DataFrame:
        """datadir 上证指数日线派生交易日历。

        日历源为上证指数（SH/86400/000001.DAT），故无论入参 exchange 为何
        均输出 SSE 口径（与派生源一致）；start/end 为 'YYYY-MM-DD' 闭区间。
        """
        dates = await self._run_reader("trade_calendar", self._reader.trading_dates)
        dates = dates or []
        lo, hi = iso_to_yyyymmdd(start_date), iso_to_yyyymmdd(end_date)
        if lo:
            dates = [d for d in dates if d >= lo]
        if hi:
            dates = [d for d in dates if d <= hi]

        rows = {"exchange": [], "cal_date": [], "is_open": [], "pretrade_date": []}
        prev: Optional[str] = None
        for d in dates:
            cal_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            rows["exchange"].append("SSE")
            rows["cal_date"].append(cal_date)
            rows["is_open"].append(1)
            rows["pretrade_date"].append(prev)
            prev = cal_date
        return pd.DataFrame(rows)

    # ── daily_quotes ──

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs,
    ) -> pd.DataFrame:
        """单只日线（原始帧 + ts_code 列；拒读/缺文件返回空帧）。"""
        ts_code = bare_to_ts_code(symbol)
        s, e = iso_to_yyyymmdd(start_date), iso_to_yyyymmdd(end_date)
        df = await self._run_reader(
            "daily_quotes",
            lambda: self._reader.daily(ts_code, start=s, end=e),
        )
        return self._with_ts_code(df, ts_code)

    async def get_daily_quotes_batch(self, trade_date: str, **kwargs) -> pd.DataFrame:
        """全市场按交易日批量（单日窗口；router 兜底链契约）。"""
        d = iso_to_yyyymmdd(trade_date)
        return await self.get_daily_quotes_batch_range(d, d)

    async def get_daily_quotes_batch_range(
        self, start_date: str, end_date: str, **kwargs,
    ) -> pd.DataFrame:
        """全市场按日期区间批量（worker 采集主路径）。

        每只股票文件只解析一次覆盖整个窗口，避免「按日循环 × 全宇宙」把
        同一份文件重复读 N 次（6 日窗口即 6× 磁盘放大，直接影响 M1 时效）。
        逐票失败（拒读/缺文件）跳过不中断整批 —— 缺口由补采承接（FR-12）。
        """
        self._ensure_reader("daily_quotes")
        s, e = iso_to_yyyymmdd(start_date), iso_to_yyyymmdd(end_date)
        codes = await asyncio.to_thread(self._reader.stock_codes)
        if not codes:
            return pd.DataFrame()

        async def _one(code: str):
            async with self._sem:
                return code, await asyncio.to_thread(
                    self._reader.daily, code, s, e
                )

        results = await asyncio.gather(
            *[_one(c) for c in codes], return_exceptions=True
        )
        frames: List[pd.DataFrame] = []
        rejected = 0
        for r in results:
            if isinstance(r, BaseException):
                rejected += 1
                continue
            code, df = r
            if df is None or df.empty:
                continue
            frames.append(self._with_ts_code(df, code))
        if rejected:
            self.logger.warning(
                "QMT daily_quotes_range %s~%s 有 %d 只读取异常（已跳过）",
                s, e, rejected,
            )
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    # ── intraday_quotes（M2 / FR-04） ──

    async def get_intraday_quotes(
        self, symbol: str, start_date: str, end_date: str,
        freq: str = "5min", **kwargs,
    ) -> pd.DataFrame:
        """单只分时（1m/5m K 线，与日线同为 64B 记录结构）。

        index 为平台 freq 词表（'1min'/'5min'），与 tushare/akshare 一致；
        datadir 只有 1m/5m 两个周期目录，其余频率明确报错而非静默降级
        （见 ``field_maps.freq_to_reader_period``）。
        """
        ts_code = bare_to_ts_code(symbol)
        period = freq_to_reader_period(freq)
        s, e = iso_to_yyyymmdd(start_date), iso_to_yyyymmdd(end_date)
        df = await self._run_reader(
            "intraday_quotes",
            lambda: self._reader.minute(ts_code, period, start=s, end=e),
        )
        return self._annotate_intraday(df, ts_code, freq)

    async def get_intraday_quotes_batch_range(
        self, start_date: str, end_date: str,
        freq: str = "5min", **kwargs,
    ) -> pd.DataFrame:
        """全市场分时区间批量（worker 采集主路径，按**单日**窗口调用）。

        与日线批量同构：每只股票文件只解析一次覆盖整个窗口。全市场单日
        5m ≈ 26 万条 / 1m ≈ 130 万条，故 worker 按交易日逐日分块调用，
        避免把整个窗口一次性堆进内存（PRD FR-04 规则 2「增量按日分块」）。
        逐票失败（拒读/缺文件）跳过不中断整批 —— 缺口由补采承接。
        """
        self._ensure_reader("intraday_quotes")
        period = freq_to_reader_period(freq)
        s, e = iso_to_yyyymmdd(start_date), iso_to_yyyymmdd(end_date)
        codes = await asyncio.to_thread(self._reader.stock_codes)
        if not codes:
            return pd.DataFrame()

        async def _one(code: str):
            async with self._sem:
                return code, await asyncio.to_thread(
                    self._reader.minute, code, period, s, e
                )

        results = await asyncio.gather(
            *[_one(c) for c in codes], return_exceptions=True
        )
        frames: List[pd.DataFrame] = []
        rejected = 0
        for r in results:
            if isinstance(r, BaseException):
                rejected += 1
                continue
            code, df = r
            if df is None or df.empty:
                continue
            frames.append(self._annotate_intraday(df, code, freq))
        if rejected:
            self.logger.warning(
                "QMT intraday(%s) %s~%s 有 %d 只读取异常（已跳过）",
                freq, s, e, rejected,
            )
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    # ── tick_quotes（M2 / FR-06） ──

    async def get_tick_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs,
    ) -> pd.DataFrame:
        """单只逐笔（144B tick，按日循环；无竞价行/缺文件当日跳过）。

        只读**交易日**文件：datadir 日历派生自上证指数日线（单文件毫秒级），
        比逐日试读全部自然日省掉周末/节假日的无效 IO。

        注意：单日 tick 可达数万条，全市场单日可达千万级 —— 批量入库走
        ``app/worker/qmt/tick_collect.py`` 的**逐票流式**路径，不要在此
        拼全市场帧（会打满内存）。
        """
        ts_code = bare_to_ts_code(symbol)
        s, e = iso_to_yyyymmdd(start_date), iso_to_yyyymmdd(end_date)
        self._ensure_reader("tick_quotes")
        dates = await self._tick_dates(s, e)
        if not dates:
            return pd.DataFrame()

        frames: List[pd.DataFrame] = []
        for d in dates:
            async with self._sem:
                df = await asyncio.to_thread(self._reader.tick, ts_code, d)
            if df is None or df.empty:
                continue
            frames.append(self._annotate_tick(df, ts_code, d))
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    async def read_tick_one(self, ts_code: str, trade_date: str) -> pd.DataFrame:
        """单只单日 tick（**流式采集路径专用**；trade_date 为 'YYYYMMDD'）。

        与 ``get_tick_quotes`` 的区别：不做交易日历解析、不循环日期 —— worker
        已经按日分块并持有宇宙列表，逐票调用本方法只产生一次文件读取。
        """
        self._ensure_reader("tick_quotes")
        async with self._sem:
            df = await asyncio.to_thread(self._reader.tick, ts_code, trade_date)
        return self._annotate_tick(df, ts_code, trade_date)

    async def _tick_dates(self, s: Optional[str], e: Optional[str]) -> List[str]:
        """窗口内的交易日（YYYYMMDD 升序）。

        日历不可用时退化为「窗口内全部自然日」：多试读几个不存在的文件，
        代价远小于漏采（``reader.tick`` 缺文件返回 None，不告警）。
        """
        all_dates = await asyncio.to_thread(self._reader.trading_dates)
        if all_dates:
            return [d for d in all_dates if (not s or d >= s) and (not e or d <= e)]
        if not s or not e:
            return []
        from datetime import datetime, timedelta

        lo = datetime.strptime(s, "%Y%m%d")
        hi = datetime.strptime(e, "%Y%m%d")
        return [
            (lo + timedelta(days=i)).strftime("%Y%m%d")
            for i in range((hi - lo).days + 1)
        ]

    # ── corporate_actions（M2 / FR-07） ──

    async def get_corporate_actions(
        self, symbol: str, start_date: str, end_date: str, **kwargs,
    ) -> pd.DataFrame:
        """单只分红送配历史（DividData LevelDB 直读，按除权日窗口过滤）。

        附带 ``record_date`` / ``date_src`` 两个诊断列 —— Adapter 需要
        ``date_src`` 判定除权日是否可信（``ts_key`` 派生者默认拒用）。
        """
        ts_code = bare_to_ts_code(symbol)
        df = await self._run_reader(
            "corporate_actions",
            lambda: self._reader.dividends(ts_code, with_record_date=True),
        )
        return self._filter_dividends(df, ts_code, start_date, end_date)

    async def get_corporate_actions_batch_range(
        self, start_date: str, end_date: str, **kwargs,
    ) -> pd.DataFrame:
        """全市场分红送配（worker 采集主路径）。

        DividData 是**全表一次性加载**（~88 万 entry）后按 ts_code 查字典，
        故先在线程池里预热一次缓存，再并发遍历宇宙 —— 否则并发首调会各自
        全扫 .ldb，把一次性成本放大 N 倍。
        """
        self._ensure_reader("corporate_actions")
        await asyncio.to_thread(self._reader._load_dividends)
        codes = await asyncio.to_thread(self._reader.stock_codes)
        if not codes:
            return pd.DataFrame()

        async def _one(code: str):
            async with self._sem:
                return code, await asyncio.to_thread(
                    self._reader.dividends, code, True
                )

        results = await asyncio.gather(
            *[_one(c) for c in codes], return_exceptions=True
        )
        frames: List[pd.DataFrame] = []
        for r in results:
            if isinstance(r, BaseException):
                continue
            code, df = r
            out = self._filter_dividends(df, code, start_date, end_date)
            if not out.empty:
                frames.append(out)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    @staticmethod
    def _filter_dividends(
        df: Optional[pd.DataFrame], ts_code: str, start_date: str, end_date: str,
    ) -> pd.DataFrame:
        """注入 ts_code 并按除权日（trade_date, 'YYYYMMDD'）闭区间过滤。"""
        if df is None or df.empty:
            return pd.DataFrame()
        out = df.copy()
        out.insert(0, "ts_code", ts_code)
        s, e = iso_to_yyyymmdd(start_date), iso_to_yyyymmdd(end_date)
        # 事件域允许「无窗口」= 全量历史（回补场景）
        if s:
            out = out[out["trade_date"] >= s]
        if e:
            out = out[out["trade_date"] <= e]
        return out.reset_index(drop=True)

    # ── adj_factors（M2 / FR-07 批量补齐） ──

    async def get_adj_factors_batch_range(
        self, start_date: str, end_date: str, **kwargs,
    ) -> pd.DataFrame:
        """全市场复权因子区间批量（每日线文件只解析一次，投影因子列）。

        与 ``get_daily_quotes_batch_range`` 是同一次文件解析的另一种投影；
        两者在同一次采集里各跑一遍意味着**双倍磁盘 IO** —— 已知的优化点是
        合并为单趟双写，但会破坏「一域一 sync」的域隔离语义，暂不做
        （见交接文档 M2 进展的「已知成本」）。
        """
        self._ensure_reader("adj_factors")
        s, e = iso_to_yyyymmdd(start_date), iso_to_yyyymmdd(end_date)
        codes = await asyncio.to_thread(self._reader.stock_codes)
        if not codes:
            return pd.DataFrame()

        async def _one(code: str):
            async with self._sem:
                return code, await asyncio.to_thread(
                    self._reader.daily, code, s, e
                )

        results = await asyncio.gather(
            *[_one(c) for c in codes], return_exceptions=True
        )
        frames: List[pd.DataFrame] = []
        for r in results:
            if isinstance(r, BaseException):
                continue
            code, df = r
            if df is None or df.empty:
                continue
            df = self._with_ts_code(df, code)
            keep = ["ts_code", "time", "adj_f_evt", "adj_f_cum"]
            frames.append(df[[c for c in keep if c in df.columns]])
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    # ── adj_factors ──

    async def get_adj_factors(
        self, symbol: str, start_date: str, end_date: str, **kwargs,
    ) -> pd.DataFrame:
        """单只复权因子（daily 帧投影：ts_code/time/adj_f_evt/adj_f_cum）。"""
        ts_code = bare_to_ts_code(symbol)
        s, e = iso_to_yyyymmdd(start_date), iso_to_yyyymmdd(end_date)
        df = await self._run_reader(
            "adj_factors",
            lambda: self._reader.daily(ts_code, start=s, end=e),
        )
        if df is None or df.empty:
            return pd.DataFrame()
        df = self._with_ts_code(df, ts_code)
        keep = ["ts_code", "time", "adj_f_evt", "adj_f_cum"]
        return df[[c for c in keep if c in df.columns]]

    # ── 内部 ──

    def _ensure_reader(self, domain: str) -> None:
        """开关关闭 / datadir 未配置 / 路径不存在 → 抛不可用（熔断降级）。"""
        if not settings.QMT_ENABLED:
            raise DataSourceUnavailableError(
                "qmt", domain, "QMT 数据源未启用（QMT_ENABLED=false）"
            )
        if self._reader is None or not self._reader.available:
            raise DataSourceUnavailableError(
                "qmt", domain, "QMT datadir 未配置或路径不存在"
            )

    async def _run_reader(self, domain: str, fn):
        """单次阻塞读取的统一包装：可用性检查 + 信号量 + 线程池。"""
        self._ensure_reader(domain)
        async with self._sem:
            return await asyncio.to_thread(fn)

    @staticmethod
    def _with_ts_code(df: Optional[pd.DataFrame], ts_code: str) -> pd.DataFrame:
        """reader 原始帧注入 ts_code 列（adapter 的 symbol 来源）。"""
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.copy()
        df.insert(0, "ts_code", ts_code)
        return df

    @classmethod
    def _annotate_intraday(
        cls, df: Optional[pd.DataFrame], ts_code: str, freq: str,
    ) -> pd.DataFrame:
        """分时帧注入 ts_code + freq 常量列。

        频率由调用方（入参）而非数据本身决定，注入成列后 Adapter 无需感知
        调用上下文即可产出 ``IntradayQuotesSchema.freq``（保持 Adapter 纯函数）。
        """
        out = cls._with_ts_code(df, ts_code)
        if out.empty:
            return out
        out["freq"] = freq
        return out

    @classmethod
    def _annotate_tick(
        cls, df: Optional[pd.DataFrame], ts_code: str, trade_date: str,
    ) -> pd.DataFrame:
        """tick 帧注入 ts_code + trade_date（'YYYY-MM-DD'）常量列。

        trade_date 由调用方按文件路径口径（YYYYMMDD）确定，比从 time 列反推
        更可靠：跨零点的极端记录不会把记录分到错误的日分区。
        """
        out = cls._with_ts_code(df, ts_code)
        if out.empty:
            return out
        out["trade_date"] = (
            f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
        )
        return out
