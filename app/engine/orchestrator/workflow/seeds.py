"""本地 JSON 种子加载（config/seeds/）。

种子的唯一职责是「初始注入」：seeder 在启动时写入 DB（DB 为运行时唯一权威），
store 在 DB 不可达/集合为空时以此作只读降级。运行期不再有任何 YAML 存放。

种子文件格式（format_version 演进时向后兼容读取）：
- agents.json:    {"format_version": 1, "agents": [{"phase": 1|2|3, "spec": {...}}, ...]}
- workflows.json: {"format_version": 1, "workflows": [{"slug": ..., ...WorkflowSpec dump...}, ...]}
"""

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.env import get_env

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: Dict[str, Tuple[float, Any]] = {}

SEED_MTIME_TTL_SECONDS = 5.0


class SeedLoadError(RuntimeError):
    """种子文件缺失或格式非法（安装损坏，属启动失败级别）。"""


def locate_seeds_dir() -> Path:
    """定位 config/seeds/：AGENT_CONFIG_DIR 优先，否则向上探测项目根。"""
    env_dir = get_env("AGENT_CONFIG_DIR")
    if env_dir:
        candidate = Path(env_dir).parent / "seeds"
        if (candidate / "agents.json").is_file():
            return candidate

    probe = Path(__file__).resolve()
    for _ in range(8):
        probe = probe.parent
        if (probe / "config" / "seeds" / "agents.json").is_file():
            return probe / "config" / "seeds"
    raise SeedLoadError("未找到 config/seeds/agents.json（安装不完整）")


def _load_seed_file(name: str) -> Dict[str, Any]:
    """读取并缓存种子文件（mtime + TTL 双失效，热路径零 stat 放大）。"""
    path = locate_seeds_dir() / name
    try:
        mtime = path.stat().st_mtime
    except OSError as e:
        raise SeedLoadError(f"种子文件不可读: {path} ({e})") from e

    now = time.monotonic()
    with _lock:
        hit = _cache.get(name)
        if hit and hit[0] > now and hit[1][0] == mtime:
            return hit[1][1]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SeedLoadError(f"种子文件解析失败: {path} ({e})") from e

    if not isinstance(data, dict) or not isinstance(data.get("format_version"), int):
        raise SeedLoadError(f"种子文件缺少 format_version: {path}")

    with _lock:
        _cache[name] = (now + SEED_MTIME_TTL_SECONDS, (mtime, data))
    return data


def load_agent_seeds() -> List[Dict[str, Any]]:
    """返回智能体种子条目列表：[{"phase": int, "spec": {...}}, ...]（保持文件序）。"""
    data = _load_seed_file("agents.json")
    agents = data.get("agents")
    if not isinstance(agents, list):
        raise SeedLoadError("agents.json 的 agents 字段必须为列表")
    return agents


def load_workflow_seeds() -> List[Dict[str, Any]]:
    """返回工作流种子列表：[WorkflowSpec dump, ...]。"""
    data = _load_seed_file("workflows.json")
    workflows = data.get("workflows")
    if not isinstance(workflows, list):
        raise SeedLoadError("workflows.json 的 workflows 字段必须为列表")
    return workflows


def agent_seed_by_slug() -> Dict[str, Dict[str, Any]]:
    """slug → 种子条目 索引。"""
    return {entry["spec"]["slug"]: entry for entry in load_agent_seeds()}


def workflow_seed_by_slug() -> Dict[str, Dict[str, Any]]:
    return {entry["slug"]: entry for entry in load_workflow_seeds()}


def agent_spec_hash(spec: Dict[str, Any]) -> str:
    """规范化内容 hash：判 builtin / 升级的一致性依据（与 YAML 时代语义无关）。"""
    canonical = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def find_seed_phase(slug: str) -> Optional[int]:
    for entry in load_agent_seeds():
        if entry["spec"].get("slug") == slug:
            return entry["phase"]
    return None
