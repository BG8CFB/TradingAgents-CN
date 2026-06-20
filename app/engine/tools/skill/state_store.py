"""
Skill 状态持久化层

封装对 MongoDB skill_state 与 skill_install_logs 集合的访问。
独立于 SkillRegistry，便于测试与未来替换存储后端。

设计原则：
- 不使用 upsert 写入空状态——只有用户显式启停或安装后才写记录
- 启动时读取全部状态，构造内存字典；运行中只读字典，不频繁访问 MongoDB
- 状态变更后异步持久化（fire-and-forget），失败时仅记录日志
"""
import logging
from typing import Dict, List, Optional

from app.core.database import get_mongo_db
from app.models.skill import SkillInstallLog, SkillState
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)


_SKILL_STATE_COLLECTION = "skill_state"
_SKILL_INSTALL_LOG_COLLECTION = "skill_install_logs"


class SkillStateStore:
    """Skill 状态持久化（异步访问 MongoDB）"""

    async def load_all_states(self) -> Dict[str, SkillState]:
        """
        加载全部 skill 状态记录。

        Returns:
            {skill_name: SkillState} 字典；MongoDB 不可用时返回空字典。
        """
        try:
            db = get_mongo_db()
            cursor = db[_SKILL_STATE_COLLECTION].find({})
            result: Dict[str, SkillState] = {}
            async for doc in cursor:
                try:
                    state = SkillState.model_validate(doc)
                    result[state.name] = state
                except Exception as e:
                    logger.warning(f"解析 skill_state 文档失败: {e}, doc={doc}")
            return result
        except Exception as e:
            logger.warning(f"加载 skill_state 失败（将使用内存默认值）: {e}")
            return {}

    async def get_state(self, name: str) -> Optional[SkillState]:
        """获取单个 skill 状态"""
        try:
            db = get_mongo_db()
            doc = await db[_SKILL_STATE_COLLECTION].find_one({"name": name})
            if doc is None:
                return None
            return SkillState.model_validate(doc)
        except Exception as e:
            logger.warning(f"获取 skill_state 失败 {name}: {e}")
            return None

    async def upsert_state(self, state: SkillState) -> bool:
        """写入或更新 skill 状态"""
        try:
            db = get_mongo_db()
            state.updated_at = now_tz()
            doc = state.model_dump(by_alias=True, exclude_none=False)
            await db[_SKILL_STATE_COLLECTION].update_one(
                {"name": state.name},
                {"$set": doc},
                upsert=True,
            )
            return True
        except Exception as e:
            logger.error(f"写入 skill_state 失败 {state.name}: {e}")
            return False

    async def set_enabled(self, name: str, enabled: bool) -> bool:
        """仅更新启停状态（轻量写入）"""
        try:
            db = get_mongo_db()
            await db[_SKILL_STATE_COLLECTION].update_one(
                {"name": name},
                {
                    "$set": {
                        "enabled": enabled,
                        "updated_at": now_tz(),
                    },
                    "$setOnInsert": {
                        "name": name,
                        "installed_dependencies": [],
                        "created_at": now_tz(),
                    },
                },
                upsert=True,
            )
            return True
        except Exception as e:
            logger.error(f"更新 skill 启停状态失败 {name}: {e}")
            return False

    async def record_installed_dependencies(
        self,
        name: str,
        packages: List[str],
    ) -> bool:
        """记录已安装的依赖包名"""
        try:
            db = get_mongo_db()
            await db[_SKILL_STATE_COLLECTION].update_one(
                {"name": name},
                {
                    "$set": {
                        "installed_dependencies": packages,
                        "last_installed_at": now_tz(),
                        "last_checked_at": now_tz(),
                        "updated_at": now_tz(),
                    },
                    "$setOnInsert": {
                        "name": name,
                        "enabled": True,
                        "created_at": now_tz(),
                    },
                },
                upsert=True,
            )
            return True
        except Exception as e:
            logger.error(f"记录 skill 已安装依赖失败 {name}: {e}")
            return False

    async def update_last_checked(self, name: str) -> bool:
        """更新最后检查时间（不修改其他字段）"""
        try:
            db = get_mongo_db()
            await db[_SKILL_STATE_COLLECTION].update_one(
                {"name": name},
                {"$set": {"last_checked_at": now_tz()}},
                upsert=True,
            )
            return True
        except Exception as e:
            logger.warning(f"更新 last_checked_at 失败 {name}: {e}")
            return False

    async def delete_state(self, name: str) -> bool:
        """删除 skill 状态（卸载时调用）"""
        try:
            db = get_mongo_db()
            await db[_SKILL_STATE_COLLECTION].delete_one({"name": name})
            return True
        except Exception as e:
            logger.error(f"删除 skill_state 失败 {name}: {e}")
            return False

    async def write_install_log(self, log: SkillInstallLog) -> bool:
        """写入安装审计日志"""
        try:
            db = get_mongo_db()
            doc = log.model_dump(by_alias=True, exclude_none=False)
            await db[_SKILL_INSTALL_LOG_COLLECTION].insert_one(doc)
            return True
        except Exception as e:
            logger.error(f"写入 skill_install_log 失败 {log.skill_name}: {e}")
            return False

    async def list_install_logs(
        self,
        skill_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[SkillInstallLog]:
        """查询安装审计日志"""
        try:
            db = get_mongo_db()
            query = {"skill_name": skill_name} if skill_name else {}
            cursor = db[_SKILL_INSTALL_LOG_COLLECTION].find(query).sort(
                "installed_at", -1
            ).limit(limit)
            result: List[SkillInstallLog] = []
            async for doc in cursor:
                try:
                    result.append(SkillInstallLog.model_validate(doc))
                except Exception as e:
                    logger.warning(f"解析 install_log 失败: {e}")
            return result
        except Exception as e:
            logger.warning(f"查询 install_logs 失败: {e}")
            return []
