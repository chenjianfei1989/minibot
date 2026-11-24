"""工具基类。"""

from abc import ABC, abstractmethod
import inspect
from typing import Any

from ..core.types import ToolDefinition
from .result import ToolOutcome


class BaseTool(ABC):
    """所有工具的抽象基类。"""

    name: str
    description: str

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """返回工具输入的 JSON Schema。"""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """使用给定参数执行工具。"""
        pass

    def validate_arguments(self, args: dict[str, Any]) -> None:
        """用绑定后的 execute 签名检查传入的关键字参数。"""
        inspect.signature(self.execute).bind(**args)

    async def execute_result(self, **kwargs) -> ToolOutcome:
        """适配现有的文本返回工具，原样传递其文本。"""
        return ToolOutcome(await self.execute(**kwargs))

    def get_definition(self) -> ToolDefinition:
        """获取提供给 API 的工具定义。"""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )

    def to_dict(self) -> dict:
        """转换为 API 兼容的字典。"""
        return self.get_definition().to_dict()


class ResultTool(BaseTool):
    """具有显式执行结果和兼容文本入口的内置工具。"""

    async def execute(self, *args, **kwargs) -> str:
        """执行工具并返回其文本结果，供兼容调用方使用。"""
        return (await self.execute_result(*args, **kwargs)).text

    def validate_arguments(self, args: dict[str, Any]) -> None:
        """按 execute_result 的签名校验参数。"""
        inspect.signature(self.execute_result).bind(**args)

    @abstractmethod
    async def execute_result(self, **kwargs) -> ToolOutcome:
        """由子类执行工具，返回文本、状态和诊断信息。"""
        pass
