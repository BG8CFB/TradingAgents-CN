"""
大模型配置与厂家管理服务
"""

import time
import asyncio
import logging
import re
from typing import List, Optional, Dict, Any

from bson import ObjectId

from app.core.database import get_mongo_db
from app.models.config import (
    LLMConfig, LLMProvider
)
from app.utils.timezone import now_tz
from app.utils.api_key_utils import is_valid_api_key

logger = logging.getLogger(__name__)


class LLMService:
    """大模型配置与厂家管理"""

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

    async def _get_system_config(self):
        """从数据库获取系统配置（内部使用）"""
        try:
            from app.models.config import SystemConfig

            db = await self._get_db()
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
            logger.error(f"❌ 获取系统配置失败: {e}")
            return None

    async def _save_system_config(self, config) -> bool:
        """保存系统配置（内部使用）

        使用原子操作替代先禁用再插入的两步操作，避免中间状态导致配置丢失。
        策略：将新配置作为唯一活跃文档插入，同时标记旧配置为非活跃。
        """
        try:
            db = await self._get_db()
            config_collection = db.system_configs

            config.updated_at = now_tz()
            config.version += 1

            config_dict = config.model_dump(by_alias=True)
            if '_id' in config_dict:
                del config_dict['_id']
            config_dict['is_active'] = True

            # 尝试使用事务（需要 MongoDB 副本集）
            try:
                async with await db.client.start_session() as session:
                    async with session.start_transaction():
                        # 先将所有活跃配置标记为非活跃
                        await config_collection.update_many(
                            {"is_active": True},
                            {"$set": {"is_active": False}},
                            session=session,
                        )
                        # 插入新配置
                        await config_collection.insert_one(config_dict, session=session)
                return True
            except Exception as txn_err:
                # 事务不支持（单机 MongoDB）时，使用 fallback:
                # 先插入新配置，再删除旧配置（新配置优先）
                logger.debug(f"事务不可用，使用 fallback 策略: {txn_err}")
                await config_collection.insert_one(config_dict)
                await config_collection.update_many(
                    {"is_active": True, "_id": {"$ne": config_dict.get("_id")}},
                    {"$set": {"is_active": False}},
                )
                return True
        except Exception as e:
            logger.error(f"保存系统配置失败: {e}")
            return False

    # ==================== LLM 配置管理 ====================

    async def update_llm_config(self, llm_config: LLMConfig) -> bool:
        """更新大模型配置"""
        try:
            config = await self._get_system_config()
            if not config:
                return False

            for i, existing_config in enumerate(config.llm_configs):
                if existing_config.model_name == llm_config.model_name:
                    config.llm_configs[i] = llm_config
                    break
            else:
                config.llm_configs.append(llm_config)

            return await self._save_system_config(config)
        except Exception as e:
            logger.error(f"更新LLM配置失败: {e}")
            return False

    async def delete_llm_config(self, provider: str, model_name: str) -> bool:
        """删除大模型配置。

        匹配条件：provider 大小写不敏感，model_name 精确匹配。
        """
        try:
            logger.info(f"🗑️ 删除大模型配置 - provider: {provider}, model_name: {model_name}")

            config = await self._get_system_config()
            if not config:
                logger.error("❌ 系统配置为空")
                return False

            original_count = len(config.llm_configs)

            # provider 大小写不敏感匹配，model_name 精确匹配
            config.llm_configs = [
                llm for llm in config.llm_configs
                if not (str(llm.provider).lower() == provider.lower() and llm.model_name == model_name)
            ]

            new_count = len(config.llm_configs)
            if new_count == original_count:
                logger.warning(f"❌ 没有找到匹配的配置: {provider}/{model_name}")
                return False

            logger.debug(f"🔄 配置数量: {original_count} -> {new_count}")

            save_result = await self._save_system_config(config)
            if not save_result:
                logger.error(f"💾 保存失败: provider={provider}, model_name={model_name}")
            return save_result

        except Exception as e:
            logger.error(f"❌ 删除LLM配置失败: {e}")
            logger.error("删除LLM配置失败", exc_info=True)
            return False

    async def set_default_llm(self, model_name: str) -> bool:
        """设置默认大模型"""
        try:
            config = await self._get_system_config()
            if not config:
                return False

            # 检查指定的模型是否存在
            model_exists = any(
                llm.model_name == model_name for llm in config.llm_configs
            )

            if not model_exists:
                return False

            config.default_llm = model_name
            return await self._save_system_config(config)

        except Exception as e:
            logger.error(f"设置默认LLM失败: {e}")
            return False

    async def test_llm_config(self, llm_config: LLMConfig) -> Dict[str, Any]:
        """测试大模型配置 - 真实调用API进行验证"""
        start_time = time.time()
        try:

            # 获取 provider 字符串值（兼容枚举和字符串）
            provider_str = llm_config.provider.value if hasattr(llm_config.provider, 'value') else str(llm_config.provider)

            logger.info(f"🧪 测试大模型配置: {provider_str} - {llm_config.model_name}")
            logger.info(f"📍 API基础URL (模型配置): {llm_config.api_base}")

            # 获取厂家配置（用于获取 API Key 和 default_base_url）
            db = await self._get_db()
            providers_collection = db.llm_providers
            provider_data = await providers_collection.find_one({"name": provider_str})

            # 1. 确定 API 基础 URL
            api_base = llm_config.api_base
            if not api_base:
                # 如果模型配置没有 api_base，从厂家配置获取 default_base_url
                if provider_data and provider_data.get("default_base_url"):
                    api_base = provider_data["default_base_url"]
                    logger.info(f"✅ 从厂家配置获取 API 基础 URL: {api_base}")
                else:
                    return {
                        "success": False,
                        "message": "模型配置和厂家配置都未设置 API 基础 URL",
                        "response_time": time.time() - start_time,
                        "details": None
                    }

            # 2. 验证 API Key
            api_key = None
            if llm_config.api_key:
                api_key = llm_config.api_key
            else:
                # 从厂家配置获取 API Key
                if provider_data and provider_data.get("api_key"):
                    api_key = provider_data["api_key"]
                    logger.info("✅ 从厂家配置获取到API密钥")

            if not api_key:
                return {
                    "success": False,
                    "message": f"{provider_str} 未配置API密钥",
                    "response_time": time.time() - start_time,
                    "details": None
                }

            # 3. 根据厂家类型选择测试方法
            if provider_str == "google":
                # Google AI 使用专门的测试方法
                logger.info("🔍 使用 Google AI 专用测试方法")
                result = self._test_google_api(api_key, f"{provider_str} {llm_config.model_name}", api_base, llm_config.model_name)
                result["response_time"] = time.time() - start_time
                return result
            elif provider_str == "deepseek":
                # DeepSeek 使用专门的测试方法
                logger.info("🔍 使用 DeepSeek 专用测试方法")
                result = self._test_deepseek_api(api_key, f"{provider_str} {llm_config.model_name}", llm_config.model_name, api_base)
                result["response_time"] = time.time() - start_time
                return result
            elif provider_str == "dashscope":
                # DashScope 使用专门的测试方法
                logger.info("🔍 使用 DashScope 专用测试方法")
                result = self._test_dashscope_api(api_key, f"{provider_str} {llm_config.model_name}", llm_config.model_name)
                result["response_time"] = time.time() - start_time
                return result
            else:
                # 其他厂家使用 OpenAI 兼容的测试方法（通过线程池避免阻塞事件循环）
                logger.info("使用 OpenAI 兼容测试方法")
                result = await asyncio.get_running_loop().run_in_executor(
                    None,
                    self._test_openai_compatible_config,
                    api_base, api_key, provider_str, llm_config.model_name, start_time,
                )
                return result

        except Exception as e:
            response_time = time.time() - start_time
            logger.error(f"测试大模型配置失败: {e}")
            return {
                "success": False,
                "message": f"连接失败: {str(e)}",
                "response_time": response_time,
                "details": None
            }

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

    def _test_openai_compatible_config(
        self, api_base: str, api_key: str, provider_str: str, model_name: str, start_time: float
    ) -> Dict[str, Any]:
        """同步测试 OpenAI 兼容 API 配置（在 run_in_executor 中调用）"""
        try:
            import requests

            api_base_normalized = api_base.rstrip("/")
            if not re.search(r'/v\d+$', api_base_normalized):
                api_base_normalized = api_base_normalized + "/v1"

            url = f"{api_base_normalized}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            data = {
                "model": model_name,
                "messages": [
                    {"role": "user", "content": "Hello, please respond with 'OK' if you can read this."}
                ],
                "max_tokens": 200,
                "temperature": 0.1
            }

            logger.info(f"发送测试请求到: {url}, 模型: {model_name}")
            response = requests.post(url, json=data, headers=headers, timeout=15)
            response_time = time.time() - start_time

            if response.status_code == 200:
                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    if content and len(content.strip()) > 0:
                        return {
                            "success": True,
                            "message": f"成功连接到 {provider_str} {model_name}",
                            "response_time": response_time,
                            "details": {
                                "provider": provider_str,
                                "model": model_name,
                                "api_base": api_base,
                                "response_preview": content[:100]
                            }
                        }
                    else:
                        return {"success": False, "message": "API响应内容为空", "response_time": response_time, "details": None}
                else:
                    return {"success": False, "message": "API响应格式异常", "response_time": response_time, "details": None}
            elif response.status_code == 401:
                return {"success": False, "message": "API密钥无效或已过期", "response_time": response_time, "details": None}
            elif response.status_code == 403:
                return {"success": False, "message": "API权限不足或配额已用完", "response_time": response_time, "details": None}
            elif response.status_code == 404:
                return {"success": False, "message": f"API端点不存在，请检查API基础URL是否正确: {url}", "response_time": response_time, "details": None}
            else:
                try:
                    error_detail = response.json()
                    error_msg = error_detail.get("error", {}).get("message", f"HTTP {response.status_code}")
                    return {"success": False, "message": f"API测试失败: {error_msg}", "response_time": response_time, "details": None}
                except Exception as e:
                    logger.debug(f"解析API错误响应失败: {e}")
                    return {"success": False, "message": f"API测试失败: HTTP {response.status_code}", "response_time": response_time, "details": None}

        except requests.exceptions.Timeout:
            return {"success": False, "message": "连接超时，请检查API基础URL是否正确或网络是否可达", "response_time": time.time() - start_time, "details": None}
        except requests.exceptions.ConnectionError as e:
            return {"success": False, "message": f"连接失败，请检查API基础URL是否正确: {str(e)}", "response_time": time.time() - start_time, "details": None}
        except Exception as e:
            return {"success": False, "message": f"连接失败: {str(e)}", "response_time": time.time() - start_time, "details": None}

    # ==================== LLM 厂家管理 ====================

    async def get_llm_providers(self) -> List[LLMProvider]:
        """获取所有大模型厂家（合并环境变量配置）"""
        try:
            db = await self._get_db()
            providers_collection = db.llm_providers

            providers_data = await providers_collection.find().to_list(length=None)
            providers = []

            logger.info(f"🔍 [get_llm_providers] 从数据库获取到 {len(providers_data)} 个供应商")

            for provider_data in providers_data:
                provider = LLMProvider(**provider_data)

                # 为了支持本地AI模型，不再验证API Key的有效性
                db_key_valid = True  # 总是有效
                logger.info(f"🔍 [get_llm_providers] 供应商 {provider.display_name} ({provider.name}): 数据库密钥有效={db_key_valid}")

                # 初始化 extra_config
                provider.extra_config = provider.extra_config or {}

                # 为了支持本地AI模型，总是使用数据库配置的API Key（即使为空）
                provider.extra_config["source"] = "database"
                provider.extra_config["has_api_key"] = bool(provider.api_key)
                logger.info(f"✅ [get_llm_providers] 使用数据库配置的 {provider.display_name} API密钥 (长度: {len(provider.api_key) if provider.api_key else 0})")

                providers.append(provider)

            logger.info(f"🔍 [get_llm_providers] 返回 {len(providers)} 个供应商")
            return providers
        except Exception as e:
            logger.error(f"❌ [get_llm_providers] 获取厂家列表失败: {e}", exc_info=True)
            return []

    def _is_valid_api_key(self, api_key: Optional[str]) -> bool:
        """
        判断 API Key 是否有效
        """
        return is_valid_api_key(api_key)

    async def add_llm_provider(self, provider: LLMProvider) -> str:
        """添加大模型厂家"""
        try:
            db = await self._get_db()
            providers_collection = db.llm_providers

            # 检查厂家名称是否已存在
            existing = await providers_collection.find_one({"name": provider.name})
            if existing:
                raise ValueError(f"厂家 {provider.name} 已存在")

            provider.created_at = now_tz()
            provider.updated_at = now_tz()

            # 修复：删除 _id 字段，让 MongoDB 自动生成 ObjectId
            provider_data = provider.model_dump(by_alias=True, exclude_unset=True)
            if "_id" in provider_data:
                del provider_data["_id"]

            result = await providers_collection.insert_one(provider_data)
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f"添加厂家失败: {e}")
            raise

    async def update_llm_provider(self, provider_id: str, update_data: Dict[str, Any]) -> bool:
        """更新大模型厂家"""
        try:
            db = await self._get_db()
            providers_collection = db.llm_providers

            update_data["updated_at"] = now_tz()

            # 兼容处理：尝试 ObjectId 和字符串两种类型
            try:
                # 先尝试作为 ObjectId 查询
                result = await providers_collection.update_one(
                    {"_id": ObjectId(provider_id)},
                    {"$set": update_data}
                )

                # 如果没有匹配到，再尝试作为字符串查询
                if result.matched_count == 0:
                    result = await providers_collection.update_one(
                        {"_id": provider_id},
                        {"$set": update_data}
                    )
            except Exception as e:
                logger.debug(f"ObjectId转换失败，使用字符串查询: {e}")
                # 如果 ObjectId 转换失败，直接用字符串查询
                result = await providers_collection.update_one(
                    {"_id": provider_id},
                    {"$set": update_data}
                )

            # 修复：matched_count > 0 表示找到了记录（即使没有修改）
            return result.matched_count > 0
        except Exception as e:
            logger.error(f"更新厂家失败: {e}")
            logger.error("更新厂家失败", exc_info=True)
            return False

    async def delete_llm_provider(self, provider_id: str) -> bool:
        """删除大模型厂家。

        兼容 ObjectId 与字符串两种 ``_id`` 存储格式（历史数据可能两者并存）：
        先用 ObjectId 查找（标准格式），未命中再用字符串查找（旧数据兜底），
        找到后用相同的查询条件执行删除，保证删的就是查到的那条。
        """
        try:
            logger.info(f"🗑️ 删除厂家 - provider_id: {provider_id}")

            db = await self._get_db()
            providers_collection = db.llm_providers

            # 兼容两种 _id 格式：ObjectId 优先（标准），字符串兜底（历史数据）
            existing = await providers_collection.find_one({"_id": ObjectId(provider_id)})
            delete_filter: dict
            if existing is not None:
                delete_filter = {"_id": ObjectId(provider_id)}
            else:
                existing = await providers_collection.find_one({"_id": provider_id})
                delete_filter = {"_id": provider_id}

            if not existing:
                logger.warning(f"❌ 找不到厂家: {provider_id}")
                return False

            logger.debug(f"✅ 找到厂家: {existing.get('display_name')}")

            result = await providers_collection.delete_one(delete_filter)
            success = result.deleted_count > 0

            logger.info(f"🗑️ 删除结果: success={success}, deleted_count={result.deleted_count}")
            return success

        except Exception as e:
            logger.error(f"❌ 删除厂家失败: {e}")
            logger.error("删除厂家失败", exc_info=True)
            return False

    async def toggle_llm_provider(self, provider_id: str, is_active: bool) -> bool:
        """切换大模型厂家状态"""
        try:
            db = await self._get_db()
            providers_collection = db.llm_providers

            # 兼容处理：尝试 ObjectId 和字符串两种类型
            try:
                # 先尝试作为 ObjectId 查询
                result = await providers_collection.update_one(
                    {"_id": ObjectId(provider_id)},
                    {"$set": {"is_active": is_active, "updated_at": now_tz()}}
                )

                # 如果没有匹配到，再尝试作为字符串查询
                if result.matched_count == 0:
                    result = await providers_collection.update_one(
                        {"_id": provider_id},
                        {"$set": {"is_active": is_active, "updated_at": now_tz()}}
                    )
            except Exception as e:
                logger.debug(f"ObjectId转换失败，使用字符串查询: {e}")
                # 如果 ObjectId 转换失败，直接用字符串查询
                result = await providers_collection.update_one(
                    {"_id": provider_id},
                    {"$set": {"is_active": is_active, "updated_at": now_tz()}}
                )

            return result.matched_count > 0
        except Exception as e:
            logger.error(f"切换厂家状态失败: {e}")
            return False

    async def init_aggregator_providers(self) -> Dict[str, Any]:
        """
        初始化聚合渠道厂家配置

        Returns:
            初始化结果统计
        """
        from app.constants.model_capabilities import AGGREGATOR_PROVIDERS

        try:
            db = await self._get_db()
            providers_collection = db.llm_providers

            added_count = 0
            skipped_count = 0
            updated_count = 0

            for provider_name, config in AGGREGATOR_PROVIDERS.items():
                # 从环境变量获取 API Key
                # LLM API Key 仅从 DB 读取，不再从环境变量读取
                api_key = None

                # 检查是否已存在
                existing = await providers_collection.find_one({"name": provider_name})

                if existing:
                    # 如果已存在但没有 API Key，且环境变量中有，则更新
                    if not existing.get("api_key") and api_key:
                        update_data = {
                            "api_key": api_key,
                            "is_active": True,  # 有 API Key 则自动启用
                            "updated_at": now_tz()
                        }
                        await providers_collection.update_one(
                            {"name": provider_name},
                            {"$set": update_data}
                        )
                        updated_count += 1
                        logger.info(f"✅ 更新聚合渠道 {config['display_name']} 的 API Key")
                    else:
                        skipped_count += 1
                        logger.info(f"⏭️ 聚合渠道 {config['display_name']} 已存在，跳过")
                    continue

                # 创建聚合渠道厂家配置
                provider_data = {
                    "name": provider_name,
                    "display_name": config["display_name"],
                    "description": config["description"],
                    "website": config.get("website"),
                    "api_doc_url": config.get("api_doc_url"),
                    "default_base_url": config["default_base_url"],
                    "is_active": bool(api_key),  # 有 API Key 则自动启用
                    "supported_features": ["chat", "completion", "function_calling", "streaming"],
                    "api_key": api_key or "",
                    "extra_config": {
                        "supported_providers": config.get("supported_providers", []),
                        "source": "environment" if api_key else "manual"
                    },
                    # 🆕 聚合渠道标识
                    "is_aggregator": True,
                    "aggregator_type": "openai_compatible",
                    "model_name_format": config.get("model_name_format", "{provider}/{model}"),
                    "created_at": now_tz(),
                    "updated_at": now_tz()
                }

                provider = LLMProvider(**provider_data)
                # 修复：删除 _id 字段，让 MongoDB 自动生成 ObjectId
                insert_data = provider.model_dump(by_alias=True, exclude_unset=True)
                if "_id" in insert_data:
                    del insert_data["_id"]
                await providers_collection.insert_one(insert_data)
                added_count += 1

                if api_key:
                    logger.info(f"✅ 添加聚合渠道: {config['display_name']} (已从环境变量获取 API Key)")
                else:
                    logger.info(f"✅ 添加聚合渠道: {config['display_name']} (需手动配置 API Key)")

            message_parts = []
            if added_count > 0:
                message_parts.append(f"成功添加 {added_count} 个聚合渠道")
            if updated_count > 0:
                message_parts.append(f"更新 {updated_count} 个")
            if skipped_count > 0:
                message_parts.append(f"跳过 {skipped_count} 个已存在的")

            return {
                "success": True,
                "added": added_count,
                "updated": updated_count,
                "skipped": skipped_count,
                "message": "，".join(message_parts) if message_parts else "无变更"
            }

        except Exception as e:
            logger.error(f"❌ 初始化聚合渠道失败: {e}")
            logger.error("初始化聚合渠道失败", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "message": "初始化聚合渠道失败"
            }

    async def migrate_env_to_providers(self) -> Dict[str, Any]:
        """将环境变量配置迁移到厂家管理"""
        try:
            db = await self._get_db()
            providers_collection = db.llm_providers

            # 预设厂家配置
            default_providers = [
                {
                    "name": "openai",
                    "display_name": "OpenAI",
                    "description": "OpenAI是人工智能领域的领先公司，提供GPT系列模型",
                    "website": "https://openai.com",
                    "api_doc_url": "https://platform.openai.com/docs",
                    "default_base_url": "https://api.openai.com/v1",
                    "supported_features": ["chat", "completion", "embedding", "image", "vision", "function_calling", "streaming"]
                },
                {
                    "name": "anthropic",
                    "display_name": "Anthropic",
                    "description": "Anthropic专注于AI安全研究，提供Claude系列模型",
                    "website": "https://anthropic.com",
                    "api_doc_url": "https://docs.anthropic.com",
                    "default_base_url": "https://api.anthropic.com",
                    "supported_features": ["chat", "completion", "function_calling", "streaming"]
                },
                {
                    "name": "dashscope",
                    "display_name": "阿里云百炼",
                    "description": "阿里云百炼大模型服务平台，提供通义千问等模型",
                    "website": "https://bailian.console.aliyun.com",
                    "api_doc_url": "https://help.aliyun.com/zh/dashscope/",
                    "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "supported_features": ["chat", "completion", "embedding", "function_calling", "streaming"]
                },
                {
                    "name": "deepseek",
                    "display_name": "DeepSeek",
                    "description": "DeepSeek提供高性能的AI推理服务",
                    "website": "https://www.deepseek.com",
                    "api_doc_url": "https://platform.deepseek.com/api-docs",
                    "default_base_url": "https://api.deepseek.com",
                    "supported_features": ["chat", "completion", "function_calling", "streaming"]
                }
            ]

            migrated_count = 0
            updated_count = 0
            skipped_count = 0

            for provider_config in default_providers:
                # LLM API Key 仅从 DB 读取
                api_key = None

                # 检查是否已存在
                existing = await providers_collection.find_one({"name": provider_config["name"]})

                if existing:
                    # 如果已存在但没有API密钥，且环境变量中有密钥，则更新
                    if not existing.get("api_key") and api_key:
                        update_data = {
                            "api_key": api_key,
                            "is_active": True,
                            "extra_config": {"migrated_from": "environment"},
                            "updated_at": now_tz()
                        }
                        await providers_collection.update_one(
                            {"name": provider_config["name"]},
                            {"$set": update_data}
                        )
                        updated_count += 1
                        logger.info(f"✅ 更新厂家 {provider_config['display_name']} 的API密钥")
                    else:
                        skipped_count += 1
                        logger.info(f"⏭️ 跳过厂家 {provider_config['display_name']} (已有配置)")
                    continue

                # 创建新厂家配置
                provider_data = {
                    **provider_config,
                    "api_key": api_key,
                    "is_active": bool(api_key),  # 有密钥的自动启用
                    "extra_config": {"migrated_from": "environment"} if api_key else {},
                    "created_at": now_tz(),
                    "updated_at": now_tz()
                }

                await providers_collection.insert_one(provider_data)
                migrated_count += 1
                logger.info(f"✅ 创建厂家 {provider_config['display_name']}")

            total_changes = migrated_count + updated_count
            message_parts = []
            if migrated_count > 0:
                message_parts.append(f"新建 {migrated_count} 个厂家")
            if updated_count > 0:
                message_parts.append(f"更新 {updated_count} 个厂家的API密钥")
            if skipped_count > 0:
                message_parts.append(f"跳过 {skipped_count} 个已配置的厂家")

            if total_changes > 0:
                message = "迁移完成：" + "，".join(message_parts)
            else:
                message = "所有厂家都已配置，无需迁移"

            return {
                "success": True,
                "migrated_count": migrated_count,
                "updated_count": updated_count,
                "skipped_count": skipped_count,
                "message": message
            }

        except Exception as e:
            logger.error(f"环境变量迁移失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "环境变量迁移失败"
            }

    # ==================== 厂家 API 测试 ====================

    async def test_provider_api(self, provider_id: str) -> dict:
        """测试厂家API密钥"""
        try:
            logger.info(f"🔍 测试厂家API - provider_id: {provider_id}")

            db = await self._get_db()
            providers_collection = db.llm_providers

            # 兼容处理：尝试 ObjectId 和字符串两种类型
            provider_data = None
            try:
                # 先尝试作为 ObjectId 查询
                provider_data = await providers_collection.find_one({"_id": ObjectId(provider_id)})
            except Exception as e:
                logger.debug(f"ObjectId查询失败: {e}")
                pass

            # 如果没有找到，再尝试作为字符串查询
            if not provider_data:
                provider_data = await providers_collection.find_one({"_id": provider_id})

            if not provider_data:
                return {
                    "success": False,
                    "message": f"厂家不存在 (ID: {provider_id})"
                }

            provider_name = provider_data.get("name")
            api_key = provider_data.get("api_key")
            display_name = provider_data.get("display_name", provider_name)

            # 为了支持本地AI模型，直接使用数据库配置的API Key（可以为空）
            logger.info(f"✅ 使用数据库配置的 {display_name} API密钥 (长度: {len(api_key) if api_key else 0})")

            # 根据厂家类型调用相应的测试函数
            test_result = await self._test_provider_connection(provider_name, api_key, display_name)

            return test_result

        except Exception as e:
            logger.error(f"测试厂家API失败: {e}")
            return {
                "success": False,
                "message": f"测试失败: {str(e)}"
            }

    async def _test_provider_connection(self, provider_name: str, api_key: str, display_name: str) -> dict:
        """测试具体厂家的连接"""
        try:
            # 聚合渠道（使用 OpenAI 兼容 API）
            if provider_name in ["302ai", "oneapi", "newapi", "custom_aggregator"]:
                # 获取厂家的 base_url
                db = await self._get_db()
                providers_collection = db.llm_providers
                provider_data = await providers_collection.find_one({"name": provider_name})
                base_url = provider_data.get("default_base_url") if provider_data else None
                return await asyncio.get_running_loop().run_in_executor(
                    None, self._test_openai_compatible_api, api_key, display_name, base_url, provider_name
                )
            elif provider_name == "google":
                # 获取厂家的 base_url
                db = await self._get_db()
                providers_collection = db.llm_providers
                provider_data = await providers_collection.find_one({"name": provider_name})
                base_url = provider_data.get("default_base_url") if provider_data else None
                return await asyncio.get_running_loop().run_in_executor(None, self._test_google_api, api_key, display_name, base_url)
            elif provider_name == "deepseek":
                # 获取厂家的 base_url
                db = await self._get_db()
                providers_collection = db.llm_providers
                provider_data = await providers_collection.find_one({"name": provider_name})
                base_url = provider_data.get("default_base_url") if provider_data else None
                return await asyncio.get_running_loop().run_in_executor(None, self._test_deepseek_api, api_key, display_name, None, base_url)
            elif provider_name == "dashscope":
                return await asyncio.get_running_loop().run_in_executor(None, self._test_dashscope_api, api_key, display_name)
            elif provider_name == "openrouter":
                return await asyncio.get_running_loop().run_in_executor(None, self._test_openrouter_api, api_key, display_name)
            elif provider_name == "openai":
                return await asyncio.get_running_loop().run_in_executor(None, self._test_openai_api, api_key, display_name)
            elif provider_name == "anthropic":
                return await asyncio.get_running_loop().run_in_executor(None, self._test_anthropic_api, api_key, display_name)
            elif provider_name == "qianfan":
                return await asyncio.get_running_loop().run_in_executor(None, self._test_qianfan_api, api_key, display_name)
            else:
                # 🔧 对于未知的自定义厂家，使用 OpenAI 兼容 API 测试
                logger.info(f"🔍 使用 OpenAI 兼容 API 测试自定义厂家: {provider_name}")
                # 获取厂家的 base_url
                db = await self._get_db()
                providers_collection = db.llm_providers
                provider_data = await providers_collection.find_one({"name": provider_name})
                base_url = provider_data.get("default_base_url") if provider_data else None

                if not base_url:
                    return {
                        "success": False,
                        "message": f"自定义厂家 {display_name} 未配置 API 基础 URL"
                    }

                return await asyncio.get_running_loop().run_in_executor(
                    None, self._test_openai_compatible_api, api_key, display_name, base_url, provider_name
                )
        except Exception as e:
            return {
                "success": False,
                "message": f"{display_name} 连接测试失败: {str(e)}"
            }

    def _test_google_api(self, api_key: str, display_name: str, base_url: str = None, model_name: str = None) -> dict:
        """测试Google AI API"""
        try:
            import requests

            # 如果没有指定模型，使用默认模型
            if not model_name:
                model_name = "gemini-2.0-flash-exp"
                logger.info(f"⚠️ 未指定模型，使用默认模型: {model_name}")

            logger.info("🔍 [Google AI 测试] 开始测试")
            logger.info(f"   display_name: {display_name}")
            logger.info(f"   model_name: {model_name}")
            logger.info(f"   base_url (原始): {base_url}")
            logger.info(f"   api_key 长度: {len(api_key) if api_key else 0}")

            # 使用配置的 base_url 或默认值
            if not base_url:
                base_url = "https://generativelanguage.googleapis.com/v1beta"
                logger.info(f"   ⚠️ base_url 为空，使用默认值: {base_url}")

            # 移除末尾的斜杠
            base_url = base_url.rstrip('/')
            logger.info(f"   base_url (去除斜杠): {base_url}")

            # 如果 base_url 以 /v1 结尾，替换为 /v1beta（Google AI 的正确端点）
            if base_url.endswith('/v1'):
                base_url = base_url[:-3] + '/v1beta'
                logger.info(f"   ✅ 将 /v1 替换为 /v1beta: {base_url}")

            # 构建完整的 API 端点（使用用户配置的模型）
            url = f"{base_url}/models/{model_name}:generateContent?key={api_key}"

            logger.info(f"🔗 [Google AI 测试] 最终请求 URL: {url.replace(api_key, '***') if api_key else url}")

            headers = {
                "Content-Type": "application/json"
            }

            # 🔧 增加 token 限制到 2000，避免思考模式消耗导致无输出
            data = {
                "contents": [{
                    "parts": [{
                        "text": "Hello, please respond with 'OK' if you can read this."
                    }]
                }],
                "generationConfig": {
                    "maxOutputTokens": 2000,
                    "temperature": 0.1
                }
            }

            response = requests.post(url, json=data, headers=headers, timeout=15)

            logger.info(f"📥 [Google AI 测试] 响应状态码: {response.status_code}")

            if response.status_code == 200:
                # 打印完整的响应内容用于调试
                logger.info(f"📥 [Google AI 测试] 响应内容（前1000字符）: {response.text[:1000]}")

                result = response.json()
                logger.info("📥 [Google AI 测试] 解析后的 JSON 结构:")
                logger.info(f"   - 顶层键: {list(result.keys())}")
                logger.info(f"   - 是否包含 'candidates': {'candidates' in result}")
                if "candidates" in result:
                    logger.info(f"   - candidates 长度: {len(result['candidates'])}")
                    if len(result['candidates']) > 0:
                        logger.info(f"   - candidates[0] 的键: {list(result['candidates'][0].keys())}")

                if "candidates" in result and len(result["candidates"]) > 0:
                    candidate = result["candidates"][0]
                    logger.info(f"📥 [Google AI 测试] candidate 结构: {candidate}")

                    # 检查 finishReason
                    finish_reason = candidate.get("finishReason", "")
                    logger.info(f"📥 [Google AI 测试] finishReason: {finish_reason}")

                    if "content" in candidate:
                        content = candidate["content"]

                        # 检查是否有 parts
                        if "parts" in content and len(content["parts"]) > 0:
                            text = content["parts"][0].get("text", "")
                            logger.info(f"📥 [Google AI 测试] 提取的文本: {text}")

                            if text and len(text.strip()) > 0:
                                return {
                                    "success": True,
                                    "message": f"{display_name} API连接测试成功"
                                }
                            else:
                                logger.error("❌ [Google AI 测试] 文本为空")
                                return {
                                    "success": False,
                                    "message": f"{display_name} API响应内容为空"
                                }
                        else:
                            # content 中没有 parts，可能是因为 MAX_TOKENS 或其他原因
                            logger.error("❌ [Google AI 测试] content 中没有 parts")
                            logger.info(f"   content 的键: {list(content.keys())}")

                            if finish_reason == "MAX_TOKENS":
                                return {
                                    "success": False,
                                    "message": f"{display_name} API响应被截断（MAX_TOKENS），请增加 maxOutputTokens 配置"
                                }
                            else:
                                return {
                                    "success": False,
                                    "message": f"{display_name} API响应格式异常（缺少 parts，finishReason: {finish_reason}）"
                                }
                    else:
                        logger.error("❌ [Google AI 测试] candidate 中缺少 'content'")
                        logger.info(f"   candidate 的键: {list(candidate.keys())}")
                        return {
                            "success": False,
                            "message": f"{display_name} API响应格式异常（缺少 content）"
                        }
                else:
                    logger.error("❌ [Google AI 测试] 缺少 candidates 或 candidates 为空")
                    return {
                        "success": False,
                        "message": f"{display_name} API无有效候选响应"
                    }
            elif response.status_code == 400:
                logger.error(f"❌ [Google AI 测试] 400 错误，响应内容: {response.text[:500]}")
                try:
                    error_detail = response.json()
                    error_msg = error_detail.get("error", {}).get("message", "未知错误")
                    return {
                        "success": False,
                        "message": f"{display_name} API请求错误: {error_msg}"
                    }
                except Exception as e:
                    logger.debug(f"解析API错误响应失败: {e}")
                    return {
                        "success": False,
                        "message": f"{display_name} API请求格式错误"
                    }
            elif response.status_code == 403:
                logger.error(f"❌ [Google AI 测试] 403 错误，响应内容: {response.text[:500]}")
                return {
                    "success": False,
                    "message": f"{display_name} API密钥无效或权限不足"
                }
            elif response.status_code == 503:
                logger.error(f"❌ [Google AI 测试] 503 错误，响应内容: {response.text[:500]}")
                try:
                    error_detail = response.json()
                    error_code = error_detail.get("code", "")
                    error_msg = error_detail.get("message", "服务暂时不可用")

                    if error_code == "NO_KEYS_AVAILABLE":
                        return {
                            "success": False,
                            "message": f"{display_name} 中转服务暂时无可用密钥，请稍后重试或联系中转服务提供商"
                        }
                    else:
                        return {
                            "success": False,
                            "message": f"{display_name} 服务暂时不可用: {error_msg}"
                        }
                except Exception as e:
                    logger.debug(f"解析503错误响应失败: {e}")
                    return {
                        "success": False,
                        "message": f"{display_name} 服务暂时不可用 (HTTP 503)"
                    }
            else:
                logger.error(f"❌ [Google AI 测试] {response.status_code} 错误，响应内容: {response.text[:500]}")
                return {
                    "success": False,
                    "message": f"{display_name} API测试失败: HTTP {response.status_code}"
                }

        except Exception as e:
            return {
                "success": False,
                "message": f"{display_name} API测试异常: {str(e)}"
            }

    def _test_deepseek_api(self, api_key: str, display_name: str, model_name: str = None, base_url: str = None) -> dict:
        """测试DeepSeek API"""
        try:
            import requests

            # 如果没有指定模型，使用默认模型
            if not model_name:
                model_name = "deepseek-v4-flash"
                logger.info(f"未指定模型，使用默认模型: {model_name}")

            resolved_base = base_url or "https://api.deepseek.com"
            url = f"{resolved_base.rstrip('/')}/chat/completions"

            logger.info(f"[DeepSeek 测试] 使用模型: {model_name}, URL: {url}")

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }

            data = {
                "model": model_name,
                "messages": [
                    {"role": "user", "content": "你好，请简单介绍一下你自己。"}
                ],
                "max_tokens": 500,
                "temperature": 0.1
            }

            response = requests.post(url, json=data, headers=headers, timeout=10)

            if response.status_code == 200:
                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    msg = result["choices"][0]["message"]
                    content = msg.get("content", "")
                    # DeepSeek 推理模型可能返回空 content 但非空 reasoning_content
                    if not content or len(content.strip()) == 0:
                        reasoning = msg.get("reasoning_content", "") or msg.get("reasoning", "")
                        if reasoning and len(reasoning.strip()) > 0:
                            return {
                                "success": True,
                                "message": f"{display_name} API连接测试成功（推理模式）"
                            }
                    if content and len(content.strip()) > 0:
                        return {
                            "success": True,
                            "message": f"{display_name} API连接测试成功"
                        }
                    else:
                        return {
                            "success": False,
                            "message": f"{display_name} API响应为空"
                        }
                else:
                    return {
                        "success": False,
                        "message": f"{display_name} API响应格式异常"
                    }
            else:
                return {
                    "success": False,
                    "message": f"{display_name} API测试失败: HTTP {response.status_code}"
                }

        except Exception as e:
            return {
                "success": False,
                "message": f"{display_name} API测试异常: {str(e)}"
            }

    def _test_dashscope_api(self, api_key: str, display_name: str, model_name: str = None) -> dict:
        """测试阿里云百炼API"""
        try:
            import requests

            # 如果没有指定模型，使用默认模型
            if not model_name:
                model_name = "qwen-turbo"
                logger.info(f"⚠️ 未指定模型，使用默认模型: {model_name}")

            logger.info(f"🔍 [DashScope 测试] 使用模型: {model_name}")

            # 使用阿里云百炼的OpenAI兼容接口
            url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }

            data = {
                "model": model_name,
                "messages": [
                    {"role": "user", "content": "你好，请简单介绍一下你自己。"}
                ],
                "max_tokens": 50,
                "temperature": 0.1
            }

            response = requests.post(url, json=data, headers=headers, timeout=10)

            if response.status_code == 200:
                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    if content and len(content.strip()) > 0:
                        return {
                            "success": True,
                            "message": f"{display_name} API连接测试成功"
                        }
                    else:
                        return {
                            "success": False,
                            "message": f"{display_name} API响应为空"
                        }
                else:
                    return {
                        "success": False,
                        "message": f"{display_name} API响应格式异常"
                    }
            else:
                return {
                    "success": False,
                    "message": f"{display_name} API测试失败: HTTP {response.status_code}"
                }

        except Exception as e:
            return {
                "success": False,
                "message": f"{display_name} API测试异常: {str(e)}"
            }

    def _test_openrouter_api(self, api_key: str, display_name: str) -> dict:
        """测试OpenRouter API"""
        try:
            import requests

            url = "https://openrouter.ai/api/v1/chat/completions"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://tradingagents.cn",  # OpenRouter要求
                "X-Title": "TradingAgents-CN"
            }

            data = {
                "model": "meta-llama/llama-3.2-3b-instruct:free",  # 使用免费模型
                "messages": [
                    {"role": "user", "content": "你好，请简单介绍一下你自己。"}
                ],
                "max_tokens": 50,
                "temperature": 0.1
            }

            response = requests.post(url, json=data, headers=headers, timeout=15)

            if response.status_code == 200:
                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    if content and len(content.strip()) > 0:
                        return {
                            "success": True,
                            "message": f"{display_name} API连接测试成功"
                        }
                    else:
                        return {
                            "success": False,
                            "message": f"{display_name} API响应为空"
                        }
                else:
                    return {
                        "success": False,
                        "message": f"{display_name} API响应格式异常"
                    }
            else:
                return {
                    "success": False,
                    "message": f"{display_name} API测试失败: HTTP {response.status_code}"
                }

        except Exception as e:
            return {
                "success": False,
                "message": f"{display_name} API测试异常: {str(e)}"
            }

    def _test_openai_api(self, api_key: str, display_name: str) -> dict:
        """测试OpenAI API"""
        try:
            import requests

            url = "https://api.openai.com/v1/chat/completions"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }

            data = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {"role": "user", "content": "你好，请简单介绍一下你自己。"}
                ],
                "max_tokens": 50,
                "temperature": 0.1
            }

            response = requests.post(url, json=data, headers=headers, timeout=10)

            if response.status_code == 200:
                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    if content and len(content.strip()) > 0:
                        return {
                            "success": True,
                            "message": f"{display_name} API连接测试成功"
                        }
                    else:
                        return {
                            "success": False,
                            "message": f"{display_name} API响应为空"
                        }
                else:
                    return {
                        "success": False,
                        "message": f"{display_name} API响应格式异常"
                    }
            else:
                return {
                    "success": False,
                    "message": f"{display_name} API测试失败: HTTP {response.status_code}"
                }

        except Exception as e:
            return {
                "success": False,
                "message": f"{display_name} API测试异常: {str(e)}"
            }

    def _test_anthropic_api(self, api_key: str, display_name: str) -> dict:
        """测试Anthropic API"""
        try:
            import requests

            url = "https://api.anthropic.com/v1/messages"

            headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01"
            }

            data = {
                "model": "claude-3-haiku-20240307",
                "max_tokens": 50,
                "messages": [
                    {"role": "user", "content": "你好，请简单介绍一下你自己。"}
                ]
            }

            response = requests.post(url, json=data, headers=headers, timeout=10)

            if response.status_code == 200:
                result = response.json()
                if "content" in result and len(result["content"]) > 0:
                    content = result["content"][0]["text"]
                    if content and len(content.strip()) > 0:
                        return {
                            "success": True,
                            "message": f"{display_name} API连接测试成功"
                        }
                    else:
                        return {
                            "success": False,
                            "message": f"{display_name} API响应为空"
                        }
                else:
                    return {
                        "success": False,
                        "message": f"{display_name} API响应格式异常"
                    }
            else:
                return {
                    "success": False,
                    "message": f"{display_name} API测试失败: HTTP {response.status_code}"
                }

        except Exception as e:
            return {
                "success": False,
                "message": f"{display_name} API测试异常: {str(e)}"
            }

    def _test_qianfan_api(self, api_key: str, display_name: str) -> dict:
        """测试百度千帆API"""
        try:
            import requests

            # 千帆新一代API使用OpenAI兼容接口
            url = "https://qianfan.baidubce.com/v2/chat/completions"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }

            data = {
                "model": "ernie-3.5-8k",
                "messages": [
                    {"role": "user", "content": "你好，请简单介绍一下你自己。"}
                ],
                "max_tokens": 50,
                "temperature": 0.1
            }

            response = requests.post(url, json=data, headers=headers, timeout=15)

            if response.status_code == 200:
                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    if content and len(content.strip()) > 0:
                        return {
                            "success": True,
                            "message": f"{display_name} API连接测试成功"
                        }
                    else:
                        return {
                            "success": False,
                            "message": f"{display_name} API响应为空"
                        }
                else:
                    return {
                        "success": False,
                        "message": f"{display_name} API响应格式异常"
                    }
            elif response.status_code == 401:
                return {
                    "success": False,
                    "message": f"{display_name} API密钥无效或已过期"
                }
            elif response.status_code == 403:
                return {
                    "success": False,
                    "message": f"{display_name} API权限不足或配额已用完"
                }
            else:
                try:
                    error_detail = response.json()
                    error_msg = error_detail.get("error", {}).get("message", f"HTTP {response.status_code}")
                    return {
                        "success": False,
                        "message": f"{display_name} API测试失败: {error_msg}"
                    }
                except Exception as e:
                    logger.debug(f"解析API测试错误响应失败: {e}")
                    return {
                        "success": False,
                        "message": f"{display_name} API测试失败: HTTP {response.status_code}"
                    }

        except Exception as e:
            return {
                "success": False,
                "message": f"{display_name} API测试异常: {str(e)}"
            }

    def _test_openai_compatible_api(self, api_key: str, display_name: str, base_url: str = None, provider_name: str = None) -> dict:
        """测试 OpenAI 兼容 API（用于聚合渠道和自定义厂家）"""
        try:
            import requests

            # 如果没有提供 base_url，使用默认值
            if not base_url:
                return {
                    "success": False,
                    "message": f"{display_name} 未配置 API 基础地址 (default_base_url)"
                }

            # 🔧 智能版本号处理：只有在没有版本号的情况下才添加 /v1
            logger.info(f"   [测试API] 原始 base_url: {base_url}")
            base_url = base_url.rstrip("/")
            logger.info(f"   [测试API] 去除斜杠后: {base_url}")

            if not re.search(r'/v\d+$', base_url):
                # URL末尾没有版本号，添加 /v1（OpenAI标准）
                base_url = base_url + "/v1"
                logger.info(f"   [测试API] 添加 /v1 版本号: {base_url}")
            else:
                # URL已包含版本号（如 /v4），不添加
                logger.info(f"   [测试API] 检测到已有版本号，保持原样: {base_url}")

            url = f"{base_url}/chat/completions"
            logger.info(f"   [测试API] 最终请求URL: {url}")

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }

            # 🔥 根据不同厂家选择合适的测试模型
            test_model = "gpt-3.5-turbo"  # 默认模型
            if provider_name == "siliconflow":
                # 硅基流动使用免费的 Qwen 模型进行测试
                test_model = "Qwen/Qwen2.5-7B-Instruct"
                logger.info(f"🔍 硅基流动使用测试模型: {test_model}")
            elif provider_name == "zhipu":
                # 智谱AI使用 glm-4 模型进行测试
                test_model = "glm-4"
                logger.info(f"🔍 智谱AI使用测试模型: {test_model}")

            # 使用一个通用的模型名称进行测试
            data = {
                "model": test_model,
                "messages": [
                    {"role": "user", "content": "Hello, please respond with 'OK' if you can read this."}
                ],
                "max_tokens": 200,  # 增加到200，给推理模型（如o1/gpt-5）足够空间
                "temperature": 0.1
            }

            response = requests.post(url, json=data, headers=headers, timeout=15)

            if response.status_code == 200:
                result = response.json()
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    if content and len(content.strip()) > 0:
                        return {
                            "success": True,
                            "message": f"{display_name} API连接测试成功"
                        }
                    else:
                        return {
                            "success": False,
                            "message": f"{display_name} API响应为空"
                        }
                else:
                    return {
                        "success": False,
                        "message": f"{display_name} API响应格式异常"
                    }
            elif response.status_code == 401:
                return {
                    "success": False,
                    "message": f"{display_name} API密钥无效或已过期"
                }
            elif response.status_code == 403:
                return {
                    "success": False,
                    "message": f"{display_name} API权限不足或配额已用完"
                }
            else:
                try:
                    error_detail = response.json()
                    error_msg = error_detail.get("error", {}).get("message", f"HTTP {response.status_code}")
                    logger.error(f"❌ [{display_name}] API测试失败")
                    logger.error(f"   请求URL: {url}")
                    logger.error(f"   状态码: {response.status_code}")
                    logger.error(f"   错误详情: {error_detail}")
                    return {
                        "success": False,
                        "message": f"{display_name} API测试失败: {error_msg}"
                    }
                except Exception as e:
                    logger.debug(f"解析API测试错误详情失败: {e}")
                    logger.error(f"❌ [{display_name}] API测试失败")
                    logger.error(f"   请求URL: {url}")
                    logger.error(f"   状态码: {response.status_code}")
                    logger.error(f"   响应内容: {response.text[:500]}")
                    return {
                        "success": False,
                        "message": f"{display_name} API测试失败: HTTP {response.status_code}"
                    }

        except Exception as e:
            return {
                "success": False,
                "message": f"{display_name} API测试异常: {str(e)}"
            }

    # ==================== 厂家模型获取 ====================

    async def fetch_provider_models(self, provider_id: str) -> dict:
        """从厂家 API 获取模型列表"""
        try:
            logger.info(f"🔍 获取厂家模型列表 - provider_id: {provider_id}")

            db = await self._get_db()
            providers_collection = db.llm_providers

            # 兼容处理：尝试 ObjectId 和字符串两种类型
            provider_data = None
            try:
                provider_data = await providers_collection.find_one({"_id": ObjectId(provider_id)})
            except Exception as e:
                logger.debug(f"ObjectId查询失败: {e}")
                pass

            if not provider_data:
                provider_data = await providers_collection.find_one({"_id": provider_id})

            if not provider_data:
                return {
                    "success": False,
                    "message": f"厂家不存在 (ID: {provider_id})"
                }

            provider_name = provider_data.get("name")
            api_key = provider_data.get("api_key")
            base_url = provider_data.get("default_base_url")
            display_name = provider_data.get("display_name", provider_name)

            # 为了支持本地AI模型，直接使用数据库配置的API Key（可以为空）
            logger.info(f"✅ 使用数据库配置的 {display_name} API密钥 (长度: {len(api_key) if api_key else 0})")

            if not base_url:
                return {
                    "success": False,
                    "message": f"{display_name} 未配置 API 基础地址 (default_base_url)"
                }

            # 调用 OpenAI 兼容的 /v1/models 端点
            result = await asyncio.get_running_loop().run_in_executor(
                None, self._fetch_models_from_api, api_key, base_url, display_name
            )

            # 成功获取后同步更新 model_catalog 集合
            if result.get("success") and result.get("models"):
                try:
                    from app.models.config import ModelCatalog, ModelInfo

                    catalog_models = []
                    for m in result["models"]:
                        catalog_models.append(ModelInfo(
                            name=m.get("id") or m.get("name", ""),
                            display_name=m.get("name") or m.get("id", ""),
                            context_length=m.get("context_length"),
                            input_price_per_1k=m.get("input_price_per_1k"),
                            output_price_per_1k=m.get("output_price_per_1k"),
                        ))

                    catalog = ModelCatalog(
                        provider=provider_name,
                        provider_name=display_name,
                        models=catalog_models,
                    )

                    db = await self._get_db()
                    catalog.updated_at = now_tz()
                    await db.model_catalog.replace_one(
                        {"provider": provider_name},
                        catalog.model_dump(by_alias=True, exclude={"id"}),
                        upsert=True,
                    )
                    logger.info(f"✅ 已更新 {display_name} 模型目录: {len(catalog_models)} 个模型")
                except Exception as e:
                    logger.warning(f"更新模型目录失败: {e}")

            return result

        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            logger.error("获取模型列表失败", exc_info=True)
            return {
                "success": False,
                "message": f"获取模型列表失败: {str(e)}"
            }

    def _fetch_models_from_api(self, api_key: str, base_url: str, display_name: str) -> dict:
        """从 API 获取模型列表"""
        try:
            import requests

            base_url = base_url.rstrip("/")
            if not re.search(r'/v\d+$', base_url):
                # URL末尾没有版本号，添加 /v1（OpenAI标准）
                base_url = base_url + "/v1"
                logger.info(f"   [获取模型列表] 添加 /v1 版本号: {base_url}")
            else:
                # URL已包含版本号（如 /v4），不添加
                logger.info(f"   [获取模型列表] 检测到已有版本号，保持原样: {base_url}")

            url = f"{base_url}/models"

            # 构建请求头
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
                logger.info(f"🔍 请求 URL: {url} (with API Key)")
            else:
                logger.info(f"🔍 请求 URL: {url} (without API Key)")

            response = requests.get(url, headers=headers, timeout=15)

            logger.info(f"📊 响应状态码: {response.status_code}")
            logger.info(f"📊 响应内容: {response.text[:500]}...")

            if response.status_code == 200:
                result = response.json()
                logger.info(f"📊 响应 JSON 结构: {list(result.keys())}")

                if "data" in result and isinstance(result["data"], list):
                    all_models = result["data"]
                    logger.info(f"📊 API 返回 {len(all_models)} 个模型")

                    # 打印前几个模型的完整结构（用于调试价格字段）
                    if all_models:
                        logger.info("🔍 第一个模型的完整结构:")
                        import json
                        logger.info(json.dumps(all_models[0], indent=2, ensure_ascii=False))

                    # 打印所有 Anthropic 模型（用于调试）
                    anthropic_models = [m for m in all_models if "anthropic" in m.get("id", "").lower()]
                    if anthropic_models:
                        logger.info(f"🔍 Anthropic 模型列表 ({len(anthropic_models)} 个):")
                        for m in anthropic_models[:20]:  # 只打印前 20 个
                            logger.info(f"   - {m.get('id')}")

                    # 过滤：只保留主流大厂的常用模型
                    filtered_models = self._filter_models(all_models)
                    logger.info(f"✅ 过滤后保留 {len(filtered_models)} 个常用模型")

                    # 转换模型格式，包含价格信息
                    formatted_models = self._format_models_with_pricing(filtered_models)

                    return {
                        "success": True,
                        "models": formatted_models,
                        "message": f"成功获取 {len(formatted_models)} 个常用模型（已过滤）"
                    }
                else:
                    logger.error("❌ 响应格式异常，期望 'data' 字段为列表")
                    return {
                        "success": False,
                        "message": f"{display_name} API 响应格式异常（缺少 data 字段或格式不正确）"
                    }
            elif response.status_code == 401:
                return {
                    "success": False,
                    "message": f"{display_name} API密钥无效或已过期"
                }
            elif response.status_code == 403:
                return {
                    "success": False,
                    "message": f"{display_name} API权限不足"
                }
            else:
                try:
                    error_detail = response.json()
                    error_msg = error_detail.get("error", {}).get("message", f"HTTP {response.status_code}")
                    logger.error(f"❌ API 错误: {error_msg}")
                    return {
                        "success": False,
                        "message": f"{display_name} API请求失败: {error_msg}"
                    }
                except Exception as e:
                    logger.debug(f"解析API请求错误响应失败: {e}")
                    return {
                        "success": False,
                        "message": f"{display_name} API请求失败: HTTP {response.status_code}, 响应: {response.text[:200]}"
                    }

        except Exception as e:
            logger.error(f"❌ 异常: {e}")
            logger.error("API请求异常", exc_info=True)
            return {
                "success": False,
                "message": f"{display_name} API请求异常: {str(e)}"
            }

    def _format_models_with_pricing(self, models: list) -> list:
        """
        格式化模型列表，包含价格信息

        支持多种价格格式：
        1. OpenRouter: pricing.prompt/completion (USD per token)
        2. 302.ai: price.prompt/completion 或 price.input/output
        3. 其他: 可能没有价格信息
        """
        formatted = []
        for model in models:
            model_id = model.get("id", "")
            model_name = model.get("name", model_id)

            # 尝试从多个字段获取价格信息
            input_price_per_1k = None
            output_price_per_1k = None

            # 方式1：OpenRouter 格式 (pricing.prompt/completion)
            pricing = model.get("pricing", {})
            if pricing:
                prompt_price = pricing.get("prompt", "0")  # USD per token
                completion_price = pricing.get("completion", "0")  # USD per token

                try:
                    if prompt_price and float(prompt_price) > 0:
                        input_price_per_1k = float(prompt_price) * 1000
                    if completion_price and float(completion_price) > 0:
                        output_price_per_1k = float(completion_price) * 1000
                except (ValueError, TypeError):
                    pass

            # 方式2：302.ai 格式 (price.prompt/completion 或 price.input/output)
            if not input_price_per_1k and not output_price_per_1k:
                price = model.get("price", {})
                if price and isinstance(price, dict):
                    # 尝试 prompt/completion 字段
                    prompt_price = price.get("prompt") or price.get("input")
                    completion_price = price.get("completion") or price.get("output")

                    try:
                        if prompt_price and float(prompt_price) > 0:
                            # 假设是 per token，转换为 per 1K tokens
                            input_price_per_1k = float(prompt_price) * 1000
                        if completion_price and float(completion_price) > 0:
                            output_price_per_1k = float(completion_price) * 1000
                    except (ValueError, TypeError):
                        pass

            # 获取上下文长度
            context_length = model.get("context_length")
            if not context_length:
                # 尝试从 top_provider 获取
                top_provider = model.get("top_provider", {})
                context_length = top_provider.get("context_length")

            # 如果还是没有，尝试从 max_completion_tokens 推断
            if not context_length:
                max_tokens = model.get("max_completion_tokens")
                if max_tokens and max_tokens > 0:
                    # 通常上下文长度是最大输出的 4-8 倍
                    context_length = max_tokens * 4

            formatted_model = {
                "id": model_id,
                "name": model_name,
                "context_length": context_length,
                "input_price_per_1k": input_price_per_1k,
                "output_price_per_1k": output_price_per_1k,
            }

            formatted.append(formatted_model)

            # 打印价格信息（用于调试）
            if input_price_per_1k or output_price_per_1k:
                logger.info(f"💰 {model_id}: 输入=${input_price_per_1k:.6f}/1K, 输出=${output_price_per_1k:.6f}/1K")

        return formatted

    def _filter_models(self, models: list) -> list:
        """过滤模型列表，去除明显的变体/中间版本，保留可用的基础模型"""
        exclude_keywords = [
            ":free",
            ":extended",
            ":nitro",
            "-free",
            "-preview",
            "-experimental",
            "-alpha",
            "-beta",
            "-online",
            "-instruct",
        ]

        filtered = []
        for model in models:
            model_id = model.get("id", "")
            model_id_lower = model_id.lower()

            # 跳过排除关键词
            if any(kw in model_id_lower for kw in exclude_keywords):
                continue

            # 跳过内部/系统模型（以 . 或 _ 开头的通常是嵌入/特殊用途）
            if model_id.startswith(".") or model_id.startswith("_"):
                continue

            filtered.append(model)

        # 去重（某些 API 返回重复模型）
        seen = set()
        unique = []
        for m in filtered:
            mid = m.get("id", "")
            if mid not in seen:
                seen.add(mid)
                unique.append(m)

        return unique
