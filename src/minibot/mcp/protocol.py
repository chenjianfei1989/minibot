"""MCP 协议数据类型。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPTool:
    """MCP 工具定义。"""

    name: str
    description: str
    input_schema: dict[str, Any]
    server: str = ""


@dataclass
class MCPToolCall:
    """MCP 工具调用请求。"""

    name: str
    arguments: dict[str, Any]


@dataclass
class MCPToolResult:
    """MCP 工具调用结果。"""

    content: str
    is_error: bool = False


@dataclass
class MCPResource:
    """MCP 资源定义。"""

    uri: str
    name: str
    description: str = ""
    mime_type: str = ""
    server: str = ""


@dataclass
class MCPCapabilities:
    """服务端能力。"""

    tools: bool = False
    resources: bool = False
    prompts: bool = False


@dataclass
class MCPServerInfo:
    """MCP 服务端信息。"""

    name: str
    version: str
    capabilities: MCPCapabilities = field(default_factory=MCPCapabilities)
