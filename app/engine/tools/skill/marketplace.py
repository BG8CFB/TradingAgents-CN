"""
ClawHub 市场客户端（OpenClaw skill marketplace）

官方允许第三方只读复用公开 API（要求：缓存、遵守 429/Retry-After、回链 canonical 页）。
所有 GET 走内存 TTL 缓存；下载端点不缓存。

API 实测形状（2026-08，与 OpenAPI 声明有出入，以下以实测为准）：
- GET /api/v1/skills?limit&cursor&sort          → {items:[平铺条目], nextCursor}
- GET /api/v1/search?q=&limit                    → {results:[平铺条目]}（注意不是 items）
- GET /api/v1/skills/{slug}?owner=               → {skill:{...}, owner, latestVersion, ...}
  · 同名 slug 会 409 AMBIGUOUS_SKILL_SLUG，必须带 ?owner= 消歧
- GET /api/v1/skills/{slug}/versions?owner=      → {items:[{version,...}]}
- GET /api/v1/skills/{slug}/versions/{v}?owner=  → {skill, version:{files:[{path,size,sha256}]}}
- GET /api/v1/skills/{slug}/file?path=&owner=&version= → 单文件原始字节（≤10MB）

响应字段做容错（缺字段降级为空），格式演进的影响集中在本模块。
"""

import logging
import time
from typing import Dict, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# 容器/国内网络到 clawhub.ai 实测单请求可达 10s+，留足余量
DEFAULT_TIMEOUT = 30.0


class MarketplaceRateLimited(Exception):
    """上游 429：携带 Retry-After（秒）供调用方透传"""

    def __init__(self, retry_after: int, message: str = ""):
        self.retry_after = retry_after
        super().__init__(message or f"市场限流，请在 {retry_after} 秒后重试")


class AmbiguousSkillSlug(Exception):
    """同名 slug：携带上游给出的候选列表（[{owner_handle, slug, url}]）"""

    def __init__(self, slug: str, matches: list):
        self.slug = slug
        self.matches = matches
        owners = ", ".join(f"@{m.get('ownerHandle')}/{m.get('slug')}" for m in matches[:5])
        super().__init__(f"技能名 {slug} 有多个作者发布，请指定作者：{owners}")


def parse_reference(reference: str) -> Tuple[str, str]:
    """
    解析市场引用为 (owner, slug)。

    支持格式：
    - "owner/slug"（ClawHub install.reference）
    - "@owner/slug"（openclaw CLI 安装命令格式）
    - "slug"（无作者，owner 为空串）
    """
    ref = (reference or "").strip().lstrip("@")
    if "/" in ref:
        owner, _, slug = ref.partition("/")
        return owner.strip(), slug.strip()
    return "", ref


