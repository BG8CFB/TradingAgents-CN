"""契约测试：错误三态（阶段 1 已实现，硬断言）。

- 参数非法（未知 domain / 非法 market）→ ValueError fail-fast
- 存储故障 → app.data.core.errors.DataUnavailableError
- 无数据 → 正常返回空（见 test_read_shape_invariants.py）
"""

import pytest


async def test_read_unknown_domain_raises_value_error(
        inject_sim_db, data_interface):
    """未知 domain 抛 ValueError（fail-fast）。"""
    with pytest.raises(ValueError):
        await data_interface.read("CN", "not_a_domain", symbol="000001")


async def test_read_invalid_market_raises_value_error(
        inject_sim_db, data_interface):
    """非法 market 抛 ValueError（fail-fast）。"""
    with pytest.raises(ValueError):
        await data_interface.read("XX", "daily_quotes", symbol="000001")


def test_data_unavailable_error_importable():
    """存储故障异常类型可从 app.data.core.errors 导入。"""
    from app.data.core.errors import DataUnavailableError  # noqa: F401
