from pathlib import Path
from typing import Dict, List
from urllib.parse import quote_plus
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import logging as _logging
import os
import secrets
import shutil
import threading
import warnings

# 🔧 延迟导入以避免循环导入：runtime_paths -> logging -> config
# 将在属性方法中导入

# ── .env 自动引导 ──────────────────────────────────────────────────
# 仅在本地开发模式下生效：首次启动时若 .env 不存在，从 .env.example 复制一份。
#
# 容器模式（DOCKER_CONTAINER=true）下不做自动复制——所有配置通过
# docker-compose 的 environment: 段注入 os.environ，应用直接读取即可。
# 这样可以避免"容器内 /app/.env 与宿主机部署目录 .env 冲突"的混淆，
# 同时让"部署目录的 .env"成为用户自定义的唯一入口。
_IS_CONTAINER_ENV = os.getenv("DOCKER_CONTAINER", "").lower() in ("true", "1", "yes")
if not _IS_CONTAINER_ENV:
    _BOOT_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
    _BOOT_ENV_EXAMPLE = _BOOT_ENV_PATH.parent / ".env.example"
    if not _BOOT_ENV_PATH.exists() and _BOOT_ENV_EXAMPLE.exists():
        shutil.copy2(_BOOT_ENV_EXAMPLE, _BOOT_ENV_PATH)
        _logging.getLogger("app.config").warning(
            "已自动从 .env.example 创建 .env，请根据需要调整数据库连接配置"
        )

# Legacy env var aliases (deprecated): map API_HOST/PORT/DEBUG -> HOST/PORT/DEBUG
_LEGACY_ENV_ALIASES = {
    "API_HOST": "HOST",
    "API_PORT": "PORT",
    "API_DEBUG": "DEBUG",
}
for _legacy, _new in _LEGACY_ENV_ALIASES.items():
    if _new not in os.environ and _legacy in os.environ:
        os.environ[_new] = os.environ[_legacy]
        warnings.warn(
            f"Environment variable {_legacy} is deprecated; use {_new} instead.",
            DeprecationWarning,
            stacklevel=2,
        )


_runtime_secret_cache: Dict[str, str] = {}
_runtime_secret_lock = threading.Lock()


def _runtime_secret(name: str) -> str:
    """在未配置环境变量时生成运行期密钥，避免固定默认值。

    使用进程级缓存：每次未配置 env 时返回**同一个**随机生成的值，
    保证进程内一致性（避免同一进程内 JWT_SECRET/CSRF_SECRET 漂移）。

    SecretService 启动后会写入 ``os.environ``，下次访问 ``os.getenv`` 命中。
    """
    configured = os.getenv(name)
    if configured:
        return configured
    with _runtime_secret_lock:
        if name not in _runtime_secret_cache:
            _runtime_secret_cache[name] = secrets.token_urlsafe(32)
        return _runtime_secret_cache[name]

