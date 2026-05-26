from fastapi import APIRouter
import time
from pathlib import Path

router = APIRouter()


def get_version() -> str:
    """从 VERSION 文件读取版本号"""
    try:
        version_file = Path(__file__).parent.parent.parent / "VERSION"
        if version_file.exists():
            return version_file.read_text(encoding='utf-8').strip()
    except Exception as e:
        pass
    return "0.1.16"  # 默认版本号


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