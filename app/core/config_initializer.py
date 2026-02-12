"""
配置文件初始化模块
负责在容器首次启动时自动初始化必要的配置文件
"""

import shutil
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_config_files():
    """确保配置文件存在，不存在则从install目录复制

    这个函数会在数据库初始化时被调用，确保应用运行时所需的配置文件都已就绪。
    如果配置文件已存在，则跳过复制，保护用户自定义的配置。
    """
    try:
        # 获取配置目录路径
        project_root = Path(__file__).resolve().parents[2]
        config_dir = project_root / "config"
        install_dir = project_root / "install" / "default-config"

        # 记录初始化开始
        logger.info("=" * 60)
        logger.info("🔧 开始检查配置文件...")

        # 确保配置目录存在
        config_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 配置目录: {config_dir}")

        # 初始化结果统计
        initialized_count = 0
        skipped_count = 0

        # 1. 处理Agent配置文件 (Phase1-4)
        for phase in range(1, 5):
            filename = f"phase{phase}_agents_config.yaml"
            agent_config_src = install_dir / "agents" / filename
            agent_config_dst = config_dir / "agents" / filename
            
            # 只有当源文件存在时才尝试初始化
            if agent_config_src.exists():
                if _handle_config_file(agent_config_src, agent_config_dst, f"Agent配置(Phase{phase})"):
                    initialized_count += 1
                else:
                    skipped_count += 1

        # 2. 处理MCP配置文件
        mcp_config_src = install_dir / "mcp.json"
        mcp_config_dst = config_dir / "mcp.json"

        if _handle_config_file(mcp_config_src, mcp_config_dst, "MCP配置"):
            initialized_count += 1
        else:
            skipped_count += 1

        # 记录初始化结果
        logger.info("=" * 60)
        if initialized_count > 0:
            logger.info(f"✅ 配置初始化完成: 初始化了 {initialized_count} 个配置文件")
        if skipped_count > 0:
            logger.info(f"🔒 已存在配置: 跳过了 {skipped_count} 个配置文件")
        logger.info("=" * 60)

        return True

    except Exception as e:
        logger.error(f"❌ 配置文件初始化失败: {e}")
        # 不抛出异常，允许应用继续启动
        return False


def _handle_config_file(src: Path, dst: Path, config_name: str) -> bool:
    """处理单个配置文件的检查和复制

    Args:
        src: 源文件路径（install目录中的默认配置）
        dst: 目标文件路径（config目录中的实际配置）
        config_name: 配置文件名称（用于日志）

    Returns:
        bool: 是否进行了初始化（True=复制了文件，False=文件已存在）
    """
    try:
        # 确保目标目录存在
        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.exists():
            logger.info(f"🔒 {config_name}已存在，跳过初始化: {dst.name}")
            return False

        if not src.exists():
            logger.warning(f"⚠️ 默认{config_name}文件不存在: {src}")
            return False

        # 复制文件
        shutil.copy2(src, dst)
        logger.info(f"✅ {config_name}初始化成功: {dst.name}")
        return True

    except Exception as e:
        logger.error(f"❌ {config_name}初始化失败: {e}")
        return False

