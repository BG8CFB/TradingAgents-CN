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

    async def init_default_model_catalog(self, force: bool = False) -> bool:
        """从厂家 API 动态获取模型列表并初始化/更新模型目录

        Args:
            force: 为 True 时强制刷新所有厂家的模型列表（覆盖已有目录）
        """
        try:
            db = await self._get_db()
            catalog_collection = db.model_catalog

            # 获取所有已启用的厂家
            providers_collection = db.llm_providers
            providers_data = await providers_collection.find({"is_active": True}).to_list(None)

            if not providers_data:
                logger.info("没有已启用的厂家，跳过模型目录初始化")
                return True

            import requests
            import re
            initialized_count = 0

            for provider_data in providers_data:
                provider_name = provider_data.get("name")
                display_name = provider_data.get("display_name", provider_name)
                base_url = provider_data.get("default_base_url")
                api_key = provider_data.get("api_key")

                if not base_url:
                    logger.info(f"跳过 {display_name}：未配置 API 地址")
                    continue

                # 已有目录的厂家：仅在 force 模式下刷新
                existing = await catalog_collection.find_one({"provider": provider_name})
                if existing and not force:
                    logger.info(f"跳过 {display_name}：模型目录已存在")
                    continue

                try:
                    # 从厂家 API 拉取模型列表
                    url = base_url.rstrip("/")
                    if not re.search(r'/v\d+$', url):
                        url = url + "/v1"
                    url = f"{url}/models"

                    headers = {}
                    if api_key:
                        headers["Authorization"] = f"Bearer {api_key}"

                    resp = requests.get(url, headers=headers, timeout=15)

                    if resp.status_code != 200:
                        logger.warning(f"获取 {display_name} 模型列表失败: HTTP {resp.status_code}")
                        continue

                    result = resp.json()
                    models_data = result.get("data", [])
                    if not isinstance(models_data, list) or len(models_data) == 0:
                        logger.warning(f"{display_name} 返回空模型列表")
                        continue

                    # 去重并限制数量
                    seen = set()
                    models = []
                    for m in models_data:
                        mid = m.get("id", "")
                        if not mid or mid in seen:
                            continue
                        seen.add(mid)
                        models.append(ModelInfo(
                            name=mid,
                            display_name=mid,
                            description=f"{display_name} 模型",
                            context_length=m.get("context_length"),
                        ))
                        if len(models) >= 200:
                            break

                    catalog = ModelCatalog(
                        provider=provider_name,
                        provider_name=display_name,
                        models=models,
                    )
                    await self.save_model_catalog(catalog)
                    initialized_count += 1
                    logger.info(f"✅ 初始化 {display_name} 模型目录: {len(models)} 个模型")

                except Exception as e:
                    logger.warning(f"获取 {display_name} 模型失败: {e}")
                    continue

            logger.info(f"模型目录初始化完成: 共 {initialized_count} 个厂家")
            return True
        except Exception as e:
            logger.error(f"初始化模型目录失败: {e}", exc_info=True)
            return False

    async def get_available_models(self) -> List[Dict[str, Any]]:
        """获取可用的模型列表（从数据库读取，如果为空则从 API 动态获取）"""
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
            logger.error(f"获取模型列表失败: {e}")
            return []
