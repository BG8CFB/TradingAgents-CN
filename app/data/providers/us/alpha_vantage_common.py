"""
Alpha Vantage API 公共模块

提供 Alpha Vantage API 的通用请求功能，包括：
- API 请求封装
- 错误处理和重试
- 速率限制处理
- 响应解析

参考原版 TradingAgents 实现
"""

import os
import time
import json
import requests
from typing import Dict, Any, Optional
from datetime import datetime
from app.utils.time_utils import now_utc, now_config_tz, format_date_short, format_date_compact, format_iso

# 导入日志模块
from app.utils.logging_manager import get_logger
logger = get_logger('agents')


class AlphaVantageRateLimitError(Exception):
    """Alpha Vantage 速率限制错误"""
    pass


class AlphaVantageAPIError(Exception):
    """Alpha Vantage API 错误"""
    pass


def _get_api_key_from_database() -> Optional[str]:
    """
    从数据库读取 Alpha Vantage API Key

    优先级：数据库配置 > 环境变量
    这样用户在 Web 后台修改配置后可以立即生效

    Returns:
        Optional[str]: API Key，如果未找到返回 None
    """
    try:
        logger.debug("🔍 [DB查询] 开始从数据库读取 Alpha Vantage API Key...")
        from app.core.database import get_mongo_db_sync
        db = get_mongo_db_sync()
        config_collection = db.system_configs

        # 获取最新的激活配置
        logger.debug("🔍 [DB查询] 查询 is_active=True 的配置...")
        config_data = config_collection.find_one(
            {"is_active": True},
            sort=[("version", -1)]
        )

        if config_data:
            logger.debug(f"✅ [DB查询] 找到激活配置，版本: {config_data.get('version')}")
            if config_data.get('data_source_configs'):
                logger.debug(f"✅ [DB查询] 配置中有 {len(config_data['data_source_configs'])} 个数据源")
                for ds_config in config_data['data_source_configs']:
                    ds_type = ds_config.get('type')
                    logger.debug(f"🔍 [DB查询] 检查数据源: {ds_type}")
                    if ds_type == 'alpha_vantage':
                        api_key = ds_config.get('api_key')
                        logger.debug(f"✅ [DB查询] 找到 Alpha Vantage 配置，api_key 长度: {len(api_key) if api_key else 0}")
                        if api_key and not api_key.startswith("your_"):
                            logger.debug(f"✅ [DB查询] API Key 有效 (长度: {len(api_key)})")
                            return api_key
                        else:
                            logger.debug(f"⚠️ [DB查询] API Key 无效或为占位符")
            else:
                logger.debug("⚠️ [DB查询] 配置中没有 data_source_configs")
        else:
            logger.debug("⚠️ [DB查询] 未找到激活的配置")

        logger.debug("⚠️ [DB查询] 数据库中未找到有效的 Alpha Vantage API Key")
    except Exception as e:
        logger.debug(f"❌ [DB查询] 从数据库读取 API Key 失败: {e}")

    return None


def get_api_key() -> str:
    """
    获取 Alpha Vantage API Key

    优先级：
    1. 数据库配置（system_configs 集合）
    2. 环境变量 ALPHA_VANTAGE_API_KEY
    3. 配置文件

    Returns:
        str: API Key

    Raises:
        ValueError: 如果未配置 API Key
    """
    # 1. 从数据库获取（最高优先级）
    logger.debug("🔍 [步骤1] 开始从数据库读取 Alpha Vantage API Key...")
    db_api_key = _get_api_key_from_database()
    if db_api_key:
        logger.debug(f"✅ [步骤1] 数据库中找到 API Key (长度: {len(db_api_key)})")
        return db_api_key
    else:
        logger.debug("⚠️ [步骤1] 数据库中未找到 API Key")

    # 2. 从环境变量获取
    logger.debug("🔍 [步骤2] 读取 .env 中的 API Key...")
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if api_key:
        logger.debug(f"✅ [步骤2] .env 中找到 API Key (长度: {len(api_key)})")
        return api_key
    else:
        logger.debug("⚠️ [步骤2] .env 中未找到 API Key")

    # 3. 从配置文件获取
    logger.debug("🔍 [步骤3] 读取配置文件中的 API Key...")
    try:
        from app.engine.config.config_manager import ConfigManager
        config_manager = ConfigManager()
        api_key = config_manager.get("ALPHA_VANTAGE_API_KEY")
        if api_key:
            logger.debug(f"✅ [步骤3] 配置文件中找到 API Key (长度: {len(api_key)})")
            return api_key
    except Exception as e:
        logger.debug(f"⚠️ [步骤3] 无法从配置文件获取 Alpha Vantage API Key: {e}")

    # 所有方式都失败
    raise ValueError(
        "❌ Alpha Vantage API Key 未配置！\n"
        "请通过以下任一方式配置：\n"
        "1. Web 后台配置（推荐）: http://localhost:3000/api/config/datasource\n"
        "2. 设置环境变量: ALPHA_VANTAGE_API_KEY\n"
        "3. 在配置文件中配置\n"
        "获取 API Key: https://www.alphavantage.co/support/#api-key"
    )

    return api_key


