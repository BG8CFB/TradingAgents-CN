#!/usr/bin/env python3
"""
股票数据预获取和验证模块
用于在分析流程开始前验证股票是否存在，并预先获取和缓存必要的数据
"""

import re
import asyncio
import concurrent.futures
from typing import Dict, Tuple, Optional
from datetime import datetime, timedelta
from app.utils.time_utils import now_utc, get_current_date, parse_date_aware

# 导入日志模块
from app.utils.logging_manager import get_logger


logger = get_logger('stock_validator')


# ── 新架构同步辅助函数 ──────────────────────────────────────────────

def _get_stock_info_sync(market: str, symbol: str):
    """同步获取股票基础信息（基于 DataInterface）。"""
    try:
        import pandas as pd
        from app.data.core.interface import DataInterface

        async def _read():
            di = DataInterface.get_instance()
            result = await di.read(market, symbol, "basic_info")
            data = result.get("data")
            if data:
                doc = data[0] if isinstance(data, list) and data else data
                lines = [f"股票代码: {doc.get('symbol', symbol)}"]
                for key, label in [("name", "股票名称"), ("industry", "行业"), ("exchange", "交易所")]:
                    if doc.get(key):
                        lines.append(f"{label}: {doc[key]}")
                return "\n".join(lines)
            return None

        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _read()).result()
        except RuntimeError:
            return asyncio.run(_read())
    except Exception:
        pass
    return None


def _get_stock_data_sync(market: str, symbol: str, start_date=None, end_date=None):
    """同步获取股票日线数据（基于 DataInterface）。"""
    try:
        import pandas as pd
        from app.data.core.interface import DataInterface

        async def _read():
            di = DataInterface.get_instance()
            result = await di.read(market, symbol, "daily_quotes", start_date=start_date, end_date=end_date)
            data = result.get("data")
            if data and isinstance(data, list) and data:
                return pd.DataFrame(data).to_string()
            return None

        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _read()).result()
        except RuntimeError:
            return asyncio.run(_read())
    except Exception:
        pass
    return None


class StockDataPreparationResult:
    """股票数据预获取结果类"""

    def __init__(self, is_valid: bool, stock_code: str, market_type: str = "",
                 stock_name: str = "", error_message: str = "", suggestion: str = "",
                 has_historical_data: bool = False, has_basic_info: bool = False,
                 data_period_days: int = 0, cache_status: str = ""):
        self.is_valid = is_valid
        self.stock_code = stock_code
        self.market_type = market_type
        self.stock_name = stock_name
        self.error_message = error_message
        self.suggestion = suggestion
        self.has_historical_data = has_historical_data
        self.has_basic_info = has_basic_info
        self.data_period_days = data_period_days
        self.cache_status = cache_status

    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return {
            'is_valid': self.is_valid,
            'stock_code': self.stock_code,
            'market_type': self.market_type,
            'stock_name': self.stock_name,
            'error_message': self.error_message,
            'suggestion': self.suggestion,
            'has_historical_data': self.has_historical_data,
            'has_basic_info': self.has_basic_info,
            'data_period_days': self.data_period_days,
            'cache_status': self.cache_status
        }


# 保持向后兼容
StockValidationResult = StockDataPreparationResult


