"""
股票分析服务
整合了原 simple_analysis_service.py 和 analysis_service.py 的功能
"""

import asyncio
import atexit
import uuid
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
import concurrent.futures
import os

from app.engine.graph.trading_graph import TradingAgentsGraph
from app.engine.default_config import DEFAULT_CONFIG
from app.utils.runtime_paths import get_analysis_results_dir
from app.data.core.interface import DataInterface
from app.utils.stock_utils import StockUtils
from app.utils.dataflow_utils import get_trading_date_range

from app.models.analysis import (
    AnalysisParameters, AnalysisTask, AnalysisBatch,
    AnalysisStatus, BatchStatus, SingleAnalysisRequest, BatchAnalysisRequest
)
from app.models.user import PyObjectId
from app.models.notification import NotificationCreate
from bson import ObjectId
from app.core.database import get_mongo_db, get_mongo_db_sync, get_redis_client
from app.services.queue_service import QueueService
from app.services.usage_statistics_service import UsageStatisticsService
from app.services.progress.tracker import RedisProgressTracker, get_progress_by_id
from app.services.config_service import config_service
from app.services.config_provider import provider as config_provider
from app.services.memory_state_manager import get_memory_state_manager, TaskStatus
from app.services.progress.log_handler import register_analysis_tracker, unregister_analysis_tracker
from app.services.websocket_manager import get_websocket_manager
from app.core.config import settings
from app.utils.timezone import now_utc, now_config_tz, format_date_short, format_iso
from app.engine.tools.mcp import LANGCHAIN_MCP_AVAILABLE, get_mcp_loader_factory

# 设置日志
logger = logging.getLogger("app.services.analysis_service")

# config_service imported from app.services.config_service (facade singleton)

# 股票基础信息获取（用于补充显示名称）
try:
    _di = DataInterface.get_instance()
    def _get_stock_info_safe(stock_code: str):
        """获取股票基础信息的安全封装"""
        import asyncio
        try:
            loop = None
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = None
            except RuntimeError:
                pass
            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        _di.read("CN", "basic_info", symbol=stock_code)
                    ).result()
            else:
                result = asyncio.run(_di.read("CN", "basic_info", symbol=stock_code))
            return result.get("data")
        except Exception:
            return None
except Exception:
    _get_stock_info_safe = None

# -----------------------------------------------------------------------------
# Helper Functions (from simple_analysis_service.py)
# -----------------------------------------------------------------------------

async def get_provider_by_model_name(model_name: str) -> str:
    """
    根据模型名称从数据库配置中查找对应的供应商（异步版本）
    """
    try:
        # 从配置服务获取系统配置
        system_config = await config_service.get_system_config()
        if not system_config or not system_config.llm_configs:
            logger.warning("⚠️ 系统配置为空，使用默认供应商映射")
            return _get_default_provider_by_model(model_name)

        # 在LLM配置中查找匹配的模型
        for llm_config in system_config.llm_configs:
            if llm_config.model_name == model_name:
                provider = llm_config.provider.value if hasattr(llm_config.provider, 'value') else str(llm_config.provider)
                logger.info(f"✅ 从数据库找到模型 {model_name} 的供应商: {provider}")
                return provider

        # 如果数据库中没有找到，使用默认映射
        logger.warning(f"⚠️ 数据库中未找到模型 {model_name}，使用默认映射")
        return _get_default_provider_by_model(model_name)

    except Exception as e:
        logger.error(f"❌ 查找模型供应商失败: {e}")
        return _get_default_provider_by_model(model_name)


def get_provider_by_model_name_sync(model_name: str) -> str:
    """
    根据模型名称从数据库配置中查找对应的供应商（同步版本）
    """
    provider_info = get_provider_and_url_by_model_sync(model_name)
    return provider_info["provider"]


def get_provider_and_url_by_model_sync(model_name: str) -> dict:
    """
    根据模型名称从数据库配置中查找对应的供应商和 API URL（同步版本）
    """
    try:
        db = get_mongo_db_sync()
        # 查询最新的活跃配置
        configs_collection = db.system_configs
        doc = configs_collection.find_one({"is_active": True}, sort=[("version", -1)])

        if doc and "llm_configs" in doc:
            llm_configs = doc["llm_configs"]

            for config_dict in llm_configs:
                if config_dict.get("model_name") == model_name:
                    provider = config_dict.get("provider")
                    api_base = config_dict.get("api_base")
                    model_api_key = config_dict.get("api_key")  # 🔥 获取模型配置的 API Key

                    # 从 llm_providers 集合中查找厂家配置
                    providers_collection = db.llm_providers
                    provider_doc = providers_collection.find_one({"name": provider})

                    # 🔥 确定 API Key（优先级：模型配置 > 厂家配置 > 环境变量）
                    api_key = None
                    if model_api_key and model_api_key.strip() and model_api_key != "your-api-key":
                        api_key = model_api_key
                        logger.info("✅ [同步查询] 使用模型配置的 API Key")
                    elif provider_doc and provider_doc.get("api_key"):
                        provider_api_key = provider_doc["api_key"]
                        if provider_api_key and provider_api_key.strip() and provider_api_key != "your-api-key":
                            api_key = provider_api_key
                            logger.info("✅ [同步查询] 使用厂家配置的 API Key")

                    # 如果数据库中没有有效的 API Key，尝试从环境变量获取
                    if not api_key:
                        api_key = _get_env_api_key_for_provider(provider)
                        if api_key:
                            logger.info("✅ [同步查询] 使用环境变量的 API Key")
                        else:
                            logger.warning(f"⚠️ [同步查询] 未找到 {provider} 的 API Key")

                    # 确定 backend_url
                    backend_url = None
                    if api_base:
                        backend_url = api_base
                        logger.info(f"✅ [同步查询] 模型 {model_name} 使用自定义 API: {api_base}")
                    elif provider_doc and provider_doc.get("default_base_url"):
                        backend_url = provider_doc["default_base_url"]
                        logger.info(f"✅ [同步查询] 模型 {model_name} 使用厂家默认 API: {backend_url}")
                    else:
                        backend_url = _get_default_backend_url(provider)
                        logger.warning(f"⚠️ [同步查询] 厂家 {provider} 没有配置 default_base_url，使用硬编码默认值")

                    return {
                        "provider": provider,
                        "backend_url": backend_url,
                        "api_key": api_key
                    }

        # 如果数据库中没有找到模型配置，使用默认映射
        logger.warning(f"⚠️ [同步查询] 数据库中未找到模型 {model_name}，使用默认映射")
        provider = _get_default_provider_by_model(model_name)

        # 尝试从厂家配置中获取 default_base_url 和 API Key
        try:
            providers_collection = db.llm_providers
            provider_doc = providers_collection.find_one({"name": provider})

            backend_url = _get_default_backend_url(provider)
            api_key = None

            if provider_doc:
                if provider_doc.get("default_base_url"):
                    backend_url = provider_doc["default_base_url"]
                    logger.info(f"✅ [同步查询] 使用厂家 {provider} 的 default_base_url: {backend_url}")

                if provider_doc.get("api_key"):
                    provider_api_key = provider_doc["api_key"]
                    if provider_api_key and provider_api_key.strip() and provider_api_key != "your-api-key":
                        api_key = provider_api_key
                        logger.info(f"✅ [同步查询] 使用厂家 {provider} 的 API Key")

            # 如果厂家配置中没有 API Key，尝试从环境变量获取
            if not api_key:
                api_key = _get_env_api_key_for_provider(provider)
                if api_key:
                    logger.info("✅ [同步查询] 使用环境变量的 API Key")

            return {
                "provider": provider,
                "backend_url": backend_url,
                "api_key": api_key
            }
        except Exception as e:
            logger.warning(f"⚠️ [同步查询] 无法查询厂家配置: {e}")

        # 最后回退到硬编码的默认 URL 和环境变量 API Key
        return {
            "provider": provider,
            "backend_url": _get_default_backend_url(provider),
            "api_key": _get_env_api_key_for_provider(provider)
        }
    except Exception as e:
        logger.error(f"❌ [同步查询] 查找模型供应商失败: {e}")
        provider = _get_default_provider_by_model(model_name)
        return {
            "provider": provider,
            "backend_url": _get_default_backend_url(provider),
            "api_key": _get_env_api_key_for_provider(provider)
        }


def _get_env_api_key_for_provider(provider: str) -> str:
    """从环境变量获取指定供应商的 API Key"""
    env_key_map = {
        "google": "GOOGLE_API_KEY",
        "dashscope": "DASHSCOPE_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "siliconflow": "SILICONFLOW_API_KEY",
        "qianfan": "QIANFAN_API_KEY",
        "302ai": "AI302_API_KEY",
    }

    env_key_name = env_key_map.get(provider.lower())
    if env_key_name:
        api_key = os.getenv(env_key_name)
        if api_key and api_key.strip() and api_key != "your-api-key":
            return api_key

    return None


def _get_default_backend_url(provider: str) -> str:
    """根据供应商名称返回默认的 backend_url"""
    default_urls = {
        "google": "https://generativelanguage.googleapis.com/v1beta",
        "dashscope": "https://dashscope.aliyuncs.com/api/v1",
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com",
        "anthropic": "https://api.anthropic.com",
        "openrouter": "https://openrouter.ai/api/v1",
        "qianfan": "https://qianfan.baidubce.com/v2",
        "302ai": "https://api.302.ai/v1",
    }

    url = default_urls.get(provider, "https://dashscope.aliyuncs.com/compatible-mode/v1")
    return url


def _get_default_provider_by_model(model_name: str) -> str:
    """根据模型名称返回默认的供应商映射"""
    model_provider_map = {
        'qwen-turbo': 'dashscope',
        'qwen-plus': 'dashscope',
        'qwen-max': 'dashscope',
        'qwen-plus-latest': 'dashscope',
        'qwen-max-longcontext': 'dashscope',
        'gpt-3.5-turbo': 'openai',
        'gpt-4': 'openai',
        'gpt-4-turbo': 'openai',
        'gpt-4o': 'openai',
        'gpt-4o-mini': 'openai',
        'gemini-pro': 'google',
        'gemini-2.0-flash': 'google',
        'gemini-2.0-flash-thinking-exp': 'google',
        'deepseek-chat': 'deepseek',
        'deepseek-coder': 'deepseek',
        'glm-4': 'zhipu',
        'glm-3-turbo': 'zhipu',
        'chatglm3-6b': 'zhipu'
    }
    provider = model_provider_map.get(model_name, 'dashscope')
    return provider


