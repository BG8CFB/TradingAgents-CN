"""QmtProvider 单测 — 合成 datadir 目录树，不依赖真实 QMT 客户端。

覆盖：契约方法（connect/is_available）、基础域（stock_list/calendar/
daily/batch/adj_factors）、datadir 缺失时的 DataSourceUnavailableError
（FallbackRouter 熔断降级语义，DD-02）。
"""

from datetime import date, timedelta
from pathlib import Path

import pytest

from app.data.sources.cn.qmt.provider import QmtProvider
from tests.data.test_qmt_datadir_reader import (
    _recent_records,
    _write_kline_file,
)

# 与 _recent_records 同锚（今天）：文件日期与查询日期必须一致
_D2 = (date.today() - timedelta(days=2)).isoformat()
_D1 = (date.today() - timedelta(days=1)).isoformat()
_D0 = date.today().isoformat()


def _mk_tree(tmp_path: Path) -> Path:
    """合成含指数（日历）+ 两只股票的就绪 datadir。"""
    recs = _recent_records([2, 1, 0])
    _write_kline_file(tmp_path / 'SH' / '86400' / '000001.DAT', recs)   # 上证指数
    _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', recs)
    _write_kline_file(tmp_path / 'SH' / '86400' / '600000.DAT', recs)
    return tmp_path


@pytest.fixture
def provider(tmp_path, monkeypatch) -> QmtProvider:
    _mk_tree(tmp_path)
    monkeypatch.setattr(
        "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: str(tmp_path)
    )
    from app.core.config import settings

    monkeypatch.setattr(settings, "QMT_ENABLED", True)
    return QmtProvider()


class TestContract:
    async def test_connect_ok(self, provider: QmtProvider):
        assert await provider.connect() is True
        assert provider.connected is True
        assert provider.is_available() is True

    async def test_connect_not_configured(self, monkeypatch):
        monkeypatch.setattr(
            "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: ""
        )
        from app.core.config import settings

        monkeypatch.setattr(settings, "QMT_ENABLED", True)
        p = QmtProvider()
        assert await p.connect() is False
        assert p.is_available() is False

    async def test_disabled_short_circuit(self, tmp_path, monkeypatch):
        """QMT_ENABLED=false：即便 datadir 存在也不可用、调用抛不可用（PRD FR-09）。"""
        _mk_tree(tmp_path)
        monkeypatch.setattr(
            "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: str(tmp_path)
        )
        from app.core.config import settings

        monkeypatch.setattr(settings, "QMT_ENABLED", False)
        p = QmtProvider()
        assert p.is_available() is False
        assert await p.connect() is False
        from app.data.sources.base.exceptions import DataSourceUnavailableError

        with pytest.raises(DataSourceUnavailableError, match="未启用"):
            await p.get_daily_quotes("000001", _D1, _D1)

    async def test_missing_datadir_raises_unavailable(self, monkeypatch):
        """datadir 路径不存在 → DataSourceUnavailableError（router 计熔断）。"""
        monkeypatch.setattr(
            "app.data.sources.cn.qmt.provider.get_qmt_datadir",
            lambda: str(Path("Z:/definitely/not/exist")),
        )
        from app.core.config import settings

        monkeypatch.setattr(settings, "QMT_ENABLED", True)
        p = QmtProvider()
        from app.data.sources.base.exceptions import DataSourceUnavailableError

        with pytest.raises(DataSourceUnavailableError):
            await p.get_daily_quotes("000001", "2026-09-08", "2026-09-09")


class TestStockList:
    async def test_universe(self, provider: QmtProvider):
        df = await provider.get_stock_list()
        assert sorted(df["ts_code"].tolist()) == ["000001.SZ", "600000.SH"]


class TestDailyQuotes:
    async def test_per_symbol_bare_code(self, provider: QmtProvider):
        """裸 6 位代码自动补市场后缀：000001→SZ、600000→SH。"""
        df = await provider.get_daily_quotes("000001", _D1, _D1)
        assert len(df) == 1
        assert df.iloc[0]["ts_code"] == "000001.SZ"

        df = await provider.get_daily_quotes("600000", _D1, _D1)
        assert len(df) == 1
        assert df.iloc[0]["ts_code"] == "600000.SH"

    async def test_missing_symbol_empty(self, provider: QmtProvider):
        """未下载的代码 → 空帧（router 记 failed 降级，不抛异常）。"""
        df = await provider.get_daily_quotes("300750", _D1, _D1)
        assert df.empty

    async def test_batch_by_trade_date(self, provider: QmtProvider):
        df = await provider.get_daily_quotes_batch(_D1)
        assert len(df) == 2  # 宇宙两只各 1 行
        assert set(df["ts_code"]) == {"000001.SZ", "600000.SH"}

    async def test_batch_empty_day(self, provider: QmtProvider):
        df = await provider.get_daily_quotes_batch("1990-01-01")
        assert df.empty

    async def test_range_batch_single_pass(self, provider: QmtProvider):
        """区间批量：一次调用覆盖 3 日 × 2 只 = 6 行（每只文件只解析一次）。"""
        df = await provider.get_daily_quotes_batch_range(_D2, _D0)
        assert len(df) == 6
        assert set(df["ts_code"]) == {"000001.SZ", "600000.SH"}
        # 日期递增且含窗口首尾
        dates = sorted(df["time"].tolist())
        assert len(dates) == 6


class TestTradeCalendar:
    async def test_calendar_chain(self, provider: QmtProvider):
        df = await provider.get_trade_calendar("SSE", _D2, _D0)
        assert len(df) == 3
        assert df.iloc[0]["cal_date"] == _D2
        assert df.iloc[1]["pretrade_date"] == _D2
        assert list(df["is_open"]) == [1, 1, 1]

    async def test_calendar_range_filter(self, provider: QmtProvider):
        df = await provider.get_trade_calendar("SSE", _D1, _D1)
        assert len(df) == 1
        assert df.iloc[0]["cal_date"] == _D1


class TestAdjFactors:
    async def test_projection(self, provider: QmtProvider):
        df = await provider.get_adj_factors("000001", _D2, _D0)
        assert list(df.columns) == ["ts_code", "time", "adj_f_evt", "adj_f_cum"]
        assert len(df) == 3
        assert df.iloc[-1]["adj_f_cum"] == pytest.approx(107.62)  # fixture 因子槽


class TestWorkerPinning:
    async def test_pinned_source(self):
        """域同步钉死 qmt 单源（本地直读优先采，不走全量优先级链）。"""
        from app.worker.qmt.jobs import (
            QmtBasicInfoSync,
            QmtDailyQuotesSync,
            QmtTradeCalendarSync,
        )

        for cls in (QmtBasicInfoSync, QmtTradeCalendarSync, QmtDailyQuotesSync):
            sync = cls()
            assert sync.market == "CN"
            assert await sync.get_sources() == ["qmt"]

    async def test_sync_kwargs_fn_contract(self):
        """回归：BaseMarketDomainSync.sync 的第二参数必须是 callable（曾传 dict）。"""
        from app.worker.qmt.jobs import QmtTradeCalendarSync

        class _Stub(QmtTradeCalendarSync):
            async def get_sources(self):
                return []

            async def _write_sync_event(self, **kwargs):
                return None

            async def _write_checkpoint(self, **kwargs):
                return None

        # get_sources 为空 → 直接走失败分支，但仍会先求值 provider_kwargs_fn；
        # 传 lambda 不抛错即为通过（传 dict 会 TypeError）
        result = await _Stub().sync("get_trade_calendar", lambda: {"exchange": "SSE"})
        assert result["success"] is False
