# app/data/ 数据层架构说明

## 目录结构

```
app/data/
├── interface.py               # 公共入口：所有数据访问的统一接口
├── data_source_manager.py     # 多数据源管理 + 自动降级
├── config.py                  # 数据层配置（从 MongoDB 读取数据源优先级）
├── reader.py                  # 数据读取器（从 MongoDB 读取，无数据时触发 sources/ 预热）
├── realtime_metrics.py        # 实时指标（动态 PE/PB 计算）
│
├── schema/                    # Schema 层：标准化字段定义
│   ├── base.py                #   BaseSchema、MarketType、get_full_symbol()
│   ├── collections.py         #   集合名映射（基础名 / _hk / _us）
│   ├── stock_basic_info.py    #   股票基本信息 Schema
│   ├── stock_daily_quotes.py  #   日线行情 Schema
│   ├── market_quotes.py       #   大盘行情 Schema
│   ├── stock_financial_data.py#   财务数据 Schema
│   └── stock_news.py          #   新闻 Schema
│
├── sources/                   # Sources 层（新架构）：Provider + Adapter 模式
│   ├── base/                  #   基类 BaseProvider / BaseAdapter
│   ├── cn/                    #   A 股：tushare / akshare / baostock
│   ├── hk/                    #   港股：akshare_hk / yfinance_hk
│   └── us/                    #   美股：yfinance_us / finnhub_us
│
├── providers/                 # Providers 层（旧架构，仍活跃使用）
│   ├── base_provider.py       #   BaseStockDataProvider 基类
│   ├── china/                 #   A 股：tushare / akshare / baostock / optimized / fundamentals_snapshot
│   ├── hk/                    #   港股：hk_stock / improved_hk
│   ├── us/                    #   美股：yfinance / finnhub / optimized / alpha_vantage_common / alpha_vantage_fundamentals
│   └── tushare/               #   Tushare 独立适配器
│
├── cache/                     # 多级缓存
│   ├── integrated.py          #   集成缓存（统一入口，自动选择 MongoDB/Redis/File）
│   ├── db_cache.py            #   数据库缓存（MongoDB + Redis）
│   ├── file_cache.py          #   文件缓存
│   ├── mongodb_cache_adapter.py#  MongoDB 缓存适配器
│   └── app_adapter.py         #   应用级缓存适配器
│
├── news/                      # 新闻数据采集
│   ├── chinese_finance.py     #   中文财经新闻
│   ├── google_news.py         #   Google 新闻
│   ├── realtime_news.py       #   实时新闻聚合（Finnhub/Alpha Vantage/NewsAPI）
│   └── reddit.py              #   Reddit 新闻
│
└── technical/                 # 技术指标
    └── stockstats.py          #   基于 stockstats 的技术分析
```

## 核心文件说明

### interface.py — 公共接口层
面向 engine/agent 层的统一 API。所有数据获取函数的入口。
- 中国市场：`get_china_stock_data_unified()`、`get_china_stock_info_unified()`
- 港股市场：`get_hk_stock_data_unified()`、`get_hk_stock_info_unified()`
- 美股市场：`get_finnhub_news()`、`get_fundamentals_finnhub()`、`get_YFin_data()`
- 新闻：`get_google_news()`、`get_reddit_global_news()`、`get_stock_news_openai()`
- 技术：`get_stockstats_indicator()`

### reader.py — 统一数据读取层
从 MongoDB 读取标准化数据。港股/美股无缓存时自动触发 `sources/` 编排模块预热。
被 engine 层 27 个文件广泛引用。

### data_source_manager.py — 数据源管理器
管理 A 股多数据源（Tushare/AKShare/BaoStock）的优先级和自动降级。
包含 `DataSourceManager` 和 `USDataSourceManager`。

## 架构关系

```
engine/agents → interface.py → reader.py → MongoDB
                             ↘ data_source_manager → providers/ → 外部 API
                                                    ↘ sources/ → providers/ → 外部 API
```

- `interface.py` 是面向 agent 层的门面
- `reader.py` 是面向 MongoDB 的读取层
- `providers/` 是实际的数据获取实现
- `sources/` 是新的 Provider+Adapter 抽象层（目前仍包装 providers/）

## 使用方式

```python
from app.data.interface import get_china_stock_data_unified
data = get_china_stock_data_unified("000001", "2024-01-01", "2024-12-31")
```

## 字段标准

- 使用 `symbol`（非 `code`）
- 使用 `data_source`（非 `source`）
- A 股使用基础集合名；港股/美股使用 `_hk`/`_us` 后缀