def create_analysis_config(
    selected_analysts: list,
    analyst_model: str,
    debate_model: str,
    llm_provider: str,
    market_type: str = "A股",
    analyst_model_config: dict = None,
    debate_model_config: dict = None,
) -> dict:
    """创建分析配置"""

    # 统一复制默认配置
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = llm_provider
    config["debate_llm"] = debate_model
    config["analyst_llm"] = analyst_model

    # 轮次由阶段配置决定
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["memory_enabled"] = True
    config["online_tools"] = True

    try:
        analyst_provider_info = get_provider_and_url_by_model_sync(analyst_model)
        debate_provider_info = get_provider_and_url_by_model_sync(debate_model)

        config["backend_url"] = analyst_provider_info["backend_url"]
        config["analyst_api_key"] = analyst_provider_info.get("api_key")
        config["debate_api_key"] = debate_provider_info.get("api_key")

        # 始终设置 per-model provider，让 create_llm() 精确路由
        config["analyst_provider"] = analyst_provider_info["provider"]
        config["debate_provider"] = debate_provider_info["provider"]
        config["analyst_backend_url"] = analyst_provider_info["backend_url"]
        config["debate_backend_url"] = debate_provider_info["backend_url"]
    except Exception as e:
        logger.warning(f"⚠️  无法从数据库获取 backend_url 和 API Key: {e}")
        config["backend_url"] = _get_default_backend_url(llm_provider)
        # 回退：使用传入的 llm_provider 作为两个模型的 provider
        config["analyst_provider"] = llm_provider
        config["debate_provider"] = llm_provider
        config["analyst_backend_url"] = config["backend_url"]
        config["debate_backend_url"] = config["backend_url"]

    config["selected_analysts"] = selected_analysts
    config["debug"] = False

    if analyst_model_config:
        config["analyst_model_config"] = analyst_model_config
    if debate_model_config:
        config["debate_model_config"] = debate_model_config

    # 阶段配置默认值（交易员始终执行）
    config.setdefault("phase2_enabled", False)
    config.setdefault("phase2_debate_rounds", 1)
    config.setdefault("phase3_enabled", False)
    config.setdefault("phase3_debate_rounds", 1)
    config.setdefault("phase4_enabled", True)
    config.setdefault("phase4_debate_rounds", 1)
    config.setdefault("max_debate_rounds", 1)
    config.setdefault("max_risk_discuss_rounds", 1)

    return config


# -----------------------------------------------------------------------------
# AnalysisService Class
# -----------------------------------------------------------------------------

