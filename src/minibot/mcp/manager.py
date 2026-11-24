"""管理多个 MCP 服务的管理器。"""

import asyncio
from pathlib import Path

from ..config.schema import MCPConfig, MCPServerConfig
from ..tools.registry import ToolRegistry
from .client import MCPClient
from .protocol import MCPTool, MCPResource
from .tool_adapter import MCPToolAdapter


class MCPManager:
    """管理与多个 MCP 服务的连接。"""

    def __init__(self, config: MCPConfig, workdir: Path):
        """保存 MCP 配置及工作目录，并管理各服务的客户端实例。"""
        self.config = config
        self.workdir = workdir
        self.enabled = config.enabled

        self._clients: dict[str, MCPClient] = {}
        self._connection_locks: dict[str, asyncio.Lock] = {}

    async def connect_all(self) -> dict[str, Exception | None]:
        """连接所有已配置服务，按服务名返回连接错误。"""
        if not self.enabled:
            return {}

        names = [server.name for server in self.config.servers if server.enabled]
        results = await asyncio.gather(*(self.connect_server(name) for name in names))
        return dict(zip(names, results))

    async def disconnect_all(self) -> None:
        """断开所有服务连接。"""
        names = self._clients.keys() | self._connection_locks.keys()
        await asyncio.gather(*(self.disconnect_server(name) for name in names), return_exceptions=True)

    def get_client(self, name: str) -> MCPClient | None:
        """按服务名获取客户端。"""
        return self._clients.get(name)

    def get_all_tools(self) -> list[MCPTool]:
        """获取所有已连接服务提供的工具。"""
        tools = []
        for client in self._clients.values():
            if client.is_connected:
                tools.extend(client.get_tools())
        return tools

    def get_all_resources(self) -> list[MCPResource]:
        """获取所有已连接服务提供的资源。"""
        resources = []
        for client in self._clients.values():
            if client.is_connected:
                resources.extend(client.get_resources())
        return resources

    def register_tools(self, registry: ToolRegistry) -> int:
        """将所有 MCP 工具加入工具注册表，并返回注册数量。"""
        count = 0
        for client in self._clients.values():
            if not client.is_connected:
                continue
            for mcp_tool in client.get_tools():
                adapter = MCPToolAdapter(mcp_tool, client)
                registry.register(adapter)
                count += 1
        return count

    def list_servers(self) -> list[str]:
        """列出所有已连接的服务名称。"""
        return [name for name in self._clients if self.is_connected(name)]

    def get_all_server_configs(self) -> list[MCPServerConfig]:
        """返回所有已配置的服务，包括尚未连接的服务。"""
        return list(self.config.servers)

    def is_connected(self, name: str) -> bool:
        """判断指定服务当前是否已连接。"""
        client = self._clients.get(name)
        return client is not None and client.is_connected

    async def connect_server(self, name: str) -> Exception | None:
        """按配置名称连接一个服务，返回错误或 None。"""
        cfg = next((s for s in self.config.servers if s.name == name), None)
        if cfg is None:
            return ValueError(f"Unknown server: {name}")
        async with self._connection_locks.setdefault(name, asyncio.Lock()):
            client = self._clients.get(name)
            if client is None:
                client = MCPClient(cfg, self.workdir)
            try:
                await client.connect()
            except Exception as exc:
                return exc
            self._clients[name] = client
        return None

    async def disconnect_server(self, name: str) -> None:
        """按名称断开一个服务的连接。"""
        async with self._connection_locks.setdefault(name, asyncio.Lock()):
            client = self._clients.pop(name, None)
            if client is not None:
                await client.disconnect()

    @property
    def server_count(self) -> int:
        """已连接的服务数量。"""
        return len(self.list_servers())

    @property
    def tool_count(self) -> int:
        """MCP 工具总数。"""
        return len(self.get_all_tools())
