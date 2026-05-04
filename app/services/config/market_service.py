"""
市场分类与模型目录管理服务
"""

import logging
from typing import List, Dict, Any, Optional

from app.core.database import get_mongo_db
from app.models.config import (
    MarketCategory, ModelCatalog, ModelInfo
)
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)


class MarketService:
    """市场分类与模型目录管理"""

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

    # ==================== 市场分类管理 ====================

    async def get_market_categories(self) -> List[MarketCategory]:
        """获取所有市场分类"""
        try:
            db = await self._get_db()
            categories_collection = db.market_categories

            categories_data = await categories_collection.find({}).to_list(length=None)
            categories = [MarketCategory(**data) for data in categories_data]

            # 如果没有分类，创建默认分类
            if not categories:
                categories = await self._create_default_market_categories()

            # 按排序顺序排列
            categories.sort(key=lambda x: x.sort_order)
            return categories
        except Exception as e:
            print(f"❌ 获取市场分类失败: {e}")
            return []

    async def _create_default_market_categories(self) -> List[MarketCategory]:
        """创建默认市场分类"""
        default_categories = [
            MarketCategory(
                id="a_shares",
                name="a_shares",
                display_name="A股",
                description="中国A股市场数据源",
                enabled=True,
                sort_order=1
            ),
            MarketCategory(
                id="us_stocks",
                name="us_stocks",
                display_name="美股",
                description="美国股票市场数据源",
                enabled=True,
                sort_order=2
            ),
            MarketCategory(
                id="hk_stocks",
                name="hk_stocks",
                display_name="港股",
                description="香港股票市场数据源",
                enabled=True,
                sort_order=3
            ),
            MarketCategory(
                id="crypto",
                name="crypto",
                display_name="数字货币",
                description="数字货币市场数据源",
                enabled=True,
                sort_order=4
            ),
            MarketCategory(
                id="futures",
                name="futures",
                display_name="期货",
                description="期货市场数据源",
                enabled=True,
                sort_order=5
            )
        ]

        # 保存到数据库
        db = await self._get_db()
        categories_collection = db.market_categories

        for category in default_categories:
            await categories_collection.insert_one(category.model_dump())

        return default_categories

    async def add_market_category(self, category: MarketCategory) -> bool:
        """添加市场分类"""
        try:
            db = await self._get_db()
            categories_collection = db.market_categories

            # 检查ID是否已存在
            existing = await categories_collection.find_one({"id": category.id})
            if existing:
                return False

            await categories_collection.insert_one(category.model_dump())
            return True
        except Exception as e:
            print(f"❌ 添加市场分类失败: {e}")
            return False

    async def update_market_category(self, category_id: str, updates: Dict[str, Any]) -> bool:
        """更新市场分类"""
        try:
            db = await self._get_db()
            categories_collection = db.market_categories

            updates["updated_at"] = now_tz()
            result = await categories_collection.update_one(
                {"id": category_id},
                {"$set": updates}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"❌ 更新市场分类失败: {e}")
            return False

    async def delete_market_category(self, category_id: str) -> bool:
        """删除市场分类"""
        try:
            db = await self._get_db()
            categories_collection = db.market_categories
            groupings_collection = db.datasource_groupings

            # 检查是否有数据源使用此分类
            groupings_count = await groupings_collection.count_documents(
                {"market_category_id": category_id}
            )
            if groupings_count > 0:
                return False

            result = await categories_collection.delete_one({"id": category_id})
            return result.deleted_count > 0
        except Exception as e:
            print(f"❌ 删除市场分类失败: {e}")
            return False

    # ========== 模型目录管理 ==========

    async def get_model_catalog(self) -> List[ModelCatalog]:
        """获取所有模型目录"""
        try:
            db = await self._get_db()
            catalog_collection = db.model_catalog

            catalogs = []
            async for doc in catalog_collection.find():
                catalogs.append(ModelCatalog(**doc))

            return catalogs
        except Exception as e:
            print(f"获取模型目录失败: {e}")
            return []

    async def get_provider_models(self, provider: str) -> Optional[ModelCatalog]:
        """获取指定厂家的模型目录"""
        try:
            db = await self._get_db()
            catalog_collection = db.model_catalog

            doc = await catalog_collection.find_one({"provider": provider})
            if doc:
                return ModelCatalog(**doc)
            return None
        except Exception as e:
            print(f"获取厂家模型目录失败: {e}")
            return None

    async def save_model_catalog(self, catalog: ModelCatalog) -> bool:
        """保存或更新模型目录"""
        try:
            db = await self._get_db()
            catalog_collection = db.model_catalog

            catalog.updated_at = now_tz()

            # 更新或插入
            result = await catalog_collection.replace_one(
                {"provider": catalog.provider},
                catalog.model_dump(by_alias=True, exclude={"id"}),
                upsert=True
            )

            return result.acknowledged
        except Exception as e:
            print(f"保存模型目录失败: {e}")
            return False

    async def delete_model_catalog(self, provider: str) -> bool:
        """删除模型目录"""
        try:
            db = await self._get_db()
            catalog_collection = db.model_catalog

            result = await catalog_collection.delete_one({"provider": provider})
            return result.deleted_count > 0
        except Exception as e:
            print(f"删除模型目录失败: {e}")
            return False

    async def init_default_model_catalog(self) -> bool:
        """初始化默认模型目录"""
        try:
            db = await self._get_db()
            catalog_collection = db.model_catalog

            # 检查是否已有数据
            count = await catalog_collection.count_documents({})
            if count > 0:
                print("模型目录已存在，跳过初始化")
                return True

            # 创建默认目录
            default_catalogs = self._get_default_model_catalog()

            for catalog_data in default_catalogs:
                catalog = ModelCatalog(**catalog_data)
                await self.save_model_catalog(catalog)

            print(f"✅ 初始化了 {len(default_catalogs)} 个厂家的模型目录")
            return True
        except Exception as e:
            print(f"初始化模型目录失败: {e}")
            return False

    def _get_default_model_catalog(self) -> List[Dict[str, Any]]:
        """获取默认模型目录数据"""
        return [
            {
                "provider": "dashscope",
                "provider_name": "通义千问",
                "models": [
                    {
                        "name": "qwen-turbo",
                        "display_name": "Qwen Turbo - 快速经济 (1M上下文)",
                        "input_price_per_1k": 0.0003,
                        "output_price_per_1k": 0.0003,
                        "context_length": 1000000,
                        "currency": "CNY",
                        "description": "Qwen2.5-Turbo，支持100万tokens超长上下文"
                    },
                    {
                        "name": "qwen-plus",
                        "display_name": "Qwen Plus - 平衡推荐",
                        "input_price_per_1k": 0.0008,
                        "output_price_per_1k": 0.002,
                        "context_length": 32768,
                        "currency": "CNY"
                    },
                    {
                        "name": "qwen-plus-latest",
                        "display_name": "Qwen Plus Latest - 最新平衡",
                        "input_price_per_1k": 0.0008,
                        "output_price_per_1k": 0.002,
                        "context_length": 32768,
                        "currency": "CNY"
                    },
                    {
                        "name": "qwen-max",
                        "display_name": "Qwen Max - 最强性能",
                        "input_price_per_1k": 0.02,
                        "output_price_per_1k": 0.06,
                        "context_length": 8192,
                        "currency": "CNY"
                    },
                    {
                        "name": "qwen-max-latest",
                        "display_name": "Qwen Max Latest - 最新旗舰",
                        "input_price_per_1k": 0.02,
                        "output_price_per_1k": 0.06,
                        "context_length": 8192,
                        "currency": "CNY"
                    },
                    {
                        "name": "qwen-long",
                        "display_name": "Qwen Long - 长文本",
                        "input_price_per_1k": 0.0005,
                        "output_price_per_1k": 0.002,
                        "context_length": 1000000,
                        "currency": "CNY"
                    },
                    {
                        "name": "qwen-vl-plus",
                        "display_name": "Qwen VL Plus - 视觉理解",
                        "input_price_per_1k": 0.008,
                        "output_price_per_1k": 0.008,
                        "context_length": 8192,
                        "currency": "CNY"
                    },
                    {
                        "name": "qwen-vl-max",
                        "display_name": "Qwen VL Max - 视觉旗舰",
                        "input_price_per_1k": 0.02,
                        "output_price_per_1k": 0.02,
                        "context_length": 8192,
                        "currency": "CNY"
                    }
                ]
            },
            {
                "provider": "openai",
                "provider_name": "OpenAI",
                "models": [
                    {
                        "name": "gpt-4o",
                        "display_name": "GPT-4o - 最新旗舰",
                        "input_price_per_1k": 0.005,
                        "output_price_per_1k": 0.015,
                        "context_length": 128000,
                        "currency": "USD"
                    },
                    {
                        "name": "gpt-4o-mini",
                        "display_name": "GPT-4o Mini - 轻量旗舰",
                        "input_price_per_1k": 0.00015,
                        "output_price_per_1k": 0.0006,
                        "context_length": 128000,
                        "currency": "USD"
                    },
                    {
                        "name": "gpt-4-turbo",
                        "display_name": "GPT-4 Turbo - 强化版",
                        "input_price_per_1k": 0.01,
                        "output_price_per_1k": 0.03,
                        "context_length": 128000,
                        "currency": "USD"
                    },
                    {
                        "name": "gpt-4",
                        "display_name": "GPT-4 - 经典版",
                        "input_price_per_1k": 0.03,
                        "output_price_per_1k": 0.06,
                        "context_length": 8192,
                        "currency": "USD"
                    },
                    {
                        "name": "gpt-3.5-turbo",
                        "display_name": "GPT-3.5 Turbo - 经济版",
                        "input_price_per_1k": 0.0005,
                        "output_price_per_1k": 0.0015,
                        "context_length": 16385,
                        "currency": "USD"
                    }
                ]
            },
            {
                "provider": "google",
                "provider_name": "Google Gemini",
                "models": [
                    {
                        "name": "gemini-2.5-pro",
                        "display_name": "Gemini 2.5 Pro - 最新旗舰",
                        "input_price_per_1k": 0.00125,
                        "output_price_per_1k": 0.005,
                        "context_length": 1000000,
                        "currency": "USD"
                    },
                    {
                        "name": "gemini-2.5-flash",
                        "display_name": "Gemini 2.5 Flash - 最新快速",
                        "input_price_per_1k": 0.000075,
                        "output_price_per_1k": 0.0003,
                        "context_length": 1000000,
                        "currency": "USD"
                    },
                    {
                        "name": "gemini-1.5-pro",
                        "display_name": "Gemini 1.5 Pro - 专业版",
                        "input_price_per_1k": 0.00125,
                        "output_price_per_1k": 0.005,
                        "context_length": 2000000,
                        "currency": "USD"
                    },
                    {
                        "name": "gemini-1.5-flash",
                        "display_name": "Gemini 1.5 Flash - 快速版",
                        "input_price_per_1k": 0.000075,
                        "output_price_per_1k": 0.0003,
                        "context_length": 1000000,
                        "currency": "USD"
                    }
                ]
            },
            {
                "provider": "deepseek",
                "provider_name": "DeepSeek",
                "models": [
                    {
                        "name": "deepseek-chat",
                        "display_name": "DeepSeek Chat - 通用对话",
                        "input_price_per_1k": 0.0001,
                        "output_price_per_1k": 0.0002,
                        "context_length": 32768,
                        "currency": "CNY"
                    },
                    {
                        "name": "deepseek-coder",
                        "display_name": "DeepSeek Coder - 代码专用",
                        "input_price_per_1k": 0.0001,
                        "output_price_per_1k": 0.0002,
                        "context_length": 16384,
                        "currency": "CNY"
                    }
                ]
            },
            {
                "provider": "anthropic",
                "provider_name": "Anthropic Claude",
                "models": [
                    {
                        "name": "claude-3-5-sonnet-20241022",
                        "display_name": "Claude 3.5 Sonnet - 当前旗舰",
                        "input_price_per_1k": 0.003,
                        "output_price_per_1k": 0.015,
                        "context_length": 200000,
                        "currency": "USD"
                    },
                    {
                        "name": "claude-3-5-sonnet-20240620",
                        "display_name": "Claude 3.5 Sonnet (旧版)",
                        "input_price_per_1k": 0.003,
                        "output_price_per_1k": 0.015,
                        "context_length": 200000,
                        "currency": "USD"
                    },
                    {
                        "name": "claude-3-opus-20240229",
                        "display_name": "Claude 3 Opus - 强大性能",
                        "input_price_per_1k": 0.015,
                        "output_price_per_1k": 0.075,
                        "context_length": 200000,
                        "currency": "USD"
                    },
                    {
                        "name": "claude-3-sonnet-20240229",
                        "display_name": "Claude 3 Sonnet - 平衡版",
                        "input_price_per_1k": 0.003,
                        "output_price_per_1k": 0.015,
                        "context_length": 200000,
                        "currency": "USD"
                    },
                    {
                        "name": "claude-3-haiku-20240307",
                        "display_name": "Claude 3 Haiku - 快速版",
                        "input_price_per_1k": 0.00025,
                        "output_price_per_1k": 0.00125,
                        "context_length": 200000,
                        "currency": "USD"
                    }
                ]
            },
            {
                "provider": "qianfan",
                "provider_name": "百度千帆",
                "models": [
                    {
                        "name": "ernie-3.5-8k",
                        "display_name": "ERNIE 3.5 8K - 快速高效",
                        "input_price_per_1k": 0.0012,
                        "output_price_per_1k": 0.0012,
                        "context_length": 8192,
                        "currency": "CNY"
                    },
                    {
                        "name": "ernie-4.0-turbo-8k",
                        "display_name": "ERNIE 4.0 Turbo 8K - 强大推理",
                        "input_price_per_1k": 0.03,
                        "output_price_per_1k": 0.09,
                        "context_length": 8192,
                        "currency": "CNY"
                    },
                    {
                        "name": "ERNIE-Speed-8K",
                        "display_name": "ERNIE Speed 8K - 极速响应",
                        "input_price_per_1k": 0.0004,
                        "output_price_per_1k": 0.0004,
                        "context_length": 8192,
                        "currency": "CNY"
                    },
                    {
                        "name": "ERNIE-Lite-8K",
                        "display_name": "ERNIE Lite 8K - 轻量经济",
                        "input_price_per_1k": 0.0003,
                        "output_price_per_1k": 0.0006,
                        "context_length": 8192,
                        "currency": "CNY"
                    }
                ]
            },
            {
                "provider": "zhipu",
                "provider_name": "智谱AI",
                "models": [
                    {
                        "name": "glm-4",
                        "display_name": "GLM-4 - 旗舰版",
                        "input_price_per_1k": 0.1,
                        "output_price_per_1k": 0.1,
                        "context_length": 128000,
                        "currency": "CNY"
                    },
                    {
                        "name": "glm-4-plus",
                        "display_name": "GLM-4 Plus - 增强版",
                        "input_price_per_1k": 0.05,
                        "output_price_per_1k": 0.05,
                        "context_length": 128000,
                        "currency": "CNY"
                    },
                    {
                        "name": "glm-3-turbo",
                        "display_name": "GLM-3 Turbo - 快速版",
                        "input_price_per_1k": 0.001,
                        "output_price_per_1k": 0.001,
                        "context_length": 128000,
                        "currency": "CNY"
                    }
                ]
            }
        ]

    async def get_available_models(self) -> List[Dict[str, Any]]:
        """获取可用的模型列表（从数据库读取，如果为空则返回默认数据）"""
        try:
            catalogs = await self.get_model_catalog()

            # 如果数据库中没有数据，初始化默认目录
            if not catalogs:
                print("📦 模型目录为空，初始化默认目录...")
                await self.init_default_model_catalog()
                catalogs = await self.get_model_catalog()

            # 转换为API响应格式
            result = []
            for catalog in catalogs:
                result.append({
                    "provider": catalog.provider,
                    "provider_name": catalog.provider_name,
                    "models": [
                        {
                            "name": model.name,
                            "display_name": model.display_name,
                            "description": model.description,
                            "context_length": model.context_length,
                            "input_price_per_1k": model.input_price_per_1k,
                            "output_price_per_1k": model.output_price_per_1k,
                            "is_deprecated": model.is_deprecated
                        }
                        for model in catalog.models
                    ]
                })

            return result
        except Exception as e:
            print(f"获取模型列表失败: {e}")
            # 失败时返回默认数据
            return self._get_default_model_catalog()
