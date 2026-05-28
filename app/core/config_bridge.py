"""
配置桥接模块

将数据库中的模型配置桥接到环境变量，供引擎层使用。

简化说明（Phase 5 精简后）：
- API Key 和数据源 Token 已完全由数据库管理，不再桥接到 os.environ
- 引擎层通过显式参数传入 API Key（来源于 analysis_service 的 DB 查询）
- 仅保留模型名称和 MongoDB 存储的桥接

安全说明：
- API Key 通过数据库 llm_providers 集合管理，通过 Web UI 配置
- 日志中不记录 API Key 值，仅记录是否存在
"""

import json
import os
import tempfile
import logging
from pathlib import Path
from typing import Optional

from app.core.database import get_mongo_db

logger = logging.getLogger("app.config_bridge")


async def bridge_config_to_env() -> bool:
    """
    将数据库配置桥接到环境变量，供引擎层通过 os.getenv() 读取。

    核心步骤：
    1. 桥接 MongoDB 存储环境变量
    2. 桥接分析师/辩论推理模型 → TRADINGAGENTS_*_MODEL
    """
    try:
        logger.info("开始桥接配置到环境变量...")
        bridged_count = 0

        # ── Step 1：MongoDB 存储环境变量 ──────────────────────────────
        use_mongodb_storage = os.getenv("USE_MONGODB_STORAGE", "true")
        os.environ["USE_MONGODB_STORAGE"] = use_mongodb_storage
        logger.info(f"  USE_MONGODB_STORAGE={use_mongodb_storage}")
        bridged_count += 1

        mongodb_conn_str = os.getenv("MONGODB_CONNECTION_STRING")
        if mongodb_conn_str:
            os.environ["MONGODB_CONNECTION_STRING"] = mongodb_conn_str
            logger.info("  MONGODB_CONNECTION_STRING: 已配置")
            bridged_count += 1

        mongodb_db_name = os.getenv("MONGODB_DATABASE_NAME", "tradingagents")
        os.environ["MONGODB_DATABASE_NAME"] = mongodb_db_name
        logger.info(f"  MONGODB_DATABASE_NAME={mongodb_db_name}")
        bridged_count += 1

        # ── Step 2：桥接模型配置 ─────────────────────────────────────
        try:
            from app.services.config_service import config_service

            system_config = await config_service.get_system_config()
            if system_config:
                # 默认模型
                if system_config.default_llm:
                    os.environ["TRADINGAGENTS_DEFAULT_MODEL"] = system_config.default_llm
                    logger.info(f"  TRADINGAGENTS_DEFAULT_MODEL={system_config.default_llm}")
                    bridged_count += 1

                # 分析师/辩论模型（从 system_settings 读取）
                ss = system_config.system_settings or {}
                for model_key, env_name in [
                    ("analyst_model", "TRADINGAGENTS_ANALYST_MODEL"),
                    ("debate_model", "TRADINGAGENTS_DEBATE_MODEL"),
                ]:
                    val = ss.get(model_key)
                    if val:
                        os.environ[env_name] = val
                        logger.info(f"  {env_name}={val}")
                        bridged_count += 1
            else:
                logger.warning("  未找到激活的系统配置，模型将使用代码默认值")
        except Exception as e:
            logger.error(f"桥接系统配置失败: {e}", exc_info=True)

        logger.info(f"配置桥接完成，共桥接 {bridged_count} 项配置")
        return True
    except Exception as e:
        logger.error(f"配置桥接失败: {e}", exc_info=True)
        return False


# ── 公共查询接口 ──────────────────────────────────────────────────────

def get_bridged_model(model_type: str = "default") -> Optional[str]:
    """获取桥接的模型名称（default / analyst / debate）"""
    key = {"analyst": "TRADINGAGENTS_ANALYST_MODEL", "debate": "TRADINGAGENTS_DEBATE_MODEL"}.get(
        model_type, "TRADINGAGENTS_DEFAULT_MODEL"
    )
    return os.environ.get(key)


def clear_bridged_config():
    """清除桥接的环境变量（用于测试或重新加载）"""
    keys_to_clear = [
        "TRADINGAGENTS_DEFAULT_MODEL", "TRADINGAGENTS_ANALYST_MODEL",
        "TRADINGAGENTS_DEBATE_MODEL",
    ]
    for key in keys_to_clear:
        os.environ.pop(key, None)
    logger.info("已清除所有桥接的配置")


async def reload_bridged_config():
    """重新加载桥接配置（配置更新后调用）"""
    logger.info("重新加载配置桥接...")
    clear_bridged_config()
    return await bridge_config_to_env()


# ── 定价配置同步（供 llm.py 路由调用）──────────────────────────────────

async def sync_pricing_config_now() -> bool:
    """将定价配置写入 config/pricing.json。返回 True 表示成功。"""
    try:
        from app.services.config_service import config_service
        system_config = await config_service.get_system_config()
        if not system_config:
            logger.warning("sync_pricing_config_now: 未找到系统配置")
            return False

        pricing_configs = []
        for cfg in system_config.llm_configs:
            if cfg.enabled:
                pricing_configs.append({
                    "provider": cfg.provider.value if hasattr(cfg.provider, "value") else str(cfg.provider),
                    "model_name": cfg.model_name,
                    "input_price_per_1k": cfg.input_price_per_1k or 0.0,
                    "output_price_per_1k": cfg.output_price_per_1k or 0.0,
                    "currency": cfg.currency or "CNY",
                })

        config_dir = Path(__file__).parent.parent.parent / "config"
        config_dir.mkdir(exist_ok=True)
        pricing_file = config_dir / "pricing.json"

        # 原子写入：先写临时文件再重命名，避免中途崩溃导致文件损坏
        fd, tmp_path = tempfile.mkstemp(
            dir=str(config_dir), prefix=".pricing_", suffix=".json.tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(pricing_configs, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, str(pricing_file))
        except BaseException:
            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        logger.info(f"定价配置已写入 {pricing_file}: {len(pricing_configs)} 个模型")
        return True
    except Exception as e:
        logger.error(f"sync_pricing_config_now 失败: {e}", exc_info=True)
        return False


__all__ = [
    "bridge_config_to_env",
    "get_bridged_model",
    "clear_bridged_config",
    "reload_bridged_config",
    "sync_pricing_config_now",
]