class AnalysisService:
    """股票分析服务类 - 整合版"""

    def __init__(self):
        # 初始化组件
        self._trading_graph_cache = {}
        self.memory_manager = get_memory_state_manager()
        self._progress_trackers: Dict[str, RedisProgressTracker] = {}
        self._stock_name_cache: Dict[str, str] = {}
        # 线程池
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        atexit.register(self._shutdown_pool)
        logger.info("🔧 [服务初始化] 线程池最大并发数: 3")

        # 队列和统计服务
        try:
            redis_client = get_redis_client()
            self.queue_service = QueueService(redis_client)
            self.usage_service = UsageStatisticsService()
        except Exception as e:
            logger.warning(f"⚠️ 队列或统计服务初始化失败: {e}")

        # 设置 WebSocket 管理器
        try:
            self.memory_manager.set_websocket_manager(get_websocket_manager())
        except ImportError:
            logger.warning("⚠️ WebSocket 管理器不可用")

        logger.info(f"🔧 [服务初始化] AnalysisService 实例ID: {id(self)}")

    def _shutdown_pool(self):
        try:
            if self._thread_pool:
                self._thread_pool.shutdown(wait=False)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Private Methods
    # -------------------------------------------------------------------------

    async def _update_progress_async(self, task_id: str, progress: int, message: str):
        """异步更新进度（内存和MongoDB）"""
        try:
            await self.memory_manager.update_task_status(
                task_id=task_id,
                status=TaskStatus.RUNNING,
                progress=progress,
                message=message,
                current_step=message
            )
            db = get_mongo_db()
            await db.analysis_tasks.update_one(
                {"task_id": task_id},
                {
                    "$set": {
                        "progress": progress,
                        "current_step": message,
                        "message": message,
                        "updated_at": now_utc()
                    }
                }
            )
        except Exception as e:
            logger.warning(f"⚠️ [异步更新] 失败: {e}")

    def _resolve_stock_name(self, code: Optional[str]) -> str:
        """解析股票名称（带缓存）"""
        if not code:
            return ""
        if code in self._stock_name_cache:
            return self._stock_name_cache[code]
        name = None
        try:
            if _get_stock_info_safe:
                info = _get_stock_info_safe(code)
                if isinstance(info, dict):
                    name = info.get("name")
        except Exception:
            pass
        if not name:
            name = f"股票{code}"
        self._stock_name_cache[code] = name
        return name

    def _enrich_stock_names(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """为任务列表补齐股票名称(就地更新)

        仅查询内存缓存，不触发同步 DB/IO 操作，避免阻塞事件循环。
        未命中缓存时使用 stock_code 作为兜底名称。
        """
        try:
            for t in tasks:
                code = t.get("stock_code") or t.get("stock_symbol")
                name = t.get("stock_name")
                if not name and code:
                    t["stock_name"] = self._stock_name_cache.get(code, f"股票{code}")
        except Exception as e:
            logger.warning(f"⚠️ 补齐股票名称时出现异常: {e}")
        return tasks

    def _convert_user_id(self, user_id: str) -> PyObjectId:
        """将字符串用户ID转换为PyObjectId"""
        try:
            if user_id == "admin":
                # 从数据库查询 admin 用户的真实 ObjectId
                try:
                    db = self._get_sync_mongo_db()
                    admin_doc = db.users.find_one({"username": "admin"})
                    if admin_doc:
                        return PyObjectId(admin_doc["_id"])
                except Exception as e:
                    logger.warning(f"⚠️ 从数据库查询 admin 用户失败: {e}")
                # 回退：尝试使用 "admin" 作为 ObjectId 字符串
                raise ValueError("无法确定 admin 用户的 ObjectId")
            return PyObjectId(ObjectId(user_id))
        except Exception as e:
            logger.warning(f"⚠️ 用户ID转换失败: user_id={user_id}, error={e}")
            raise ValueError(f"无效的用户ID: {user_id}") from e

    async def _convert_user_id_async(self, user_id: str) -> PyObjectId:
        """异步将字符串用户ID转换为PyObjectId，避免在事件循环中执行同步数据库查询"""
        try:
            if user_id == "admin":
                try:
                    db = get_mongo_db()
                    admin_doc = await db.users.find_one({"username": "admin"}, {"_id": 1})
                    if admin_doc:
                        return PyObjectId(admin_doc["_id"])
                except Exception as e:
                    logger.warning(f"⚠️ 异步查询 admin 用户失败: {e}")
                raise ValueError("无法确定 admin 用户的 ObjectId")
            return PyObjectId(ObjectId(user_id))
        except Exception as e:
            logger.warning(f"⚠️ 用户ID转换失败: user_id={user_id}, error={e}")
            raise ValueError(f"无效的用户ID: {user_id}") from e

    def _serialize_for_response(self, value: Any) -> Any:
        """递归转换 Mongo 特定类型为可序列化格式"""
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, list):
            return [self._serialize_for_response(v) for v in value]
        if isinstance(value, dict):
            return {k: self._serialize_for_response(v) for k, v in value.items()}
        return value

    def _get_sync_mongo_db(self):
        """获取同步 MongoDB 数据库连接（使用全局统一管理）"""
        from app.core.database import get_mongo_db_sync
        return get_mongo_db_sync()

    def _get_trading_graph(self, config: Dict[str, Any]) -> TradingAgentsGraph:
        """获取或创建TradingAgents实例 (每次创建新实例以保证线程安全)"""
        selected = config.get("selected_analysts") or []
        if not selected:
            raise ValueError("selected_analysts 不能为空，请先在阶段1配置分析师后再发起任务。")
        return TradingAgentsGraph(
            selected_analysts=selected,
            debug=config.get("debug", False),
            config=config
        )

    def _auto_enable_mcp(self, config: Dict[str, Any], selected_tool_ids: Optional[List[str]] = None) -> None:
        """
        自动为分析任务注入 MCP 工具加载器：
        - 若用户未显式开启 MCP，但外部 MCP 工具可用，则启用并绑定 loader
        - 仅加载外部 MCP 工具（include_local=False），避免与本地 MCP 工具重复

        注意：MCP 连接在应用启动时已建立，此处直接使用已初始化的工厂
        """
        if config.get("enable_mcp"):
            return
        if not LANGCHAIN_MCP_AVAILABLE:
            return

        try:
            factory = get_mcp_loader_factory()
            # 不再检查 _initialized，因为连接在应用启动时已建立

            tool_ids = selected_tool_ids or []
            loader = factory.create_loader(tool_ids, include_local=False)
            mcp_tools = list(loader())

            if mcp_tools:
                config["enable_mcp"] = True
                config["mcp_tool_loader"] = loader
                config.setdefault("mcp_tool_ids", tool_ids)
                logger.info(f"自动启用MCP工具: {len(mcp_tools)}个")
            else:
                logger.info("MCP支持已检测，无可用外部工具")
        except Exception as exc:
            logger.warning(f"自动注入MCP工具失败: {exc}")

    # -------------------------------------------------------------------------
    # Main Analysis Methods (Core Logic from simple_analysis_service.py)
    # -------------------------------------------------------------------------

    async def create_analysis_task(
        self,
        user_id: str,
        request: SingleAnalysisRequest
    ) -> Dict[str, Any]:
        """创建分析任务（立即返回，不执行分析）"""
        try:
            task_id = str(uuid.uuid4())
            stock_code = request.get_symbol()
            if not stock_code:
                raise ValueError("股票代码不能为空")

            logger.info(f"📝 创建分析任务: {task_id} - {stock_code}")

            # 在内存中创建任务状态
            await self.memory_manager.create_task(
                task_id=task_id,
                user_id=user_id,
                stock_code=stock_code,
                parameters=request.parameters.model_dump() if request.parameters else {},
                stock_name=self._resolve_stock_name(stock_code),
            )

            # 写入MongoDB
            code = stock_code
            name = self._resolve_stock_name(code)
            try:
                db = get_mongo_db()
                await db.analysis_tasks.update_one(
                    {"task_id": task_id},
                    {"$setOnInsert": {
                        "task_id": task_id,
                        "user_id": user_id,
                        "stock_code": code,
                        "stock_symbol": code,
                        "stock_name": name,
                        "status": "pending",
                        "progress": 0,
                        "created_at": now_utc(),
                    }},
                    upsert=True
                )
            except Exception as e:
                logger.error(f"❌ 创建任务时写入MongoDB失败: {e}")

            return {
                "task_id": task_id,
                "status": "pending",
                "message": "任务已创建，等待执行"
            }

        except Exception as e:
            logger.error(f"❌ 创建分析任务失败: {e}")
            raise

    async def execute_analysis_background(
        self,
        task_id: str,
        user_id: str,
        request: SingleAnalysisRequest
    ):
        """在后台执行分析任务 (Core Logic)"""
        stock_code = request.get_symbol()
        progress_tracker = None
        try:
            logger.info(f"🚀 开始后台执行分析任务: {task_id}")

            # 验证股票代码
            from app.utils.stock_validator import prepare_stock_data_async
            market_type = request.parameters.market_type if request.parameters else "A股"
            analysis_date = request.parameters.analysis_date if request.parameters else None
            
            if analysis_date and isinstance(analysis_date, datetime):
                analysis_date = analysis_date.strftime('%Y-%m-%d')
            elif analysis_date and isinstance(analysis_date, str):
                try:
                    parsed_date = datetime.strptime(analysis_date, '%Y-%m-%d')
                    analysis_date = parsed_date.strftime('%Y-%m-%d')
                except ValueError:
                    analysis_date = format_date_short(now_config_tz())

            validation_result = await prepare_stock_data_async(
                stock_code=stock_code,
                market_type=market_type,
                period_days=30,
                analysis_date=analysis_date
            )

            if not validation_result.is_valid:
                error_msg = f"❌ 股票代码无效: {validation_result.error_message}"
                await self.memory_manager.update_task_status(
                    task_id=task_id, status=AnalysisStatus.FAILED, progress=0, error_message=error_msg
                )
                await self._update_task_status(task_id, AnalysisStatus.FAILED, 0, error_message=error_msg)
                return

            # 创建Redis进度跟踪器
            # 获取当前的 event loop (用于在子线程中调度 WebSocket 发送)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning("无法获取当前事件循环，WebSocket 推送可能失效")
                loop = None

            # 阶段配置（与前端保持一致，交易员始终执行）
            phase_config = {
                "phase2_enabled": getattr(request.parameters, "phase2_enabled", False) if request.parameters else False,
                "phase2_debate_rounds": getattr(request.parameters, "phase2_debate_rounds", 2) if request.parameters else 1,
                "phase3_enabled": getattr(request.parameters, "phase3_enabled", False) if request.parameters else False,
                "phase3_debate_rounds": getattr(request.parameters, "phase3_debate_rounds", 2) if request.parameters else 1,
                "phase4_enabled": True,
                "phase4_debate_rounds": 1,
            }

            selected_analysts = (
                request.parameters.selected_analysts
                if request.parameters and request.parameters.selected_analysts
                else []
            )
            if not selected_analysts:
                raise ValueError("selected_analysts 不能为空，请先在阶段1配置并选择分析师。")

            def progress_callback(data):
                """进度更新回调：通过 WebSocket 广播消息"""
                if not loop:
                    return
                try:
                    ws_manager = get_websocket_manager()
                    # 构造消息
                    message = {
                        "type": "progress_update",
                        "task_id": task_id,
                        "status": data.get("status"),
                        "progress": data.get("progress_percentage"),
                        "message": data.get("last_message"),
                        "current_step": data.get("current_step"),
                        "steps": data.get("steps")
                    }
                    # 在主循环中调度发送任务
                    asyncio.run_coroutine_threadsafe(
                        ws_manager.send_progress_update(task_id, message),
                        loop
                    )
                except Exception as e:
                    logger.error(f"WebSocket 广播失败: {e}")

            def create_progress_tracker():
                return RedisProgressTracker(
                    task_id=task_id,
                    analysts=selected_analysts,
                    phase_config=phase_config,
                    llm_provider=_get_default_provider_by_model(
                        getattr(request.parameters, "analyst_model", "qwen-turbo")
                    ),
                    on_update=progress_callback
                )

            progress_tracker = await asyncio.to_thread(create_progress_tracker)
            self._progress_trackers[task_id] = progress_tracker
            register_analysis_tracker(task_id, progress_tracker)

            # 更新初始状态
            await asyncio.to_thread(progress_tracker.update_progress, {"progress_percentage": 10, "last_message": "🚀 开始股票分析"})
            await self.memory_manager.update_task_status(
                task_id=task_id, status=TaskStatus.RUNNING, progress=10, message="分析开始...", current_step="initialization"
            )
            await self._update_task_status(task_id, AnalysisStatus.PROCESSING, 10)

            # 记录 MCP 工具选择（实际加载在同步执行阶段完成）
            selected_mcp_tools = []
            if request.parameters:
                selected_mcp_tools = (
                    getattr(request.parameters, "mcp_tool_ids", None) or
                    getattr(request.parameters, "mcp_tools", []) or
                    []
                )
                if selected_mcp_tools:
                    logger.info(f"MCP工具选择: {selected_mcp_tools}")

            # 执行实际分析
            result = await self._execute_analysis_sync(
                task_id, 
                user_id, 
                request, 
                progress_tracker,
                mcp_tool_ids=selected_mcp_tools
            )

            # 完成
            await asyncio.to_thread(progress_tracker.mark_completed)
            
            # 保存结果
            await self._save_analysis_results_complete(task_id, result)

            # 更新完成状态
            await self.memory_manager.update_task_status(
                task_id=task_id, status=TaskStatus.COMPLETED, progress=100, message="分析完成", current_step="completed", result_data=result
            )
            await self._update_task_status(task_id, AnalysisStatus.COMPLETED, 100)

            # 发送通知
            try:
                from app.services.notifications_service import get_notifications_service
                svc = get_notifications_service()
                summary = str(result.get("summary", ""))[:120]
                await svc.create_and_publish(
                    payload=NotificationCreate(
                        user_id=str(user_id), type='analysis', title=f"{stock_code} 分析完成",
                        content=summary, link=f"/stocks/{stock_code}", source='analysis'
                    )
                )
            except Exception:
                pass

        except Exception as e:
            logger.error(f"❌ 后台分析任务失败: {task_id} - {e}")
            if progress_tracker:
                progress_tracker.mark_failed(str(e))
            await self.memory_manager.update_task_status(
                task_id=task_id, status=TaskStatus.FAILED, progress=0, message="分析失败", error_message=str(e)
            )
            await self._update_task_status(task_id, AnalysisStatus.FAILED, 0, str(e))
        finally:
            if task_id in self._progress_trackers:
                del self._progress_trackers[task_id]
            unregister_analysis_tracker(task_id)

    # -------------------------------------------------------------------------
    # Compatibility Methods (for API Router)
    # -------------------------------------------------------------------------

    async def submit_single_analysis(self, user_id: str, request: SingleAnalysisRequest) -> Dict[str, Any]:
        """
        提交单股分析任务 (兼容旧 AnalysisService 接口)
        注意：这个方法现在只是 create_analysis_task 的别名，
        实际执行需要在调用处通过 BackgroundTasks 或其他方式触发 execute_analysis_background
        """
        return await self.create_analysis_task(user_id, request)

    async def submit_batch_analysis(self, user_id: str, request: BatchAnalysisRequest) -> Dict[str, Any]:
        """提交批量分析任务 (保留原功能)"""
        try:
            batch_id = str(uuid.uuid4())
            converted_user_id = await self._convert_user_id_async(user_id)
            
            # 读取配置
            effective_settings = await config_provider.get_effective_system_settings()
            params = request.parameters or AnalysisParameters()
            
            if not getattr(params, 'analyst_model', None):
                params.analyst_model = effective_settings.get("analyst_model", "qwen-turbo")
            if not getattr(params, 'debate_model', None):
                params.debate_model = effective_settings.get("debate_model", "qwen-max")

            stock_symbols = request.get_symbols()
            
            batch = AnalysisBatch(
                batch_id=batch_id,
                user_id=converted_user_id,
                title=request.title,
                description=request.description,
                total_tasks=len(stock_symbols),
                parameters=params,
                status=BatchStatus.PENDING
            )

            tasks = []
            for symbol in stock_symbols:
                task_id = str(uuid.uuid4())
                task = AnalysisTask(
                    task_id=task_id,
                    batch_id=batch_id,
                    user_id=converted_user_id,
                    symbol=symbol,
                    stock_code=symbol,
                    parameters=batch.parameters,
                    status=AnalysisStatus.PENDING
                )
                tasks.append(task)
            
            db = get_mongo_db()
            await db.analysis_batches.insert_one(batch.dict(by_alias=True))
            await db.analysis_tasks.insert_many([task.dict(by_alias=True) for task in tasks])
            
            for task in tasks:
                queue_params = task.parameters.dict() if task.parameters else {}
                queue_params.update({
                    "task_id": task.task_id,
                    "symbol": task.symbol,
                    "stock_code": task.symbol,
                    "user_id": str(task.user_id),
                    "batch_id": task.batch_id,
                    "created_at": task.created_at.isoformat() if task.created_at else None
                })
                await self.queue_service.enqueue_task(
                    user_id=str(converted_user_id),
                    symbol=task.symbol,
                    params=queue_params,
                    batch_id=task.batch_id
                )
            
            return {
                "batch_id": batch_id,
                "total_tasks": len(tasks),
                "status": BatchStatus.PENDING,
                "message": f"已提交{len(tasks)}个分析任务到队列"
            }
        except Exception as e:
            logger.error(f"提交批量分析任务失败: {e}")
            raise

    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        try:
            await self._update_task_status(task_id, AnalysisStatus.CANCELLED, 0)
            await self.queue_service.cancel_task(task_id)
            return True
        except Exception as e:
            logger.error(f"取消任务失败: {task_id} - {e}")
            return False

    # -------------------------------------------------------------------------
    # Internal Execution Logic (from simple_analysis_service.py)
    # -------------------------------------------------------------------------

    async def _execute_analysis_sync(
        self,
        task_id: str,
        user_id: str,
        request: SingleAnalysisRequest,
        progress_tracker: Optional[RedisProgressTracker] = None,
        mcp_tool_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """同步执行分析（在共享线程池中运行）"""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            self._thread_pool,
            self._run_analysis_sync,
            task_id,
            user_id,
            request,
            progress_tracker,
            mcp_tool_ids or []
        )
        return result

    def _prefetch_stock_data(
        self,
        market: str,
        symbol: str,
    ) -> Dict[str, str]:
        """预拉取该股票在该市场的所有支持数据域到 MongoDB。

        拉取 DataRefreshService 支持的全部按需刷新域（不依赖分析师选择），
        确保分析过程中所有数据都从 MongoDB 命中。

        Args:
            market: 市场标识 (CN/HK/US)
            symbol: 股票代码

        Returns:
            各域的刷新状态 {domain: status}
        """
        from app.core.async_utils import run_async
        from app.data.core.interface import DataInterface

        # 传入 domains=None，由 DataRefreshService 拉取全部支持的域
        di = DataInterface.get_instance()
        result = run_async(di.refresh(
            market, symbol,
            domains=None,   # None = 全部支持的域
            force=False,    # 有缓存就跳过
            timeout=60,
        ))

        # 记录结果摘要
        domain_statuses = {}
        for domain, dr in result.domains.items():
            domain_statuses[domain] = dr.status
            if dr.status == "failed":
                logger.warning(f"📊 [数据预拉取] {domain} 失败: {dr.error}")
            else:
                logger.info(f"📊 [数据预拉取] {domain}: {dr.status} ({dr.record_count} 条, {dr.latency_ms}ms)")

        refreshed = sum(1 for s in domain_statuses.values() if s == "refreshed")
        fresh = sum(1 for s in domain_statuses.values() if s == "fresh")
        failed = sum(1 for s in domain_statuses.values() if s in ("failed", "timeout"))
        logger.info(f"📊 [数据预拉取] 完成: {refreshed} 个域刷新, {fresh} 个域已是最新, {failed} 个域失败")

        return domain_statuses

    def _run_analysis_sync(
        self,
        task_id: str,
        user_id: str,
        request: SingleAnalysisRequest,
        progress_tracker: Optional[RedisProgressTracker] = None,
        mcp_tool_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """同步执行分析的具体实现"""
        # 任务级 MCP 管理器（用于隔离和管理 MCP 工具状态）
        task_mcp_manager = None

        try:
            from app.utils.logging_init import setup_logging
            from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory
            from app.engine.tools.mcp.task_manager import get_task_mcp_manager, remove_task_mcp_manager
            setup_logging()

            # 创建任务级 MCP 管理器
            task_mcp_manager = get_task_mcp_manager(task_id)
            logger.info(f"🔧 [任务管理器] 创建任务级 MCP 管理器: {task_id}")

            # 进度更新回调
            def update_progress_sync(progress: int, message: str, step: str):
                try:
                    if progress_tracker:
                        progress_tracker.update_progress({"progress_percentage": progress, "last_message": message})

                    # 1. 更新内存状态（同步）
                    self.memory_manager.update_task_status_sync(
                        task_id=task_id, status=TaskStatus.RUNNING, progress=progress, message=message, current_step=step
                    )

                    # 2. 更新MongoDB（同步复用连接，避免频繁创建）
                    sync_db = self._get_sync_mongo_db()
                    if sync_db is not None:
                        sync_db.analysis_tasks.update_one(
                            {"task_id": task_id},
                            {"$set": {"progress": progress, "current_step": step, "message": message, "updated_at": now_utc()}}
                        )
                except Exception as e:
                    logger.warning(f"⚠️ [Sync] 更新进度失败: {e}")

            update_progress_sync(7, "⚙️ 配置分析参数", "configuration")

            # 选中分析师列表（完全依赖配置文件加载，禁止写死）
            selected_analysts = []
            if request.parameters:
                selected_analysts = [
                    str(a).strip() for a in getattr(request.parameters, "selected_analysts", []) if a
                ]
            if not selected_analysts:
                raise ValueError("selected_analysts 不能为空，请先在阶段1配置并选择分析师。")

            # 通过配置文件映射规范化（兼容 slug / 简短ID / 中文名），保持顺序去重
            try:
                lookup = DynamicAnalystFactory.build_lookup_map()
                normalized: List[str] = []
                seen = set()
                for key in selected_analysts:
                    mapped = key
                    if key in lookup:
                        mapped = lookup[key].get("slug") or lookup[key].get("internal_key") or key
                    if mapped and mapped not in seen:
                        normalized.append(mapped)
                        seen.add(mapped)
                selected_analysts = normalized
            except Exception as e:
                logger.warning(f"⚠️ 规范化分析师列表失败，使用原始输入: {e}")

            if not selected_analysts:
                raise ValueError("selected_analysts 不能为空，请先在阶段1配置并选择分析师。")

            # 🔍 调试日志：打印最终的分析师列表
            logger.info(f"📋 [分析师选择] 最终分析师列表: {selected_analysts}")

            # 模型选择逻辑
            from app.services.model_capability_service import get_model_capability_service
            capability_service = get_model_capability_service()

            if (
                request.parameters
                and getattr(request.parameters, "analyst_model", None)
                and getattr(request.parameters, "debate_model", None)
            ):
                analyst_model = request.parameters.analyst_model
                debate_model = request.parameters.debate_model
            else:
                analyst_model, debate_model = capability_service.recommend_models()

            analyst_provider_info = get_provider_and_url_by_model_sync(analyst_model)
            debate_provider_info = get_provider_and_url_by_model_sync(debate_model)
            analyst_provider = analyst_provider_info["provider"]
            
            # 获取市场类型 - 优先使用 StockUtils 自动识别
            if request.parameters and request.parameters.market_type:
                market_type = request.parameters.market_type
            else:
                try:
                    # 自动识别市场类型
                    market_info = StockUtils.get_market_info(request.get_symbol())
                    if market_info.get('is_china'):
                        market_type = "A股"
                    elif market_info.get('is_hk'):
                        market_type = "港股"
                    elif market_info.get('is_us'):
                        market_type = "美股"
                    else:
                        market_type = "A股"  # 默认兜底
                    logger.info(f"📊 [自动识别] 股票 {request.get_symbol()} 市场类型: {market_type}")
                except Exception as e:
                    logger.warning(f"⚠️ 无法识别股票市场类型: {e}，使用默认值 'A股'")
                    market_type = "A股"
            
            config = create_analysis_config(
                selected_analysts=selected_analysts,
                analyst_model=analyst_model,
                debate_model=debate_model,
                llm_provider=analyst_provider,
                market_type=market_type
            )
            
            # 注入MCP工具加载器（惰性加载，避免提前长连接）
            selected_mcp_tools: List[str] = []
            if mcp_tool_ids:
                selected_mcp_tools = list(mcp_tool_ids)
            elif request.parameters:
                selected_mcp_tools = (
                    getattr(request.parameters, "mcp_tool_ids", None)
                    or getattr(request.parameters, "mcp_tools", [])
                    or []
                )

            if selected_mcp_tools:
                if not LANGCHAIN_MCP_AVAILABLE:
                    logger.warning("选择MCP工具但未安装langchain-mcp，已跳过")
                else:
                    try:
                        factory = get_mcp_loader_factory()
                        config["enable_mcp"] = True
                        # 仅加载外部 MCP 工具，避免本地 MCP 工具重复注册
                        config["mcp_tool_loader"] = factory.create_loader(selected_mcp_tools, include_local=False)
                        config["mcp_tool_ids"] = selected_mcp_tools
                        logger.info(f"配置MCP工具加载器: {len(selected_mcp_tools)}个")
                    except Exception as e:
                        logger.error(f"配置MCP工具加载器失败: {e}")

            # 若未显式选择但外部 MCP 工具已配置，则自动启用
            self._auto_enable_mcp(config, selected_mcp_tools)
                
            if request.parameters:
                config["phase2_enabled"] = getattr(request.parameters, "phase2_enabled", False)
                config["phase2_debate_rounds"] = getattr(request.parameters, "phase2_debate_rounds", 2)
                config["phase3_enabled"] = getattr(request.parameters, "phase3_enabled", False)
                config["phase3_debate_rounds"] = getattr(request.parameters, "phase3_debate_rounds", 2)
                config["phase4_enabled"] = True
                config["phase4_debate_rounds"] = 1
            else:
                # 默认阶段配置：交易员始终执行
                config.setdefault("phase2_enabled", False)
                config.setdefault("phase3_enabled", False)
                config.setdefault("phase4_enabled", True)
                config.setdefault("phase2_debate_rounds", 1)
                config.setdefault("phase3_debate_rounds", 1)
                config.setdefault("phase4_debate_rounds", 1)

            # 统一轮次配置到 ConditionalLogic
            config["max_debate_rounds"] = config.get("phase2_debate_rounds", 1)
            config["max_risk_discuss_rounds"] = config.get("phase3_debate_rounds", 1)
            
            # 注入模型 provider 路由信息
            config["analyst_provider"] = analyst_provider
            config["debate_provider"] = debate_provider_info["provider"]
            config["analyst_backend_url"] = analyst_provider_info["backend_url"]
            config["debate_backend_url"] = debate_provider_info["backend_url"]
            config["backend_url"] = analyst_provider_info["backend_url"]

            # 注入任务级 MCP 管理器
            config["task_mcp_manager"] = task_mcp_manager
            config["task_id"] = task_id
            logger.info(f"🔧 [任务管理器] 已将 MCP 管理器注入配置: task_id={task_id}")

            update_progress_sync(9, "🚀 初始化AI分析引擎", "engine_initialization")

            # 预计算内置工具可用性（基于数据域状态）
            try:
                from app.engine.tools.builtin.domain_checker import AvailabilityCache
                from app.engine.tools.builtin.registry import BUILTIN_TOOL_REGISTRY

                _market_map = {"A股": "CN", "港股": "HK", "美股": "US"}
                _market = _market_map.get(market_type, "CN")
                _cache = AvailabilityCache.get_instance()
                from app.core.async_utils import run_async
                run_async(_cache.compute(_market, BUILTIN_TOOL_REGISTRY))
                logger.info(f"📊 [工具可用性] 市场={_market}, 结果={_cache.all_results}")
            except Exception as _e:
                logger.warning(f"⚠️ [工具可用性] 预计算失败（不影响分析）: {_e}")

            # ── 预拉取阶段：拉取该股票在该市场的全部数据域到 MongoDB ──
            update_progress_sync(10, "📊 预拉取股票数据...", "data_prefetch")
            try:
                prefetch_result = self._prefetch_stock_data(
                    _market, request.get_symbol()
                )
                logger.info(f"📊 [数据预拉取] 结果: {prefetch_result}")
                # 预拉取后重新计算工具可用性
                run_async(_cache.compute(_market, BUILTIN_TOOL_REGISTRY))
                logger.info(f"📊 [工具可用性] 预拉取后重新计算: {_cache.all_results}")
            except Exception as _prefetch_err:
                logger.warning(f"⚠️ [数据预拉取] 失败（不影响分析，使用现有数据）: {_prefetch_err}")
            update_progress_sync(20, "📊 数据预拉取完成", "data_prefetch_done")

            # 🔥 添加时间戳日志，精确定位耗时
            import time
            graph_init_start = time.time()
            logger.info("⏱️ [性能追踪] 开始创建 TradingAgentsGraph...")

            trading_graph = self._get_trading_graph(config)

            graph_init_elapsed = time.time() - graph_init_start
            logger.info(f"⏱️ [性能追踪] TradingAgentsGraph 创建完成，耗时: {graph_init_elapsed:.2f} 秒 ({graph_init_elapsed/60:.2f} 分钟)")

            if graph_init_elapsed > 60:
                logger.warning("⚠️ [性能瓶颈] TradingAgentsGraph 初始化耗时超过 1 分钟！这是主要性能瓶颈！")

            start_time = now_config_tz()
            analysis_date = format_date_short(now_config_tz())
            if request.parameters and request.parameters.analysis_date:
                ad = request.parameters.analysis_date
                if isinstance(ad, datetime): analysis_date = ad.strftime("%Y-%m-%d")
                elif isinstance(ad, str): analysis_date = ad

            # 🔧 智能日期范围处理：获取最近10天的数据，自动处理周末/节假日
            data_start_date, data_end_date = get_trading_date_range(analysis_date, lookback_days=10)
            logger.info(f"📅 分析目标日期: {analysis_date}, 数据范围: {data_start_date} 至 {data_end_date}")

            update_progress_sync(10, "🤖 开始多智能体协作分析", "agent_analysis")

            # 进度回调 - 动态从配置文件加载，基于选择的智能体计算进度
            selected_analysts_for_progress = config.get("selected_analysts", [])
            node_progress_map = DynamicAnalystFactory.build_progress_map(selected_analysts=selected_analysts_for_progress)

            def graph_progress_callback(message: str):
                try:
                    if not progress_tracker: return
                    progress_pct = node_progress_map.get(message)
                    if progress_pct is not None:
                        current_progress = progress_tracker.progress_data.get('progress_percentage', 0)
                        if int(progress_pct) > current_progress:
                            # 优先使用同步更新
                            update_progress_sync(int(progress_pct), message, message)
                        else:
                            progress_tracker.update_progress({'last_message': message})
                    else:
                        progress_tracker.update_progress({'last_message': message})
                except Exception:
                    pass

            # 执行分析
            state, decision = trading_graph.propagate(
                request.stock_code,
                analysis_date,
                progress_callback=graph_progress_callback,
                task_id=task_id
            )

            update_progress_sync(90, "处理分析结果...", "result_processing")
            execution_time = (now_config_tz() - start_time).total_seconds()

            # 提取 reports 从 state
            reports = {}
            if isinstance(state, dict):
                # 1. 动态发现所有 *_report 字段和其他已知报告字段
                # 🔥 使用动态发现而非硬编码列表，自动支持新添加的分析师报告
                known_non_report_keys = [
                    "trader_investment_plan", "investment_plan", "final_trade_decision"
                ]
                
                # 🔍 调试：打印所有 state 中的键
                report_keys_found = [k for k in state.keys() if k.endswith("_report") or k in known_non_report_keys]
                logger.info(f"🔍 [报告提取] state中发现的报告键: {report_keys_found}")
                
                for key in state.keys():
                    # 匹配所有 *_report 字段或已知的非 _report 后缀的报告字段
                    if key.endswith("_report") or key in known_non_report_keys:
                        content = state[key]
                        if content:
                            # 确保内容是字符串或可序列化的
                            if isinstance(content, str):
                                reports[key] = content
                                logger.debug(f"🔍 [报告提取] 提取报告 {key}: 长度={len(content)}")
                            elif hasattr(content, "content") and isinstance(content.content, str):
                                reports[key] = content.content
                                logger.debug(f"🔍 [报告提取] 提取报告 {key} (从content属性): 长度={len(content.content)}")
                            else:
                                try:
                                    reports[key] = str(content)
                                    logger.debug(f"🔍 [报告提取] 提取报告 {key} (转换为字符串): 长度={len(str(content))}")
                                except Exception:
                                    logger.warning(f"⚠️ [报告提取] 无法提取报告 {key}: 内容类型={type(content)}")
                        else:
                            logger.debug(f"🔍 [报告提取] 跳过空报告 {key}")
                
                logger.info(f"🔍 [报告提取] 最终提取的报告: {list(reports.keys())}")
                
                # 2. 提取 investment_debate_state (多空博弈) 中的报告
                if "investment_debate_state" in state and isinstance(state["investment_debate_state"], dict):
                    inv_state = state["investment_debate_state"]
                    # 映射: 内部状态字段 -> 前端报告key
                    inv_mapping = {
                        "bull_history": "bull_researcher",
                        "bear_history": "bear_researcher",
                        "judge_decision": "research_team_decision"
                    }
                    for state_key, report_key in inv_mapping.items():
                        if state_key in inv_state and inv_state[state_key]:
                            reports[report_key] = inv_state[state_key]

                # 3. 提取 risk_debate_state (风险管理) 中的报告
                if "risk_debate_state" in state and isinstance(state["risk_debate_state"], dict):
                    risk_state = state["risk_debate_state"]
                    # 映射: 内部状态字段 -> 前端报告key
                    risk_mapping = {
                        "risky_history": "risky_analyst",
                        "safe_history": "safe_analyst",
                        "neutral_history": "neutral_analyst",
                        "judge_decision": "risk_management_decision"
                    }
                    for state_key, report_key in risk_mapping.items():
                        if state_key in risk_state and risk_state[state_key]:
                            reports[report_key] = risk_state[state_key]

                # 4. 🔥 从 reports 字典中提取 (支持动态添加的智能体)
                if "reports" in state and isinstance(state["reports"], dict):
                    dynamic_reports = state["reports"]
                    logger.info(f"🔍 [报告提取] 从 reports 字典发现 {len(dynamic_reports)} 个报告: {list(dynamic_reports.keys())}")
                    for key, content in dynamic_reports.items():
                        # 如果key已经存在（优先使用根级别的），则跳过
                        if key not in reports and content:
                            if isinstance(content, str):
                                reports[key] = content
                            else:
                                reports[key] = str(content)

                # 5. 🔥 从 messages 列表中提取 (作为最终兜底，绕过 TypedDict 限制)
                # 遍历消息历史，提取带有 name 且以 _report 结尾的 AIMessage
                if "messages" in state and isinstance(state["messages"], list):
                    from langchain_core.messages import AIMessage
                    # 倒序遍历，取最新的
                    messages_reports_count = 0
                    for msg in reversed(state["messages"]): 
                        if isinstance(msg, AIMessage) and hasattr(msg, "name") and msg.name and msg.name.endswith("_report"):
                            report_key = msg.name
                            if report_key not in reports:
                                content = msg.content
                                if content and isinstance(content, str):
                                    reports[report_key] = content
                                    messages_reports_count += 1
                                    logger.debug(f"🔍 [报告提取] 从 AIMessage 恢复报告: {report_key}")
                    if messages_reports_count > 0:
                        logger.info(f"🔍 [报告提取] 从消息历史中恢复了 {messages_reports_count} 个报告")

            # 提取结构化总结
            structured_summary = state.get("structured_summary") or {}
            
            # 优先从结构化总结中获取摘要和建议
            summary_text = ""
            if structured_summary and structured_summary.get("analysis_summary"):
                summary_text = structured_summary.get("analysis_summary")
            elif isinstance(decision, dict):
                summary_text = str(decision.get("summary", ""))[:200]
                
            recommendation_text = ""
            if structured_summary and structured_summary.get("investment_recommendation"):
                recommendation_text = structured_summary.get("investment_recommendation")
            elif isinstance(decision, dict):
                recommendation_text = str(decision.get("recommendation", ""))

            # 构建结果 (简化版，完整版在 _save_analysis_result_web_style 中重构)
            # 这里直接返回字典
            result = {
                "stock_code": request.stock_code,
                "stock_symbol": request.stock_code,
                "analysis_date": analysis_date,
                "market_type": market_type,
                "summary": summary_text,
                "recommendation": recommendation_text,
                "confidence_score": decision.get("confidence_score", 0.0) if isinstance(decision, dict) else 0.0,
                "risk_level": decision.get("risk_level", "中等") if isinstance(decision, dict) else "中等",
                "detailed_analysis": decision,
                "execution_time": execution_time,
                "state": state,
                "structured_summary": structured_summary, # 🔥 显式添加到顶层结果
                "reports": reports,  # 🔥 添加提取的报告
                "decision": decision,
                "model_info": decision.get('model_info', 'Unknown') if isinstance(decision, dict) else 'Unknown',
                "analysts": request.parameters.selected_analysts if request.parameters else [],
            }
            return result

        except Exception as e:
            logger.error(f"❌ 分析执行失败: {task_id} - {e}")
            raise

        finally:
            # 清理任务级 MCP 管理器
            if task_mcp_manager is not None:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(remove_task_mcp_manager(task_id))
                    logger.info(f"🔧 [任务管理器] 已调度清理任务级 MCP 管理器: {task_id}")
                except RuntimeError:
                    # 无运行中的事件循环时，直接从全局字典移除
                    try:
                        from app.engine.tools.mcp.task_manager import _task_managers, _managers_thread_lock
                        with _managers_thread_lock:
                            _task_managers.pop(task_id, None)
                        logger.info(f"🔧 [任务管理器] 已同步清理任务级 MCP 管理器: {task_id}")
                    except Exception as e:
                        logger.warning(f"⚠️ [任务管理器] 同步清理失败: {e}")
                except Exception as e:
                    logger.warning(f"⚠️ [任务管理器] 清理任务管理器失败: {e}")

    # -------------------------------------------------------------------------
    # Status & Saving Methods
    # -------------------------------------------------------------------------

    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态 (包含详细进度)"""
        global_memory_manager = get_memory_state_manager()
        result = await global_memory_manager.get_task_dict(task_id)
        if result:
            redis_progress = get_progress_by_id(task_id)
            if redis_progress:
                result.update({
                    'progress': redis_progress.get('progress_percentage', result.get('progress', 0)),
                    'message': redis_progress.get('last_message', result.get('message', '')),
                    'steps': redis_progress.get('steps', [])
                })
        return result

    async def list_all_tasks(self, status: Optional[str] = None, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """获取所有任务列表 (数据库 + 内存状态合并)"""
        # 兼容性处理：processing -> running
        if status == "processing":
            status = "running"
        
        # 构建查询条件
        query = {}
        if status:
            query["status"] = status
        
        try:
            db = get_mongo_db()
            cursor = db.analysis_tasks.find(query).sort("created_at", -1).skip(offset).limit(limit)
            db_tasks = await cursor.to_list(length=limit)
            
            results = []
            for task in db_tasks:
                if "_id" in task:
                    task["_id"] = str(task["_id"])
                
                task_id = task.get("task_id")
                if task_id:
                    memory_task = await self.memory_manager.get_task_dict(task_id)
                    if memory_task:
                        task["status"] = memory_task.get("status", task.get("status"))
                        task["progress"] = memory_task.get("progress", task.get("progress"))
                        task["message"] = memory_task.get("message", task.get("message"))
                        task["current_step"] = memory_task.get("current_step", task.get("current_step"))
                
                results.append(task)
            
            enriched = self._enrich_stock_names(results)
            return self._serialize_for_response(enriched)
            
        except Exception as e:
            logger.error(f"❌ 获取所有任务列表失败 (DB): {e}")
            status_enum = None
            if status:
                try:
                    status_enum = TaskStatus(status)
                except ValueError:
                    logger.warning(f"⚠️ 无效的任务状态过滤: {status}")
            
            tasks = await self.memory_manager.list_all_tasks(status=status_enum, limit=limit, offset=offset)
            enriched = self._enrich_stock_names(tasks)
            return self._serialize_for_response(enriched)

    async def list_user_tasks(self, user_id: str, status: Optional[str] = None, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """获取用户任务列表 (数据库 + 内存状态合并)"""
        # 兼容性处理：processing -> running
        if status == "processing":
            status = "running"
            
        # 构建查询条件
        query = {"user_id": user_id}
        if status:
            query["status"] = status
            
        try:
            db = get_mongo_db()
            # 按创建时间倒序
            cursor = db.analysis_tasks.find(query).sort("created_at", -1).skip(offset).limit(limit)
            db_tasks = await cursor.to_list(length=limit)
            
            # 批量获取内存中的实时状态（一次加锁，替代逐条查询）
            task_ids = [t.get("task_id") for t in db_tasks if t.get("task_id")]
            memory_map = self.memory_manager.batch_get_task_dicts(task_ids)

            results = []
            for task in db_tasks:
                if "_id" in task:
                    task["_id"] = str(task["_id"])

                task_id = task.get("task_id")
                if task_id and task_id in memory_map:
                    memory_task = memory_map[task_id]
                    task["status"] = memory_task.get("status", task.get("status"))
                    task["progress"] = memory_task.get("progress", task.get("progress"))
                    task["message"] = memory_task.get("message", task.get("message"))
                    task["current_step"] = memory_task.get("current_step", task.get("current_step"))

                results.append(task)
            
            # 如果数据库返回为空，可能是因为所有数据都在内存中（极少见情况，例如DB写入失败但内存成功）
            # 或者如果是刚启动，DB 为空也是正常的。
            # 这里我们只返回 DB 的结果，因为 create_analysis_task 保证了先写 DB。
            
            enriched = self._enrich_stock_names(results)
            return self._serialize_for_response(enriched)
            
        except Exception as e:
            logger.error(f"❌ 获取用户任务列表失败 (DB): {e}")
            # 降级：如果 DB 失败，尝试返回内存中的数据
            status_enum = None
            if status:
                try:
                    status_enum = TaskStatus(status)
                except ValueError:
                    pass
                    
            tasks = await self.memory_manager.list_user_tasks(
                user_id=user_id, 
                status=status_enum, 
                limit=limit, 
                offset=offset
            )
            enriched = self._enrich_stock_names(tasks)
            return self._serialize_for_response(enriched)

    async def query_user_tasks(
        self,
        user_id: str,
        status: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        symbol: Optional[str] = None,
        market_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """查询用户任务列表（支持复杂筛选与分页）"""
        # 兼容性处理
        if status == "processing":
            status = "running"

        # 构建查询条件
        query = {"user_id": user_id}
        
        if status:
            if status == "running":
                # 前端"进行中"包括 processing, running, pending
                query["status"] = {"$in": ["running", "pending", "processing"]}
            else:
                query["status"] = status
            
        if symbol:
            # 同时匹配 symbol 和 stock_code
            query["$or"] = [
                {"symbol": symbol},
                {"stock_code": symbol},
                {"stock_symbol": symbol}
            ]
            
        if market_type:
            query["parameters.market_type"] = market_type
            
        # 时间范围查询
        date_query = {}
        if start_date:
            try:
                # 假设传入的是 YYYY-MM-DD
                s_date = datetime.strptime(start_date, "%Y-%m-%d")
                date_query["$gte"] = s_date
            except Exception:
                logger.warning(f"⚠️ 日期解析失败: start_date={start_date}")
                pass
        if end_date:
            try:
                e_date = datetime.strptime(end_date, "%Y-%m-%d")
                # 结束日期加一天，包含当天
                e_date = e_date.replace(hour=23, minute=59, second=59, microsecond=999999)
                date_query["$lte"] = e_date
            except Exception:
                logger.warning(f"⚠️ 日期解析失败: end_date={end_date}")
                pass
                
        if date_query:
            query["created_at"] = date_query

        try:
            db = get_mongo_db()
            
            # 获取总数
            total = await db.analysis_tasks.count_documents(query)
            
            # 分页查询
            skip = (page - 1) * page_size
            cursor = db.analysis_tasks.find(query).sort("created_at", -1).skip(skip).limit(page_size)
            db_tasks = await cursor.to_list(length=page_size)
            
            # 批量获取内存中的实时状态（一次加锁，替代逐条查询）
            task_ids = [t.get("task_id") for t in db_tasks if t.get("task_id")]
            memory_map = self.memory_manager.batch_get_task_dicts(task_ids)

            results = []
            for task in db_tasks:
                if "_id" in task:
                    task["_id"] = str(task["_id"])

                task_id = task.get("task_id")
                if task_id and task_id in memory_map:
                    memory_task = memory_map[task_id]
                    task["status"] = memory_task.get("status", task.get("status"))
                    task["progress"] = memory_task.get("progress", task.get("progress"))
                    task["message"] = memory_task.get("message", task.get("message"))
                    task["current_step"] = memory_task.get("current_step", task.get("current_step"))

                results.append(task)

            enriched_tasks = self._enrich_stock_names(results)
            
            return self._serialize_for_response({
                "tasks": enriched_tasks,
                "total": total,
                "page": page,
                "page_size": page_size
            })
            
        except Exception as e:
            logger.error(f"❌ 查询用户任务列表失败 (DB): {e}")
            # 降级处理：使用 list_user_tasks 获取并手动过滤（不太精确但可用）
            all_tasks = await self.list_user_tasks(user_id, status, limit=1000) # 获取最近1000条
            
            # 手动过滤
            filtered = []
            for t in all_tasks:
                if symbol:
                    s = t.get("symbol") or t.get("stock_code") or t.get("stock_symbol")
                    if s != symbol:
                        continue
                if market_type and t.get("parameters", {}).get("market_type") != market_type:
                    continue
                filtered.append(t)
                
            # 手动分页
            start = (page - 1) * page_size
            paginated = filtered[start : start + page_size]
            
            return self._serialize_for_response({
                "tasks": paginated,
                "total": len(filtered),
                "page": page,
                "page_size": page_size
            })

    async def cleanup_zombie_tasks(self, max_running_hours: int = 2) -> Dict[str, Any]:
        """清理僵尸任务"""
        return await self.memory_manager.cleanup_zombie_tasks(max_running_hours)

    async def _update_task_status(self, task_id: str, status: AnalysisStatus, progress: int, error_message: str = None):
        """更新任务状态到MongoDB"""
        try:
            db = get_mongo_db()
            update_data = {"status": status, "progress": progress, "updated_at": now_utc()}
            if status == AnalysisStatus.PROCESSING and progress == 10:
                update_data["started_at"] = now_utc()
            elif status == AnalysisStatus.COMPLETED:
                update_data["completed_at"] = now_utc()
            elif status == AnalysisStatus.FAILED:
                update_data["last_error"] = error_message
                update_data["completed_at"] = now_utc()
            await db.analysis_tasks.update_one({"task_id": task_id}, {"$set": update_data})
        except Exception as e:
            logger.error(f"❌ 更新任务状态失败: {task_id} - {e}")

    async def _save_analysis_results_complete(self, task_id: str, result: Dict[str, Any]):
        """完整的分析结果保存"""
        try:
            stock_symbol = result.get('stock_symbol') or result.get('stock_code', 'UNKNOWN')
            # 1. 保存到本地
            await self._save_modular_reports_to_data_dir(result, stock_symbol)
            # 2. 保存到数据库 (Web Style)
            await self._save_analysis_result_web_style(task_id, result)
        except Exception as e:
            logger.error(f"❌ 保存结果失败: {e}")

    async def _save_modular_reports_to_data_dir(self, result: Dict[str, Any], stock_symbol: str) -> Dict[str, str]:
        """保存分模块报告到data目录 - 完全采用web目录的文件结构"""
        try:
            # 使用统一的路径获取方式
            runtime_base = settings.RUNTIME_BASE_DIR
            results_dir = get_analysis_results_dir(runtime_base)

            analysis_date_raw = result.get('analysis_date', now_config_tz())
            
            # 确保 analysis_date 是字符串格式
            if isinstance(analysis_date_raw, datetime):
                analysis_date_str = analysis_date_raw.strftime('%Y-%m-%d')
            elif isinstance(analysis_date_raw, str):
                # 如果已经是字符串，检查格式
                try:
                    # 尝试解析日期字符串，确保格式正确
                    datetime.strptime(analysis_date_raw, '%Y-%m-%d')
                    analysis_date_str = analysis_date_raw
                except ValueError:
                    # 如果格式不正确，使用当前日期
                    analysis_date_str = format_date_short(now_config_tz())
            else:
                # 其他类型，使用当前日期
                analysis_date_str = format_date_short(now_config_tz())
            
            stock_dir = results_dir / stock_symbol / analysis_date_str
            reports_dir = stock_dir / "reports"
            await asyncio.to_thread(reports_dir.mkdir, parents=True, exist_ok=True)
            
            # 创建message_tool.log文件 - 与web目录保持一致（线程池中执行避免阻塞事件循环）
            log_file = stock_dir / "message_tool.log"
            await asyncio.to_thread(log_file.touch, exist_ok=True)
            
            # 获取已提取的报告
            reports = result.get('reports', {})
            saved_files = {}
            
            # 🔥 动态从配置文件获取报告标题映射
            known_report_titles = {
                # 非第1阶段的固定报告（这些不是动态分析师）
                'investment_plan': '投资决策报告',
                'trader_investment_plan': '交易计划报告',
                'bull_researcher': '看涨研究报告',
                'bear_researcher': '看跌研究报告',
                'research_team_decision': '研究团队决策报告',
                'risky_analyst': '激进风险分析报告',
                'safe_analyst': '保守风险分析报告',
                'neutral_analyst': '中性风险分析报告',
                'risk_management_decision': '风险管理团队决策报告',
                'risk_manager_decision': '风险管理团队决策报告',
            }
            
            # 从配置文件动态加载第1阶段分析师的报告标题
            try:
                from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory
                for agent in DynamicAnalystFactory.get_all_agents():
                    slug = agent.get('slug', '')
                    name = agent.get('name', '')
                    if slug and name:
                        internal_key = slug.replace("-analyst", "").replace("-", "_")
                        report_key = f"{internal_key}_report"
                        known_report_titles[report_key] = f"{name}报告"
            except Exception as e:
                logger.warning(f"⚠️ 无法从配置文件加载报告标题: {e}")
            
            # 🔥 动态保存所有报告（包括新添加的智能体报告）
            for report_key, report_content in reports.items():
                try:
                    if report_content:
                        # 生成文件名：使用 report_key 作为文件名
                        filename = f"{report_key}.md"
                        # 获取友好标题，如果没有则使用 key 的格式化版本
                        title = known_report_titles.get(
                            report_key, 
                            report_key.replace('_', ' ').title() + '报告'
                        )
                        
                        file_path = reports_dir / filename
                        await asyncio.to_thread(file_path.write_text, report_content, encoding='utf-8')
                        
                        saved_files[report_key] = str(file_path)
                        logger.info(f"✅ 保存模块报告: {file_path} ({title})")
                except Exception as e:
                    logger.warning(f"⚠️ 保存模块 {report_key} 失败: {e}")
            
            # 保存最终决策报告 - 完全按照web目录的方式
            decision = result.get('decision', {})
            if decision:
                decision_content = f"# {stock_symbol} 最终投资决策\n\n"
                if isinstance(decision, dict):
                    decision_content += "## 投资建议\n\n"
                    decision_content += f"**行动**: {decision.get('action', 'N/A')}\n\n"
                    decision_content += f"**置信度**: {decision.get('confidence', 0):.1%}\n\n"
                    decision_content += f"**风险评分**: {decision.get('risk_score', 0):.1%}\n\n"
                    decision_content += f"**目标价位**: {decision.get('target_price', 'N/A')}\n\n"
                    decision_content += f"## 分析推理\n\n{decision.get('reasoning', '暂无分析推理')}\n\n"
                else:
                    decision_content += f"{str(decision)}\n\n"
                
                decision_file = reports_dir / "final_trade_decision.md"
                await asyncio.to_thread(decision_file.write_text, decision_content, encoding='utf-8')
                saved_files['final_trade_decision'] = str(decision_file)
            
            # 保存分析元数据文件 - 完全按照web目录的方式
            metadata = {
                'stock_symbol': stock_symbol,
                'analysis_date': analysis_date_str,
                'timestamp': format_iso(now_config_tz()),
                'analysts': result.get('analysts', []),
                'status': 'completed',
                'reports_count': len(saved_files),
                'report_types': list(saved_files.keys())
            }
            
            metadata_file = reports_dir.parent / "analysis_metadata.json"
            await asyncio.to_thread(
                metadata_file.write_text,
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
                
            return saved_files
        except Exception as e:
            logger.error(f"❌ 保存分模块报告失败: {e}")
            return {}

    async def _save_analysis_result_web_style(self, task_id: str, result: Dict[str, Any]):
        """保存分析结果 (Web Style)"""
        try:
            db = get_mongo_db()
            stock_symbol = result.get('stock_symbol') or result.get('stock_code', 'UNKNOWN')
            timestamp = now_utc()
            analysis_id = result.get('analysis_id') or f"{stock_symbol}_{timestamp.strftime('%Y%m%d_%H%M%S')}"

            # 处理 reports，确保为字符串内容，避免空值
            raw_reports = result.get("reports") or {}
            cleaned_reports: Dict[str, str] = {}
            if isinstance(raw_reports, dict):
                for key, value in raw_reports.items():
                    if value is None:
                        continue
                    if isinstance(value, str):
                        content = value.strip()
                    else:
                        # 对非字符串内容进行 JSON 序列化，保持可读
                        content = json.dumps(value, ensure_ascii=False, indent=2)
                    if content:
                        cleaned_reports[key] = content

            # 关键字段兜底
            analysis_date = result.get('analysis_date') or timestamp.strftime('%Y-%m-%d')
            summary = result.get("summary", "")
            recommendation = result.get("recommendation", "")
            risk_level = result.get("risk_level", "中等")
            confidence_score = result.get("confidence_score", 0.0)
            key_points = result.get("key_points") or []
            analysts = result.get("analysts") or result.get("selected_analysts") or []
            model_info = result.get("model_info") or result.get("llm_model") or "Unknown"
            tokens_used = result.get("tokens_used") or result.get("token_usage", {}).get("total_tokens", 0)
            execution_time = result.get("execution_time", 0)
            structured_summary = result.get("structured_summary") or {}
            market_type = result.get("market_type") or result.get("parameters", {}).get("market_type") or "A股"

            document = {
                "analysis_id": analysis_id,
                "stock_symbol": stock_symbol,
                "stock_name": self._resolve_stock_name(stock_symbol),
                "analysis_date": analysis_date,
                "market_type": market_type,
                "status": result.get("status", "completed"),
                "decision": result.get("decision", {}),
                "structured_summary": structured_summary,  # 🔥 显式保存结构化总结到DB
                "task_id": task_id,
                "created_at": timestamp,
                "updated_at": timestamp,
                "summary": summary,
                "recommendation": recommendation,
                "reports": cleaned_reports,
                "confidence_score": confidence_score,
                "risk_level": risk_level,
                "key_points": key_points,
                "analysts": analysts,
                "model_info": model_info,
                "tokens_used": tokens_used,
                "execution_time": execution_time,
                "source": result.get("source", "analysis_service")
            }

            # 写入报告集合
            insert_result = await db.analysis_reports.insert_one(document)

            # 更新任务集合中的结果，携带 report_id 便于前端关联
            document_for_task = {**document, "_id": insert_result.inserted_id}
            await db.analysis_tasks.update_one(
                {"task_id": task_id},
                {"$set": {"result": document_for_task}}
            )
        except Exception as e:
            logger.error(f"❌ 保存DB结果失败: {e}")


    # -------------------------------------------------------------------------
    # Router-facing Methods (added for analysis.py DB abstraction)
    # -------------------------------------------------------------------------

    async def get_task_with_status_fallback(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务状态，依次尝试：内存 → analysis_tasks 集合 → analysis_reports 集合。

        Returns:
            包含 "source" 字段标记数据来源的字典（mongodb_tasks / mongodb_reports），
            或 None 表示所有来源均未找到。
        """
        # 1) 先走现有的 get_task_status（内存 + Redis 进度）
        result = await self.get_task_status(task_id)
        if result:
            return result

        # 2) 从 analysis_tasks 集合查找
        try:
            db = get_mongo_db()
            task_result = await db.analysis_tasks.find_one({"task_id": task_id})
        except Exception as e:
            logger.warning(f"⚠️ get_task_with_status_fallback 查询 analysis_tasks 失败: {e}")
            task_result = None

        if task_result:
            status = task_result.get("status", "pending")
            progress = task_result.get("progress", 0)
            start_time = task_result.get("started_at") or task_result.get("created_at")
            current_time = now_utc()
            elapsed_time = 0
            if start_time:
                elapsed_time = (current_time - start_time).total_seconds()

            return {
                "task_id": task_id,
                "status": status,
                "progress": progress,
                "message": f"任务{status}中...",
                "current_step": status,
                "start_time": start_time,
                "end_time": task_result.get("completed_at"),
                "elapsed_time": elapsed_time,
                "remaining_time": 0,
                "estimated_total_time": 0,
                "symbol": task_result.get("symbol") or task_result.get("stock_code"),
                "stock_code": task_result.get("symbol") or task_result.get("stock_code"),
                "stock_symbol": task_result.get("symbol") or task_result.get("stock_code"),
                "source": "mongodb_tasks",
            }

        # 3) 尝试通过 analysis_id 兜底查找 analysis_reports
        report = await self._find_report_by_task_id(task_id)
        if report:
            start_time = report.get("created_at")
            end_time = report.get("updated_at")
            elapsed_time = 0
            if start_time and end_time:
                elapsed_time = (end_time - start_time).total_seconds()

            return {
                "task_id": task_id,
                "status": "completed",
                "progress": 100,
                "message": "分析完成（从历史记录恢复）",
                "current_step": "completed",
                "start_time": start_time,
                "end_time": end_time,
                "elapsed_time": elapsed_time,
                "remaining_time": 0,
                "estimated_total_time": elapsed_time,
                "stock_code": report.get("stock_symbol"),
                "stock_symbol": report.get("stock_symbol"),
                "source": "mongodb_reports",
            }

        return None

    async def _find_report_by_task_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        从 analysis_reports 中根据 task_id 查找报告。
        兼容旧数据：如果直接查不到，通过 analysis_tasks.result.analysis_id 兜底。
        """
        try:
            db = get_mongo_db()
            report = await db.analysis_reports.find_one({"task_id": task_id})
            if report:
                return report

            # 兼容旧数据
            tasks_doc = await db.analysis_tasks.find_one(
                {"task_id": task_id},
                {"result.analysis_id": 1}
            )
            if tasks_doc:
                analysis_id = tasks_doc.get("result", {}).get("analysis_id")
                if analysis_id:
                    return await db.analysis_reports.find_one({"analysis_id": analysis_id})
        except Exception as e:
            logger.warning(f"⚠️ _find_report_by_task_id 失败: {e}")
        return None

    async def get_task_result_data(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务的完整分析结果数据。

        查询顺序：内存 → analysis_reports（按 task_id / analysis_id）→ analysis_tasks.result。

        Returns:
            结果字典（含 "source" 标记），或 None。
        """
        # 1) 内存中获取
        task_status = await self.get_task_status(task_id)
        if task_status and task_status.get("status") == "completed" and task_status.get("result_data"):
            return task_status["result_data"]

        # 2) 从 analysis_reports 获取
        mongo_result = await self._find_report_by_task_id(task_id)
        if mongo_result:
            result_data = {
                "analysis_id": mongo_result.get("analysis_id"),
                "stock_symbol": mongo_result.get("stock_symbol"),
                "stock_code": mongo_result.get("stock_symbol"),
                "analysis_date": mongo_result.get("analysis_date"),
                "summary": mongo_result.get("summary", ""),
                "recommendation": mongo_result.get("recommendation", ""),
                "confidence_score": mongo_result.get("confidence_score", 0.0),
                "risk_level": mongo_result.get("risk_level", "中等"),
                "key_points": mongo_result.get("key_points", []),
                "execution_time": mongo_result.get("execution_time", 0),
                "tokens_used": mongo_result.get("tokens_used", 0),
                "analysts": mongo_result.get("analysts", []),
                "reports": mongo_result.get("reports", {}),
                "created_at": mongo_result.get("created_at"),
                "updated_at": mongo_result.get("updated_at"),
                "status": mongo_result.get("status", "completed"),
                "decision": mongo_result.get("decision", {}),
                "source": "mongodb",
            }
            return result_data

        # 3) 从 analysis_tasks.result 兜底
        try:
            db = get_mongo_db()
            tasks_doc = await db.analysis_tasks.find_one(
                {"task_id": task_id},
                {"result": 1, "symbol": 1, "stock_code": 1, "created_at": 1, "completed_at": 1}
            )
            if tasks_doc and tasks_doc.get("result"):
                r = tasks_doc["result"] or {}
                symbol = (
                    tasks_doc.get("symbol") or tasks_doc.get("stock_code") or
                    r.get("stock_symbol") or r.get("stock_code")
                )
                return {
                    "analysis_id": r.get("analysis_id"),
                    "stock_symbol": symbol,
                    "stock_code": symbol,
                    "analysis_date": r.get("analysis_date"),
                    "summary": r.get("summary", ""),
                    "recommendation": r.get("recommendation", ""),
                    "confidence_score": r.get("confidence_score", 0.0),
                    "risk_level": r.get("risk_level", "中等"),
                    "key_points": r.get("key_points", []),
                    "execution_time": r.get("execution_time", 0),
                    "tokens_used": r.get("tokens_used", 0),
                    "analysts": r.get("analysts", []),
                    "reports": r.get("reports", {}),
                    "state": r.get("state", {}),
                    "detailed_analysis": r.get("detailed_analysis", {}),
                    "created_at": tasks_doc.get("created_at"),
                    "updated_at": tasks_doc.get("completed_at"),
                    "status": r.get("status", "completed"),
                    "decision": r.get("decision", {}),
                    "source": "analysis_tasks",
                }
        except Exception as e:
            logger.warning(f"⚠️ get_task_result_data 从 analysis_tasks.result 兜底失败: {e}")

        return None

    async def mark_task_failed(self, task_id: str, error_message: str = "用户手动标记为失败") -> bool:
        """
        将任务标记为失败（内存 + MongoDB 同步更新）。
        """
        try:
            # 更新内存状态
            await self.memory_manager.update_task_status(
                task_id=task_id,
                status=TaskStatus.FAILED,
                message="手动标记为失败",
                error_message=error_message,
            )

            # 更新 MongoDB
            db = get_mongo_db()
            result = await db.analysis_tasks.update_one(
                {"task_id": task_id},
                {"$set": {
                    "status": "failed",
                    "last_error": error_message,
                    "completed_at": now_utc(),
                    "updated_at": now_utc(),
                }},
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"❌ mark_task_failed 失败: {e}")
            return False

    async def validate_task_ownership(self, task_id: str, user_id: str) -> bool:
        """
        验证任务是否属于指定用户。

        查询顺序：内存 → MongoDB（兼容 Redis 已过期的完成/失败任务）。
        """
        # 1) 内存中查找
        task = await self.memory_manager.get_task_dict(task_id)
        if task and task.get("user_id") == user_id:
            return True

        # 2) MongoDB 中查找
        try:
            db = get_mongo_db()
            task_doc = await db.analysis_tasks.find_one(
                {"task_id": task_id}, {"user_id": 1}
            )
            return task_doc is not None and task_doc.get("user_id") == user_id
        except Exception as e:
            logger.error(f"❌ validate_task_ownership 查询失败: {e}")
            return False

    async def delete_task_by_id(self, task_id: str, user_id: Optional[str] = None) -> bool:
        """
        从内存和数据库中删除任务记录。

        支持通过 user_id 进行所有权验证。当 Redis 中找不到任务时，
        会回退到 MongoDB 进行验证（适用于已完成/失败等过期任务）。
        """
        try:
            # 构造过滤条件：将所有权校验合并到删除操作中，减少数据库往返
            filter_doc: Dict[str, Any] = {"task_id": task_id}
            if user_id is not None:
                filter_doc["user_id"] = user_id

            db = get_mongo_db()
            result = await db.analysis_tasks.delete_one(filter_doc)

            if result.deleted_count > 0:
                await self.memory_manager.remove_task(task_id)
                return True

            # 删除失败时，区分"非本人任务"和"任务不存在"
            if user_id is not None:
                existing = await db.analysis_tasks.find_one(
                    {"task_id": task_id}, {"user_id": 1}
                )
                if existing and existing.get("user_id") != user_id:
                    logger.warning(f"⚠️ 用户 {user_id} 尝试删除非本人任务: {task_id}")
                    return False

            # 任务不在 MongoDB 中（可能仅在内存中），仍需清理内存状态
            await self.memory_manager.remove_task(task_id)
            return False
        except Exception as e:
            logger.error(f"❌ delete_task_by_id 失败: {e}")
            return False

    async def get_analysis_stats(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        market_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        获取分析报告统计信息（总数、按日期、按市场分布）。
        """
        try:
            db = get_mongo_db()
            query: Dict[str, Any] = {}
            if start_date or end_date:
                date_query: Dict[str, Any] = {}
                if start_date:
                    date_query["$gte"] = start_date
                if end_date:
                    date_query["$lte"] = end_date
                query["created_at"] = date_query
            if market_type:
                query["market_type"] = market_type

            total = await db.analysis_reports.count_documents(query)
            completed = await db.analysis_reports.count_documents({**query, "status": "completed"})
            failed = await db.analysis_reports.count_documents({**query, "status": "failed"})

            # 按日期统计
            pipeline_date = [
                {"$match": query},
                {"$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                    "count": {"$sum": 1},
                }},
                {"$sort": {"_id": -1}},
                {"$limit": 30},
            ]
            by_date = []
            async for doc in db.analysis_reports.aggregate(pipeline_date):
                by_date.append({"date": doc["_id"], "count": doc["count"]})

            # 按市场统计
            pipeline_market = [
                {"$match": query},
                {"$group": {"_id": "$market_type", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ]
            by_market = []
            async for doc in db.analysis_reports.aggregate(pipeline_market):
                by_market.append({"market": doc["_id"] or "未知", "count": doc["count"]})

            return {
                "total_analyses": total,
                "successful_analyses": completed,
                "failed_analyses": failed,
                "avg_duration": 0,
                "total_tokens": 0,
                "total_cost": 0,
                "popular_stocks": [],
                "analysis_by_date": by_date,
                "analysis_by_market": by_market,
            }
        except Exception as e:
            logger.error(f"❌ get_analysis_stats 失败: {e}")
            raise

    async def get_stock_info_with_quote(self, symbol: str, market: str = "A股") -> Optional[Dict[str, Any]]:
        """
        获取股票基础信息 + 实时行情（用于分析前预览）。

        按数据源优先级查询 stock_basic_info，并补充 market_quotes。
        """
        try:
            db = get_mongo_db()
            code6 = str(symbol).zfill(6)

            # 数据源优先级
            try:
                from app.data.core.registry.priority import PriorityConfig
                enabled_sources = PriorityConfig().get_default_sources("CN", "basic_info")
            except Exception:
                enabled_sources = ["tushare", "akshare", "baostock"]

            b = None
            for src in enabled_sources:
                b = await db.stock_basic_info.find_one({"symbol": code6, "data_source": src}, {"_id": 0})
                if b:
                    break
            if not b:
                b = await db.stock_basic_info.find_one({"symbol": code6}, {"_id": 0})

            if not b:
                return None

            q = await db.market_quotes.find_one({"symbol": code6}, {"_id": 0})

            return {
                "symbol": b.get("symbol", code6),
                "name": b.get("name", ""),
                "market": b.get("market", market),
                "industry": b.get("industry", ""),
                "sector": b.get("sector", ""),
                "market_cap": b.get("total_mv"),
                "price": (q or {}).get("close") or b.get("close"),
                "change_percent": (q or {}).get("pct_chg"),
                "pe_ratio": b.get("pe"),
                "pb_ratio": b.get("pb"),
                "dividend_yield": b.get("dividend_yield"),
                "volume": (q or {}).get("volume"),
            }
        except Exception as e:
            logger.error(f"❌ get_stock_info_with_quote 失败: {e}")
            raise

    async def search_stock_basic_info(
        self,
        query: str,
        market: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        在 stock_basic_info 集合中搜索股票（支持名称/代码/符号模糊匹配）。
        """
        try:
            db = get_mongo_db()
            import re
            escaped_query = re.escape(query)
            search_regex = f".*{escaped_query}.*"
            filter_expr: Dict[str, Any] = {
                "$or": [
                    {"name": {"$regex": search_regex, "$options": "i"}},
                    {"symbol": {"$regex": search_regex, "$options": "i"}},
                ],
            }
            if market:
                filter_expr["market"] = market

            cursor = db.stock_basic_info.find(filter_expr, {
                "name": 1, "symbol": 1, "market": 1, "industry": 1, "_id": 0,
            }).limit(limit)

            results = []
            async for doc in cursor:
                results.append({
                    "symbol": doc.get("symbol", ""),
                    "name": doc.get("name", ""),
                    "market": doc.get("market", "A股"),
                    "type": "stock",
                })
            return results
        except Exception as e:
            logger.error(f"❌ search_stock_basic_info 失败: {e}")
            raise

    async def get_popular_stocks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取热门股票（按分析报告次数排序），并补充基础信息和行情。
        """
        try:
            db = get_mongo_db()
            pipeline = [
                {"$group": {"_id": "$stock_symbol", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": limit},
            ]

            results = []
            async for doc in db.analysis_reports.aggregate(pipeline):
                symbol = doc["_id"]
                if not symbol:
                    continue
                code6 = str(symbol).zfill(6)
                b = await db.stock_basic_info.find_one({"symbol": code6}, {"_id": 0, "name": 1, "market": 1})
                q = await db.market_quotes.find_one({"symbol": code6}, {"_id": 0, "close": 1, "pct_chg": 1, "volume": 1})

                results.append({
                    "symbol": symbol,
                    "name": (b or {}).get("name", ""),
                    "market": (b or {}).get("market", "A股"),
                    "current_price": (q or {}).get("close"),
                    "change_percent": (q or {}).get("pct_chg"),
                    "volume": (q or {}).get("volume"),
                    "analysis_count": doc["count"],
                })

            return results
        except Exception as e:
            logger.error(f"❌ get_popular_stocks 失败: {e}")
            raise


# 全局分析服务实例
analysis_service: Optional[AnalysisService] = None

def get_analysis_service() -> AnalysisService:
    """获取分析服务实例"""
    global analysis_service
    if analysis_service is None:
        analysis_service = AnalysisService()
    return analysis_service


