from pathlib import Path

from fastapi import APIRouter
import time
from importlib.metadata import version as _pkg_version, PackageNotFoundError

router = APIRouter()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _PROJECT_ROOT / "pyproject.toml"


def get_version() -> str:
    """读取项目版本号，以 pyproject.toml 为唯一权威源。

    解析顺序：
    1. 直接读取项目根目录的 pyproject.toml（热重载友好，容器内修改即生效）
    2. 安装的包元数据（作为兜底）
    3. 返回 "0.0.0+unknown" 表示版本未知

    不缓存结果，保证每次调用都读取最新值。
    """
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
async def healthz():
    """Kubernetes健康检查"""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz():
    """Kubernetes就绪检查"""
    return {"ready": True}