class StockDataPreparer:
    """股票数据预获取和验证器"""

    def __init__(self, default_period_days: int = 30):
        self.timeout_seconds = 15  # 数据获取超时时间
        self.default_period_days = default_period_days  # 默认历史数据时长（天）
    
    def prepare_stock_data(self, stock_code: str, market_type: str = "auto",
                          period_days: int = None, analysis_date: str = None) -> StockDataPreparationResult:
        """
        预获取和验证股票数据

        Args:
            stock_code: 股票代码
            market_type: 市场类型 ("A股", "港股", "美股", "auto")
            period_days: 历史数据时长（天），默认使用类初始化时的值
            analysis_date: 分析日期，默认为今天

        Returns:
            StockDataPreparationResult: 数据准备结果
        """
        if period_days is None:
            period_days = self.default_period_days

        if analysis_date is None:
            analysis_date = get_current_date()

        logger.info(f"📊 [数据准备] 开始准备股票数据: {stock_code} (市场: {market_type}, 时长: {period_days}天)")

        # 1. 基本格式验证
        format_result = self._validate_format(stock_code, market_type)
        if not format_result.is_valid:
            return format_result

        # 2. 自动检测市场类型
        if market_type == "auto":
            market_type = self._detect_market_type(stock_code)
            logger.debug(f"📊 [数据准备] 自动检测市场类型: {market_type}")

        # 3. 预获取数据并验证
        return self._prepare_data_by_market(stock_code, market_type, period_days, analysis_date)
    
    def _validate_format(self, stock_code: str, market_type: str) -> StockDataPreparationResult:
        """验证股票代码格式"""
        stock_code = stock_code.strip()
        
        if not stock_code:
            return StockDataPreparationResult(
                is_valid=False,
                stock_code=stock_code,
                error_message="股票代码不能为空",
                suggestion="请输入有效的股票代码"
            )

        if len(stock_code) > 10:
            return StockDataPreparationResult(
                is_valid=False,
                stock_code=stock_code,
                error_message="股票代码长度不能超过10个字符",
                suggestion="请检查股票代码格式"
            )
        
        # 根据市场类型验证格式
        if market_type == "A股":
            if not re.match(r'^\d{6}$', stock_code):
                return StockDataPreparationResult(
                    is_valid=False,
                    stock_code=stock_code,
                    market_type="A股",
                    error_message="A股代码格式错误，应为6位数字",
                    suggestion="请输入6位数字的A股代码，如：000001、600519"
                )
        elif market_type == "港股":
            stock_code_upper = stock_code.upper()
            hk_format = re.match(r'^\d{4,5}\.HK$', stock_code_upper)
            digit_format = re.match(r'^\d{4,5}$', stock_code)

            if not (hk_format or digit_format):
                return StockDataPreparationResult(
                    is_valid=False,
                    stock_code=stock_code,
                    market_type="港股",
                    error_message="港股代码格式错误",
                    suggestion="请输入4-5位数字.HK格式（如：0700.HK）或4-5位数字（如：0700）"
                )
        elif market_type == "美股":
            if not re.match(r'^[A-Z]{1,5}$', stock_code.upper()):
                return StockDataPreparationResult(
                    is_valid=False,
                    stock_code=stock_code,
                    market_type="美股",
                    error_message="美股代码格式错误，应为1-5位字母",
                    suggestion="请输入1-5位字母的美股代码，如：AAPL、TSLA"
                )
        
        return StockDataPreparationResult(
            is_valid=True,
            stock_code=stock_code,
            market_type=market_type
        )
    
    def _detect_market_type(self, stock_code: str) -> str:
        """自动检测市场类型"""
        stock_code = stock_code.strip().upper()
        
        # A股：6位数字
        if re.match(r'^\d{6}$', stock_code):
            return "A股"
        
        # 港股：4-5位数字.HK 或 纯4-5位数字
        if re.match(r'^\d{4,5}\.HK$', stock_code) or re.match(r'^\d{4,5}$', stock_code):
            return "港股"
        
        # 美股：1-5位字母
        if re.match(r'^[A-Z]{1,5}$', stock_code):
            return "美股"
        
        return "未知"

    def _get_hk_network_limitation_suggestion(self) -> str:
        """获取港股网络限制的详细建议"""
        suggestions = [
            "🌐 港股数据获取受到网络API限制，这是常见的临时问题",
            "",
            "💡 解决方案：",
            "1. 等待5-10分钟后重试（API限制通常会自动解除）",
            "2. 检查网络连接是否稳定",
            "3. 如果是知名港股（如腾讯0700.HK、阿里9988.HK），代码格式通常正确",
            "4. 可以尝试使用其他时间段进行分析",
            "",
            "📋 常见港股代码格式：",
            "• 腾讯控股：0700.HK",
            "• 阿里巴巴：9988.HK",
            "• 美团：3690.HK",
            "• 小米集团：1810.HK",
            "",
            "⏰ 建议稍后重试，或联系技术支持获取帮助"
        ]
        return "\n".join(suggestions)

    def _extract_hk_stock_name(self, stock_info, stock_code: str) -> str:
        """从港股信息中提取股票名称，支持多种格式"""
        if not stock_info:
            return "未知"

        # 处理不同类型的返回值
        if isinstance(stock_info, dict):
            # 如果是字典，尝试从常见字段提取名称
            name_fields = ['name', 'longName', 'shortName', 'companyName', '公司名称', '股票名称']
            for field in name_fields:
                if field in stock_info and stock_info[field]:
                    name = str(stock_info[field]).strip()
                    if name and name != "未知":
                        return name

            # 如果字典包含有效信息但没有名称字段，使用股票代码
            if len(stock_info) > 0:
                return stock_code
            return "未知"

        # 转换为字符串处理
        stock_info_str = str(stock_info)

        # 方法1: 标准格式 "公司名称: XXX"
        if "公司名称:" in stock_info_str:
            lines = stock_info_str.split('\n')
            for line in lines:
                if "公司名称:" in line:
                    name = line.split(':')[1].strip()
                    if name and name != "未知":
                        return name

        # 方法2: Yahoo Finance格式检测
        # 日志显示: "✅ Yahoo Finance成功获取港股信息: 0700.HK -> TENCENT"
        if "Yahoo Finance成功获取港股信息" in stock_info_str:
            # 从日志中提取名称
            if " -> " in stock_info_str:
                parts = stock_info_str.split(" -> ")
                if len(parts) > 1:
                    name = parts[-1].strip()
                    if name and name != "未知":
                        return name

        # 方法3: 检查是否包含常见的公司名称关键词
        company_indicators = [
            "Limited", "Ltd", "Corporation", "Corp", "Inc", "Group",
            "Holdings", "Company", "Co", "集团", "控股", "有限公司"
        ]

        lines = stock_info_str.split('\n')
        for line in lines:
            line = line.strip()
            if any(indicator in line for indicator in company_indicators):
                # 尝试提取公司名称
                if ":" in line:
                    potential_name = line.split(':')[-1].strip()
                    if potential_name and len(potential_name) > 2:
                        return potential_name
                elif len(line) > 2 and len(line) < 100:  # 合理的公司名称长度
                    return line

        # 方法4: 如果信息看起来有效但无法解析名称，使用股票代码
        if len(stock_info_str) > 50 and "❌" not in stock_info_str:
            # 信息看起来有效，但无法解析名称，使用代码作为名称
            return stock_code

        return "未知"

    def _prepare_data_by_market(self, stock_code: str, market_type: str,
                               period_days: int, analysis_date: str) -> StockDataPreparationResult:
        """根据市场类型预获取数据"""
        logger.debug(f"📊 [数据准备] 开始为{market_type}股票{stock_code}准备数据")

        try:
            if market_type == "A股":
                return self._prepare_china_stock_data(stock_code, period_days, analysis_date)
            elif market_type == "港股":
                return self._prepare_hk_stock_data(stock_code, period_days, analysis_date)
            elif market_type == "美股":
                return self._prepare_us_stock_data(stock_code, period_days, analysis_date)
            else:
                return StockDataPreparationResult(
                    is_valid=False,
                    stock_code=stock_code,
                    market_type=market_type,
                    error_message=f"不支持的市场类型: {market_type}",
                    suggestion="请选择支持的市场类型：A股、港股、美股"
                )
        except Exception as e:
            logger.error(f"❌ [数据准备] 数据准备异常: {e}")
            return StockDataPreparationResult(
                is_valid=False,
                stock_code=stock_code,
                market_type=market_type,
                error_message=f"数据准备过程中发生错误: {str(e)}",
                suggestion="请检查网络连接或稍后重试"
            )

    async def _prepare_data_by_market_async(self, stock_code: str, market_type: str,
                                           period_days: int, analysis_date: str) -> StockDataPreparationResult:
        """根据市场类型预获取数据（异步版本）"""
        logger.debug(f"📊 [数据准备-异步] 开始为{market_type}股票{stock_code}准备数据")

        try:
            if market_type == "A股":
                return await self._prepare_china_stock_data_async(stock_code, period_days, analysis_date)
            elif market_type == "港股":
                return await asyncio.to_thread(self._prepare_hk_stock_data, stock_code, period_days, analysis_date)
            elif market_type == "美股":
                return await asyncio.to_thread(self._prepare_us_stock_data, stock_code, period_days, analysis_date)
            else:
                return StockDataPreparationResult(
                    is_valid=False,
                    stock_code=stock_code,
                    market_type=market_type,
                    error_message=f"不支持的市场类型: {market_type}",
                    suggestion="请选择支持的市场类型：A股、港股、美股"
                )
        except Exception as e:
            logger.error(f"❌ [数据准备-异步] 数据准备异常: {e}")
            return StockDataPreparationResult(
                is_valid=False,
                stock_code=stock_code,
                market_type=market_type,
                error_message=f"数据准备过程中发生错误: {str(e)}",
                suggestion="请检查网络连接或稍后重试"
            )

    def _prepare_china_stock_data(self, stock_code: str, period_days: int,
                                 analysis_date: str) -> StockDataPreparationResult:
        """预获取A股数据，包含数据库检查和自动同步"""
        logger.info(f"📊 [A股数据] 开始准备{stock_code}的数据 (时长: {period_days}天)")

        # 计算日期范围（使用扩展后的日期范围，与get_china_stock_data_unified保持一致）
        end_date = parse_date_aware(analysis_date, to_config_tz=False)

        # 获取配置的回溯天数（与get_china_stock_data_unified保持一致）
        from app.core.config import settings
        lookback_days = getattr(settings, 'MARKET_ANALYST_LOOKBACK_DAYS', 365)

        # 使用扩展后的日期范围进行数据检查和同步
        extended_start_date = end_date - timedelta(days=lookback_days)  # ✅ aware - timedelta = aware
        extended_start_date_str = extended_start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')

        logger.info(f"📅 [A股数据] 实际数据范围: {extended_start_date_str} 到 {end_date_str} ({lookback_days}天)")

        has_historical_data = False
        has_basic_info = False
        stock_name = "未知"
        cache_status = ""
        data_synced = False

        try:
            # 1. 检查数据库中的数据是否存在和最新
            logger.debug(f"📊 [A股数据] 检查数据库中{stock_code}的数据...")
            db_check_result = self._check_database_data(stock_code, extended_start_date_str, end_date_str)

            # 2. 如果数据不存在或不是最新，自动触发同步
            if not db_check_result["has_data"] or not db_check_result["is_latest"]:
                logger.warning(f"⚠️ [A股数据] 数据库数据不完整: {db_check_result['message']}")
                logger.info(f"🔄 [A股数据] 自动触发数据同步: {stock_code}")

                # 使用扩展后的日期范围进行同步
                sync_result = self._trigger_data_sync_sync(stock_code, extended_start_date_str, end_date_str)
                if sync_result["success"]:
                    logger.info(f"✅ [A股数据] 数据同步成功: {sync_result['message']}")
                    data_synced = True
                    cache_status += "数据已同步; "
                else:
                    logger.warning(f"⚠️ [A股数据] 数据同步失败: {sync_result['message']}")
                    # 继续尝试从API获取数据
            else:
                logger.info(f"✅ [A股数据] 数据库数据检查通过: {db_check_result['message']}")
                cache_status += "数据库数据最新; "

            # 3. 获取基本信息
            logger.debug(f"📊 [A股数据] 获取{stock_code}基本信息...")
            stock_info = _get_stock_info_sync("CN", stock_code)

            if stock_info and "❌" not in stock_info and "未能获取" not in stock_info:
                # 解析股票名称
                if "股票名称:" in stock_info:
                    lines = stock_info.split('\n')
                    for line in lines:
                        if "股票名称:" in line:
                            stock_name = line.split(':')[1].strip()
                            break

                # 检查是否为有效的股票名称
                if stock_name != "未知" and not stock_name.startswith(f"股票{stock_code}"):
                    has_basic_info = True
                    logger.info(f"✅ [A股数据] 基本信息获取成功: {stock_code} - {stock_name}")
                    cache_status += "基本信息已缓存; "
                else:
                    logger.warning(f"⚠️ [A股数据] 基本信息无效: {stock_code}")
                    return StockDataPreparationResult(
                        is_valid=False,
                        stock_code=stock_code,
                        market_type="A股",
                        error_message=f"股票代码 {stock_code} 不存在或信息无效",
                        suggestion="请检查股票代码是否正确，或确认该股票是否已上市"
                    )
            else:
                logger.warning(f"⚠️ [A股数据] 无法获取基本信息: {stock_code}")
                return StockDataPreparationResult(
                    is_valid=False,
                    stock_code=stock_code,
                    market_type="A股",
                    error_message=f"无法获取股票 {stock_code} 的基本信息",
                    suggestion="请检查股票代码是否正确，或确认该股票是否已上市"
                )

            # 4. 获取历史数据（使用扩展后的日期范围）
            logger.debug(f"📊 [A股数据] 获取{stock_code}历史数据 ({extended_start_date_str} 到 {end_date_str})...")
            historical_data = _get_stock_data_sync("CN", stock_code, extended_start_date_str, end_date_str)

            if historical_data and "❌" not in historical_data and "获取失败" not in historical_data:
                # 更宽松的数据有效性检查
                data_indicators = [
                    "开盘价", "收盘价", "最高价", "最低价", "成交量",
                    "open", "close", "high", "low", "volume",
                    "日期", "date", "时间", "time"
                ]

                has_valid_data = (
                    len(historical_data) > 50 and  # 降低长度要求
                    any(indicator in historical_data for indicator in data_indicators)
                )

                if has_valid_data:
                    has_historical_data = True
                    logger.info(f"✅ [A股数据] 历史数据获取成功: {stock_code} ({lookback_days}天)")
                    cache_status += f"历史数据已缓存({lookback_days}天); "
                else:
                    logger.warning(f"⚠️ [A股数据] 历史数据无效: {stock_code}")
                    logger.debug(f"🔍 [A股数据] 数据内容预览: {historical_data[:200]}...")
                    return StockDataPreparationResult(
                        is_valid=False,
                        stock_code=stock_code,
                        market_type="A股",
                        stock_name=stock_name,
                        has_basic_info=has_basic_info,
                        error_message=f"股票 {stock_code} 的历史数据无效或不足",
                        suggestion="该股票可能为新上市股票或数据源暂时不可用，请稍后重试"
                    )
            else:
                logger.warning(f"⚠️ [A股数据] 无法获取历史数据: {stock_code}")
                return StockDataPreparationResult(
                    is_valid=False,
                    stock_code=stock_code,
                    market_type="A股",
                    stock_name=stock_name,
                    has_basic_info=has_basic_info,
                    error_message=f"无法获取股票 {stock_code} 的历史数据",
                    suggestion="请检查网络连接或数据源配置，或稍后重试"
                )

            # 5. 数据准备成功
            logger.info(f"🎉 [A股数据] 数据准备完成: {stock_code} - {stock_name}")
            return StockDataPreparationResult(
                is_valid=True,
                stock_code=stock_code,
                market_type="A股",
                stock_name=stock_name,
                has_historical_data=has_historical_data,
                has_basic_info=has_basic_info,
                data_period_days=lookback_days,  # 使用实际的数据天数
                cache_status=cache_status.rstrip('; ')
            )

        except Exception as e:
            logger.error(f"❌ [A股数据] 数据准备失败: {e}")
            import traceback
            logger.debug(f"详细错误: {traceback.format_exc()}")
            return StockDataPreparationResult(
                is_valid=False,
                stock_code=stock_code,
                market_type="A股",
                stock_name=stock_name,
                has_basic_info=has_basic_info,
                has_historical_data=has_historical_data,
                error_message=f"数据准备失败: {str(e)}",
                suggestion="请检查网络连接或数据源配置"
            )

    async def _prepare_china_stock_data_async(self, stock_code: str, period_days: int,
                                             analysis_date: str) -> StockDataPreparationResult:
        """预获取A股数据（异步版本），包含数据库检查和自动同步"""
        logger.info(f"📊 [A股数据-异步] 开始准备{stock_code}的数据 (时长: {period_days}天)")

        # 计算日期范围
        end_date = parse_date_aware(analysis_date, to_config_tz=False)
        from app.core.config import settings
        lookback_days = getattr(settings, 'MARKET_ANALYST_LOOKBACK_DAYS', 365)
        extended_start_date = end_date - timedelta(days=lookback_days)  # ✅ aware - timedelta = aware
        extended_start_date_str = extended_start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')

        logger.info(f"📅 [A股数据-异步] 实际数据范围: {extended_start_date_str} 到 {end_date_str} ({lookback_days}天)")

        has_historical_data = False
        has_basic_info = False
        stock_name = "未知"
        cache_status = ""

        try:
            # 1. 检查数据库中的数据是否存在和最新
            logger.debug(f"📊 [A股数据-异步] 检查数据库中{stock_code}的数据...")
            db_check_result = self._check_database_data(stock_code, extended_start_date_str, end_date_str)

            # 2. 如果数据不存在或不是最新，自动触发同步（使用异步方法）
            if not db_check_result["has_data"] or not db_check_result["is_latest"]:
                logger.warning(f"⚠️ [A股数据-异步] 数据库数据不完整: {db_check_result['message']}")
                logger.info(f"🔄 [A股数据-异步] 自动触发数据同步: {stock_code}")

                # 🔥 使用异步方法同步数据
                sync_result = await self._trigger_data_sync_async(stock_code, extended_start_date_str, end_date_str)
                if sync_result["success"]:
                    logger.info(f"✅ [A股数据-异步] 数据同步成功: {sync_result['message']}")
                    cache_status += "数据已同步; "
                else:
                    logger.warning(f"⚠️ [A股数据-异步] 数据同步失败: {sync_result['message']}")
            else:
                logger.info(f"✅ [A股数据-异步] 数据库数据检查通过: {db_check_result['message']}")
                cache_status += "数据库数据最新; "

            # 3. 获取基本信息
            logger.debug(f"📊 [A股数据-异步] 获取{stock_code}基本信息...")
            from app.data.core.interface import DataInterface
            di = DataInterface.get_instance()
            info_result = await di.read("CN", stock_code, "basic_info")
            info_doc = info_result.get("data")

            if info_doc:
                name = info_doc.get("name", "") if isinstance(info_doc, dict) else ""
                if name and name != "未知" and not name.startswith(f"股票{stock_code}"):
                    stock_name = name
                    has_basic_info = True
                    logger.info(f"✅ [A股数据-异步] 基本信息获取成功: {stock_code} - {stock_name}")
                    cache_status += "基本信息已缓存; "

            # 4. 获取历史数据
            logger.debug(f"📊 [A股数据-异步] 获取{stock_code}历史数据...")
            quotes_result = await di.read("CN", stock_code, "daily_quotes",
                                          start_date=extended_start_date_str, end_date=end_date_str)
            quotes_data = quotes_result.get("data")

            if quotes_data and isinstance(quotes_data, list) and len(quotes_data) > 0:
                has_historical_data = True
                logger.info(f"✅ [A股数据-异步] 历史数据获取成功: {stock_code} ({len(quotes_data)}条)")
                cache_status += f"历史数据已缓存({lookback_days}天); "
            else:
                return StockDataPreparationResult(
                    is_valid=False,
                    stock_code=stock_code,
                    market_type="A股",
                    stock_name=stock_name,
                    has_basic_info=has_basic_info,
                    error_message=f"无法获取股票 {stock_code} 的历史数据",
                    suggestion="请检查网络连接或数据源配置，或稍后重试"
                )

            # 5. 数据准备成功
            logger.info(f"🎉 [A股数据-异步] 数据准备完成: {stock_code} - {stock_name}")
            return StockDataPreparationResult(
                is_valid=True,
                stock_code=stock_code,
                market_type="A股",
                stock_name=stock_name,
                has_historical_data=has_historical_data,
                has_basic_info=has_basic_info,
                data_period_days=lookback_days,
                cache_status=cache_status.rstrip('; ')
            )

        except Exception as e:
            logger.error(f"❌ [A股数据-异步] 数据准备失败: {e}")
            import traceback
            logger.debug(f"详细错误: {traceback.format_exc()}")
            return StockDataPreparationResult(
                is_valid=False,
                stock_code=stock_code,
                market_type="A股",
                stock_name=stock_name,
                has_basic_info=has_basic_info,
                has_historical_data=has_historical_data,
                error_message=f"数据准备失败: {str(e)}",
                suggestion="请检查网络连接或数据源配置"
            )

    def _check_database_data(self, stock_code: str, start_date: str, end_date: str) -> Dict:
        """
        检查数据库中的数据是否存在和最新

        Returns:
            Dict: {
                "has_data": bool,  # 是否有数据
                "is_latest": bool,  # 是否最新（包含最近交易日）
                "record_count": int,  # 记录数
                "latest_date": str,  # 最新数据日期
                "message": str  # 检查结果消息
            }
        """
        try:
            from app.data.core.interface import DataInterface

            async def _query():
                di = DataInterface.get_instance()
                result = await di.read("CN", stock_code, "daily_quotes",
                                       start_date=start_date, end_date=end_date)
                return result.get("data")

            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    records = pool.submit(asyncio.run, _query()).result()
            except RuntimeError:
                records = asyncio.run(_query())

            if not records or not isinstance(records, list) or len(records) == 0:
                return {
                    "has_data": False,
                    "is_latest": False,
                    "record_count": 0,
                    "latest_date": None,
                    "message": "数据库中没有数据"
                }

            record_count = len(records)

            # 获取最新数据日期
            latest_date = None
            for rec in reversed(records):
                td = rec.get("trade_date")
                if td:
                    latest_date = str(td)[:10]
                    break

            # 检查是否包含最近的交易日
            from datetime import timedelta
            today = now_utc()

            recent_trade_date = today
            for i in range(5):
                check_date = today - timedelta(days=i)
                if check_date.weekday() < 5:
                    recent_trade_date = check_date
                    break

            recent_trade_date_str = recent_trade_date.strftime('%Y-%m-%d')

            is_latest = False
            if latest_date:
                latest_dt = parse_date_aware(latest_date, to_config_tz=False)
                days_diff = (recent_trade_date - latest_dt).days
                is_latest = days_diff <= 1

            message = f"找到{record_count}条记录，最新日期: {latest_date}"
            if not is_latest:
                message += f"（需要更新到{recent_trade_date_str}）"

            return {
                "has_data": True,
                "is_latest": is_latest,
                "record_count": record_count,
                "latest_date": latest_date,
                "message": message
            }

        except Exception as e:
            logger.error(f"❌ [数据检查] 检查数据库数据失败: {e}")
            return {
                "has_data": False,
                "is_latest": False,
                "record_count": 0,
                "latest_date": None,
                "message": f"检查失败: {str(e)}"
            }

    def _trigger_data_sync_sync(self, stock_code: str, start_date: str, end_date: str) -> Dict:
        """
        触发数据同步（同步包装器）
        在同步上下文中调用异步同步方法

        🔥 兼容 asyncio.to_thread() 调用：
        - 如果在 asyncio.to_thread() 创建的线程中运行，创建新的事件循环
        - 避免 "attached to a different loop" 错误
        """
        import asyncio

        try:
            coro = self._trigger_data_sync_async(stock_code, start_date, end_date)

            try:
                asyncio.get_running_loop()
                logger.info("🔍 [数据同步] 检测到正在运行的事件循环，切换到独立线程执行异步同步任务")
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(asyncio.run, coro)
                    return future.result()
            except RuntimeError:
                return asyncio.run(coro)
        except Exception as e:
            logger.error(f"❌ [数据同步] 同步包装器失败: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"同步失败: {str(e)}",
                "synced_records": 0,
                "data_source": None
            }

    async def _trigger_data_sync_async(self, stock_code: str, start_date: str, end_date: str) -> Dict:
        """
        触发数据同步（异步版本，根据数据库配置的数据源优先级）
        同步内容包括：历史数据、财务数据、实时行情

        Returns:
            Dict: {
                "success": bool,
                "message": str,
                "synced_records": int,
                "data_source": str,  # 使用的数据源
                "historical_records": int,  # 历史数据记录数
                "financial_synced": bool,  # 财务数据是否同步成功
                "realtime_synced": bool  # 实时行情是否同步成功
            }
        """
        try:
            logger.info(f"🔄 [数据同步] 开始同步{stock_code}的数据（历史+财务+实时）...")

            # 1. 从数据库获取数据源优先级
            priority_order = self._get_data_source_priority_for_sync(stock_code)
            logger.info(f"📊 [数据同步] 数据源优先级: {priority_order}")

            # 2. 通过 DataInterface 同步
            try:
                from app.data.core.interface import DataInterface
                di = DataInterface.get_instance()

                domains = ["daily_quotes", "daily_indicators", "financial"]
                result = await di.refresh("CN", stock_code, domains=domains, force=True, timeout=60)

                historical_records = 0
                financial_synced = False
                realtime_synced = False

                for domain, dr in result.domains.items():
                    if dr.status in ("refreshed", "fresh"):
                        historical_records += dr.record_count
                    if "financial" in domain and dr.status in ("refreshed", "fresh"):
                        financial_synced = True

                # 实时行情
                try:
                    rt_result = await di.refresh("CN", stock_code, domains=["market_quotes"], force=True)
                    rt_domain = rt_result.domains.get("market_quotes")
                    realtime_synced = rt_domain is not None and rt_domain.status in ("refreshed", "fresh")
                except Exception as e:
                    logger.warning(f"⚠️ [数据同步] 实时行情同步异常: {e}")

                if historical_records > 0:
                    message = f"同步成功: {historical_records}条记录"
                    if financial_synced:
                        message += ", 财务数据✓"
                    if realtime_synced:
                        message += ", 实时行情✓"

                    logger.info(f"✅ [数据同步] {message}")
                    return {
                        "success": True,
                        "message": message,
                        "synced_records": historical_records,
                        "data_source": "orchestrator",
                        "historical_records": historical_records,
                        "financial_synced": financial_synced,
                        "realtime_synced": realtime_synced
                    }
                else:
                    last_error = "编排器同步失败: 无记录"
                    logger.warning(f"⚠️ [数据同步] {last_error}")

            except Exception as e:
                last_error = f"编排器异常: {str(e)}"
                logger.warning(f"⚠️ [数据同步] {last_error}")

            # 同步失败
            message = f"数据同步失败: {last_error}"
            logger.error(f"❌ [数据同步] {message}")
            return {
                "success": False,
                "message": message,
                "synced_records": 0,
                "data_source": None,
                "historical_records": 0,
                "financial_synced": False,
                "realtime_synced": False
            }

        except Exception as e:
            logger.error(f"❌ [数据同步] 同步数据失败: {e}")
            import traceback
            logger.debug(f"详细错误: {traceback.format_exc()}")
            return {
                "success": False,
                "message": f"同步失败: {str(e)}",
                "synced_records": 0,
                "data_source": None,
                "historical_records": 0,
                "financial_synced": False,
                "realtime_synced": False
            }

    def _get_data_source_priority_for_sync(self, stock_code: str) -> list:
        """
        获取数据源优先级（用于同步）

        Returns:
            list: 数据源列表，按优先级排序 ['tushare', 'akshare', 'baostock']
        """
        try:
            from app.data.core.interface import DataInterface

            async def _get_priority():
                di = DataInterface.get_instance()
                config = await di.get_config("CN", "daily_quotes")
                if config and "sources" in config:
                    return config["sources"]
                return None

            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    priority_order = pool.submit(asyncio.run, _get_priority()).result()
            except RuntimeError:
                priority_order = asyncio.run(_get_priority())

            if priority_order:
                logger.info(f"✅ [数据源优先级] 从数据库获取: {priority_order}")
                return priority_order
            else:
                logger.warning(f"⚠️ [数据源优先级] 未找到配置，使用默认顺序")
                return ['tushare', 'akshare', 'baostock']

        except Exception as e:
            logger.error(f"❌ [数据源优先级] 获取失败: {e}")
            return ['tushare', 'akshare', 'baostock']

    def _prepare_hk_stock_data(self, stock_code: str, period_days: int,
                              analysis_date: str) -> StockDataPreparationResult:
        """预获取港股数据"""
        logger.info(f"📊 [港股数据] 开始准备{stock_code}的数据 (时长: {period_days}天)")

        # 标准化港股代码格式
        if not stock_code.upper().endswith('.HK'):
            # 移除前导0，然后补齐到4位
            clean_code = stock_code.lstrip('0')
            if not clean_code:
                # 全零代码（如 "00000"），可能是无效输入
                logger.warning(f"⚠️ [港股数据] 疑似无效的全零代码: {stock_code}，保留原始值")
                clean_code = stock_code
            formatted_code = f"{clean_code.zfill(4)}.HK"
            logger.debug(f"🔍 [港股数据] 代码格式化: {stock_code} → {formatted_code}")
        else:
            formatted_code = stock_code.upper()

        # 计算日期范围
        end_date = parse_date_aware(analysis_date, to_config_tz=False)
        start_date = end_date - timedelta(days=period_days)  # ✅ aware - timedelta = aware
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')

        logger.debug(f"📅 [港股数据] 日期范围: {start_date_str} → {end_date_str}")

        has_historical_data = False
        has_basic_info = False
        stock_name = "未知"
        cache_status = ""

        try:
            # 1. 获取基本信息
            logger.debug(f"📊 [港股数据] 获取{formatted_code}基本信息...")
            from app.data.core.interface import DataInterface

            hk_code = formatted_code.replace(".HK", "").zfill(4)

            async def _get_hk_info():
                di = DataInterface.get_instance()
                return await di.read("HK", hk_code, "basic_info")

            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    info_result = pool.submit(asyncio.run, _get_hk_info()).result()
            except RuntimeError:
                info_result = asyncio.run(_get_hk_info())

            info_doc = info_result.get("data") if info_result else None

            if info_doc:
                name = info_doc.get("name", "") if isinstance(info_doc, dict) else ""
                if name and name != "未知":
                    stock_name = name
                    has_basic_info = True
                    logger.info(f"✅ [港股数据] 基本信息获取成功: {formatted_code} - {stock_name}")
                    cache_status += "基本信息已缓存; "
                else:
                    logger.warning(f"⚠️ [港股数据] 基本信息无效: {formatted_code}")
                    return StockDataPreparationResult(
                        is_valid=False,
                        stock_code=formatted_code,
                        market_type="港股",
                        error_message=f"港股代码 {formatted_code} 不存在或信息无效",
                        suggestion="请检查港股代码是否正确，格式如：0700.HK"
                    )
            else:
                logger.warning(f"⚠️ [港股数据] 无法获取基本信息: {formatted_code}")
                return StockDataPreparationResult(
                    is_valid=False,
                    stock_code=formatted_code,
                    market_type="港股",
                    error_message=f"港股代码 {formatted_code} 可能不存在或数据源暂时不可用",
                    suggestion="请检查港股代码是否正确，格式如：0700.HK，或稍后重试"
                )

            # 2. 获取历史数据
            logger.debug(f"📊 [港股数据] 获取{formatted_code}历史数据 ({start_date_str} 到 {end_date_str})...")

            async def _get_hk_quotes():
                di = DataInterface.get_instance()
                return await di.read("HK", hk_code, "daily_quotes",
                                     start_date=start_date_str, end_date=end_date_str)

            try:
                loop = asyncio.get_running_loop()
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    quotes_result = pool.submit(asyncio.run, _get_hk_quotes()).result()
            except RuntimeError:
                quotes_result = asyncio.run(_get_hk_quotes())

            quotes_data = quotes_result.get("data") if quotes_result else None

            if quotes_data and isinstance(quotes_data, list) and len(quotes_data) > 0:
                has_historical_data = True
                logger.info(f"✅ [港股数据] 历史数据获取成功: {formatted_code} ({len(quotes_data)}条)")
                cache_status += f"历史数据已缓存({period_days}天); "
            else:
                logger.warning(f"⚠️ [港股数据] 无法获取历史数据: {formatted_code}")
                return StockDataPreparationResult(
                    is_valid=False,
                    stock_code=formatted_code,
                    market_type="港股",
                    stock_name=stock_name,
                    has_basic_info=has_basic_info,
                    error_message=f"无法获取港股 {formatted_code} 的历史数据",
                    suggestion="数据源可能暂时不可用，请稍后重试或联系技术支持"
                )

            # 3. 数据准备成功
            logger.info(f"🎉 [港股数据] 数据准备完成: {formatted_code} - {stock_name}")
            return StockDataPreparationResult(
                is_valid=True,
                stock_code=formatted_code,
                market_type="港股",
                stock_name=stock_name,
                has_historical_data=has_historical_data,
                has_basic_info=has_basic_info,
                data_period_days=period_days,
                cache_status=cache_status.rstrip('; ')
            )

        except Exception as e:
            logger.error(f"❌ [港股数据] 数据准备失败: {e}")
            return StockDataPreparationResult(
                is_valid=False,
                stock_code=formatted_code,
                market_type="港股",
                stock_name=stock_name,
                has_basic_info=has_basic_info,
                has_historical_data=has_historical_data,
                error_message=f"数据准备失败: {str(e)}",
                suggestion="请检查网络连接或数据源配置"
            )

    def _prepare_us_stock_data(self, stock_code: str, period_days: int,
                              analysis_date: str) -> StockDataPreparationResult:
        """预获取美股数据"""
        logger.info(f"📊 [美股数据] 开始准备{stock_code}的数据 (时长: {period_days}天)")

        # 标准化美股代码格式
        formatted_code = stock_code.upper()

        # 计算日期范围
        end_date = parse_date_aware(analysis_date, to_config_tz=False)
        start_date = end_date - timedelta(days=period_days)  # ✅ aware - timedelta = aware
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')

        logger.debug(f"📅 [美股数据] 日期范围: {start_date_str} → {end_date_str}")

        has_historical_data = False
        has_basic_info = False
        stock_name = formatted_code  # 美股通常使用代码作为名称
        cache_status = ""

        try:
            # 1. 获取历史数据（美股通常直接通过历史数据验证股票是否存在）
            logger.debug(f"📊 [美股数据] 获取{formatted_code}历史数据 ({start_date_str} 到 {end_date_str})...")

            # 通过新架构获取美股数据
            try:
                _stock_data = _get_stock_data_sync("US", formatted_code, start_date_str, end_date_str)
                historical_data = _stock_data
            except Exception:
                historical_data = None

            if historical_data and "❌" not in historical_data and "错误" not in historical_data and "无法获取" not in historical_data:
                # 更宽松的数据有效性检查
                data_indicators = [
                    "开盘价", "收盘价", "最高价", "最低价", "成交量",
                    "Open", "Close", "High", "Low", "Volume",
                    "日期", "Date", "时间", "Time"
                ]

                has_valid_data = (
                    len(historical_data) > 50 and  # 降低长度要求
                    any(indicator in historical_data for indicator in data_indicators)
                )

                if has_valid_data:
                    has_historical_data = True
                    has_basic_info = True  # 美股通常不单独获取基本信息
                    logger.info(f"✅ [美股数据] 历史数据获取成功: {formatted_code} ({period_days}天)")
                    cache_status = f"历史数据已缓存({period_days}天)"

                    # 数据准备成功
                    logger.info(f"🎉 [美股数据] 数据准备完成: {formatted_code}")
                    return StockDataPreparationResult(
                        is_valid=True,
                        stock_code=formatted_code,
                        market_type="美股",
                        stock_name=stock_name,
                        has_historical_data=has_historical_data,
                        has_basic_info=has_basic_info,
                        data_period_days=period_days,
                        cache_status=cache_status
                    )
                else:
                    logger.warning(f"⚠️ [美股数据] 历史数据无效: {formatted_code}")
                    logger.debug(f"🔍 [美股数据] 数据内容预览: {historical_data[:200]}...")
                    return StockDataPreparationResult(
                        is_valid=False,
                        stock_code=formatted_code,
                        market_type="美股",
                        error_message=f"美股 {formatted_code} 的历史数据无效或不足",
                        suggestion="该股票可能为新上市股票或数据源暂时不可用，请稍后重试"
                    )
            else:
                logger.warning(f"⚠️ [美股数据] 无法获取历史数据: {formatted_code}")
                return StockDataPreparationResult(
                    is_valid=False,
                    stock_code=formatted_code,
                    market_type="美股",
                    error_message=f"美股代码 {formatted_code} 不存在或无法获取数据",
                    suggestion="请检查美股代码是否正确，如：AAPL、TSLA、MSFT"
                )

        except Exception as e:
            logger.error(f"❌ [美股数据] 数据准备失败: {e}")
            return StockDataPreparationResult(
                is_valid=False,
                stock_code=formatted_code,
                market_type="美股",
                error_message=f"数据准备失败: {str(e)}",
                suggestion="请检查网络连接或数据源配置"
            )