class Settings(BaseSettings):
    # 基础配置
    DEBUG: bool = Field(default=False)
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)
    ALLOWED_ORIGINS: List[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    ALLOWED_HOSTS: List[str] = Field(default_factory=lambda: ["*"])

    # 运行时根目录（所有日志/数据/缓存统一收敛到此目录下）
    RUNTIME_BASE_DIR: str = Field(default="runtime")

    # MongoDB配置
    MONGODB_HOST: str = Field(default="localhost")
    MONGODB_PORT: int = Field(default=27017)
    MONGODB_USERNAME: str = Field(default="")
    MONGODB_PASSWORD: str = Field(default="")
    MONGODB_DATABASE: str = Field(default="tradingagents")
    MONGODB_AUTH_SOURCE: str = Field(default="admin")
    MONGO_MAX_CONNECTIONS: int = Field(default=100)
    MONGO_MIN_CONNECTIONS: int = Field(default=10)
    # MongoDB超时参数（毫秒）- 用于处理大量历史数据
    MONGO_CONNECT_TIMEOUT_MS: int = Field(default=30000)  # 连接超时：30秒（原为10秒）
    MONGO_SOCKET_TIMEOUT_MS: int = Field(default=60000)   # 套接字超时：60秒（原为20秒）
    MONGO_SERVER_SELECTION_TIMEOUT_MS: int = Field(default=5000)  # 服务器选择超时：5秒

    @property
    def JWT_SECRET(self) -> str:
        """动态读取 JWT_SECRET，保证 SecretService 持久化后多 worker 一致。

        读源顺序：
        1. ``os.getenv("JWT_SECRET")``（由 SecretService.persist_to_env 写入）
        2. 运行期随机生成（仅启动早期 SecretService 未运行时使用）

        lifespan 中 ``_init_secrets`` 会通过 SecretService 把 DB 密钥同步到
        ``os.environ``，之后所有访问都会拿到稳定值。

        Warning:
            此 property 不会被 Pydantic 的 ``model_dump()`` / ``settings.dict()``
            序列化。请勿使用这些方法导出含密钥的配置；如需导出，应显式调用
            ``SecretService`` 并按脱敏规则处理。
        """
        value = os.getenv("JWT_SECRET")
        if value:
            return value
        return _runtime_secret("JWT_SECRET")

    @property
    def CSRF_SECRET(self) -> str:
        """动态读取 CSRF_SECRET（同 JWT_SECRET 策略）。

        Warning:
            同 ``JWT_SECRET``，不会被 ``model_dump()`` 序列化。
        """
        value = os.getenv("CSRF_SECRET")
        if value:
            return value
        return _runtime_secret("CSRF_SECRET")

    @property
    def MONGO_URI(self) -> str:
        """构建 MongoDB URI（密码中特殊字符会 URL 编码）。

        与 REDIS_URL 同样的策略：仅当提供账号密码时附加鉴权段；
        否则回退为无密码 URI。`authSource=admin` 与已部署环境保持一致。
        """
        if self.MONGODB_USERNAME and self.MONGODB_PASSWORD:
            user = quote_plus(self.MONGODB_USERNAME)
            pwd = quote_plus(self.MONGODB_PASSWORD)
            return (
                f"mongodb://{user}:{pwd}@{self.MONGODB_HOST}:{self.MONGODB_PORT}/"
                f"{self.MONGODB_DATABASE}?authSource={self.MONGODB_AUTH_SOURCE}"
            )
        return (
            f"mongodb://{self.MONGODB_HOST}:{self.MONGODB_PORT}/"
            f"{self.MONGODB_DATABASE}"
        )

    @property
    def MONGO_DB(self) -> str:
        """获取数据库名称"""
        return self.MONGODB_DATABASE

    # Redis配置
    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)
    REDIS_PASSWORD: str = Field(default="")
    REDIS_DB: int = Field(default=0)
    REDIS_MAX_CONNECTIONS: int = Field(default=20)
    REDIS_RETRY_ON_TIMEOUT: bool = Field(default=True)

    @property
    def REDIS_URL(self) -> str:
        """构建Redis URL（密码中的特殊字符会被URL编码）"""
        if self.REDIS_PASSWORD:
            pwd = quote_plus(self.REDIS_PASSWORD)
            return f"redis://:{pwd}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        else:
            return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # JWT配置（动态 property，下方覆盖）
    JWT_ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=30)

    # 队列配置
    QUEUE_MAX_SIZE: int = Field(default=10000)
    QUEUE_VISIBILITY_TIMEOUT: int = Field(default=300)  # 5分钟
    QUEUE_MAX_RETRIES: int = Field(default=3)
    WORKER_HEARTBEAT_INTERVAL: int = Field(default=30)  # 30秒


    # 队列轮询/清理间隔（秒）
    QUEUE_POLL_INTERVAL_SECONDS: float = Field(default=1.0)
    QUEUE_CLEANUP_INTERVAL_SECONDS: float = Field(default=60.0)

    # 并发控制
    DEFAULT_USER_CONCURRENT_LIMIT: int = Field(default=3)
    GLOBAL_CONCURRENT_LIMIT: int = Field(default=50)
    DEFAULT_DAILY_QUOTA: int = Field(default=1000)

    # 速率限制
    RATE_LIMIT_ENABLED: bool = Field(default=True)
    DEFAULT_RATE_LIMIT: int = Field(default=100)  # 每分钟请求数

    # 日志配置
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FORMAT: str = Field(default="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    LOG_FILE: str = Field(
        default="logs/tradingagents.log",
        description="日志文件名，实际落盘路径由 settings.log_file_path 解析到 runtime/ 下",
    )

    # 代理配置
    # 用于配置需要绕过代理的域名（国内数据源）
    # 多个域名用逗号分隔
    # ⚠️ Windows 不支持通配符 *，必须使用完整域名
    # 详细说明: docs/proxy_configuration.md
    HTTP_PROXY: str = Field(default="")
    HTTPS_PROXY: str = Field(default="")
    NO_PROXY: str = Field(
        default="localhost,127.0.0.1,eastmoney.com,push2.eastmoney.com,82.push2.eastmoney.com,82.push2delay.eastmoney.com,gtimg.cn,sinaimg.cn,api.tushare.pro,baostock.com"
    )

    # 文件上传配置
    MAX_UPLOAD_SIZE: int = Field(default=10 * 1024 * 1024)  # 10MB
    UPLOAD_DIR: str = Field(default="uploads")

    # 缓存配置
    CACHE_TTL: int = Field(default=3600)  # 1小时
    SCREENING_CACHE_TTL: int = Field(default=1800)  # 30分钟

    # 安全配置
    BCRYPT_ROUNDS: int = Field(default=12)
    SESSION_EXPIRE_HOURS: int = Field(default=24)
    # CSRF_SECRET 改为动态 property（下方定义），保证多 worker env 一致

    # 受信代理 IP 列表（逗号分隔，用于反向代理后获取真实客户端 IP）
    TRUSTED_PROXIES: str = Field(default="127.0.0.1,::1")

    # SSE 配置
    SSE_POLL_TIMEOUT_SECONDS: float = Field(default=1.0)
    SSE_HEARTBEAT_INTERVAL_SECONDS: int = Field(default=10)
    SSE_TASK_MAX_IDLE_SECONDS: int = Field(default=300)
    SSE_BATCH_POLL_INTERVAL_SECONDS: float = Field(default=2.0)
    SSE_BATCH_MAX_IDLE_SECONDS: int = Field(default=600)


    # 监控配置
    METRICS_ENABLED: bool = Field(default=True)
    HEALTH_CHECK_INTERVAL: int = Field(default=60)  # 60秒


    # 配置真相来源（方案A）：file|db|hybrid
    # - file：以文件/env 为准（推荐，生产缺省）
    # - db：以数据库为准（仅兼容旧版，不推荐）
    # - hybrid：文件/env 优先，DB 作为兜底
    CONFIG_SOT: str = Field(default="file")


    # 基础信息同步任务配置（可配置调度）
    SYNC_STOCK_BASICS_ENABLED: bool = Field(default=True)
    # 优先使用 CRON 表达式，例如 "30 6 * * *" 表示每日 06:30
    SYNC_STOCK_BASICS_CRON: str = Field(default="")
    # 若未提供 CRON，则使用简单时间字符串 "HH:MM"（24小时制）
    SYNC_STOCK_BASICS_TIME: str = Field(default="06:30")
    # 时区（默认值，实际运行时会从运行时配置获取）
    TIMEZONE: str = Field(default="Asia/Shanghai")

    # 实时行情入库任务
    QUOTES_INGEST_ENABLED: bool = Field(default=True)
    QUOTES_INGEST_INTERVAL_SECONDS: int = Field(
        default=360,
        description="实时行情采集间隔（秒）。默认360秒（6分钟），免费用户建议>=300秒，付费用户可设置5-60秒"
    )
    # 休市期/启动兜底补数（填充上一笔快照）
    QUOTES_BACKFILL_ON_STARTUP: bool = Field(default=True)
    QUOTES_BACKFILL_ON_OFFHOURS: bool = Field(default=True)

    # 实时行情接口轮换配置
    QUOTES_ROTATION_ENABLED: bool = Field(
        default=True,
        description="启用接口轮换机制（Tushare → AKShare东方财富 → AKShare新浪财经）"
    )
    QUOTES_TUSHARE_HOURLY_LIMIT: int = Field(
        default=2,
        description="Tushare rt_k接口每小时调用次数限制（免费用户2次，付费用户可设置更高）"
    )
    QUOTES_AUTO_DETECT_TUSHARE_PERMISSION: bool = Field(
        default=True,
        description="自动检测Tushare rt_k接口权限，付费用户自动切换到高频模式（5秒）"
    )

    # Tushare基础配置
    # 旧字段保留作为兜底：若三市场专属 Token 未配置，回退到 TUSHARE_TOKEN
    TUSHARE_TOKEN: str = Field(default="", description="Tushare API Token 兜底字段（市场专属 Token 未配置时使用）")
    # 三市场独立 Token — 实现真正的凭据隔离与积分池隔离
    TUSHARE_CN_TOKEN: str = Field(default="", description="A 股 Tushare Token（优先于 TUSHARE_TOKEN）")
    TUSHARE_HK_TOKEN: str = Field(default="", description="港股 Tushare Token（优先于 TUSHARE_TOKEN；积分门槛 ≥ 2000）")
    TUSHARE_US_TOKEN: str = Field(default="", description="美股 Tushare Token（优先于 TUSHARE_TOKEN；积分门槛 ≥ 120）")
    TUSHARE_ENABLED: bool = Field(default=True, description="启用Tushare数据源")
    TUSHARE_TIER: str = Field(default="standard", description="Tushare积分等级 (free/basic/standard/premium/vip)")
    TUSHARE_RATE_LIMIT_SAFETY_MARGIN: float = Field(default=0.8, ge=0.1, le=1.0, description="速率限制安全边际")

    # Tushare统一数据同步配置
    TUSHARE_UNIFIED_ENABLED: bool = Field(default=True)
    TUSHARE_BASIC_INFO_SYNC_ENABLED: bool = Field(default=True)
    TUSHARE_BASIC_INFO_SYNC_CRON: str = Field(default="0 2 * * *")  # 每日凌晨2点
    TUSHARE_QUOTES_SYNC_ENABLED: bool = Field(default=True)
    TUSHARE_QUOTES_SYNC_CRON: str = Field(default="*/5 9-15 * * 1-5")  # 交易时间每5分钟
    TUSHARE_HISTORICAL_SYNC_ENABLED: bool = Field(default=True)
    TUSHARE_HISTORICAL_SYNC_CRON: str = Field(default="0 16 * * 1-5")  # 工作日16点
    TUSHARE_FINANCIAL_SYNC_ENABLED: bool = Field(default=True)
    TUSHARE_FINANCIAL_SYNC_CRON: str = Field(default="0 3 * * 0")  # 周日凌晨3点
    TUSHARE_STATUS_CHECK_ENABLED: bool = Field(default=True)
    TUSHARE_STATUS_CHECK_CRON: str = Field(default="0 * * * *")  # 每小时

    # Tushare数据初始化配置
    TUSHARE_INIT_HISTORICAL_DAYS: int = Field(default=365, ge=1, le=3650, description="初始化历史数据天数")
    TUSHARE_INIT_BATCH_SIZE: int = Field(default=100, ge=10, le=1000, description="初始化批处理大小")
    TUSHARE_INIT_AUTO_START: bool = Field(default=False, description="应用启动时自动检查并初始化数据")

    # AKShare统一数据同步配置
    AKSHARE_UNIFIED_ENABLED: bool = Field(default=True, description="启用AKShare统一数据同步")
    AKSHARE_BASIC_INFO_SYNC_ENABLED: bool = Field(default=True, description="启用基础信息同步")
    AKSHARE_BASIC_INFO_SYNC_CRON: str = Field(default="0 3 * * *", description="基础信息同步CRON表达式")  # 每日凌晨3点
    AKSHARE_QUOTES_SYNC_ENABLED: bool = Field(default=True, description="启用行情同步")
    AKSHARE_QUOTES_SYNC_CRON: str = Field(default="*/30 9-15 * * 1-5", description="行情同步CRON表达式")  # 交易时间每30分钟（避免频率限制）
    AKSHARE_HISTORICAL_SYNC_ENABLED: bool = Field(default=True, description="启用历史数据同步")
    AKSHARE_HISTORICAL_SYNC_CRON: str = Field(default="0 17 * * 1-5", description="历史数据同步CRON表达式")  # 工作日17点
    AKSHARE_FINANCIAL_SYNC_ENABLED: bool = Field(default=True, description="启用财务数据同步")
    AKSHARE_FINANCIAL_SYNC_CRON: str = Field(default="0 4 * * 0", description="财务数据同步CRON表达式")  # 周日凌晨4点
    AKSHARE_STATUS_CHECK_ENABLED: bool = Field(default=True, description="启用状态检查")
    AKSHARE_STATUS_CHECK_CRON: str = Field(default="30 * * * *", description="状态检查CRON表达式")  # 每小时30分

    # AKShare数据初始化配置
    AKSHARE_INIT_HISTORICAL_DAYS: int = Field(default=365, ge=1, le=3650, description="初始化历史数据天数")
    AKSHARE_INIT_BATCH_SIZE: int = Field(default=100, ge=10, le=1000, description="初始化批处理大小")
    AKSHARE_INIT_AUTO_START: bool = Field(default=False, description="应用启动时自动检查并初始化数据")

    # ==================== 分析师数据获取配置 ====================

    # 市场分析师数据范围配置
    # 默认60天：可覆盖MA60等所有常用技术指标（MA5/10/20/60, MACD, RSI, BOLL）
    MARKET_ANALYST_LOOKBACK_DAYS: int = Field(default=60, ge=5, le=365, description="市场分析回溯天数（用于技术分析）")

    # ==================== BaoStock统一数据同步配置 ====================

    # BaoStock统一数据同步总开关
    BAOSTOCK_UNIFIED_ENABLED: bool = Field(default=True, description="启用BaoStock统一数据同步")

    # BaoStock数据同步任务配置
    BAOSTOCK_BASIC_INFO_SYNC_ENABLED: bool = Field(default=True, description="启用基础信息同步")
    BAOSTOCK_BASIC_INFO_SYNC_CRON: str = Field(default="0 4 * * *", description="基础信息同步CRON表达式")  # 每日凌晨4点
    BAOSTOCK_DAILY_QUOTES_SYNC_ENABLED: bool = Field(default=True, description="启用日K线同步（注意：BaoStock不支持实时行情）")
    BAOSTOCK_DAILY_QUOTES_SYNC_CRON: str = Field(default="0 16 * * 1-5", description="日K线同步CRON表达式")  # 工作日收盘后16:00
    BAOSTOCK_HISTORICAL_SYNC_ENABLED: bool = Field(default=True, description="启用历史数据同步")
    BAOSTOCK_HISTORICAL_SYNC_CRON: str = Field(default="0 18 * * 1-5", description="历史数据同步CRON表达式")  # 工作日18点
    BAOSTOCK_STATUS_CHECK_ENABLED: bool = Field(default=True, description="启用状态检查")
    BAOSTOCK_STATUS_CHECK_CRON: str = Field(default="45 * * * *", description="状态检查CRON表达式")  # 每小时45分

    # BaoStock数据初始化配置
    BAOSTOCK_INIT_HISTORICAL_DAYS: int = Field(default=365, ge=1, le=3650, description="初始化历史数据天数")
    BAOSTOCK_INIT_BATCH_SIZE: int = Field(default=50, ge=10, le=500, description="初始化批处理大小")
    BAOSTOCK_INIT_AUTO_START: bool = Field(default=False, description="应用启动时自动检查并初始化数据")

    # ==================== 数据同步并发控制 ====================
    # BaseSyncJob 串行 for 循环改为 asyncio.Semaphore + gather 时的并发上限
    # 默认 8（保守值，避免压垮数据源）；按市场可单独配置
    DATA_SYNC_CONCURRENCY: int = Field(default=8, ge=1, le=32, description="数据同步默认并发上限")
    CN_SYNC_CONCURRENCY: int = Field(default=8, ge=1, le=32, description="CN 数据同步并发上限")
    HK_SYNC_CONCURRENCY: int = Field(default=8, ge=1, le=32, description="HK 数据同步并发上限")
    US_SYNC_CONCURRENCY: int = Field(default=8, ge=1, le=32, description="US 数据同步并发上限")

    # ==================== 港股全量同步配置 ====================
    # 默认关闭，用户通过 .env 手动启用
    HK_UNIFIED_ENABLED: bool = Field(default=False, description="启用港股统一数据同步")
    HK_BASIC_INFO_SYNC_ENABLED: bool = Field(default=False, description="启用港股基础信息同步")
    HK_BASIC_INFO_SYNC_CRON: str = Field(default="0 3 * * *", description="港股基础信息同步CRON")
    HK_DAILY_QUOTES_SYNC_ENABLED: bool = Field(default=False, description="启用港股日线行情同步")
    HK_DAILY_QUOTES_SYNC_CRON: str = Field(default="0 17 * * 1-5", description="港股日线行情同步CRON")
    HK_STATUS_CHECK_ENABLED: bool = Field(default=False, description="启用港股状态检查")
    HK_STATUS_CHECK_CRON: str = Field(default="0 * * * *", description="港股状态检查CRON")
    HK_SYNC_BATCH_SIZE: int = Field(default=50, ge=10, le=200, description="港股同步批处理大小")
    HK_SYNC_RATE_LIMIT_DELAY: float = Field(default=0.5, ge=0.1, le=10.0, description="港股同步API间隔(秒)")

    # ==================== 美股全量同步配置 ====================
    # 默认关闭，用户通过 .env 手动启用
    US_UNIFIED_ENABLED: bool = Field(default=False, description="启用美股统一数据同步")
    US_BASIC_INFO_SYNC_ENABLED: bool = Field(default=False, description="启用美股基础信息同步")
    US_BASIC_INFO_SYNC_CRON: str = Field(default="0 4 * * *", description="美股基础信息同步CRON")
    US_DAILY_QUOTES_SYNC_ENABLED: bool = Field(default=False, description="启用美股日线行情同步")
    US_DAILY_QUOTES_SYNC_CRON: str = Field(default="0 5 * * 2-6", description="美股日线行情同步CRON")
    US_STATUS_CHECK_ENABLED: bool = Field(default=False, description="启用美股状态检查")
    US_STATUS_CHECK_CRON: str = Field(default="30 * * * *", description="美股状态检查CRON")
    US_SYNC_BATCH_SIZE: int = Field(default=50, ge=10, le=200, description="美股同步批处理大小")
    US_SYNC_RATE_LIMIT_DELAY: float = Field(default=1.0, ge=0.1, le=10.0, description="美股同步API间隔(秒)")

    # ==================== 异步执行池配置 ====================
    # 默认执行器（loop.set_default_executor）线程上限，影响 asyncio.to_thread / run_in_executor 默认池
    ASYNC_THREAD_POOL_SIZE: int = Field(default=16, ge=1, le=64, description="默认异步线程池上限")
    # AnalysisService 单实例专用线程池上限（运行 LangGraph 同步执行）
    ANALYSIS_THREAD_POOL_SIZE: int = Field(default=3, ge=1, le=16, description="分析任务线程池上限")
    # 队列任务最大重试次数：超过则移入死信队列
    QUEUE_MAX_RETRIES: int = Field(default=3, ge=1, le=10, description="队列任务最大重试次数")

    # ==================== WebSocket 连接限制 ====================
    WEBSOCKET_MAX_CONNECTIONS_PER_TASK: int = Field(default=5, ge=1, le=50, description="单任务 WebSocket 最大连接数")
    WEBSOCKET_MAX_TOTAL_CONNECTIONS: int = Field(default=1000, ge=1, le=10000, description="全局 WebSocket 最大连接数")

    # 数据目录配置
    TRADINGAGENTS_DATA_DIR: str = Field(default="data")

    @property
    def runtime_dir(self) -> str:
        """运行时根目录（绝对路径，确保存在）"""
        # 🔧 延迟导入以避免循环导入
        from app.utils.runtime_paths import get_runtime_base_dir
        return str(get_runtime_base_dir(self.RUNTIME_BASE_DIR))

    def resolve_runtime_path(self, path_value: str) -> str:
        """将相对路径解析到运行时根目录下（并确保父目录存在）"""
        # 🔧 延迟导入以避免循环导入
        from app.utils.runtime_paths import resolve_path
        return str(resolve_path(path_value, self.RUNTIME_BASE_DIR))

    @property
    def log_file_path(self) -> str:
        """日志文件绝对路径"""
        return self.resolve_runtime_path(self.LOG_FILE)

    @property
    def log_dir(self) -> str:
        """获取日志目录（绝对路径）"""
        return str(Path(self.log_file_path).parent)

    @property
    def upload_dir(self) -> str:
        """上传目录（绝对路径）"""
        return self.resolve_runtime_path(self.UPLOAD_DIR)

    @property
    def data_dir(self) -> str:
        """数据目录（绝对路径）"""
        return self.resolve_runtime_path(self.TRADINGAGENTS_DATA_DIR)

    # ==================== 港股数据配置 ====================

    # 港股数据源配置（按需获取+缓存模式）
    HK_DATA_CACHE_HOURS: int = Field(default=24, ge=1, le=168, description="港股数据缓存时长（小时）")
    HK_DEFAULT_DATA_SOURCE: str = Field(default="yfinance", description="港股默认数据源（yfinance/akshare）")

    # ==================== 美股数据配置 ====================

    # 美股数据源配置（按需获取+缓存模式）
    US_DATA_CACHE_HOURS: int = Field(default=24, ge=1, le=168, description="美股数据缓存时长（小时）")
    US_DEFAULT_DATA_SOURCE: str = Field(default="yfinance", description="美股默认数据源（yfinance/finnhub）")

    # ===== 新闻数据同步服务配置 =====
    NEWS_SYNC_ENABLED: bool = Field(default=True)
    NEWS_SYNC_CRON: str = Field(default="0 */2 * * *")  # 每2小时
    NEWS_SYNC_HOURS_BACK: int = Field(default=24)
    NEWS_SYNC_MAX_PER_SOURCE: int = Field(default=50)

    # ==================== Skill 系统配置 ====================

    # 是否启用 skill 依赖首次加载自动安装（缓解供应链风险的关键开关）
    SKILL_AUTO_INSTALL: bool = Field(
        default=True,
        description="首次加载 skill 时自动 pip install 声明的依赖（仅在容器内执行）",
    )
    # 包名白名单（逗号分隔，空表示不限制）
    SKILL_ALLOWED_PACKAGES: str = Field(
        default="",
        description="允许自动安装的 PyPI 包名白名单（逗号分隔），空表示不限制",
    )
    # 单次 pip install 超时（秒）
    SKILL_INSTALL_TIMEOUT: int = Field(
        default=300,
        ge=30,
        le=1800,
        description="单次 skill 依赖 pip install 的超时时间（秒）",
    )
    # 未来中心化注册表地址（本期未使用）
    SKILL_REGISTRY_URL: str = Field(
        default="",
        description="中心化 skill 注册表地址（预留，本期未实现）",
    )
    # Git URL 安装的可信主机白名单（逗号分隔）
    SKILL_GIT_TRUSTED_HOSTS: str = Field(
        default="github.com,gitee.com",
        description="允许从 Git URL 安装 skill 的可信主机白名单（逗号分隔）",
    )

    @property
    def is_production(self) -> bool:
        """是否为生产环境"""
        return not self.DEBUG

    # Ignore any extra environment variables present in .env or process env
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