class MarketplaceClient:
    """ClawHub 只读 API 客户端（带 TTL 缓存）"""

    def __init__(self, base_url: str, cache_ttl: int = 300):
        self.base_url = (base_url or "").rstrip("/")
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, tuple] = {}  # key -> (expires_at, value)

    # ── 内部 ─────────────────────────────────────────────────────────

    def _get_cached(self, key: str):
        entry = self._cache.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            self._cache.pop(key, None)
            return None
        return value

    def _set_cached(self, key: str, value) -> None:
        if self.cache_ttl <= 0:
            return
        self._cache[key] = (time.monotonic() + self.cache_ttl, value)

    async def _request_json(self, path: str, params: Optional[Dict] = None) -> Dict:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(url, params=params)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "5") or 5)
            raise MarketplaceRateLimited(retry_after)
        if resp.status_code == 409:
            try:
                data = resp.json()
            except Exception:
                data = {}
            if data.get("code") == "AMBIGUOUS_SKILL_SLUG":
                raise AmbiguousSkillSlug(
                    data.get("slug", ""), data.get("matches") or []
                )
            raise RuntimeError(f"市场请求冲突 {path}: {resp.text[:200]}")
        if resp.status_code == 404:
            raise RuntimeError(f"市场资源不存在: {path}")
        if resp.status_code != 200:
            raise RuntimeError(f"市场请求失败 {resp.status_code}: {path} {resp.text[:200]}")
        try:
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"市场响应 JSON 解析失败 {path}: {e}") from e
        return data if isinstance(data, dict) else {"items": data}

    async def _download_bytes(self, path: str, params: Optional[Dict] = None) -> bytes:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(url, params=params)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "5") or 5)
            raise MarketplaceRateLimited(retry_after)
        if resp.status_code != 200:
            raise RuntimeError(f"市场文件下载失败 {resp.status_code}: {path}")
        return resp.content

    # ── 公开方法 ─────────────────────────────────────────────────────

    async def list_skills(
        self, limit: int = 60, cursor: str = "", sort: str = "", prefix: str = ""
    ) -> Dict:
        """市场技能列表（分页）；返回 {items: [...], next_cursor}"""
        params = {"limit": max(1, min(int(limit), 200))}
        if cursor:
            params["cursor"] = cursor
        if sort:
            params["sort"] = sort
        if prefix:
            params["prefix"] = prefix
        key = f"list:{limit}:{cursor}:{sort}:{prefix}"
        cached = self._get_cached(key)
        if cached is not None:
            return cached
        data = await self._request_json("/api/v1/skills", params)
        result = {
            "items": [self._normalize_item(i) for i in data.get("items") or []],
            "next_cursor": data.get("nextCursor") or "",
        }
        self._set_cached(key, result)
        return result

    async def search(self, q: str, limit: int = 30) -> Dict:
        """市场搜索；返回 {items: [...], next_cursor: ''}

        实测：/api/v1/search 返回 {results: [...]}（不是 items），条目为平铺结构。
        """
        key = f"search:{q}:{limit}"
        cached = self._get_cached(key)
        if cached is not None:
            return cached
        data = await self._request_json(
            "/api/v1/search", {"q": q, "limit": max(1, min(int(limit), 50))}
        )
        raw_items = data.get("results") or data.get("items") or []
        result = {
            "items": [self._normalize_item(i) for i in raw_items],
            "next_cursor": "",
        }
        self._set_cached(key, result)
        return result

    async def get_skill(self, reference: str) -> Dict:
        """市场技能详情（reference: "owner/slug" 或 "slug"）

        返回 {slug, owner, reference, display_name, description, latest_version,
        skill_md, stats, canonical_url}
        """
        owner, slug = parse_reference(reference)
        params = {"owner": owner} if owner else {}
        key = f"detail:{owner}/{slug}"
        cached = self._get_cached(key)
        if cached is not None:
            return cached
        data = await self._request_json(f"/api/v1/skills/{slug}", params)

        # 实测结构：{skill:{slug,displayName,summary,description,stats}, owner, latestVersion}
        skill = data.get("skill") if isinstance(data.get("skill"), dict) else data
        owner_obj = data.get("owner")
        real_owner = owner or self._owner_handle(owner_obj)

        detail = {
            "slug": skill.get("slug") or slug,
            "owner": real_owner,
            "reference": f"{real_owner}/{skill.get('slug') or slug}" if real_owner else (skill.get("slug") or slug),
            "display_name": skill.get("displayName") or "",
            "description": skill.get("summary") or "",
            "latest_version": (data.get("latestVersion") or {}).get("version", "")
            if isinstance(data.get("latestVersion"), dict)
            else "",
            # description 字段是 SKILL.md 原文，skillMd 同义
            "skill_md": skill.get("description") or "",
            "stats": skill.get("stats") or {},
            "canonical_url": self.canonical_url(real_owner, skill.get("slug") or slug),
        }
        self._set_cached(key, detail)
        return detail

    async def list_versions(self, reference: str) -> list:
        """版本列表（精简为 {version, created_at}）"""
        owner, slug = parse_reference(reference)
        params = {"limit": 20}
        if owner:
            params["owner"] = owner
        key = f"versions:{owner}/{slug}"
        cached = self._get_cached(key)
        if cached is not None:
            return cached
        data = await self._request_json(f"/api/v1/skills/{slug}/versions", params)
        items = data.get("items") if isinstance(data, dict) else data
        versions = [
            {"version": v.get("version", ""), "created_at": v.get("createdAt")}
            for v in (items or [])
            if isinstance(v, dict)
        ]
        self._set_cached(key, versions)
        return versions

    async def get_version_files(self, reference: str, version: str) -> list:
        """指定版本的文件清单（[{path, size, sha256}]）"""
        owner, slug = parse_reference(reference)
        params = {"owner": owner} if owner else {}
        data = await self._request_json(
            f"/api/v1/skills/{slug}/versions/{version}", params
        )
        # 实测结构：{skill, version:{files:[...]}}；容错顶层 files
        version_obj = data.get("version") if isinstance(data.get("version"), dict) else data
        files = []
        for f in version_obj.get("files") or []:
            if isinstance(f, dict) and f.get("path"):
                files.append(
                    {
                        "path": f["path"],
                        "size": int(f.get("size") or 0),
                        "sha256": f.get("sha256") or "",
                    }
                )
            elif isinstance(f, str):
                files.append({"path": f, "size": 0, "sha256": ""})
        return files

    async def download_file(
        self, reference: str, path: str, version: str = "", tag: str = ""
    ) -> bytes:
        """下载单个文件原始字节（不缓存）"""
        owner, slug = parse_reference(reference)
        params: Dict = {"path": path}
        if owner:
            params["owner"] = owner
        if version:
            params["version"] = version
        if tag:
            params["tag"] = tag
        return await self._download_bytes(f"/api/v1/skills/{slug}/file", params)

    def canonical_url(self, owner: str, slug: str) -> str:
        """ClawHub 要求第三方回链 canonical 页面"""
        if owner:
            return f"{self.base_url}/{owner}/skills/{slug}"
        return f"{self.base_url}/skills/{slug}"

    def _owner_handle(self, owner_obj) -> str:
        if isinstance(owner_obj, dict):
            return str(owner_obj.get("handle") or owner_obj.get("username") or "")
        if owner_obj:
            return str(owner_obj)
        return ""

    def _normalize_item(self, item: Dict) -> Dict:
        """列表/搜索条目归一化（两种接口字段略有差异，统一容错）"""
        if not isinstance(item, dict):
            return {}
        slug = item.get("slug") or ""
        owner = item.get("ownerHandle") or self._owner_handle(item.get("owner"))
        if not owner:
            # 列表接口条目可能没有作者信息（搜索接口有 install.reference）
            ref = (item.get("install") or {}).get("reference") if isinstance(item.get("install"), dict) else ""
            if ref:
                owner, _, ref_slug = ref.strip().lstrip("@").partition("/")
                slug = slug or ref_slug
        latest = item.get("latestVersion") or item.get("latest_version")
        latest_version = latest.get("version", "") if isinstance(latest, dict) else ""
        stats = item.get("stats") or {}
        metrics = item.get("metrics") or {}
        return {
            "slug": slug,
            "name": slug,
            "reference": f"{owner}/{slug}" if owner and slug else slug,
            "display_name": item.get("displayName") or "",
            "description": item.get("summary") or "",
            "owner": owner,
            "latest_version": latest_version,
            "downloads": item.get("downloads") or stats.get("downloads") or 0,
            "updated_at": item.get("updatedAt") or metrics.get("updatedAt"),
            "canonical_url": self.canonical_url(owner, slug) if slug else "",
        }


# ── 单例 ─────────────────────────────────────────────────────────────

_client_instance: Optional[MarketplaceClient] = None


def get_marketplace_client(base_url: str = "") -> MarketplaceClient:
    """获取市场客户端单例（base_url 由 SkillService 传入，含 SKILL_REGISTRY_URL fallback）"""
    global _client_instance
    if _client_instance is None:
        url = base_url or getattr(settings, "SKILL_MARKETPLACE_URL", "") or "https://clawhub.ai"
        ttl = int(getattr(settings, "SKILL_MARKETPLACE_CACHE_TTL", 300))
        _client_instance = MarketplaceClient(url, cache_ttl=ttl)
    return _client_instance
