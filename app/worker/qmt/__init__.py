"""QMT 盘后采集 worker（datadir 本地直读）。

入口 ``run_qmt_sync``：就绪轮询 → 合约列表 → 交易日历 → 日线（按交易日
批量）。域同步复用 ``BaseMarketDomainSync`` 的四件套 + Repo upsert +
sync_events/checkpoints 全套语义，仅钉死数据源为 qmt（本地直读零成本
优先采，失败不与既有源抢跑——回退语义由路由/按需刷新承接，D-2）。
"""
