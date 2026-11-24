"""MiniBot 结构化记忆工具。"""

from __future__ import annotations

import json
from typing import Any

from ...memory.manager import MemoryManager
from ...tools.base import BaseTool


class ReadMemoryTool(BaseTool):
    name = "read_memory"
    description = "Read a memory node or system view by URI."

    def __init__(self, memory_manager: MemoryManager):
        """绑定读取记忆使用的管理器。"""
        self.memory_manager = memory_manager

    @property
    def input_schema(self) -> dict[str, Any]:
        """声明读取记忆所需的 URI。"""
        return {
            "type": "object",
            "properties": {
                "uri": {"type": "string", "description": "Memory URI, for example memory://characters/ali or system://boot."},
            },
            "required": ["uri"],
        }

    async def execute(self, **kwargs) -> str:
        """按 URI 读取记忆条目。"""
        return self.memory_manager.read(kwargs["uri"])


class CreateMemoryTool(BaseTool):
    name = "create_memory"
    description = "Create a folder or memory node inside the active namespace."

    def __init__(self, memory_manager: MemoryManager):
        """绑定创建记忆使用的管理器。"""
        self.memory_manager = memory_manager

    @property
    def input_schema(self) -> dict[str, Any]:
        """声明创建记忆条目的字段。"""
        return {
            "type": "object",
            "properties": {
                "parent_uri": {"type": ["string", "null"]},
                "title": {"type": "string"},
                "kind": {"type": "string", "enum": ["folder", "memory"]},
                "slug": {"type": "string"},
                "node_type": {"type": "string"},
                "content": {"type": "string"},
                "is_core": {"type": "boolean"},
                "priority": {"type": "integer"},
            },
            "required": ["parent_uri", "title", "kind"],
        }

    async def execute(self, **kwargs) -> str:
        """创建记忆条目并返回其标识与创建信息。"""
        node = self.memory_manager.create_memory(
            parent_uri=kwargs.get("parent_uri"),
            title=kwargs["title"],
            kind=kwargs["kind"],
            slug=kwargs.get("slug"),
            node_type=kwargs.get("node_type"),
            content=kwargs.get("content", ""),
            is_core=bool(kwargs.get("is_core", False)),
            priority=int(kwargs.get("priority", 0)),
        )
        return f"Created {node.kind} at {node.uri}"


class UpdateMemoryTool(BaseTool):
    name = "update_memory"
    description = "Update memory node metadata or replace full content."

    def __init__(self, memory_manager: MemoryManager):
        """绑定更新记忆使用的管理器。"""
        self.memory_manager = memory_manager

    @property
    def input_schema(self) -> dict[str, Any]:
        """声明更新记忆所需的 URI 和待更新字段。"""
        return {
            "type": "object",
            "properties": {
                "uri": {"type": "string"},
                "title": {"type": "string"},
                "slug": {"type": "string"},
                "content": {"type": "string"},
                "node_type": {"type": "string"},
                "is_core": {"type": "boolean"},
                "priority": {"type": "integer"},
                "parent_uri": {"type": ["string", "null"]},
            },
            "required": ["uri"],
        }

    async def execute(self, **kwargs) -> str:
        """按 URI 更新记忆条目的字段。"""
        uri = kwargs.pop("uri")
        node = self.memory_manager.update_memory(uri, **kwargs)
        return f"Updated {node.uri}"


class EditMemoryTool(BaseTool):
    name = "edit_memory"
    description = "Edit memory content locally via replace_text or append_text."

    def __init__(self, memory_manager: MemoryManager):
        """绑定编辑记忆使用的管理器。"""
        self.memory_manager = memory_manager

    @property
    def input_schema(self) -> dict[str, Any]:
        """声明编辑记忆文本所需的 URI 和编辑参数。"""
        return {
            "type": "object",
            "properties": {
                "uri": {"type": "string"},
                "operation": {"type": "string", "enum": ["replace_text", "append_text"]},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["uri", "operation"],
        }

    async def execute(self, **kwargs) -> str:
        """按 URI 执行记忆编辑操作并返回结果。"""
        uri = kwargs.pop("uri")
        node = self.memory_manager.edit_memory(uri, **kwargs)
        return f"Edited {node.uri}"


class DeleteMemoryTool(BaseTool):
    name = "delete_memory"
    description = "Delete a memory node by URI."

    def __init__(self, memory_manager: MemoryManager):
        """绑定删除记忆使用的管理器。"""
        self.memory_manager = memory_manager

    @property
    def input_schema(self) -> dict[str, Any]:
        """声明删除记忆所需的 URI。"""
        return {
            "type": "object",
            "properties": {"uri": {"type": "string"}},
            "required": ["uri"],
        }

    async def execute(self, **kwargs) -> str:
        """按 URI 删除记忆条目。"""
        self.memory_manager.delete_memory(kwargs["uri"])
        return f"Deleted {kwargs['uri']}"


class SearchMemoryTool(BaseTool):
    name = "search_memory"
    description = "Search memory nodes inside the active namespace."

    def __init__(self, memory_manager: MemoryManager):
        """绑定搜索记忆使用的管理器。"""
        self.memory_manager = memory_manager

    @property
    def input_schema(self) -> dict[str, Any]:
        """声明记忆搜索的查询文本、筛选和结果限制参数。"""
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search text matched against title, URI, content, and triggers."},
                "limit": {"type": "integer", "description": "Maximum number of results to return."},
                "node_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional filters. Values may match node kinds like `memory` or `folder`, or node_type labels like `character` or `location`.",
                },
                "include_folders": {
                    "type": "boolean",
                    "description": "When true, folder nodes may appear in results. When false, folders are excluded even if filters mention `folder`.",
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs) -> str:
        """按查询与筛选条件搜索记忆，格式化结果供模型读取。"""
        results = self.memory_manager.search(
            kwargs["query"],
            limit=int(kwargs.get("limit", 8)),
            node_types=kwargs.get("node_types"),
            include_folders=bool(kwargs.get("include_folders", False)),
        )
        payload = [
            {
                "uri": result.uri,
                "title": result.title,
                "kind": result.kind,
                "node_type": result.node_type,
                "matched_by": result.matched_by,
                "snippet": result.snippet,
                "parent_uri": result.parent_uri,
            }
            for result in results
        ]
        return json.dumps(payload, ensure_ascii=False, indent=2)


class ManageTriggersTool(BaseTool):
    name = "manage_triggers"
    description = "Add or remove glossary triggers for a memory node."

    def __init__(self, memory_manager: MemoryManager):
        """绑定管理记忆触发器使用的管理器。"""
        self.memory_manager = memory_manager

    @property
    def input_schema(self) -> dict[str, Any]:
        """声明列出、设置或移除记忆触发器所需的参数。"""
        return {
            "type": "object",
            "properties": {
                "uri": {"type": "string"},
                "add": {"type": "array", "items": {"type": "string"}},
                "remove": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["uri"],
        }

    async def execute(self, **kwargs) -> str:
        """调用管理器执行触发器操作并返回处理结果。"""
        payload = self.memory_manager.manage_triggers(
            kwargs["uri"],
            add=kwargs.get("add"),
            remove=kwargs.get("remove"),
        )
        return json.dumps(payload, ensure_ascii=False, indent=2)
