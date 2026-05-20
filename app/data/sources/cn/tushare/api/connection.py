"""
Tushare 连接管理：Token 获取、连接建立、单例维护
"""
import asyncio
import logging
from typing import Optional

from app.core.config import settings

try:
    import tushare as ts
    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False
    ts = None

logger = logging.getLogger(__name__)


class TushareConnection:
    """Tushare API 连接管理器"""

    def __init__(self):
        self.api = None
        self.connected = False
        self.token_source: Optional[str] = None
        self._token: Optional[str] = None

    @staticmethod
    def _get_token_from_database() -> Optional[str]:
        """从数据库读取 Tushare Token（优先于环境变量）"""
        try:
            from app.core.database import get_mongo_db_sync
            db = get_mongo_db_sync()
            config_data = db.system_configs.find_one(
                {"is_active": True},
                sort=[("version", -1)],
            )
            if config_data and config_data.get("data_source_configs"):
                for ds_config in config_data["data_source_configs"]:
                    if ds_config.get("type") == "tushare":
                        api_key = ds_config.get("api_key")
                        if api_key and not api_key.startswith("your_"):
                            return api_key
        except Exception as e:
            logger.debug(f"从数据库读取 Token 失败: {e}")
        return None

    def connect_sync(self) -> bool:
        """同步连接到 Tushare"""
        if not TUSHARE_AVAILABLE:
            logger.error("Tushare 库不可用")
            return False

        db_token = self._get_token_from_database()
        env_token = settings.TUSHARE_TOKEN

        for token, source in [(db_token, "database"), (env_token, "env")]:
            if not token:
                continue
            try:
                ts.set_token(token)
                api = ts.pro_api()
                test = api.stock_basic(list_status="L", limit=1)
                if test is not None and not test.empty:
                    self.api = api
                    self.connected = True
                    self.token_source = source
                    self._token = token
                    logger.info(f"Tushare 连接成功 (Token 来源: {source})")
                    return True
            except Exception as e:
                logger.debug(f"{source} Token 连接失败: {e}")

        logger.warning("Tushare Token 未配置或全部失效")
        return False

    async def connect(self) -> bool:
        """异步连接"""
        return await asyncio.to_thread(self.connect_sync)

    def is_available(self) -> bool:
        return TUSHARE_AVAILABLE and self.connected and self.api is not None

    def query(self, api_name: str, **kwargs):
        """通用 Tushare API 查询"""
        if not self.is_available():
            return None
        try:
            method = getattr(self.api, api_name, None)
            if method:
                return method(**kwargs)
            return self.api.query(api_name, **kwargs)
        except Exception as e:
            logger.error(f"Tushare query({api_name}) 失败: {e}")
            return None


# 单例
_instance: Optional[TushareConnection] = None


def get_tushare_api() -> TushareConnection:
    """获取 Tushare 连接单例"""
    global _instance
    if _instance is None:
        _instance = TushareConnection()
        _instance.connect_sync()
    return _instance
