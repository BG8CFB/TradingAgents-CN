from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from app.utils.timezone import now_utc, now_config_tz, format_date_short, format_date_compact, format_iso

import pandas as pd
import numpy as np

# 统一指标库
from app.engine.tools.analysis.indicators import IndicatorSpec, compute_many
# 统一多数据源DF接口（按优先级降级）
from app.data.data_source_manager import get_data_source_manager
from app.data.providers.china.fundamentals_snapshot import get_cn_fund_snapshot


from app.services.screening.eval_utils import (
    collect_fields_from_conditions as _collect_fields_from_conditions_util,
    evaluate_conditions as _evaluate_conditions_util,
    evaluate_fund_conditions as _evaluate_fund_conditions_util,
    safe_float as _safe_float_util,
)

# --- DSL 约束 ---
ALLOWED_FIELDS = {
    # 原始行情（统一为小写列）
    "open", "high", "low", "close", "vol", "amount",
    # 派生
    "pct_chg",  # 当日涨跌幅
    # 指标（固定参数）
    "ma5", "ma10", "ma20", "ma60",
    "ema12", "ema26",
    "dif", "dea", "macd_hist",
    "rsi14",
    "boll_mid", "boll_upper", "boll_lower",
    "atr14",
    "kdj_k", "kdj_d", "kdj_j",
    # 预留：基本面（后续实现）
    "pe", "pb", "roe", "market_cap",
}

# 分类：基础行情字段、技术指标字段、基本面字段
BASE_FIELDS = {"open", "high", "low", "close", "vol", "amount", "pct_chg"}
TECH_FIELDS = {
    "ma5", "ma10", "ma20", "ma60",
    "ema12", "ema26",
    "dif", "dea", "macd_hist",
    "rsi14",
    "boll_mid", "boll_upper", "boll_lower",
    "atr14",
    "kdj_k", "kdj_d", "kdj_j",
}
FUND_FIELDS = {"pe", "pb", "roe", "market_cap"}

ALLOWED_OPS = {">", "<", ">=", "<=", "==", "!=", "between", "cross_up", "cross_down"}


@dataclass
class ScreeningParams:
    market: str = "CN"
    date: Optional[str] = None  # YYYY-MM-DD，None=最近交易日
    adj: str = "qfq"  # 预留参数，当前实现使用Tdx数据，不区分复权
    limit: int = 50
    offset: int = 0
    order_by: Optional[List[Dict[str, str]]] = None  # [{field, direction}]


import logging
logger = logging.getLogger("agents")

