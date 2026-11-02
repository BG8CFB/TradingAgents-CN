"""基础数据同步子包：共享的文档构建/指标处理函数。

（历史 utils.py 的 4 个 Tushare 直连函数零调用方，随数据生产归位删除，2026-11-02）
"""
from .processing import add_financial_metrics

__all__ = ["add_financial_metrics"]