# 全局数据准备器实例
_stock_preparer = None

def get_stock_preparer(default_period_days: int = 30) -> StockDataPreparer:
    """获取股票数据准备器实例（单例模式）"""
    global _stock_preparer
    if _stock_preparer is None:
        _stock_preparer = StockDataPreparer(default_period_days)
    return _stock_preparer


def prepare_stock_data(stock_code: str, market_type: str = "auto",
                      period_days: int = None, analysis_date: str = None) -> StockDataPreparationResult:
    """
    便捷函数：预获取和验证股票数据

    Args:
        stock_code: 股票代码
        market_type: 市场类型 ("A股", "港股", "美股", "auto")
        period_days: 历史数据时长（天），默认30天
        analysis_date: 分析日期，默认为今天

    Returns:
        StockDataPreparationResult: 数据准备结果
    """
    preparer = get_stock_preparer()
    return preparer.prepare_stock_data(stock_code, market_type, period_days, analysis_date)


def is_stock_data_ready(stock_code: str, market_type: str = "auto",
                       period_days: int = None, analysis_date: str = None) -> bool:
    """
    便捷函数：检查股票数据是否准备就绪

    Args:
        stock_code: 股票代码
        market_type: 市场类型 ("A股", "港股", "美股", "auto")
        period_days: 历史数据时长（天），默认30天
        analysis_date: 分析日期，默认为今天

    Returns:
        bool: 数据是否准备就绪
    """
    result = prepare_stock_data(stock_code, market_type, period_days, analysis_date)
    return result.is_valid


