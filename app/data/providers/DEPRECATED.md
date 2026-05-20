# DEPRECATED — 本目录计划删除

## 迁移状态

| 旧文件 | 新位置 | 状态 |
|--------|--------|------|
| `china/tushare.py` | `sources/cn/tushare/api/` | ✅ 已迁移 |
| `china/akshare.py` | `sources/cn/akshare/api/` | ✅ 已迁移 |
| `china/baostock.py` | `sources/cn/baostock/api/` | ✅ 已迁移 |
| `china/optimized.py` | `services/fundamentals/` (中转) | 🔄 过渡中 |
| `china/fundamentals_snapshot.py` | 待迁移到 reader | ⏳ 待处理 |
| `hk/hk_stock.py` | `sources/hk/yfinance_hk/provider.py` | ✅ 已迁移 |
| `hk/improved_hk.py` | `sources/hk/akshare_hk/provider.py` | 🔄 部分迁移 |
| `us/optimized.py` | 待迁移 | ⏳ 待处理 |
| `us/yfinance.py` | `sources/us/yfinance_us/provider.py` | ✅ 已替代 |
| `us/finnhub.py` | `sources/us/finnhub_us/provider.py` | ✅ 已替代 |
| `us/alpha_vantage_*.py` | `sources/us/alpha_vantage/` (中转) | 🔄 过渡中 |
| `base_provider.py` | `sources/base/provider.py` | ✅ 已替代 |
| `tushare/adapter.py` | `sources/cn/tushare/adapter.py` | ✅ 已替代 |

## 仍引用本目录的模块

- `services/foreign_stock_service.py` — improved_hk 特定函数
- `engine/agents/utils/agent_utils.py` — get_us_stock_data_cached
- `services/fundamentals/__init__.py` — 中转层
- `sources/us/alpha_vantage/__init__.py` — 中转层