class ScreeningService:
    def __init__(self):
        # 数据源通过统一DF接口获取，不直接绑定具体源
        self.provider = None

    # --- 公共入口 ---
    def run(self, conditions: Dict[str, Any], params: ScreeningParams) -> Dict[str, Any]:
        symbols = self._get_universe()
        # 为控制时长，先限制样本规模（后续用批量/缓存优化）
        symbols = symbols[:120]

        end_date = now_utc()
        start_date = end_date - timedelta(days=220)
        end_s = end_date.strftime("%Y-%m-%d")
        start_s = start_date.strftime("%Y-%m-%d")

        results: List[Dict[str, Any]] = []

        # 解析条件中涉及的字段，决定是否需要技术指标/行情
        needed_fields = self._collect_fields_from_conditions(conditions)
        order_fields = {o.get("field") for o in (params.order_by or []) if o.get("field")}
        all_needed = set(needed_fields) | set(order_fields)
        need_tech = any(f in TECH_FIELDS for f in all_needed)
        need_base = any(f in BASE_FIELDS for f in all_needed) or need_tech
        need_fund = any(f in FUND_FIELDS for f in all_needed)

        for code in symbols:
            try:
                dfc = None
                last = None

                # 如需要基础行情/技术指标才取K线
                if need_base:
                    manager = get_data_source_manager()
                    df = manager.get_stock_dataframe(code, start_s, end_s)
                    if df is None or df.empty:
                        continue
                    # 统一列为小写
                    dfu = df.rename(columns={
                        "Open": "open", "High": "high", "Low": "low", "Close": "close",
                        "Volume": "vol", "Amount": "amount"
                    }).copy()
                    # 计算派生：pct_chg
                    if "close" in dfu.columns:
                        dfu["pct_chg"] = dfu["close"].pct_change() * 100.0

                    # 仅在需要技术指标时计算
                    if need_tech:
                        specs = [
                            IndicatorSpec("ma", {"n": 5}),
                            IndicatorSpec("ma", {"n": 10}),
                            IndicatorSpec("ma", {"n": 20}),
                            IndicatorSpec("ema", {"n": 12}),
                            IndicatorSpec("ema", {"n": 26}),
                            IndicatorSpec("macd"),
                            IndicatorSpec("rsi", {"n": 14}),
                            IndicatorSpec("boll", {"n": 20, "k": 2}),
                            IndicatorSpec("atr", {"n": 14}),
                            IndicatorSpec("kdj", {"n": 9, "m1": 3, "m2": 3}),
                        ]
                        dfc = compute_many(dfu, specs)
                    else:
                        dfc = dfu

                    last = dfc.iloc[-1]

                # 评估条件（若条件完全是基本面且不涉及行情/技术，这里可跳过K线）
                passes = True
                if need_base:
                    passes = self._evaluate_conditions(dfc, conditions)
                elif need_fund and not need_base and not need_tech:
                    # 仅基本面条件：使用基本面快照判断
                    snap = get_cn_fund_snapshot(code)
                    if not snap:
                        passes = False
                    else:
                        passes = self._evaluate_fund_conditions(snap, conditions)

                if passes:
                    item = {"code": code}
                    if last is not None:
                        item.update({
                            "close": self._safe_float(last.get("close")),
                            "pct_chg": self._safe_float(last.get("pct_chg")),
                            "amount": self._safe_float(last.get("amount")),
                            "ma20": self._safe_float(last.get("ma20")) if need_tech else None,
                            "rsi14": self._safe_float(last.get("rsi14")) if need_tech else None,
                            "kdj_k": self._safe_float(last.get("kdj_k")) if need_tech else None,
                            "kdj_d": self._safe_float(last.get("kdj_d")) if need_tech else None,
                            "kdj_j": self._safe_float(last.get("kdj_j")) if need_tech else None,
                            "dif": self._safe_float(last.get("dif")) if need_tech else None,
                            "dea": self._safe_float(last.get("dea")) if need_tech else None,
                            "macd_hist": self._safe_float(last.get("macd_hist")) if need_tech else None,
                        })
                    results.append(item)
            except Exception:
                continue

        total = len(results)
        # 排序
        if params.order_by:
            for order in reversed(params.order_by):  # 后者优先级低
                f = order.get("field")
                d = order.get("direction", "desc").lower()
                if f in ALLOWED_FIELDS:
                    results.sort(key=lambda x: (x.get(f) is None, x.get(f)), reverse=(d == "desc"))

        # 分页
        start = params.offset or 0
        end = start + (params.limit or 50)
        page_items = results[start:end]

        return {
            "total": total,
            "items": page_items,
        }
    def _evaluate_fund_conditions(self, snap: Dict[str, Any], node: Dict[str, Any]) -> bool:
        """Delegate fundamental condition evaluation to utils to keep service slim."""
        return _evaluate_fund_conditions_util(snap, node, FUND_FIELDS)


    def _collect_fields_from_conditions(self, node: Dict[str, Any]) -> List[str]:
        """Delegate field collection to utils."""
        return _collect_fields_from_conditions_util(node, ALLOWED_FIELDS)

    # --- 内部：DSL 评估 ---
    def _evaluate_conditions(self, df: pd.DataFrame, node: Dict[str, Any]) -> bool:
        """Delegate technical/base condition evaluation to utils."""
        return _evaluate_conditions_util(df, node, ALLOWED_FIELDS, ALLOWED_OPS)

    # --- 工具 ---
    def _safe_float(self, v: Any) -> Optional[float]:
        """Delegate numeric coercion to utils."""
        return _safe_float_util(v)

    def _get_universe(self) -> List[str]:
        """获取A股代码集合：从 MongoDB stock_basic_info 集合获取所有A股股票代码"""
        try:
            from app.core.database import get_mongo_db

            db = get_mongo_db()
            collection = db.stock_basic_info

            # 查询所有A股股票代码（兼容不同的数据结构）
            cursor = collection.find(
                {
                    "$or": [
                        {"market_info.market": "CN"},  # 新数据结构
                        {"category": "stock_cn"},      # 旧数据结构
                        {"market": {"$in": ["主板", "创业板", "科创板", "北交所"]}}  # 按市场类型
                    ]
                },
                {"code": 1, "_id": 0}
            )

            # 同步获取所有股票代码
            codes = [doc.get("code") for doc in cursor if doc.get("code")]

            if codes:
                logger.info(f"📊 从 MongoDB 获取到 {len(codes)} 只A股股票")
                return codes
            else:
                # 如果数据库为空，返回常见股票代码作为兜底
                logger.warning("⚠️ MongoDB 中未找到股票数据，使用兜底股票列表")
                return ["000001", "000002", "000858", "600519", "600036", "601318", "300750"]

        except Exception as e:
            logger.error(f"❌ 从 MongoDB 获取股票列表失败: {e}")
            # 异常时返回常见股票代码作为兜底
            return ["000001", "000002", "000858", "600519", "600036", "601318", "300750"]

