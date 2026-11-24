"""MCP 客户端实现。"""

from contextlib import suppress
from pathlib import Path
from typing import Any

from ..config.schema import MCPServerConfig
from .protocol import MCPTool, MCPToolResult, MCPResource, MCPServerInfo, MCPCapabilities
from .streamable_http import STREAMABLE_HTTP_VERSIONS, StreamableHTTPTransport
from .transport import MCPTransport, StdioTransport, SSETransport


class MCPClient:
    """连接单个 MCP 服务的客户端。"""

    def __init__(self, config: MCPServerConfig, workdir: Path | None = None):
        """保存单个服务的连接配置并初始化传输和资源状态。"""
        self.config = config
        self.name = config.name
        self.workdir = workdir

        self._transport: MCPTransport | None = None
        self._server_info: MCPServerInfo | None = None
        self._tools: list[MCPTool] = []
        self._resources: list[MCPResource] = []

    @property
    def is_connected(self) -> bool:
        """判断底层传输是否已连接到 MCP 服务。"""
        return self._server_info is not None and self._transport is not None and self._transport.is_connected

    async def connect(self) -> None:
        """连接 MCP 服务。"""
        if self.is_connected:
            return
        await self.disconnect()
        protocol_version = "2024-11-05"
        if self.config.transport == "stdio":
            self._transport = StdioTransport(
                command=self.config.command,
                args=self.config.args,
                env=self.config.env,
                cwd=self.workdir,
            )
        elif self.config.transport == "sse":
            self._transport = SSETransport(url=self.config.url)
        elif self.config.transport == "streamable_http":
            self._transport = StreamableHTTPTransport(self.config.url, self.config.headers)
            protocol_version = STREAMABLE_HTTP_VERSIONS[0]
        else:
            raise ValueError(f"Unknown transport: {self.config.transport}")

        try:
            await self._transport.connect()
            await self._initialize(protocol_version)
        except BaseException:
            with suppress(Exception):
                await self.disconnect()
            raise

    async def disconnect(self) -> None:
        """断开与 MCP 服务的连接。"""
        transport, self._transport = self._transport, None
        self._server_info = None
        self._tools.clear()
        self._resources.clear()
        if transport is not None:
            await transport.disconnect()

    async def _initialize(self, protocol_version: str) -> None:
        """初始化 MCP 会话。"""
        result = await self._transport.send({
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version,
                "capabilities": {},
                "clientInfo": {
                    "name": "minibot",
                    "version": "0.1.0",
                },
            },
        })

        # 解析服务端信息。
        server_info = result.get("serverInfo", {})
        capabilities = result.get("capabilities", {})

        info = MCPServerInfo(
            name=server_info.get("name", self.name),
            version=server_info.get("version", "unknown"),
            capabilities=MCPCapabilities(
                tools="tools" in capabilities,
                resources="resources" in capabilities,
                prompts="prompts" in capabilities,
            ),
        )

        # 发送初始化完成通知。
        await self._transport.notify({
            "method": "notifications/initialized",
        })

        # 服务端支持时加载工具。
        if info.capabilities.tools:
            await self._load_tools()

        # 服务端支持时加载资源。
        if info.capabilities.resources:
            await self._load_resources()

        self._server_info = info

    async def _load_tools(self) -> None:
        """从服务端加载可用工具。"""
        result = await self._transport.send({
            "method": "tools/list",
        })

        self._tools = []
        for tool_data in result.get("tools", []):
            self._tools.append(MCPTool(
                name=tool_data["name"],
                description=tool_data.get("description", ""),
                input_schema=tool_data.get("inputSchema", {}),
                server=self.name,
            ))

    async def _load_resources(self) -> None:
        """从服务端加载可用资源。"""
        result = await self._transport.send({
            "method": "resources/list",
        })

        self._resources = []
        for resource_data in result.get("resources", []):
            self._resources.append(MCPResource(
                uri=resource_data["uri"],
                name=resource_data.get("name", ""),
                description=resource_data.get("description", ""),
                mime_type=resource_data.get("mimeType", ""),
                server=self.name,
            ))

    def get_tools(self) -> list[MCPTool]:
        """获取全部可用工具。"""
        return self._tools

    def get_resources(self) -> list[MCPResource]:
        """获取全部可用资源。"""
        return self._resources

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        """调用服务端的一个工具。"""
        if not self.is_connected:
            return MCPToolResult(
                content=f"Error: Not connected to server {self.name}",
                is_error=True,
            )

        try:
            result = await self._transport.send({
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": arguments,
                },
            })

            # 从结果中提取内容。
            content_list = result.get("content", [])
            if content_list:
                # 合并所有文本内容。
                text_parts = []
                for content in content_list:
                    if content.get("type") == "text":
                        text_parts.append(content.get("text", ""))
                content = "\n".join(text_parts)
            else:
                content = str(result)

            return MCPToolResult(
                content=content,
                is_error=result.get("isError", False),
            )

        except Exception as e:
            return MCPToolResult(
                content=f"Error calling tool: {e}",
                is_error=True,
            )

    async def read_resource(self, uri: str) -> str:
        """从服务端读取一项资源。"""
        if not self.is_connected:
            return f"Error: Not connected to server {self.name}"

        try:
            result = await self._transport.send({
                "method": "resources/read",
                "params": {
                    "uri": uri,
                },
            })

            contents = result.get("contents", [])
            if contents:
                return contents[0].get("text", str(contents))
            return str(result)

        except Exception as e:
            return f"Error reading resource: {e}"