def get_stock_preparation_message(stock_code: str, market_type: str = "auto",
                                 period_days: int = None, analysis_date: str = None) -> str:
    """
    便捷函数：获取股票数据准备消息

    Args:
        stock_code: 股票代码
        market_type: 市场类型 ("A股", "港股", "美股", "auto")
        period_days: 历史数据时长（天），默认30天
        analysis_date: 分析日期，默认为今天

    Returns:
        str: 数据准备消息
    """
    result = prepare_stock_data(stock_code, market_type, period_days, analysis_date)

    if result.is_valid:
        return f"✅ 数据准备成功: {result.stock_code} ({result.market_type}) - {result.stock_name}\n📊 {result.cache_status}"
    else:
        return f"❌ 数据准备失败: {result.error_message}\n💡 建议: {result.suggestion}"


async def prepare_stock_data_async(stock_code: str, market_type: str = "auto",
                                   period_days: int = None, analysis_date: str = None) -> StockDataPreparationResult:
    """
    异步版本：预获取和验证股票数据

    🔥 专门用于 FastAPI 异步上下文，避免事件循环冲突

    Args:
        stock_code: 股票代码
        market_type: 市场类型 ("A股", "港股", "美股", "auto")
        period_days: 历史数据时长（天），默认30天
        analysis_date: 分析日期，默认为今天

    Returns:
        StockDataPreparationResult: 数据准备结果
    """
    preparer = get_stock_preparer()

    # 使用异步版本的内部方法
    if period_days is None:
        period_days = preparer.default_period_days

    if analysis_date is None:
        analysis_date = get_current_date()

    logger.info(f"📊 [数据准备-异步] 开始准备股票数据: {stock_code} (市场: {market_type}, 时长: {period_days}天)")

    # 1. 基本格式验证（同步操作）
    format_result = preparer._validate_format(stock_code, market_type)
    if not format_result.is_valid:
        return format_result

    # 2. 自动检测市场类型
    if market_type == "auto":
        market_type = preparer._detect_market_type(stock_code)
        logger.debug(f"📊 [数据准备-异步] 自动检测市场类型: {market_type}")

    # 3. 预获取数据并验证（使用异步版本）
    return await preparer._prepare_data_by_market_async(stock_code, market_type, period_days, analysis_date)


# 保持向后兼容的别名
StockValidator = StockDataPreparer
get_stock_validator = get_stock_preparer
validate_stock_exists = prepare_stock_data
is_stock_valid = is_stock_data_ready
get_stock_validation_message = get_stock_preparation_message