# Docker 容器环境下放宽安全检查（Nginx 反代已保证同源，无需严格 CORS/Host 校验）
_IS_DOCKER = os.getenv("DOCKER_CONTAINER", "").lower() in ("true", "1", "yes")

# 安全密钥检查：密钥将自动生成并持久化到 DB（由 SecretService 管理）
# 此处仅检查并提示，不再阻止启动
_REQUIRED_SECRETS = ("JWT_SECRET", "CSRF_SECRET")

for _key in _REQUIRED_SECRETS:
    if not os.getenv(_key):
        warnings.warn(
            f"安全提示: 未配置 {_key}，将在首次连接数据库后自动生成并持久化。",
            stacklevel=2,
        )

# 生产环境安全检查：CORS 和 TrustedHost 不能使用通配符
# 非 Docker 环境严格阻止，Docker 环境（Nginx 反代已保证同源安全）降级为警告
if settings.is_production:
    if "*" in settings.ALLOWED_ORIGINS:
        if not _IS_DOCKER:
            raise RuntimeError(
                "❌ 安全错误: 生产环境 ALLOWED_ORIGINS 不能包含 '*'，"
                "请在 .env 中显式配置允许的域名！"
            )
        else:
            warnings.warn(
                "⚠️ 安全提示: Docker 环境 ALLOWED_ORIGINS 包含 '*'，"
                "Nginx 反代已保证同源安全，但建议在 .env 中配置具体域名。",
                stacklevel=2,
            )
    if "*" in settings.ALLOWED_HOSTS:
        if not _IS_DOCKER:
            raise RuntimeError(
                "❌ 安全错误: 生产环境 ALLOWED_HOSTS 不能包含 '*'，"
                "请在 .env 中显式配置允许的主机名！"
            )
        else:
            warnings.warn(
                "⚠️ 安全提示: Docker 环境 ALLOWED_HOSTS 包含 '*'，"
                "Nginx 反代已保证同源安全，但建议在 .env 中配置具体主机名。",
                stacklevel=2,
            )

