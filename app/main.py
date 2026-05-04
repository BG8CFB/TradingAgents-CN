"""
TradingAgents-CN v1.0.0-preview FastAPI Backend
主应用程序入口

Copyright (c) 2025 hsliuping. All rights reserved.
版权所有 (c) 2025 hsliuping。保留所有权利。

This software is proprietary and confidential. Unauthorized copying, distribution,
or use of this software, via any medium, is strictly prohibited.
本软件为专有和机密软件。严禁通过任何媒介未经授权复制、分发或使用本软件。

For commercial licensing, please contact: hsliup@163.com
商业许可咨询，请联系：hsliup@163.com
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import logging
import time
from datetime import datetime
from contextlib import asynccontextmanager
import asyncio
from pathlib import Path

from app.core.config import settings
from app.utils.timezone import now_utc
from app.core.database import init_db, close_db
from app.core.logging_config import setup_logging
from app.routers import auth_db as auth, analysis, screening, sse, health, favorites, config, reports, database, operation_logs, tags, news_data, usage_statistics, model_capabilities, cache, logs
from app.routers import mcp, tools
from app.routers import agent_configs
from app.routers import multi_source_sync
from app.routers import stocks as stocks_router
from app.routers import stock_sync as stock_sync_router
from app.routers import notifications as notifications_router
from app.routers import websocket_notifications as websocket_notifications_router
from app.routers import scheduler as scheduler_router
from app.services.basics_sync_service import get_basics_sync_service
from app.services.multi_source_basics_sync_service import MultiSourceBasicsSyncService
from app.services.scheduler_service import set_scheduler_instance
# Phase 4G: 数据源 sync service 导入已移至 app/worker/scheduler_setup.py
from app.middleware.operation_log_middleware import OperationLogMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.quotes_ingestion_service import QuotesIngestionService

# 模块级变量：供 APScheduler 调度的基础信息同步服务实例
_basics_sync_service: MultiSourceBasicsSyncService | None = None


async def _run_basics_sync(force: bool = False, preferred_sources: list | None = None):
    """
    模块级异步函数，供 APScheduler 调度基础信息同步。
    APScheduler 要求 job 目标函数可被模块路径引用（app.main._run_basics_sync），
    因此不能使用闭包或局部函数。
    """
    if _basics_sync_service is None:
        logger_placeholder = logging.getLogger("app.main")
        logger_placeholder.warning("⚠️ 基础信息同步服务未初始化，跳过同步")
        return
    await _basics_sync_service.run_full_sync(force=force, preferred_sources=preferred_sources)


def get_version() -> str:
    """从 VERSION 文件读取版本号"""
    try:
        version_file = Path(__file__).parent.parent / "VERSION"
        if version_file.exists():
            return version_file.read_text(encoding='utf-8').strip()
    except Exception:
        pass
    return "1.0.0"  # 默认版本号


async def _print_config_summary(logger):
    """显示配置摘要"""
    try:
        logger.info("=" * 70)
        logger.info("📋 TradingAgents-CN Configuration Summary")
        logger.info("=" * 70)

        # .env 文件路径信息
        import os
        from pathlib import Path
        
        current_dir = Path.cwd()
        logger.info(f"📁 Current working directory: {current_dir}")
        
        # 检查可能的 .env 文件位置
        env_files_to_check = [
            current_dir / ".env",
            current_dir / "app" / ".env",
            Path(__file__).parent.parent / ".env",  # 项目根目录
        ]
        
        logger.info("🔍 Checking .env file locations:")
        env_file_found = False
        for env_file in env_files_to_check:
            if env_file.exists():
                logger.info(f"  ✅ Found: {env_file} (size: {env_file.stat().st_size} bytes)")
                env_file_found = True
                # 显示文件的前几行（隐藏敏感信息）
                try:
                    with open(env_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()[:5]  # 只读前5行
                        logger.info(f"     Preview (first 5 lines):")
                        for i, line in enumerate(lines, 1):
                            # 隐藏包含密码、密钥等敏感信息的行
                            if any(keyword in line.upper() for keyword in ['PASSWORD', 'SECRET', 'KEY', 'TOKEN']):
                                logger.info(f"       {i}: {line.split('=')[0]}=***")
                            else:
                                logger.info(f"       {i}: {line.strip()}")
                except Exception as e:
                    logger.warning(f"     Could not preview file: {e}")
            else:
                logger.info(f"  ❌ Not found: {env_file}")
        
        if not env_file_found:
            logger.warning("⚠️  No .env file found in checked locations")
        
        # Pydantic Settings 配置加载状态
        logger.info("⚙️  Pydantic Settings Configuration:")
        logger.info(f"  • Settings class: {settings.__class__.__name__}")
        logger.info(f"  • Config source: {getattr(settings.model_config, 'env_file', 'Not specified')}")
        logger.info(f"  • Encoding: {getattr(settings.model_config, 'env_file_encoding', 'Not specified')}")
        
        # 显示一些关键配置值的来源（环境变量 vs 默认值）
        key_settings = ['HOST', 'PORT', 'DEBUG', 'MONGODB_HOST', 'REDIS_HOST']
        logger.info("  • Key settings sources:")
        for setting_name in key_settings:
            env_var_name = setting_name
            env_value = os.getenv(env_var_name)
            config_value = getattr(settings, setting_name, None)
            if env_value is not None:
                logger.info(f"    - {setting_name}: from environment variable ({config_value})")
            else:
                logger.info(f"    - {setting_name}: using default value ({config_value})")
        
        # 环境信息
        env = "Production" if settings.is_production else "Development"
        logger.info(f"Environment: {env}")

        # 数据库连接
        logger.info(f"MongoDB: {settings.MONGODB_HOST}:{settings.MONGODB_PORT}/{settings.MONGODB_DATABASE}")
        logger.info(f"Redis: {settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}")

        # 代理配置
        import os
        if settings.HTTP_PROXY or settings.HTTPS_PROXY:
            logger.info("Proxy Configuration:")
            if settings.HTTP_PROXY:
                logger.info(f"  HTTP_PROXY: {settings.HTTP_PROXY}")
            if settings.HTTPS_PROXY:
                logger.info(f"  HTTPS_PROXY: {settings.HTTPS_PROXY}")
            if settings.NO_PROXY:
                # 只显示前3个域名
                no_proxy_list = settings.NO_PROXY.split(',')
                if len(no_proxy_list) <= 3:
                    logger.info(f"  NO_PROXY: {settings.NO_PROXY}")
                else:
                    logger.info(f"  NO_PROXY: {','.join(no_proxy_list[:3])}... ({len(no_proxy_list)} domains)")
            logger.info(f"  ✅ Proxy environment variables set successfully")
        else:
            logger.info("Proxy: Not configured (direct connection)")

        # 检查大模型配置
        try:
            from app.services.config_service import config_service
            config = await config_service.get_system_config()
            if config and config.llm_configs:
                enabled_llms = [llm for llm in config.llm_configs if llm.enabled]
                logger.info(f"Enabled LLMs: {len(enabled_llms)}")
                if enabled_llms:
                    for llm in enabled_llms[:3]:  # 只显示前3个
                        logger.info(f"  • {llm.provider}: {llm.model_name}")
                    if len(enabled_llms) > 3:
                        logger.info(f"  • ... and {len(enabled_llms) - 3} more")
                else:
                    logger.warning("⚠️  No LLM enabled. Please configure at least one LLM in Web UI.")
            else:
                logger.warning("⚠️  No LLM configured. Please configure at least one LLM in Web UI.")
        except Exception as e:
            logger.warning(f"⚠️  Failed to check LLM configs: {e}")

        # 检查数据源配置
        try:
            if config and config.data_source_configs:
                enabled_sources = [ds for ds in config.data_source_configs if ds.enabled]
                logger.info(f"Enabled Data Sources: {len(enabled_sources)}")
                if enabled_sources:
                    for ds in enabled_sources[:3]:  # 只显示前3个
                        logger.info(f"  • {ds.type.value}: {ds.name}")
                    if len(enabled_sources) > 3:
                        logger.info(f"  • ... and {len(enabled_sources) - 3} more")
            else:
                logger.info("Data Sources: Using default (AKShare)")
        except Exception as e:
            logger.warning(f"⚠️  Failed to check data source configs: {e}")

        logger.info("=" * 70)
    except Exception as e:
        logger.error(f"Failed to print config summary: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    setup_logging()
    logger = logging.getLogger("app.main")

    # 验证启动配置
    try:
        from app.core.startup_validator import validate_startup_config
        validate_startup_config()
    except Exception as e:
        logger.error(f"配置验证失败: {e}")
        raise

    await init_db()

    # 初始化 UserService 的数据库连接
    try:
        from app.services.user_service import user_service
        from app.core.database import get_mongo_db
        user_service.set_database(get_mongo_db())
        logger.info("✅ UserService 数据库连接已初始化")
    except Exception as e:
        logger.error(f"❌ UserService 初始化失败: {e}")
        raise

    # 系统初始化：导入默认配置和用户
    try:
        from app.services.system_init_service import SystemInitService
        await SystemInitService.initialize_system()
    except Exception as e:
        logger.error(f"❌ System initialization failed: {e}")
        logger.error("❌ Application cannot start without proper initialization")
        raise  # 必须抛出异常，防止系统在半初始化状态下运行

    #  配置桥接：将统一配置写入环境变量，供 TradingAgents 核心库使用
    try:
        from app.core.config_bridge import bridge_config_to_env

        bridge_success = await asyncio.wait_for(
            bridge_config_to_env(),
            timeout=30
        )
        if not bridge_success:
            logger.warning("⚠️  配置桥接未成功完成，TradingAgents 将使用 .env 文件中的配置")
    except asyncio.TimeoutError:
        logger.error("❌ 配置桥接超时（30 秒），启动流程将降级使用 .env 配置")
        logger.warning("⚠️  TradingAgents 将使用 .env 文件中的配置")
    except Exception as e:
        logger.warning(f"⚠️  配置桥接失败: {e}")
        logger.warning("⚠️  TradingAgents 将使用 .env 文件中的配置")

    # Apply dynamic settings (log_level, enable_monitoring) from ConfigProvider
    try:
        from app.services.config_provider import provider as config_provider  # local import to avoid early DB init issues
        eff = await config_provider.get_effective_system_settings()

        # 将动态配置注入引擎层缓存，供 sync 上下文读取
        from app.engine.config.runtime_settings import set_cached_settings
        set_cached_settings(eff)

        desired_level = str(eff.get("log_level", "INFO")).upper()
        setup_logging(log_level=desired_level)
        for name in ("webapi", "worker", "uvicorn", "fastapi"):
            logging.getLogger(name).setLevel(desired_level)
        try:
            from app.middleware.operation_log_middleware import set_operation_log_enabled
            set_operation_log_enabled(bool(eff.get("enable_monitoring", True)))
        except Exception:
            pass
    except Exception as e:
        logging.getLogger("webapi").warning(f"Failed to apply dynamic settings: {e}")

    # 显示配置摘要
    await _print_config_summary(logger)

    logger.info("TradingAgents FastAPI backend started")

    # 启动期：若需要在休市时补充上一交易日收盘快照
    if settings.QUOTES_BACKFILL_ON_STARTUP:
        try:
            qi = QuotesIngestionService()
            await qi.ensure_indexes()
            await qi.backfill_last_close_snapshot_if_needed()
        except Exception as e:
            logger.warning(f"Startup backfill failed (ignored): {e}")

    # 启动每日定时任务：可配置
    scheduler: AsyncIOScheduler | None = None

    try:
        scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)

        # 初始化多数据源同步服务
        global _basics_sync_service
        _basics_sync_service = MultiSourceBasicsSyncService()

        # Phase 4G: 所有定时任务注册已提取到 app/worker/scheduler_setup.py
        from app.worker.scheduler_setup import register_jobs
        await register_jobs(scheduler, _basics_sync_service, _run_basics_sync)

        scheduler.start()

        # 设置调度器实例到服务中，以便API可以管理任务
        set_scheduler_instance(scheduler)
        logger.info("调度器服务已初始化")
    except Exception as e:
        logger.error(f"❌ 调度器启动失败: {e}", exc_info=True)
        raise  # 抛出异常，阻止应用启动

    # ==================== MCP 连接初始化（应用级基础设施） ====================
    # 在应用启动时建立所有 MCP 连接，在整个应用生命周期内保持活跃
    mcp_health_check_task = None
    try:
        from app.engine.tools.mcp import LANGCHAIN_MCP_AVAILABLE, get_mcp_loader_factory

        if LANGCHAIN_MCP_AVAILABLE:
            logger.info("🔧 初始化 MCP 连接管理器...")

            factory = get_mcp_loader_factory()
            await factory.initialize_connections()

            # 启动健康检查后台任务
            async def mcp_health_check_loop():
                """MCP 服务器健康检查后台任务"""
                while True:
                    try:
                        await factory.health_check_all()
                        await asyncio.sleep(30)  # 每 30 秒检查一次
                    except asyncio.CancelledError:
                        logger.info("🛑 MCP 健康检查任务已停止")
                        break
                    except Exception as e:
                        logger.error(f"MCP 健康检查失败: {e}")
                        await asyncio.sleep(30)

            mcp_health_check_task = asyncio.create_task(mcp_health_check_loop())
            logger.info("✅ MCP 连接已初始化，健康检查任务已启动")
        else:
            logger.info("ℹ️  langchain-mcp-adapters 未安装，MCP 功能不可用")
    except Exception as e:
        logger.error(f"❌ MCP 初始化失败: {e}", exc_info=True)
        # MCP 初始化失败不应阻止应用启动，记录警告并继续
        logger.warning("⚠️  应用将在 MCP 功能不可用的情况下继续运行")

    try:
        yield
    finally:
        # 关闭时清理
        # 1. 停止 MCP 健康检查任务
        if mcp_health_check_task:
            try:
                mcp_health_check_task.cancel()
                try:
                    await mcp_health_check_task
                except asyncio.CancelledError:
                    pass
                logger.info("🛑 MCP 健康检查任务已停止")
            except Exception as e:
                logger.warning(f"MCP 健康检查任务停止失败: {e}")

        # 2. 关闭所有 MCP 连接
        try:
            from app.engine.tools.mcp import get_mcp_loader_factory
            factory = get_mcp_loader_factory()
            await factory.close()
            logger.info("🛑 MCP 连接已关闭")
        except Exception as e:
            logger.warning(f"MCP 连接关闭失败: {e}")

        # 3. 停止调度器
        if scheduler:
            try:
                scheduler.shutdown(wait=True)
                logger.info("🛑 Scheduler stopped")
            except Exception as e:
                logger.warning(f"Scheduler shutdown error: {e}")

        # 4. 关闭数据库连接
        await close_db()
        logger.info("TradingAgents FastAPI backend stopped")


# 创建FastAPI应用
app = FastAPI(
    title="TradingAgents-CN API",
    description="股票分析与批量队列系统 API",
    version=get_version(),
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan
)

# 安全中间件
if not settings.DEBUG:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.ALLOWED_HOSTS
    )

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# 操作日志中间件
app.add_middleware(OperationLogMiddleware)

# 速率限制中间件（在操作日志之后注册 = 在操作日志之前执行）
from app.middleware.rate_limit import RateLimitMiddleware, QuotaMiddleware
app.add_middleware(QuotaMiddleware)
app.add_middleware(RateLimitMiddleware)


# 请求日志中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()

    # 跳过健康检查和静态文件请求的日志
    if request.url.path in ["/health", "/favicon.ico"] or request.url.path.startswith("/static"):
        response = await call_next(request)
        return response

    # 使用webapi logger记录请求
    logger = logging.getLogger("webapi")
    logger.info(f"🔄 {request.method} {request.url.path} - 开始处理")

    response = await call_next(request)
    process_time = time.time() - start_time

    # 记录请求完成
    status_emoji = "✅" if response.status_code < 400 else "❌"
    logger.info(f"{status_emoji} {request.method} {request.url.path} - 状态: {response.status_code} - 耗时: {process_time:.3f}s")

    return response


# 全局异常处理
# 请求ID/Trace-ID 中间件（需作为最外层，放在函数式中间件之后）
from app.middleware.request_id import RequestIDMiddleware
app.add_middleware(RequestIDMiddleware)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器，提供异常分类和标准化错误响应"""
    request_id = getattr(request.state, "request_id", None)

    if isinstance(exc, ValueError):
        logging.warning(f"Validation error: {exc}")
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": str(exc),
                    "request_id": request_id
                }
            }
        )

    if isinstance(exc, PermissionError):
        logging.warning(f"Permission denied: {exc}")
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "PERMISSION_DENIED",
                    "message": "权限不足",
                    "request_id": request_id
                }
            }
        )

    if isinstance(exc, FileNotFoundError):
        logging.warning(f"Resource not found: {exc}")
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "RESOURCE_NOT_FOUND",
                    "message": "请求的资源不存在",
                    "request_id": request_id
                }
            }
        )

    logging.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Internal server error occurred",
                "request_id": request_id
            }
        }
    )


