"""看板查询路径依赖的索引守卫。

看板按 ``updated_at`` 倒序取「最后更新时间」，缺索引时该排序退化为全集合扫描
（千万级集合下单次数秒）。本测试锁定这几个高频集合始终声明该索引。
"""

from __future__ import annotations

import pytest

from app.data.storage.mongo.index_definitions import INDEX_DEFINITIONS

# 看板「最后更新时间」会扫到的时序集合
DASHBOARD_SORTED_COLLECTIONS = ("daily_quotes", "daily_indicators", "adj_factors", "money_flow")


@pytest.mark.parametrize("collection", DASHBOARD_SORTED_COLLECTIONS)
def test_collection_declares_updated_at_index(collection):
    indexes = INDEX_DEFINITIONS.get(collection)
    assert indexes, f"{collection} 没有索引定义"
    keys = [tuple(k) for k, _unique in indexes]
    assert (("updated_at", -1),) in keys, f"{collection} 缺少 updated_at 倒序索引：{keys}"


@pytest.mark.parametrize("collection", DASHBOARD_SORTED_COLLECTIONS)
def test_updated_at_index_is_not_unique(collection):
    """updated_at 会随每次写入更新，绝不能建成唯一索引（否则并发写冲突）。"""
    for keys, unique in INDEX_DEFINITIONS[collection]:
        if tuple(keys) == (("updated_at", -1),):
            assert unique is False
