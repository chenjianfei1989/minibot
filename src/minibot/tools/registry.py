"""管理可用工具的工具注册表。"""

from typing import Any

from ..core.runtime_budget import RuntimeBudgetExceeded
from .base import BaseTool
from .result import ToolOutcome


class ToolRegistry:
    """管理和访问工具的注册表。"""

    def __init__(self):
        """初始化工具名称映射及注册限制状态。"""
        self._tools: dict[str, BaseTool] = {}
        self._sealed = False

    def register(self, tool: BaseTool) -> None:
        """注册一个工具。"""
        if self._sealed:
            raise ValueError("Host tools are unavailable in a restricted Docker workspace")
        self._tools[tool.name] = tool

    def seal(self) -> None:
        """在允许的工具全部注册后，禁止继续添加。"""
        self._sealed = True

    def unregister(self, name: str) -> None:
        """按名称取消注册工具。"""
        self._tools.pop(name, None)

    def get(self, name: str) -> BaseTool | None:
        """按名称获取工具。"""
        return self._tools.get(name)

    def get_all(self) -> list[BaseTool]:
        """获取全部已注册工具。"""
        return list(self._tools.values())

    def get_definitions(self) -> list[dict[str, Any]]:
        """获取提供给 API 的全部工具定义。"""
        return [tool.to_dict() for tool in self._tools.values()]

    def filter_by_names(self, names: list[str] | str) -> list[BaseTool]:
        """按名称筛选工具。使用 '*' 选中全部工具。"""
        if names == "*":
            return self.get_all()
        return [t for t in self._tools.values() if t.name in names]

    async def execute(self, name: str, args: dict[str, Any]) -> str:
        """通过兼容文本接口执行工具。"""
        return (await self.execute_result(name, args)).text

    async def execute_result(self, name: str, args: dict[str, Any]) -> ToolOutcome:
        """执行工具并保留其执行结果与取消信号。"""
        tool = self.get(name)
        if tool is None:
            return ToolOutcome(f"Unknown tool: {name}", "unknown_tool")
        if not isinstance(args, dict):
            return ToolOutcome("Error: Tool arguments must be an object", "invalid_arguments")
        try:
            schema = tool.input_schema
            required = schema.get("required", [])
            missing = [key for key in required if key not in args]
            if missing:
                return ToolOutcome(f"Error: Missing required arguments: {', '.join(missing)}", "invalid_arguments")
            if schema.get("additionalProperties") is False:
                unexpected = args.keys() - schema.get("properties", {}).keys()
                if unexpected:
                    return ToolOutcome(f"Error: Unexpected arguments: {', '.join(sorted(unexpected))}", "invalid_arguments")
            tool.validate_arguments(args)
        except (TypeError, ValueError) as exc:
            return ToolOutcome(f"Error: {exc}", "invalid_arguments")
        try:
            return await tool.execute_result(**args)
        except RuntimeBudgetExceeded:
            raise
        except TimeoutError as exc:
            return ToolOutcome(f"Error: {exc}", "timeout")
        except Exception as exc:
            return ToolOutcome(f"Error: {exc}", "error")

    def __contains__(self, name: str) -> bool:
        """判断给定名称是否已注册。"""
        return name in self._tools

    def __len__(self) -> int:
        """返回已注册工具的数量。"""
        return len(self._tools)