# 自动将代理配置设置到环境变量
# 这样 requests 库可以直接读取 os.environ['NO_PROXY']
if settings.HTTP_PROXY:
    os.environ['HTTP_PROXY'] = settings.HTTP_PROXY
if settings.HTTPS_PROXY:
    os.environ['HTTPS_PROXY'] = settings.HTTPS_PROXY
if settings.NO_PROXY:
    os.environ['NO_PROXY'] = settings.NO_PROXY


def get_settings() -> Settings:
    """获取配置实例"""
    return settings


# ── 安全密钥检查（共享函数，避免 main.py / startup_validator.py 各自维护） ──

# 已知的不安全默认占位符前缀（必须替换为强随机值）
DEFAULT_SECRET_PATTERNS: dict[str, str] = {
    "JWT_SECRET": "docker-jwt-secret-key-change-in-production",
    "CSRF_SECRET": "docker-csrf-secret-key-change-in-production",
}

# 其他已知不安全前缀（小写比较）
_INSECURE_DEFAULT_PREFIXES: tuple[str, ...] = (
    "docker-jwt-secret-key-change-in-production",
    "docker-csrf-secret-key-change-in-production",
    "change-me",
    "change_me",
    "insecure-default",
    "please-change",
)


def is_using_default_secret(key: str) -> bool:
    """检查指定的安全密钥是否使用了不安全默认占位符。

    Args:
        key: 环境变量名（如 ``"JWT_SECRET"``、``"CSRF_SECRET"``）

    Returns:
        True 表示使用了不安全默认值（生产环境禁止启动）
    """
    value = os.getenv(key, "")
    if not value:
        return False
    lowered = value.lower()
    return any(lowered.startswith(p.lower()) for p in _INSECURE_DEFAULT_PREFIXES)


