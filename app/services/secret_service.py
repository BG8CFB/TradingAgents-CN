"""
安全密钥服务

管理 JWT_SECRET、CSRF_SECRET 等安全密钥的自动生成和持久化。
密钥存储在 MongoDB system_secrets 集合中，首次启动自动生成，
后续启动从 DB 加载，确保服务重启后会话不失效。

持久化层级（多层兜底，保证多 worker 一致性）：
1. MongoDB system_secrets 集合（主存储）
2. runtime/.secrets.json 文件（DB 不可达时的兜底）
3. os.environ（运行期共享）
"""

import json
import os
import secrets
import tempfile
import logging
from pathlib import Path
from typing import Optional

from app.core.database import get_mongo_db

logger = logging.getLogger("app.secret_service")

# 集合名
_COLLECTION = "system_secrets"

# 文件兜底路径：runtime/.secrets.json（权限建议 600）
_RUNTIME_BASE_DIR = os.getenv("RUNTIME_BASE_DIR", "runtime")
_FALLBACK_FILE = Path(_RUNTIME_BASE_DIR) / ".secrets.json"

# 需要自动管理的密钥及其默认长度
_MANAGED_SECRETS = {
    "jwt_secret": 48,
    "csrf_secret": 48,
}

# name → 环境变量名映射
_ENV_MAP = {"jwt_secret": "JWT_SECRET", "csrf_secret": "CSRF_SECRET"}


def _load_fallback_file() -> dict[str, str]:
    """读取文件兜底中的密钥。"""
    try:
        if _FALLBACK_FILE.exists():
            data = json.loads(_FALLBACK_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if isinstance(v, str) and v}
    except Exception as exc:
        logger.warning(f"读取密钥兜底文件失败: {exc}")
    return {}


def _save_fallback_file(values: dict[str, str]) -> None:
    """把密钥原子写入文件兜底（tempfile + os.replace）。

    多 worker 并发首启时，write_text 覆盖式写入可能产生截断/部分内容；
    改为先写临时文件再原子重命名，确保读端不会读到半成品 JSON。
    """
    tmp_path = None
    try:
        _FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=_FALLBACK_FILE.parent,
            mode="w",
            encoding="utf-8",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(json.dumps(values, ensure_ascii=False, indent=2))
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, _FALLBACK_FILE)
        tmp_path = None
        # 尝试收紧文件权限（Unix 系生效，Windows 上 no-op）
        try:
            os.chmod(_FALLBACK_FILE, 0o600)
        except Exception:
            pass
        logger.debug(f"密钥兜底文件已写入: {_FALLBACK_FILE}")
    except Exception as exc:
        if tmp_path is not None and tmp_path.exists():
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        logger.warning(f"写入密钥兜底文件失败: {exc}（仍可使用 DB 与环境变量）")


