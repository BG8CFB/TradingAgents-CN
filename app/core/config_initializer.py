"""
配置文件初始化模块
负责在容器首次启动时自动初始化必要的配置文件
"""

import os
import shutil
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def ensure_config_files():
    """确保配置文件存在，不存在则从install目录复制

    这个函数会在数据库初始化时被调用，确保应用运行时所需的配置文件都已就绪。
    如果配置文件已存在，则跳过复制，保护用户自定义的配置。
    """
    try:
        # 获取配置目录路径
        config_dir = Path("/app/config")
        install_dir = Path("/app/install/default-config")

        # 记录初始化开始
        logger.info("=" * 60)
        logger.info("🔧 开始检查配置文件...")

        # 确保配置目录存在
        config_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 配置目录: {config_dir}")

        # 初始化结果统计
        initialized_count = 0
        skipped_count = 0

        # 1. 处理Agent配置文件
        agent_config_src = install_dir / "agents" / "phase1_agents_config.yaml"
        agent_config_dst = config_dir / "agents" / "phase1_agents_config.yaml"

        if _handle_config_file(agent_config_src, agent_config_dst, "Agent配置"):
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


def get_config_status() -> dict:
    """获取当前配置文件状态

    Returns:
        dict: 包含各配置文件状态的字典
    """
    config_dir = Path("/app/config")
    status = {}

    # 检查Agent配置
    agent_config = config_dir / "agents" / "phase1_agents_config.yaml"
    status["agent_config"] = {
        "path": str(agent_config),
        "exists": agent_config.exists(),
        "is_custom": agent_config.exists() and _is_custom_config(agent_config)
    }

    # 检查MCP配置
    mcp_config = config_dir / "mcp.json"
    status["mcp_config"] = {
        "path": str(mcp_config),
        "exists": mcp_config.exists(),
        "is_custom": mcp_config.exists() and _is_custom_config(mcp_config)
    }

    return status


def _is_custom_config(file_path: Path) -> bool:
    """判断配置文件是否为用户自定义的

    通过比较文件修改时间与容器启动时间来判断
    """
    try:
        # 获取文件修改时间
        file_mtime = file_path.stat().st_mtime

        # 获取容器启动时间（近似为/proc/1的启动时间）
        try:
            with open('/proc/1/stat', 'r') as f:
                # 第22个字段是进程启动时间（从系统启动开始的时钟滴答数）
                start_ticks = int(f.read().split()[21])
            # 转换为秒（需要获取系统时钟频率）
            import psutil
            boot_time = psutil.boot_time()
            container_start_time = boot_time + (start_ticks * psutil.cpu_times().system / psutil.cpu_count())
        except:
            # 如果无法获取容器启动时间，使用当前时间减去10分钟作为估算
            import time
            container_start_time = time.time() - 600

        # 如果文件修改时间早于容器启动时间，说明是挂载的已有文件
        return file_mtime < container_start_time

    except Exception:
        # 如果无法判断，保守地认为是自定义配置
        return True


def reset_config_to_default() -> bool:
    """重置配置为默认版本

    删除现有配置文件，下次启动时会自动重新初始化

    Returns:
        bool: 是否成功重置
    """
    try:
        config_dir = Path("/app/config")
        reset_count = 0

        # 删除Agent配置
        agent_config = config_dir / "agents" / "phase1_agents_config.yaml"
        if agent_config.exists():
            agent_config.unlink()
            reset_count += 1
            logger.info(f"🗑️ 已删除Agent配置: {agent_config}")

        # 删除MCP配置
        mcp_config = config_dir / "mcp.json"
        if mcp_config.exists():
            mcp_config.unlink()
            reset_count += 1
            logger.info(f"🗑️ 已删除MCP配置: {mcp_config}")

        if reset_count > 0:
            logger.info(f"✅ 配置重置完成，请重启服务以重新初始化")
        else:
            logger.info("ℹ️ 没有找到需要重置的配置文件")

        return True

    except Exception as e:
        logger.error(f"❌ 配置重置失败: {e}")
        return False