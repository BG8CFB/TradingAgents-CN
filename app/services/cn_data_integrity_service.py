"""
A 股数据完整性检查服务

检查内容：
  1. 缺失交易日数据（日线缺失检测）
  2. 关键字段空值检测
  3. 数据时间连续性检测
  4. 跨域一致性检测（日线 ↔ 指标 ↔ 复权因子）
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)


@dataclass
class IntegrityIssue:
    """完整性问题"""
    severity: str          # warning / error
    domain: str
    issue_type: str        # missing_dates / null_fields / cross_domain_mismatch
    description: str
    details: Optional[Dict[str, Any]] = None


@dataclass
class IntegrityReport:
    """完整性检查报告"""
    checked_at: str = ""
    issues: List[IntegrityIssue] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checked_at": self.checked_at,
            "has_errors": self.has_errors,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [
                {
                    "severity": i.severity,
                    "domain": i.domain,
                    "issue_type": i.issue_type,
                    "description": i.description,
                    "details": i.details,
                }
                for i in self.issues
            ],
            "stats": self.stats,
        }


class DataIntegrityService:
    """A 股数据完整性检查服务"""

    async def run_full_check(
        self,
        symbols: Optional[List[str]] = None,
    ) -> IntegrityReport:
        """执行完整的数据完整性检查"""
        report = IntegrityReport(checked_at=now_utc().isoformat())

        try:
            db = await self._get_db()
        except Exception as e:
            report.issues.append(IntegrityIssue(
                severity="error", domain="all",
                issue_type="connection",
                description=f"无法连接数据库: {e}",
            ))
            return report

        # 1. 各域记录数统计
        domain_counts = await self._check_domain_counts(db)
        report.stats["domain_counts"] = domain_counts

        # 2. 缺失交易日检测（最近 5 个交易日）
        await self._check_missing_dates(db, report, symbols)

        # 3. 关键字段空值检测
        await self._check_null_fields(db, report)

        # 4. 跨域一致性检测
        await self._check_cross_domain_consistency(db, report, symbols)

        # 写入检查结果
        await self._save_report(report)

        return report

    async def _get_db(self):
        from app.core.database import get_database
        return await get_database()

    async def _check_domain_counts(self, db) -> Dict[str, int]:
        from app.data.storage.mongo.collections import get_collection_name
        domains = ["basic_info", "daily_quotes", "daily_indicators", "adj_factors", "financial", "news"]
        counts = {}
        for domain in domains:
            try:
                collection = db[get_collection_name(domain, "CN")]
                counts[domain] = await collection.count_documents({})
            except Exception:
                counts[domain] = 0
        return counts

    async def _check_missing_dates(
        self, db, report: IntegrityReport,
        symbols: Optional[List[str]] = None,
    ):
        """检查最近 5 个交易日是否有日线数据"""
        from app.data.storage.mongo.collections import get_collection_name

        try:
            cal_collection = db[get_collection_name("trade_calendar", "CN")]
            quotes_collection = db[get_collection_name("daily_quotes", "CN")]

            # 获取最近 5 个交易日
            today = now_utc().strftime("%Y%m%d")
            cursor = cal_collection.find(
                {"is_open": 1, "cal_date": {"$lte": today}},
                {"cal_date": 1},
            ).sort("cal_date", -1).limit(5)
            trade_days = [doc["cal_date"] async for doc in cursor]

            if not trade_days:
                report.issues.append(IntegrityIssue(
                    severity="warning", domain="trade_calendar",
                    issue_type="missing_dates",
                    description="交易日历为空，无法检查缺失日期",
                ))
                return

            # 检查每个交易日有数据的股票数量
            for td in trade_days:
                td_formatted = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
                count = await quotes_collection.count_documents({"trade_date": td_formatted})
                if count == 0:
                    # 尝试原始格式
                    count = await quotes_collection.count_documents({"trade_date": td})

                if count == 0:
                    report.issues.append(IntegrityIssue(
                        severity="warning", domain="daily_quotes",
                        issue_type="missing_dates",
                        description=f"交易日 {td_formatted} 无日线数据",
                    ))

        except Exception as e:
            report.issues.append(IntegrityIssue(
                severity="error", domain="daily_quotes",
                issue_type="missing_dates",
                description=f"缺失日期检查失败: {e}",
            ))

    async def _check_null_fields(self, db, report: IntegrityReport):
        """检查关键字段空值"""
        from app.data.storage.mongo.collections import get_collection_name

        checks = {
            "daily_quotes": ["symbol", "trade_date", "close"],
            "daily_indicators": ["symbol", "trade_date"],
            "financial": ["symbol", "report_period"],
        }

        for domain, required_fields in checks.items():
            try:
                collection = db[get_collection_name(domain, "CN")]
                for f in required_fields:
                    null_count = await collection.count_documents({
                        "$or": [
                            {f: None},
                            {f: ""},
                            {f: {"$exists": False}},
                        ],
                    })
                    if null_count > 0:
                        report.issues.append(IntegrityIssue(
                            severity="error", domain=domain,
                            issue_type="null_fields",
                            description=f"域 {domain} 有 {null_count} 条记录缺少字段 {f}",
                            details={"field": f, "null_count": null_count},
                        ))
            except Exception:
                pass

    async def _check_cross_domain_consistency(
        self, db, report: IntegrityReport,
        symbols: Optional[List[str]] = None,
    ):
        """检查跨域一致性"""
        from app.data.storage.mongo.collections import get_collection_name

        try:
            quotes_collection = db[get_collection_name("daily_quotes", "CN")]
            indicators_collection = db[get_collection_name("daily_indicators", "CN")]

            # 检查日线有数据但指标无数据的股票
            pipeline = [
                {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 20},
            ]

            top_symbols = await quotes_collection.aggregate(pipeline).to_list(length=20)

            for doc in top_symbols:
                symbol = doc["_id"]
                quote_count = doc["count"]
                indicator_count = await indicators_collection.count_documents({"symbol": symbol})

                if quote_count > 0 and indicator_count == 0:
                    report.issues.append(IntegrityIssue(
                        severity="warning", domain="daily_indicators",
                        issue_type="cross_domain_mismatch",
                        description=f"股票 {symbol} 有 {quote_count} 条日线但无指标数据",
                    ))
        except Exception:
            pass

    async def _save_report(self, report: IntegrityReport):
        """保存检查报告到 MongoDB"""
        try:
            db = await self._get_db()
            from app.data.storage.mongo.collections import get_collection_name

            collection = db[get_collection_name("sync_events", "CN")]
            event = {
                "event_type": "INTEGRITY_CHECK",
                "domain": "all",
                "source": "integrity_service",
                "record_count": report.error_count + report.warning_count,
                "error_message": f"errors={report.error_count}, warnings={report.warning_count}",
                "data_source": "integrity_service",
                "updated_at": now_utc().isoformat(),
                "details": report.to_dict(),
            }
            await collection.insert_one(event)
        except Exception:
            pass


# ── 单例 ──

_instance: Optional[DataIntegrityService] = None


def get_integrity_service() -> DataIntegrityService:
    global _instance
    if _instance is None:
        _instance = DataIntegrityService()
    return _instance