def format_datetime_for_api(date_str: str) -> str:
    """
    格式化日期时间为 Alpha Vantage API 要求的格式
    
    Args:
        date_str: 日期字符串，格式 YYYY-MM-DD
        
    Returns:
        格式化后的日期时间字符串，格式 YYYYMMDDTHHMM
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%Y%m%dT0000")
    except Exception as e:
        logger.warning(f"⚠️ 日期格式化失败 {date_str}: {e}，使用原始值")
        return date_str


def _make_api_request(
    function: str,
    params: Dict[str, Any],
    max_retries: int = 3,
    retry_delay: int = 2
) -> Dict[str, Any] | str:
    """
    发起 Alpha Vantage API 请求
    
    Args:
        function: API 函数名（如 NEWS_SENTIMENT, OVERVIEW 等）
        params: 请求参数字典
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）
        
    Returns:
        API 响应的 JSON 数据或错误信息字符串
        
    Raises:
        AlphaVantageRateLimitError: 速率限制错误
        AlphaVantageAPIError: API 错误
    """
    api_key = get_api_key()
    base_url = "https://www.alphavantage.co/query"
    
    # 构建请求参数
    request_params = {
        "function": function,
        "apikey": api_key,
        **params
    }
    
    logger.debug(f"📡 [Alpha Vantage] 请求 {function}: {params}")
    
    for attempt in range(max_retries):
        try:
            # 发起请求
            response = requests.get(base_url, params=request_params, timeout=30)
            response.raise_for_status()
            
            # 解析响应
            data = response.json()
            
            # 检查错误信息
            if "Error Message" in data:
                error_msg = data["Error Message"]
                logger.error(f"❌ [Alpha Vantage] API 错误: {error_msg}")
                raise AlphaVantageAPIError(f"Alpha Vantage API Error: {error_msg}")
            
            # 检查速率限制
            if "Note" in data and "API call frequency" in data["Note"]:
                logger.warning(f"⚠️ [Alpha Vantage] 速率限制: {data['Note']}")
                
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (attempt + 1)
                    logger.info(f"⏳ 等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise AlphaVantageRateLimitError(
                        "Alpha Vantage API rate limit exceeded. "
                        "Please wait a moment and try again, or upgrade your API plan."
                    )
            
            # 检查信息字段（可能包含限制提示）
            if "Information" in data:
                info_msg = data["Information"]
                logger.warning(f"⚠️ [Alpha Vantage] 信息: {info_msg}")
                
                # 如果是速率限制信息
                if "premium" in info_msg.lower() or "limit" in info_msg.lower():
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (attempt + 1)
                        logger.info(f"⏳ 等待 {wait_time} 秒后重试...")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise AlphaVantageRateLimitError(
                            f"Alpha Vantage API limit: {info_msg}"
                        )
            
            # 成功获取数据
            logger.debug(f"✅ [Alpha Vantage] 请求成功: {function}")
            return data
            
        except requests.exceptions.Timeout:
            logger.warning(f"⚠️ [Alpha Vantage] 请求超时 (尝试 {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            else:
                raise AlphaVantageAPIError("Alpha Vantage API request timeout")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ [Alpha Vantage] 请求失败: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            else:
                raise AlphaVantageAPIError(f"Alpha Vantage API request failed: {e}")
        
        except json.JSONDecodeError as e:
            logger.error(f"❌ [Alpha Vantage] JSON 解析失败: {e}")
            raise AlphaVantageAPIError(f"Failed to parse Alpha Vantage API response: {e}")
    
    # 所有重试都失败
    raise AlphaVantageAPIError(f"Failed to get data from Alpha Vantage after {max_retries} attempts")


def format_response_as_string(data: Dict[str, Any], title: str = "Alpha Vantage Data") -> str:
    """
    将 API 响应格式化为字符串
    
    Args:
        data: API 响应数据
        title: 数据标题
        
    Returns:
        格式化后的字符串
    """
    try:
        # 添加头部信息
        header = f"# {title}\n"
        header += f"# Data retrieved on: {now_utc().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        # 转换为 JSON 字符串（格式化）
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        
        return header + json_str
        
    except Exception as e:
        logger.error(f"❌ 格式化响应失败: {e}")
        return str(data)


def check_api_key_valid() -> bool:
    """
    检查 Alpha Vantage API Key 是否有效
    
    Returns:
        True 如果 API Key 有效，否则 False
    """
    try:
        # 使用简单的 API 调用测试
        data = _make_api_request("GLOBAL_QUOTE", {"symbol": "IBM"})
        
        # 检查是否有错误
        if isinstance(data, dict) and "Global Quote" in data:
            logger.info("✅ Alpha Vantage API Key 有效")
            return True
        else:
            logger.warning("⚠️ Alpha Vantage API Key 可能无效")
            return False
            
    except Exception as e:
        logger.error(f"❌ Alpha Vantage API Key 验证失败: {e}")
        return False

