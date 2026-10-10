"""批量域「按交易日拉全市场」的守卫用例（adj_factors / margin_trading）。

背景：同步任务传 `symbol="__all__"` 走批量路径。这两个域原先**缺** `__all__→None`
转换 → 拼成 `ts_code=__all__.SZ` → 两源全失败（adj_factors 等 150s 熔断）；
即使转了 None，API 层也只认 `ts_code`、没有 `trade_date` 分支，照样拿不到数据。

修法（两层，缺一不可）：
  ① `fallback_router.method_map`：`None if symbol == "__all__" else symbol`；
  ② `api/*.py`：`ts_code` 为空时改调 `trade_date=` 拉全市场；
  ③ `provider`：`ts_code = self._to_ts_code(symbol) if symbol else None`（别再拼 .SZ）。

整批实测：adj_factors 5,562 行/0.6s、margin_trading 4,451 行/0.4s（原本逐只要 ~50 分钟）。
"""

import inspect

import pandas as pd
import pytest

from app.data.processor import fallback_router as fr
from app.data.sources.cn.tushare.api import adj_factors as af
from app.data.sources.cn.tushare.api import margin_trading as mt


class _Recorder:
    """替身 call_tushare：记录 (api_name, params)，返回非空 DataFrame。"""

    def __init__(self):
        self.calls = []

    async def __call__(self, conn, api_name, source, domain, context, **params):
        self.calls.append({"api_name": api_name, "params": params})
        return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": params.get("trade_date")}])


@pytest.mark.asyncio
async def test_adj_factors_batch_uses_trade_date(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(af, "call_tushare", rec)
    out = await af.fetch_adj_factors(None, None, "2026-09-15", "2026-09-15")
    assert rec.calls, "批量模式必须真的发起调用"
    call = rec.calls[0]
    assert call["api_name"] == "adj_factor"
    assert call["params"].get("trade_date") == "20260915"
    assert "ts_code" not in call["params"], "批量模式不得带 ts_code（否则拼成 __all__.SZ）"
    assert out is not None


@pytest.mark.asyncio
async def test_margin_trading_batch_uses_trade_date(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(mt, "call_tushare", rec)
    await mt.fetch_margin_detail(None, None, "2026-09-23", "2026-09-23")
    call = rec.calls[0]
    assert call["api_name"] == "margin_detail"
    assert call["params"].get("trade_date") == "20260923"
    assert "ts_code" not in call["params"]


@pytest.mark.asyncio
async def test_per_symbol_path_unchanged(monkeypatch):
    """逐只路径不能被改坏：仍带 ts_code、不带 trade_date。"""
    rec = _Recorder()
    monkeypatch.setattr(af, "call_tushare", rec)
    await af.fetch_adj_factors(None, "000001.SZ", "2026-09-01", "2026-09-15")
    call = rec.calls[0]
    assert call["params"].get("ts_code") == "000001.SZ"
    assert "trade_date" not in call["params"]
    assert call["params"].get("start_date") == "20260901"


def test_router_converts_all_sentinel_for_both_domains():
    src = inspect.getsource(fr)
    for dom in ("adj_factors", "margin_trading"):
        i = src.index(f'"{dom}": lambda')
        block = src[i : i + 260]
        assert 'None if symbol == "__all__"' in block, f"{dom} 缺 __all__→None 转换"


def test_provider_guards_to_ts_code():
    from app.data.sources.cn.tushare import provider as pv

    src = inspect.getsource(pv)
    assert src.count("self._to_ts_code(symbol) if symbol else None") >= 2, (
        "adj_factors/margin_trading 的 provider 都要加空 symbol 守卫"
    )