# ── 配置摘要脱敏（共享函数，避免 main.py / __main__.py 各自维护） ──

# 已知安全的环境变量名（值不包含敏感信息，可在日志中显示）
SAFE_ENV_KEYS: frozenset[str] = frozenset({
    "DEBUG", "LOG_LEVEL", "HOST", "PORT",
    "TIMEZONE", "TZ",  # 系统时区，与 TIMEZONE 等价
    "LANG", "LC_ALL", "LC_CTYPE",  # 系统 locale，容器排障常见
    "PYTHONIOENCODING", "PYTHONUTF8",
    "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE",
    "MONGODB_DATABASE", "REDIS_DB",
    "MONGODB_PORT", "REDIS_PORT",
    "QUOTES_INGEST_INTERVAL_SECONDS",
})

# 敏感关键字（用于反向匹配，命中关键字的行一律脱敏）
SENSITIVE_KEYWORDS: tuple[str, ...] = (
    "PASSWORD", "SECRET", "KEY", "TOKEN",
    "CREDENTIAL", "PRIVATE", "CERT", "AUTH",
)


def redact_env_line(line: str) -> str:
    """对单行环境变量配置进行脱敏。

    策略（fail-closed）：
    - 注释行 / 空行 / 无 ``=`` 的行 → 原样返回（无法解析键）
    - bash ``export KEY=VALUE`` 前缀会被剥除
    - 键在 ``SAFE_ENV_KEYS`` 显式白名单 → 原样返回
    - 其他所有键 → 返回 ``KEY=***``（默认脱敏）

    旧实现：仅 SENSITIVE_KEYWORDS 命中才脱敏，fail-open 风险在于"未识别的敏感字段名"
    （例如未来新增 ``OPENAI_APIKEY`` 拼写变形、``AUTH_BEARER`` 等）会被原样打到日志。
    新策略 fail-closed：除显式白名单外一律脱敏，宁可多掩几个非敏感变量。
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return line
    # 兼容 bash export KEY=VALUE 语法
    if stripped.startswith("export "):
        stripped = stripped[len("export "):].lstrip()
    if "=" not in stripped:
        return line
    key = stripped.split("=", 1)[0].strip()
    if key in SAFE_ENV_KEYS:
        return line
    # fail-closed：不在白名单的键一律脱敏（含 SENSITIVE_KEYWORDS 命中项）
    return f"{key}=***"
