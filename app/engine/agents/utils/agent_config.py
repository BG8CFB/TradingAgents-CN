"""
Agent 配置与工具函数

从 generic_agent.py 迁出的共享工具函数，供 Stage 2-4 智能体使用。
"""

import os
import re
import tempfile
import yaml
from typing import Optional

from app.core.async_utils import run_async
from app.core.env import get_env
from app.utils.logging_init import get_logger
from app.utils.stock_utils import StockUtils

logger = get_logger("agents.config")


def resolve_company_name(ticker: str, market_info: dict) -> str:
    """统一解析公司名称，避免各阶段智能体复制脆弱逻辑。"""
    try:
        if market_info["is_china"]:
            try:
                from app.data.core.interface import DataInterface
                _di = DataInterface.get_instance()
                _r = run_async(_di.read("CN", "basic_info", symbol=ticker))
                data = _r.get("data")
                if data and isinstance(data, dict) and data.get("name"):
                    return data["name"]
                if data and isinstance(data, list) and data and data[0].get("name"):
                    return data[0]["name"]
            except Exception as e:
                logger.debug(f"获取A股公司名称失败: {e}")
                pass
            return f"股票代码{ticker}"

        if market_info["is_hk"]:
            try:
                from app.data.core.interface import DataInterface
                clean_ticker = ticker.replace(".HK", "").replace(".hk", "").zfill(5)
                di = DataInterface.get_instance()
                result = run_async(
                    di.read("HK", "basic_info", symbol=clean_ticker)
                )
                data = result.get("data")
                if data:
                    name = data.get("name_zh") or data.get("name_en") if isinstance(data, dict) else None
                    if name:
                        return name
                    if isinstance(data, list) and data:
                        name = data[0].get("name_zh") or data[0].get("name_en")
                        if name:
                            return name
            except Exception as e:
                logger.debug(f"获取港股公司名称失败: {e}")
            clean_ticker = ticker.replace(".HK", "").replace(".hk", "")
            return f"港股{clean_ticker}"

        if market_info["is_us"]:
            try:
                from app.data.core.interface import DataInterface
                di = DataInterface.get_instance()
                result = run_async(di.read("US", "basic_info", symbol=ticker.upper()))
                data = result.get("data")
                if data:
                    doc = data[0] if isinstance(data, list) and data else data
                    company_name = doc.get("name") or doc.get("shortName") or doc.get("longName")
                    if company_name:
                        return company_name
            except Exception as e:
                logger.debug(f"获取美股公司名称失败: {e}")
            return StockUtils.US_STOCK_NAMES.get(ticker.upper(), f"美股{ticker}")

        return f"股票{ticker}"
    except Exception as exc:
        logger.error(f"❌ 获取公司名称失败: {exc}")
        return f"股票{ticker}"


def build_stage3_report_path(task_id: Optional[str], ticker: str, report_slug: str) -> str:
    """为 Stage 3 报告生成隔离路径，避免并发任务相互覆盖。"""
    safe_task_id = re.sub(r"[^A-Za-z0-9_-]+", "_", re.sub(r"\.\.", "_", task_id or ticker or "unknown"))
    safe_ticker = re.sub(r"[^A-Za-z0-9_-]+", "_", re.sub(r"\.\.", "_", ticker or "unknown"))
    report_dir = os.path.join(tempfile.gettempdir(), "tradingagents_stage3_reports")
    os.makedirs(report_dir, exist_ok=True)
    return os.path.join(report_dir, f"{safe_task_id}_{safe_ticker}_{report_slug}.md")


def load_agent_config(slug: str) -> str:
    """从 YAML 配置加载智能体角色定义"""
    try:
        env_dir = get_env("AGENT_CONFIG_DIR")
        agents_dirs = []

        if env_dir and os.path.exists(env_dir):
            agents_dirs.append(env_dir)
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
            config_agents_dir = os.path.join(project_root, "config", "agents")
            if os.path.exists(config_agents_dir):
                agents_dirs.append(config_agents_dir)

        config_files = [
            "phase1_agents_config.yaml",
            "phase2_agents_config.yaml",
            "phase3_agents_config.yaml",
        ]

        for agents_dir in agents_dirs:
            for config_file in config_files:
                yaml_path = os.path.join(agents_dir, config_file)
                if not os.path.exists(yaml_path):
                    continue

                with open(yaml_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)

                for agent in config.get("customModes", []):
                    if agent.get("slug") == slug:
                        return agent.get("roleDefinition", "")

                for agent in config.get("agents", []):
                    if agent.get("slug") == slug:
                        return agent.get("roleDefinition", "")

        logger.warning(f"在配置中未找到智能体: {slug}")
        return ""
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
        return ""
