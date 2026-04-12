"""
数据同步服务基类
抽取 Tushare/AKShare/BaoStock 三个同步服务的公共逻辑
"""
import logging
from abc import ABC
from datetime import datetime, timedelta
from typing import Any, Dict

from app.utils.timezone import now_utc, now_config_tz, format_date_short

logger = logging.getLogger(__name__)


class BaseSyncService(ABC):
    """
    数据同步服务基类

    提供三个同步服务的公共方法：
    - get_last_sync_date(): 增量日期获取
    - is_data_fresh(): 数据新鲜度检查
    - make_stats(): 标准统计字典创建
    - complete_stats(): 统计字典完成（填充 end_time/duration）
    """

    def __init__(self, data_source: str, batch_size: int = 100, rate_limit_delay: float = 0.1):
        """
        初始化同步服务基类

        Args:
            data_source: 数据源标识（"tushare" / "akshare" / "baostock"）
            batch_size: 批量处理大小
            rate_limit_delay: API调用间隔（秒）
        """
        self.data_source = data_source
        self.batch_size = batch_size
        self.rate_limit_delay = rate_limit_delay
        self.db = None
        self.historical_service = None

    async def get_last_sync_date(self, symbol: str = None) -> str:
        """
        获取最后同步日期（增量策略）

        策略：
        1. 如果传了 symbol：获取该股票的最新同步日期，返回下一天（避免重复同步）
        2. 如果无历史数据，查找上市日期(list_date)，从上市日期开始全量同步
        3. 如果也没有上市日期，从 1990-01-01 开始
        4. 如果没传 symbol：返回 30 天前（确保不漏数据）
        5. 异常时：返回 30 天前

        Args:
            symbol: 股票代码，如果提供则返回该股票的最后日期+1天

        Returns:
            日期字符串 (YYYY-MM-DD)
        """
        try:
            # 延迟初始化历史数据服务
            if self.historical_service is None:
                from app.services.historical_data_service import get_historical_data_service
                self.historical_service = await get_historical_data_service()

            if symbol:
                # 获取特定股票的最新日期
                latest_date = await self.historical_service.get_latest_date(symbol, self.data_source)
                if latest_date:
                    # 返回最后日期的下一天（避免重复同步）
                    try:
                        last_date_obj = datetime.strptime(latest_date, '%Y-%m-%d')
                        next_date = last_date_obj + timedelta(days=1)
                        return next_date.strftime('%Y-%m-%d')
                    except ValueError:
                        # 如果日期格式不对，直接返回
                        return latest_date
                else:
                    # 没有历史数据时，从上市日期开始全量同步
                    return await self._get_list_date_or_default(symbol)

            # 默认返回30天前（确保不漏数据）
            return format_date_short(now_config_tz() - timedelta(days=30))

        except Exception as e:
            logger.error(f"获取最后同步日期失败 {symbol}: {e}")
            # 出错时返回30天前，确保不漏数据
            return format_date_short(now_config_tz() - timedelta(days=30))

    async def _get_list_date_or_default(self, symbol: str) -> str:
        """
        获取股票上市日期，如果获取失败则返回默认值

        Args:
            symbol: 股票代码

        Returns:
            上市日期字符串或默认值 "1990-01-01"
        """
        if self.db is None:
            logger.warning(f"{symbol}: 数据库未初始化，从1990-01-01开始同步")
            return "1990-01-01"

        try:
            stock_info = await self.db.stock_basic_info.find_one(
                {"code": symbol},
                {"list_date": 1}
            )
            if stock_info and stock_info.get("list_date"):
                list_date = stock_info["list_date"]
                # 处理不同的日期格式
                if isinstance(list_date, str):
                    # 格式可能是 "20100101" 或 "2010-01-01"
                    if len(list_date) == 8 and list_date.isdigit():
                        return f"{list_date[:4]}-{list_date[4:6]}-{list_date[6:]}"
                    else:
                        return list_date
                else:
                    return list_date.strftime('%Y-%m-%d')

            # 如果没有上市日期，从1990年开始
            logger.warning(f"{symbol}: 未找到上市日期，从1990-01-01开始同步")
            return "1990-01-01"

        except Exception as e:
            logger.warning(f"{symbol}: 获取上市日期失败: {e}，从1990-01-01开始同步")
            return "1990-01-01"

    def is_data_fresh(self, updated_at: Any, hours: int = 24) -> bool:
        """
        检查数据是否新鲜

        Args:
            updated_at: 更新时间（datetime 或 ISO 字符串）
            hours: 新鲜度阈值（小时）

        Returns:
            是否新鲜
        """
        if not updated_at:
            return False

        try:
            if isinstance(updated_at, str):
                updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            elif isinstance(updated_at, datetime):
                pass
            else:
                return False

            # 去掉时区信息，统一比较
            if updated_at.tzinfo is not None:
                updated_at = updated_at.replace(tzinfo=None)

            now = now_utc()
            # now_utc() 返回的可能是 aware datetime，统一去掉 tzinfo
            if now.tzinfo is not None:
                now = now.replace(tzinfo=None)

            time_diff = now - updated_at
            return time_diff.total_seconds() < (hours * 3600)

        except Exception as e:
            logger.debug(f"检查数据新鲜度失败: {e}")
            return False

    def make_stats(self, **extra_fields) -> Dict[str, Any]:
        """
        创建标准统计字典

        Args:
            **extra_fields: 额外的统计字段

        Returns:
            标准统计字典
        """
        stats = {
            "total_processed": 0,
            "success_count": 0,
            "error_count": 0,
            "start_time": now_utc(),
            "end_time": None,
            "duration": 0,
            "errors": []
        }
        stats.update(extra_fields)
        return stats

    def complete_stats(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """
        完成统计（填充 end_time 和 duration）

        Args:
            stats: 统计字典

        Returns:
            更新后的统计字典
        """
        stats["end_time"] = now_utc()
        start_time = stats.get("start_time")
        if start_time:
            stats["duration"] = (stats["end_time"] - start_time).total_seconds()
        return stats
