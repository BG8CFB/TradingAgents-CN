"""
MCP 连接管理（参考 claude-code mcp-client 生命周期策略，官方 mcp SDK）

- 连接按 (name, config) 缓存；配置变化则重建
- 连接超时 30s；stdio 优雅关闭
- 会话失效（进程退出等）时清缓存，下次调用懒重连
- 本地 server 并发连接数 3
"""

import asyncio
from contextlib import AsyncExitStack
from typing import Dict, Optional, Tuple

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.utils.logging_init import get_logger

from .config import MCPServerConfig

logger = get_logger("app.llm.mcp")

CONNECT_TIMEOUT = 30.0  # 秒，参考 claude-code
LOCAL_CONNECT_CONCURRENCY = 3


class MCPManager:
    """管理全部 MCP server 连接的生命周期"""

    def __init__(self):
        self._stack: Optional[AsyncExitStack] = None
        self._sessions: Dict[str, Tuple[MCPServerConfig, ClientSession]] = {}
        self._connecting: Dict[str, asyncio.Lock] = {}
        self._local_semaphore = asyncio.Semaphore(LOCAL_CONNECT_CONCURRENCY)
        self._closed = False

    async def _ensure_stack(self) -> AsyncExitStack:
        if self._stack is None:
            self._stack = AsyncExitStack()
        return self._stack

    async def connect(self, cfg: MCPServerConfig) -> ClientSession:
        """建立（或复用）到指定 server 的会话；缓存命中直接返回"""
        if self._closed:
            raise RuntimeError("MCPManager 已关闭")
        cached = self._sessions.get(cfg.name)
        if cached and cached[0].cache_key == cfg.cache_key:
            return cached[1]

        lock = self._connecting.setdefault(cfg.name, asyncio.Lock())
        async with lock:
            cached = self._sessions.get(cfg.name)
            if cached and cached[0].cache_key == cfg.cache_key:
                return cached[1]
            session = await self._connect_one(cfg)
            self._sessions[cfg.name] = (cfg, session)
            return session

    async def _connect_one(self, cfg: MCPServerConfig) -> ClientSession:
        """单 server 连接（带并发闸与超时）"""
        stack = await self._ensure_stack()
        async with self._local_semaphore:
            try:
                async with asyncio.timeout(CONNECT_TIMEOUT):
                    if cfg.type == "http":
                        session = await self._connect_http(stack, cfg)
                    else:
                        session = await self._connect_stdio(stack, cfg)
            except asyncio.TimeoutError:
                raise TimeoutError(f"MCP server '{cfg.name}' 连接超时({CONNECT_TIMEOUT}s)")
        logger.info(f"🔗 [mcp] 已连接 {cfg.name} ({cfg.type})")
        return session

    async def _connect_stdio(self, stack: AsyncExitStack, cfg: MCPServerConfig) -> ClientSession:
        params = StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env or None)
        read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        return session

    async def _connect_http(self, stack: AsyncExitStack, cfg: MCPServerConfig) -> ClientSession:
        from mcp.client.streamable_http import streamablehttp_client

        transport = await stack.enter_async_context(streamablehttp_client(cfg.url, headers=cfg.headers or None))
        read_stream, write_stream, _ = transport
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        return session

    async def get_session(self, cfg: MCPServerConfig) -> ClientSession:
        """获取会话；会话已死时清缓存并重连一次（懒重连，参考 claude-code）"""
        session = await self.connect(cfg)
        try:
            # 廉价探活：list_tools 空参数由 server 自行处理，此处用 ping
            await asyncio.wait_for(session.send_ping(), timeout=10.0)
        except Exception as e:
            logger.warning(f"⚠️ [mcp] server '{cfg.name}' 会话失效({e})，尝试重连")
            self._sessions.pop(cfg.name, None)
            session = await self.connect(cfg)
        return session

    async def close_all(self) -> None:
        """关闭全部连接（进程退出前调用）"""
        self._closed = True
        self._sessions.clear()
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
        logger.info("[mcp] 全部连接已关闭")