# 测试端点 - 仅在 DEBUG 模式下注册
if settings.DEBUG:
    @app.get("/api/test-log")
    async def test_log():
        """测试日志中间件是否工作（仅 DEBUG 模式）"""
        logging.getLogger("app.main").debug("test-log endpoint called")
        return {"message": "测试成功", "timestamp": time.time()}

# 注册路由
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(reports.router)
app.include_router(screening.router)
app.include_router(favorites.router)
app.include_router(stocks_router.router)
app.include_router(stock_sync_router.router)
app.include_router(tags.router)
app.include_router(config.router)
app.include_router(model_capabilities.router)
app.include_router(usage_statistics.router)
app.include_router(database.router)
app.include_router(cache.router)
app.include_router(operation_logs.router)
app.include_router(logs.router)
# 新增：智能体管理
from app.routers import agents
app.include_router(agents.router)
# 系统配置只读摘要
from app.routers import system_config as system_config_router
app.include_router(system_config_router.router)
app.include_router(mcp.router)
# 统一工具清单
app.include_router(tools.router)
# 按阶段编辑智能体配置
app.include_router(agent_configs.router)

# 通知模块（REST + SSE）
app.include_router(notifications_router.router)

# 🔥 WebSocket 通知模块（替代 SSE + Redis PubSub）
app.include_router(websocket_notifications_router.router)

# 定时任务管理
app.include_router(scheduler_router.router)

app.include_router(sse.router)
app.include_router(multi_source_sync.router)
app.include_router(news_data.router)


@app.get("/")
async def root():
    """根路径，返回API信息"""
    logging.getLogger("app.main").debug("Root path accessed")
    return {
        "name": "TradingAgents-CN API",
        "version": get_version(),
        "status": "running",
        "docs_url": "/docs" if settings.DEBUG else None
    }


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
        reload_dirs=["app"] if settings.DEBUG else None,
        reload_excludes=[
            "__pycache__",
            "*.pyc",
            "*.pyo",
            "*.pyd",
            ".git",
            ".pytest_cache",
            "*.log",
            "*.tmp"
        ] if settings.DEBUG else None,
        reload_includes=["*.py"] if settings.DEBUG else None
    )
