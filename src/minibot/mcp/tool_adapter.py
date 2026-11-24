"""把 MCP 工具纳入工具注册表的适配器。"""

from typing import Any

from ..tools.base import ResultTool
from ..tools.result import ToolOutcome
from .client import MCPClient
from .protocol import MCPTool


class MCPToolAdapter(ResultTool):
    """将 MCP 工具适配为 BaseTool 接口。"""

    def __init__(self, mcp_tool: MCPTool, client: MCPClient):
        """将 MCP 服务提供的工具定义与对应客户端绑定。"""
        self._mcp_tool = mcp_tool
        self._client = client
        self.name = f"mcp__{client.name}__{mcp_tool.name}"

    @property
    def description(self) -> str:
        """返回 MCP 服务声明的工具用途描述。"""
        return f"[MCP:{self._client.name}] {self._mcp_tool.description}"

    @property
    def input_schema(self) -> dict[str, Any]:
        """返回 MCP 服务声明的工具输入 Schema。"""
        return self._mcp_tool.input_schema

    async def execute_result(self, **kwargs) -> ToolOutcome:
        """执行 MCP 工具。"""
        result = await self._client.call_tool(
            name=self._mcp_tool.name,
            arguments=kwargs,
        )
        return ToolOutcome(result.content, "error" if result.is_error else "success")