class SecretService:
    """安全密钥管理服务"""

    @staticmethod
    async def ensure_secrets() -> dict[str, str]:
        """确保所有受管密钥都已生成并持久化。

        首次启动时自动生成，后续从 DB 加载。
        同时将密钥写入 os.environ 与 runtime/.secrets.json 文件兜底，
        供多 worker / DB 不可达等场景使用。
        """
        db = get_mongo_db()
        collection = db[_COLLECTION]
        result: dict[str, str] = {}
        newly_generated: dict[str, str] = {}

        for name, length in _MANAGED_SECRETS.items():
            value: Optional[str] = None
            try:
                doc = await collection.find_one({"name": name})
                if doc and doc.get("value"):
                    value = doc["value"]
                    logger.debug(f"从 DB 加载密钥: {name}")
            except Exception as exc:
                logger.warning(f"从 DB 读取密钥 {name} 失败: {exc}")

            if not value:
                # DB 不可用或首次启动，先尝试文件兜底
                fallback = _load_fallback_file()
                value = fallback.get(name)

            if not value:
                # 仍然没有，生成新密钥
                value = secrets.token_urlsafe(length)
                try:
                    # 关键：用 $setOnInsert + upsert 而非 $set，确保多 worker 并发首启时
                    # 仅第一个 worker 真正写入，其他 worker 的 update_one 会匹配到
                    # 已存在文档但不会修改它（upserted_id 为 None）。再用 find_one
                    # 读出权威值，避免各 worker 持有不同的本地生成密钥。
                    result_op = await collection.update_one(
                        {"name": name},
                        {"$setOnInsert": {"name": name, "value": value}},
                        upsert=True,
                    )
                    if result_op.upserted_id is None:
                        # 已被其他 worker 创建：读出权威值替换本地生成值
                        existing = await collection.find_one({"name": name})
                        if existing and existing.get("value"):
                            value = existing["value"]
                            logger.info(f"密钥 {name} 已由其他 worker 创建，使用 DB 权威值")
                        else:
                            # 极少见：upserted_id 为 None 但文档读不到（如 race + 删除）
                            # 这种情况下保留本地生成值，落兜底文件
                            logger.warning(
                                f"密钥 {name} upsert 未创建新文档且 DB 读取为空，使用本地生成值"
                            )
                    else:
                        logger.info(f"自动生成并持久化密钥: {name}")
                except Exception as exc:
                    # 并发竞争 + 唯一索引：两个 worker 几乎同时插入同一 name 会触发
                    # DuplicateKeyError。此时应直接读出权威值而非保留本地随机值，
                    # 否则各 worker 持有的密钥会漂移。
                    try:
                        existing = await collection.find_one({"name": name})
                    except Exception:
                        existing = None
                    if existing and existing.get("value"):
                        value = existing["value"]
                        logger.info(
                            f"密钥 {name} 并发插入冲突已解决，使用 DB 权威值: {type(exc).__name__}"
                        )
                    else:
                        logger.warning(
                            f"密钥 {name} 写入 DB 失败且无法读取: {exc}（将仅落兜底文件 + os.environ）"
                        )
                newly_generated[name] = value

            result[name] = value

        # 同步到 os.environ，供依赖环境变量的代码使用
        for name, env_key in _ENV_MAP.items():
            if name in result:
                os.environ[env_key] = result[name]

        # 文件兜底：仅在密钥有变化时覆盖式写入
        if newly_generated or not _load_fallback_file():
            _save_fallback_file(result)

        logger.info(f"安全密钥管理完成，共 {len(result)} 个密钥已就绪")
        return result

    @staticmethod
    def persist_to_env() -> None:
        """把所有受管密钥同步到 os.environ。

        供 lifespan 在 _init_secrets 之后显式调用，确保多 worker（fork 模型）
        继承到一致的密钥。

        设计意图：uvicorn 多 worker 使用 prefork 模型，fork 前的 os.environ
        会被所有 worker 继承。这里只补齐未设置的 env_key（不覆盖已存在的环境变量），
        这样部署侧通过 .env / docker-compose 注入的密钥优先级最高，自动生成的
        密钥仅在缺失时才落兜底。注意：venv 模式下 os.environ 不持久化跨进程，
        因此配合 _save_fallback_file 形成两层兜底。
        """
        fallback = _load_fallback_file()
        for name, env_key in _ENV_MAP.items():
            if env_key in os.environ and os.environ[env_key]:
                continue
            value = fallback.get(name)
            if value:
                os.environ[env_key] = value
                logger.debug(f"从兜底文件同步密钥到 os.environ: {env_key}")

    @staticmethod
    async def get_secret(name: str) -> Optional[str]:
        """从 DB 读取指定密钥"""
        db = get_mongo_db()
        doc = await db[_COLLECTION].find_one({"name": name})
        return doc.get("value") if doc else None

    @staticmethod
    async def rotate_secret(name: str) -> str:
        """重新生成并更新密钥"""
        if name not in _MANAGED_SECRETS:
            raise ValueError(f"未知密钥: {name}")

        length = _MANAGED_SECRETS[name]
        new_value = secrets.token_urlsafe(length)

        db = get_mongo_db()
        await db[_COLLECTION].update_one(
            {"name": name},
            {"$set": {"value": new_value}},
            upsert=True,
        )

        # 同步到 os.environ 与文件兜底
        env_key = _ENV_MAP.get(name)
        if env_key:
            os.environ[env_key] = new_value

        # 同步文件兜底（保留其他密钥）
        current = _load_fallback_file()
        current[name] = new_value
        _save_fallback_file(current)

        logger.warning(f"密钥已轮换: {name}")
        return new_value
