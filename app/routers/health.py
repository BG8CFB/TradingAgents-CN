from pathlib import Path

from fastapi import APIRouter
import time
from importlib.metadata import version as _pkg_version, PackageNotFoundError

router = APIRouter()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _PROJECT_ROOT / "pyproject.toml"

# 版本号 TTL 缓存：健康检查高频调用（Docker healthcheck 30s 间隔 + 前端探测），
# 每次请求读盘会把探针延迟耦合到存储长尾（NAS 实测曾卡 9.9~26s）。
# routers 分层约束禁止 import app.data.storage 的 TTLCache，故模块内自建微型缓存
# （元组整体赋值，GIL 下无读写撕裂，无需加锁）。
_VERSION_TTL_SECONDS = 300.0
_version_cache: tuple[str, float] | None = None  # (version, cached_at_monotonic)


def _read_version() -> str:
    """读一次版本号（磁盘 / 包元数据），不经过缓存。"""
    # 优先读源码目录的 pyproject.toml（开发模式热重载场景）
    try:
        if _PYPROJECT.is_file():
            text = _PYPROJECT.read_text(encoding="utf-8")
            for line in text.splitlines():
                if line.strip().startswith("version"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        return parts[1].strip().strip('"').strip("'")
    except OSError:
        pass

    try:
        return _pkg_version("tradingagents")
    except PackageNotFoundError:
        return "0.0.0+unknown"


def get_version() -> str:
    """读取项目版本号，以 pyproject.toml 为唯一权威源。

    解析顺序：
    1. 直接读取项目根目录的 pyproject.toml（TTL 过期后重读，容器内修改延迟生效）
    2. 安装的包元数据（作为兜底）
    3. 返回 "0.0.0+unknown" 表示版本未知

    带 TTL 缓存（300s，monotonic 时钟）：版本号进程内近乎静态，
    每次调用读盘会让健康检查随存储长尾一起卡顿。
    """
    global _version_cache
    now = time.monotonic()
    if _version_cache is not None and now - _version_cache[1] < _VERSION_TTL_SECONDS:
        return _version_cache[0]
    version = _read_version()
    _version_cache = (version, now)
    return version


def _health_response():
    return {
        "success": True,
        "data": {
            "status": "ok",
            "version": get_version(),
            "timestamp": int(time.time()),
            "service": "TradingAgents-CN API"
        },
        "message": "服务运行正常"
    }


@router.get("/health")
@router.get("/api/health")
async def health():
    """健康检查接口 - 前端使用 /health 或 /api/health"""
    return _health_response()


@router.get("/healthz")
@router.get("/api/healthz")
async def healthz():
    """纯内存 liveness 探针（零磁盘 I/O）。

    Docker healthcheck 与前端连通性探测统一走本端点，与含版本信息的
    /health、/api/health（informative）分离，探针延迟永不耦合到存储。
    /api/healthz 别名供前端使用（vite dev 代理只转发 /api 前缀）。
    """
    return {"status": "ok"}


@router.get("/readyz")
async def readyz():
    """Kubernetes就绪检查"""
    return {"ready": True}