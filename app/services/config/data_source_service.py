"""
数据源分组与连接测试服务
"""

import time
import logging
import os
from typing import List, Dict, Any, Optional

from app.core.database import get_mongo_db
from app.models.config import (
    DataSourceConfig, DataSourceGrouping
)
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)


class DataSourceService:
    """数据源分组管理与连接测试"""

    def __init__(self, db_manager=None):
        self.db = None
        self.db_manager = db_manager

    async def _get_db(self):
        """获取数据库连接"""
        if self.db is None:
            if self.db_manager and self.db_manager.mongo_db is not None:
                self.db = self.db_manager.mongo_db
            else:
                self.db = get_mongo_db()
        return self.db

    # ==================== 数据源分组管理 ====================

    async def get_datasource_groupings(self) -> List[DataSourceGrouping]:
        """获取所有数据源分组关系"""
        try:
            db = await self._get_db()
            groupings_collection = db.datasource_groupings

            groupings_data = await groupings_collection.find({}).to_list(length=None)
            return [DataSourceGrouping(**data) for data in groupings_data]
        except Exception as e:
            print(f"❌ 获取数据源分组关系失败: {e}")
            return []

    async def add_datasource_to_category(self, grouping: DataSourceGrouping) -> bool:
        """将数据源添加到分类"""
        try:
            db = await self._get_db()
            groupings_collection = db.datasource_groupings

            # 检查是否已存在
            existing = await groupings_collection.find_one({
                "data_source_name": grouping.data_source_name,
                "market_category_id": grouping.market_category_id
            })
            if existing:
                return False

            await groupings_collection.insert_one(grouping.model_dump())
            return True
        except Exception as e:
            print(f"❌ 添加数据源到分类失败: {e}")
            return False

    async def remove_datasource_from_category(self, data_source_name: str, category_id: str) -> bool:
        """从分类中移除数据源"""
        try:
            db = await self._get_db()
            groupings_collection = db.datasource_groupings

            result = await groupings_collection.delete_one({
                "data_source_name": data_source_name,
                "market_category_id": category_id
            })
            return result.deleted_count > 0
        except Exception as e:
            print(f"❌ 从分类中移除数据源失败: {e}")
            return False

    async def update_datasource_grouping(self, data_source_name: str, category_id: str, updates: Dict[str, Any]) -> bool:
        """更新数据源分组关系

        🔥 重要：同时更新 datasource_groupings 和 system_configs 两个集合
        - datasource_groupings: 用于前端展示和管理
        - system_configs.data_source_configs: 用于实际数据获取时的优先级判断
        """
        try:
            db = await self._get_db()
            groupings_collection = db.datasource_groupings
            config_collection = db.system_configs

            # 1. 更新 datasource_groupings 集合
            updates["updated_at"] = now_tz()
            result = await groupings_collection.update_one(
                {
                    "data_source_name": data_source_name,
                    "market_category_id": category_id
                },
                {"$set": updates}
            )

            # 2. 🔥 如果更新了优先级，同步更新 system_configs 集合
            if "priority" in updates and result.modified_count > 0:
                # 获取当前激活的配置
                config_data = await config_collection.find_one(
                    {"is_active": True},
                    sort=[("version", -1)]
                )

                if config_data:
                    data_source_configs = config_data.get("data_source_configs", [])

                    # 查找并更新对应的数据源配置
                    updated = False
                    for ds_config in data_source_configs:
                        if (ds_config.get("name") == data_source_name or
                            ds_config.get("type") == data_source_name.lower()):
                            ds_config["priority"] = updates["priority"]
                            updated = True
                            logger.info(f"✅ [优先级同步] 更新 system_configs 中的数据源: {data_source_name}, 新优先级: {updates['priority']}")
                            break

                    if updated:
                        # 更新配置版本
                        version = config_data.get("version", 0)
                        await config_collection.update_one(
                            {"_id": config_data["_id"]},
                            {
                                "$set": {
                                    "data_source_configs": data_source_configs,
                                    "version": version + 1,
                                    "updated_at": now_tz()
                                }
                            }
                        )
                        logger.info(f"✅ [优先级同步] system_configs 版本更新: {version} -> {version + 1}")
                    else:
                        logger.warning(f"⚠️ [优先级同步] 未找到匹配的数据源配置: {data_source_name}")

            return result.modified_count > 0
        except Exception as e:
            logger.error(f"❌ 更新数据源分组关系失败: {e}")
            return False

    async def update_category_datasource_order(self, category_id: str, ordered_datasources: List[Dict[str, Any]]) -> bool:
        """更新分类中数据源的排序

        🔥 重要：同时更新 datasource_groupings 和 system_configs 两个集合
        - datasource_groupings: 用于前端展示和管理
        - system_configs.data_source_configs: 用于实际数据获取时的优先级判断
        """
        try:
            db = await self._get_db()
            groupings_collection = db.datasource_groupings
            config_collection = db.system_configs

            # 1. 批量更新 datasource_groupings 集合中的优先级
            for item in ordered_datasources:
                await groupings_collection.update_one(
                    {
                        "data_source_name": item["name"],
                        "market_category_id": category_id
                    },
                    {
                        "$set": {
                            "priority": item["priority"],
                            "updated_at": now_tz()
                        }
                    }
                )

            # 2. 🔥 同步更新 system_configs 集合中的 data_source_configs
            # 获取当前激活的配置
            config_data = await config_collection.find_one(
                {"is_active": True},
                sort=[("version", -1)]
            )

            if config_data:
                # 构建数据源名称到优先级的映射
                priority_map = {item["name"]: item["priority"] for item in ordered_datasources}

                # 更新 data_source_configs 中对应数据源的优先级
                data_source_configs = config_data.get("data_source_configs", [])
                updated = False

                for ds_config in data_source_configs:
                    ds_name = ds_config.get("name")
                    if ds_name in priority_map:
                        ds_config["priority"] = priority_map[ds_name]
                        updated = True
                        print(f"📊 [优先级同步] 更新数据源 {ds_name} 的优先级为 {priority_map[ds_name]}")

                # 如果有更新，保存回数据库
                if updated:
                    await config_collection.update_one(
                        {"_id": config_data["_id"]},
                        {
                            "$set": {
                                "data_source_configs": data_source_configs,
                                "updated_at": now_tz(),
                                "version": config_data.get("version", 0) + 1
                            }
                        }
                    )
                    print(f"✅ [优先级同步] 已同步更新 system_configs 集合，新版本: {config_data.get('version', 0) + 1}")
                else:
                    print(f"⚠️ [优先级同步] 没有找到需要更新的数据源配置")
            else:
                print(f"⚠️ [优先级同步] 未找到激活的系统配置")

            return True
        except Exception as e:
            print(f"❌ 更新分类数据源排序失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    # ==================== 数据源连接测试 ====================

    def _truncate_api_key(self, api_key: str, prefix_len: int = 6, suffix_len: int = 6) -> str:
        """
        截断 API Key 用于显示

        Args:
            api_key: 完整的 API Key
            prefix_len: 保留前缀长度
            suffix_len: 保留后缀长度

        Returns:
            截断后的 API Key，例如：0f229a...c550ec
        """
        if not api_key or len(api_key) <= prefix_len + suffix_len:
            return api_key

        return f"{api_key[:prefix_len]}...{api_key[-suffix_len:]}"

    async def test_data_source_config(self, ds_config: DataSourceConfig, system_config_getter=None) -> Dict[str, Any]:
        """测试数据源配置 - 真实调用API进行验证

        Args:
            ds_config: 数据源配置
            system_config_getter: 可选的异步回调，用于获取系统配置（避免循环依赖）
        """
        start_time = time.time()
        try:
            import requests

            ds_type = ds_config.type.value if hasattr(ds_config.type, 'value') else str(ds_config.type)

            logger.info(f"🧪 [TEST] Testing data source config: {ds_config.name} ({ds_type})")

            # 🔥 优先使用配置中的 API Key，如果没有或被截断，则从数据库获取
            api_key = ds_config.api_key
            used_db_credentials = False
            used_env_credentials = False

            logger.info(f"🔍 [TEST] Received API Key from config (type: {type(api_key).__name__}, length: {len(api_key) if api_key else 0})")

            # 根据不同的数据源类型进行测试
            if ds_type == "tushare":
                # 🔥 如果配置中的 API Key 包含 "..."（截断标记），需要验证是否是未修改的原值
                if api_key and "..." in api_key:
                    logger.info(f"🔍 [TEST] API Key contains '...' (truncated), checking if it matches database value")

                    # 从数据库中获取完整的 API Key
                    system_config = None
                    if system_config_getter:
                        system_config = await system_config_getter()
                    else:
                        system_config = await self._get_system_config_from_db()

                    db_config = None
                    if system_config:
                        for ds in system_config.data_source_configs:
                            if ds.name == ds_config.name:
                                db_config = ds
                                break

                    if db_config and db_config.api_key:
                        # 对数据库中的完整 API Key 进行相同的截断处理
                        truncated_db_key = self._truncate_api_key(db_config.api_key)
                        logger.info(f"🔍 [TEST] Database API Key truncated: {truncated_db_key}")
                        logger.info(f"🔍 [TEST] Received API Key: {api_key}")

                        # 比较截断后的值
                        if api_key == truncated_db_key:
                            # 相同，说明用户没有修改，使用数据库中的完整值
                            api_key = db_config.api_key
                            used_db_credentials = True
                            logger.info(f"✅ [TEST] Truncated values match, using complete API Key from database (length: {len(api_key)})")
                        else:
                            # 不同，说明用户修改了但修改得不完整
                            logger.error(f"❌ [TEST] Truncated API Key doesn't match database value, user may have modified it incorrectly")
                            return {
                                "success": False,
                                "message": "API Key 格式错误：检测到截断标记但与数据库中的值不匹配，请输入完整的 API Key",
                                "response_time": time.time() - start_time,
                                "details": {
                                    "error": "truncated_key_mismatch",
                                    "received": api_key,
                                    "expected": truncated_db_key
                                }
                            }
                    else:
                        # 数据库中没有有效的 API Key，尝试从环境变量获取
                        logger.info(f"⚠️  [TEST] No valid API Key in database, trying environment variable")
                        env_token = os.getenv('TUSHARE_TOKEN')
                        if env_token:
                            api_key = env_token.strip().strip('"').strip("'")
                            used_env_credentials = True
                            logger.info(f"🔑 [TEST] Using TUSHARE_TOKEN from environment (length: {len(api_key)})")
                        else:
                            logger.error(f"❌ [TEST] No valid API Key in database or environment")
                            return {
                                "success": False,
                                "message": "API Key 无效：数据库和环境变量中均未配置有效的 Token",
                                "response_time": time.time() - start_time,
                                "details": None
                            }

                # 如果 API Key 为空，尝试从数据库或环境变量获取
                elif not api_key:
                    logger.info(f"⚠️  [TEST] API Key is empty, trying to get from database")

                    # 从数据库中获取完整的 API Key
                    system_config = None
                    if system_config_getter:
                        system_config = await system_config_getter()
                    else:
                        system_config = await self._get_system_config_from_db()

                    db_config = None
                    if system_config:
                        for ds in system_config.data_source_configs:
                            if ds.name == ds_config.name:
                                db_config = ds
                                break

                    if db_config and db_config.api_key and "..." not in db_config.api_key:
                        api_key = db_config.api_key
                        used_db_credentials = True
                        logger.info(f"🔑 [TEST] Using API Key from database (length: {len(api_key)})")
                    else:
                        # 如果数据库中也没有，尝试从环境变量获取
                        logger.info(f"⚠️  [TEST] No valid API Key in database, trying environment variable")
                        env_token = os.getenv('TUSHARE_TOKEN')
                        if env_token:
                            api_key = env_token.strip().strip('"').strip("'")
                            used_env_credentials = True
                            logger.info(f"🔑 [TEST] Using TUSHARE_TOKEN from environment (length: {len(api_key)})")
                        else:
                            logger.error(f"❌ [TEST] No valid API Key in config, database, or environment")
                            return {
                                "success": False,
                                "message": "API Key 无效：配置、数据库和环境变量中均未配置有效的 Token",
                                "response_time": time.time() - start_time,
                                "details": None
                            }
                else:
                    # API Key 是完整的，直接使用
                    logger.info(f"✅ [TEST] Using complete API Key from config (length: {len(api_key)})")

                # 测试 Tushare API
                try:
                    logger.info(f"🔌 [TEST] Calling Tushare API with token (length: {len(api_key)})")
                    import tushare as ts
                    ts.set_token(api_key)
                    pro = ts.pro_api()
                    # 获取交易日历（轻量级测试）
                    df = pro.trade_cal(exchange='SSE', start_date='20240101', end_date='20240101')

                    if df is not None and len(df) > 0:
                        response_time = time.time() - start_time
                        logger.info(f"✅ [TEST] Tushare API call successful (response time: {response_time:.2f}s)")

                        # 构建消息，说明使用了哪个来源的凭证
                        credential_source = "配置"
                        if used_db_credentials:
                            credential_source = "数据库"
                        elif used_env_credentials:
                            credential_source = "环境变量"

                        return {
                            "success": True,
                            "message": f"成功连接到 Tushare 数据源（使用{credential_source}中的凭证）",
                            "response_time": response_time,
                            "details": {
                                "type": ds_type,
                                "test_result": "获取交易日历成功",
                                "credential_source": credential_source,
                                "used_db_credentials": used_db_credentials,
                                "used_env_credentials": used_env_credentials
                            }
                        }
                    else:
                        logger.error(f"❌ [TEST] Tushare API returned empty data")
                        return {
                            "success": False,
                            "message": "Tushare API 返回数据为空",
                            "response_time": time.time() - start_time,
                            "details": None
                        }
                except ImportError:
                    logger.error(f"❌ [TEST] Tushare library not installed")
                    return {
                        "success": False,
                        "message": "Tushare 库未安装，请运行: pip install tushare",
                        "response_time": time.time() - start_time,
                        "details": None
                    }
                except Exception as e:
                    logger.error(f"❌ [TEST] Tushare API call failed: {e}")
                    return {
                        "success": False,
                        "message": f"Tushare API 调用失败: {str(e)}",
                        "response_time": time.time() - start_time,
                        "details": None
                    }

            elif ds_type == "akshare":
                # AKShare 不需要 API Key，直接测试
                try:
                    import akshare as ak
                    # 使用更轻量级的接口测试 - 获取交易日历
                    df = ak.tool_trade_date_hist_sina()

                    if df is not None and len(df) > 0:
                        response_time = time.time() - start_time
                        return {
                            "success": True,
                            "message": f"成功连接到 AKShare 数据源",
                            "response_time": response_time,
                            "details": {
                                "type": ds_type,
                                "test_result": f"获取交易日历成功（{len(df)} 条记录）"
                            }
                        }
                    else:
                        return {
                            "success": False,
                            "message": "AKShare API 返回数据为空",
                            "response_time": time.time() - start_time,
                            "details": None
                        }
                except ImportError:
                    return {
                        "success": False,
                        "message": "AKShare 库未安装，请运行: pip install akshare",
                        "response_time": time.time() - start_time,
                        "details": None
                    }
                except Exception as e:
                    return {
                        "success": False,
                        "message": f"AKShare API 调用失败: {str(e)}",
                        "response_time": time.time() - start_time,
                        "details": None
                    }

            elif ds_type == "baostock":
                # BaoStock 不需要 API Key，直接测试登录
                try:
                    import baostock as bs
                    # 测试登录
                    lg = bs.login()

                    if lg.error_code == '0':
                        # 登录成功，测试获取数据
                        try:
                            # 获取交易日历（轻量级测试）
                            rs = bs.query_trade_dates(start_date="2024-01-01", end_date="2024-01-01")

                            if rs.error_code == '0':
                                response_time = time.time() - start_time
                                bs.logout()
                                return {
                                    "success": True,
                                    "message": f"成功连接到 BaoStock 数据源",
                                    "response_time": response_time,
                                    "details": {
                                        "type": ds_type,
                                        "test_result": "登录成功，获取交易日历成功"
                                    }
                                }
                            else:
                                bs.logout()
                                return {
                                    "success": False,
                                    "message": f"BaoStock 数据获取失败: {rs.error_msg}",
                                    "response_time": time.time() - start_time,
                                    "details": None
                                }
                        except Exception as e:
                            bs.logout()
                            return {
                                "success": False,
                                "message": f"BaoStock 数据获取异常: {str(e)}",
                                "response_time": time.time() - start_time,
                                "details": None
                            }
                    else:
                        return {
                            "success": False,
                            "message": f"BaoStock 登录失败: {lg.error_msg}",
                            "response_time": time.time() - start_time,
                            "details": None
                        }
                except ImportError:
                    return {
                        "success": False,
                        "message": "BaoStock 库未安装，请运行: pip install baostock",
                        "response_time": time.time() - start_time,
                        "details": None
                    }
                except Exception as e:
                    return {
                        "success": False,
                        "message": f"BaoStock API 调用失败: {str(e)}",
                        "response_time": time.time() - start_time,
                        "details": None
                    }

            elif ds_type == "yahoo_finance":
                # Yahoo Finance 测试
                if not ds_config.endpoint:
                    ds_config.endpoint = "https://query1.finance.yahoo.com"

                try:
                    url = f"{ds_config.endpoint}/v8/finance/chart/AAPL"
                    params = {"interval": "1d", "range": "1d"}
                    response = requests.get(url, params=params, timeout=10)

                    if response.status_code == 200:
                        data = response.json()
                        if "chart" in data and "result" in data["chart"]:
                            response_time = time.time() - start_time
                            return {
                                "success": True,
                                "message": f"成功连接到 Yahoo Finance 数据源",
                                "response_time": response_time,
                                "details": {
                                    "type": ds_type,
                                    "endpoint": ds_config.endpoint,
                                    "test_result": "获取 AAPL 数据成功"
                                }
                            }

                    return {
                        "success": False,
                        "message": f"Yahoo Finance API 返回错误: HTTP {response.status_code}",
                        "response_time": time.time() - start_time,
                        "details": None
                    }
                except Exception as e:
                    return {
                        "success": False,
                        "message": f"Yahoo Finance API 调用失败: {str(e)}",
                        "response_time": time.time() - start_time,
                        "details": None
                    }

            elif ds_type == "alpha_vantage":
                # 🔥 如果配置中的 API Key 包含 "..."（截断标记），需要验证是否是未修改的原值
                if api_key and "..." in api_key:
                    logger.info(f"🔍 [TEST] API Key contains '...' (truncated), checking if it matches database value")

                    # 从数据库中获取完整的 API Key
                    system_config = None
                    if system_config_getter:
                        system_config = await system_config_getter()
                    else:
                        system_config = await self._get_system_config_from_db()

                    db_config = None
                    if system_config:
                        for ds in system_config.data_source_configs:
                            if ds.name == ds_config.name:
                                db_config = ds
                                break

                    if db_config and db_config.api_key:
                        # 对数据库中的完整 API Key 进行相同的截断处理
                        truncated_db_key = self._truncate_api_key(db_config.api_key)
                        logger.info(f"🔍 [TEST] Database API Key truncated: {truncated_db_key}")
                        logger.info(f"🔍 [TEST] Received API Key: {api_key}")

                        # 比较截断后的值
                        if api_key == truncated_db_key:
                            # 相同，说明用户没有修改，使用数据库中的完整值
                            api_key = db_config.api_key
                            used_db_credentials = True
                            logger.info(f"✅ [TEST] Truncated values match, using complete API Key from database (length: {len(api_key)})")
                        else:
                            # 不同，说明用户修改了但修改得不完整
                            logger.error(f"❌ [TEST] Truncated API Key doesn't match database value")
                            return {
                                "success": False,
                                "message": "API Key 格式错误：检测到截断标记但与数据库中的值不匹配，请输入完整的 API Key",
                                "response_time": time.time() - start_time,
                                "details": {
                                    "error": "truncated_key_mismatch",
                                    "received": api_key,
                                    "expected": truncated_db_key
                                }
                            }
                    else:
                        # 数据库中没有有效的 API Key，尝试从环境变量获取
                        logger.info(f"⚠️  [TEST] No valid API Key in database, trying environment variable")
                        env_key = os.getenv('ALPHA_VANTAGE_API_KEY')
                        if env_key:
                            api_key = env_key.strip().strip('"').strip("'")
                            used_env_credentials = True
                            logger.info(f"🔑 [TEST] Using ALPHA_VANTAGE_API_KEY from environment (length: {len(api_key)})")
                        else:
                            logger.error(f"❌ [TEST] No valid API Key in database or environment")
                            return {
                                "success": False,
                                "message": "API Key 无效：数据库和环境变量中均未配置有效的 API Key",
                                "response_time": time.time() - start_time,
                                "details": None
                            }

                # 如果 API Key 为空，尝试从数据库或环境变量获取
                elif not api_key:
                    logger.info(f"⚠️  [TEST] API Key is empty, trying to get from database")

                    # 从数据库中获取完整的 API Key
                    system_config = None
                    if system_config_getter:
                        system_config = await system_config_getter()
                    else:
                        system_config = await self._get_system_config_from_db()

                    db_config = None
                    if system_config:
                        for ds in system_config.data_source_configs:
                            if ds.name == ds_config.name:
                                db_config = ds
                                break

                    if db_config and db_config.api_key and "..." not in db_config.api_key:
                        api_key = db_config.api_key
                        used_db_credentials = True
                        logger.info(f"🔑 [TEST] Using API Key from database (length: {len(api_key)})")
                    else:
                        # 如果数据库中也没有，尝试从环境变量获取
                        logger.info(f"⚠️  [TEST] No valid API Key in database, trying environment variable")
                        env_key = os.getenv('ALPHA_VANTAGE_API_KEY')
                        if env_key:
                            api_key = env_key.strip().strip('"').strip("'")
                            used_env_credentials = True
                            logger.info(f"🔑 [TEST] Using ALPHA_VANTAGE_API_KEY from environment (length: {len(api_key)})")
                        else:
                            logger.error(f"❌ [TEST] No valid API Key in config, database, or environment")
                            return {
                                "success": False,
                                "message": "API Key 无效：配置、数据库和环境变量中均未配置有效的 API Key",
                                "response_time": time.time() - start_time,
                                "details": None
                            }
                else:
                    # API Key 是完整的，直接使用
                    logger.info(f"✅ [TEST] Using complete API Key from config (length: {len(api_key)})")

                # 测试 Alpha Vantage API
                endpoint = ds_config.endpoint or "https://www.alphavantage.co"
                url = f"{endpoint}/query"
                params = {
                    "function": "TIME_SERIES_INTRADAY",
                    "symbol": "IBM",
                    "interval": "5min",
                    "apikey": api_key
                }

                try:
                    logger.info(f"🔌 [TEST] Calling Alpha Vantage API with key (length: {len(api_key)})")
                    response = requests.get(url, params=params, timeout=10)

                    if response.status_code == 200:
                        data = response.json()
                        if "Time Series (5min)" in data or "Meta Data" in data:
                            response_time = time.time() - start_time
                            logger.info(f"✅ [TEST] Alpha Vantage API call successful (response time: {response_time:.2f}s)")

                            # 构建消息，说明使用了哪个来源的凭证
                            credential_source = "配置"
                            if used_db_credentials:
                                credential_source = "数据库"
                            elif used_env_credentials:
                                credential_source = "环境变量"

                            return {
                                "success": True,
                                "message": f"成功连接到 Alpha Vantage 数据源（使用{credential_source}中的凭证）",
                                "response_time": response_time,
                                "details": {
                                    "type": ds_type,
                                    "endpoint": endpoint,
                                    "test_result": "API 密钥有效",
                                    "credential_source": credential_source,
                                    "used_db_credentials": used_db_credentials,
                                    "used_env_credentials": used_env_credentials
                                }
                            }
                        elif "Error Message" in data:
                            return {
                                "success": False,
                                "message": f"Alpha Vantage API 错误: {data['Error Message']}",
                                "response_time": time.time() - start_time,
                                "details": None
                            }
                        elif "Note" in data:
                            return {
                                "success": False,
                                "message": "API 调用频率超限，请稍后再试",
                                "response_time": time.time() - start_time,
                                "details": None
                            }

                    return {
                        "success": False,
                        "message": f"Alpha Vantage API 返回错误: HTTP {response.status_code}",
                        "response_time": time.time() - start_time,
                        "details": None
                    }
                except Exception as e:
                    return {
                        "success": False,
                        "message": f"Alpha Vantage API 调用失败: {str(e)}",
                        "response_time": time.time() - start_time,
                        "details": None
                    }

            else:
                # 其他数据源类型 - 尝试从环境变量获取 API Key（如果需要）
                # 支持的环境变量映射
                env_key_map = {
                    "finnhub": "FINNHUB_API_KEY",
                    "polygon": "POLYGON_API_KEY",
                    "iex": "IEX_API_KEY",
                    "quandl": "QUANDL_API_KEY",
                }

                # 如果配置中没有 API Key，尝试从环境变量获取
                if ds_type in env_key_map and (not api_key or "..." in api_key):
                    env_var_name = env_key_map[ds_type]
                    env_key = os.getenv(env_var_name)
                    if env_key:
                        api_key = env_key.strip()
                        used_env_credentials = True
                        logger.info(f"🔑 使用环境变量中的 {ds_type.upper()} API Key ({env_var_name})")

                # 基本的端点测试
                if ds_config.endpoint:
                    try:
                        # 如果有 API Key，添加到请求中
                        headers = {}
                        params = {}

                        if api_key:
                            # 根据不同数据源的认证方式添加 API Key
                            if ds_type == "finnhub":
                                params["token"] = api_key
                            elif ds_type in ["polygon", "alpha_vantage"]:
                                params["apiKey"] = api_key
                            elif ds_type == "iex":
                                params["token"] = api_key
                            else:
                                # 默认使用 header 认证
                                headers["Authorization"] = f"Bearer {api_key}"

                        response = requests.get(ds_config.endpoint, params=params, headers=headers, timeout=10)
                        response_time = time.time() - start_time

                        if response.status_code < 500:
                            return {
                                "success": True,
                                "message": f"成功连接到数据源 {ds_config.name}",
                                "response_time": response_time,
                                "details": {
                                    "type": ds_type,
                                    "endpoint": ds_config.endpoint,
                                    "status_code": response.status_code,
                                    "used_env_credentials": used_env_credentials
                                }
                            }
                        else:
                            return {
                                "success": False,
                                "message": f"数据源返回服务器错误: HTTP {response.status_code}",
                                "response_time": response_time,
                                "details": None
                            }
                    except Exception as e:
                        return {
                            "success": False,
                            "message": f"连接失败: {str(e)}",
                            "response_time": time.time() - start_time,
                            "details": None
                        }
                else:
                    return {
                        "success": False,
                        "message": f"不支持的数据源类型: {ds_type}，且未配置端点",
                        "response_time": time.time() - start_time,
                        "details": None
                    }

        except Exception as e:
            response_time = time.time() - start_time
            logger.error(f"❌ 测试数据源配置失败: {e}")
            return {
                "success": False,
                "message": f"连接失败: {str(e)}",
                "response_time": response_time,
                "details": None
            }

    async def _get_system_config_from_db(self):
        """从数据库直接获取系统配置（内部使用，避免循环依赖）"""
        try:
            from app.core.database import get_mongo_db
            from app.models.config import SystemConfig

            db = get_mongo_db()
            config_collection = db.system_configs
            config_data = await config_collection.find_one(
                {"is_active": True},
                sort=[("version", -1)]
            )
            if config_data:
                config_data.setdefault('config_name', config_data.get('config_name', 'bridged'))
                config_data.setdefault('config_type', config_data.get('config_type', 'system'))
                return SystemConfig(**config_data)
            return None
        except Exception as e:
            logger.error(f"❌ 从数据库获取系统配置失败: {e}")
            return None
