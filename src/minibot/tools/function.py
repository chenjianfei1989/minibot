"""供 SDK 集成使用的 Python 函数工具。"""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Callable, get_args, get_origin, get_type_hints, Literal

from .base import BaseTool


def _is_optional(annotation: Any) -> tuple[bool, Any]:
    """判断类型注解是否允许 None，并返回其非空类型信息。"""
    origin = get_origin(annotation)
    if origin is None:
        return False, annotation

    # Optional[T] 等价于 Union[T, None]。
    if origin is Literal or origin is list or origin is dict:
        return False, annotation

    if origin is getattr(__import__("types"), "UnionType", object()) or origin is getattr(__import__("typing"), "Union", object()):
        args = [a for a in get_args(annotation)]
        non_none = [a for a in args if a is not type(None)]  # noqa: E721
        if len(non_none) == 1 and len(non_none) != len(args):
            return True, non_none[0]
    return False, annotation


def _schema_from_type(annotation: Any) -> dict[str, Any]:
    """将受支持的 Python 类型注解转换成 JSON Schema。"""
    origin = get_origin(annotation)

    if origin is None:
        if annotation in {str}:
            return {"type": "string"}
        if annotation in {int}:
            return {"type": "integer"}
        if annotation in {float}:
            return {"type": "number"}
        if annotation in {bool}:
            return {"type": "boolean"}
        if annotation in {dict, Any}:
            return {"type": "object"}
        if annotation in {list}:
            return {"type": "array"}
        raise TypeError(f"Unsupported annotation: {annotation!r}")

    if origin is Literal:
        values = list(get_args(annotation))
        if not values:
            raise TypeError("Literal[] must include at least one value")
        value_types = {type(v) for v in values}
        if len(value_types) != 1:
            raise TypeError("Literal values must share the same type")
        base = next(iter(value_types))
        schema = _schema_from_type(base)
        schema["enum"] = values
        return schema

    if origin in {list, tuple}:
        args = get_args(annotation)
        item_ann = args[0] if args else Any
        return {"type": "array", "items": _schema_from_type(item_ann)}

    if origin is dict:
        args = get_args(annotation)
        value_ann = args[1] if len(args) == 2 else Any
        return {"type": "object", "additionalProperties": _schema_from_type(value_ann)}

    # 支持 Optional[T]，即 Union[T, None]。
    is_opt, inner = _is_optional(annotation)
    if is_opt:
        return {"anyOf": [_schema_from_type(inner), {"type": "null"}]}

    raise TypeError(f"Unsupported annotation: {annotation!r}")


def schema_from_callable(func: Callable[..., Any]) -> dict[str, Any]:
    """从函数签名和类型提示生成模型可读取的参数 Schema。"""
    sig = inspect.signature(func)
    hints = get_type_hints(func)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if param.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
            raise TypeError("Function tools do not support *args/**kwargs parameters")
        if name not in hints:
            raise TypeError(f"Parameter '{name}' must have a type annotation")

        ann = hints[name]
        schema = _schema_from_type(ann)

        if param.default is not inspect.Parameter.empty:
            default = param.default
            try:
                json.dumps(default)
            except TypeError:
                pass
            else:
                schema["default"] = default
        else:
            required.append(name)

        properties[name] = schema

    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        result["required"] = required
    return result


class FunctionTool(BaseTool):
    """将 Python 可调用对象包装为 MiniBot 的 BaseTool。"""

    def __init__(
        self,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
        input_schema: dict[str, Any] | None = None,
    ) -> None:
        """包装 Python 可调用对象，确定名称、描述、Schema 与调用方式。"""
        if not callable(func):
            raise TypeError("func must be callable")
        self._func = func
        self.name = name or getattr(func, "__name__", "tool")
        self.description = description or (getattr(func, "__doc__", None) or "").strip() or "User provided tool."
        self._input_schema = input_schema or schema_from_callable(func)
        self._is_async = inspect.iscoroutinefunction(func)

    @property
    def input_schema(self) -> dict[str, Any]:
        """返回初始化时生成或显式传入的参数 Schema。"""
        return self._input_schema

    def validate_arguments(self, args: dict[str, Any]) -> None:
        """用被包装函数的签名校验传入的命名参数。"""
        inspect.signature(self._func).bind(**args)

    async def execute(self, **kwargs) -> str:
        """根据函数是否异步执行，并将返回值转换为工具文本。"""
        if self._is_async:
            result = await self._func(**kwargs)
        else:
            result = await asyncio.to_thread(self._func, **kwargs)

        if result is None:
            return ""
        if isinstance(result, str):
            return result
        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False)
        return str(result)

