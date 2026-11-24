"""结构化记忆的领域模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MemoryNamespace:
    """独立的记忆空间，通常代表一本小说。"""

    id: str
    slug: str
    title: str
    description: str | None = None


@dataclass
class MemoryNode:
    """记忆树中的一个节点。"""

    id: str
    namespace_id: str
    parent_id: str | None
    slug: str
    uri: str
    title: str
    kind: str
    node_type: str | None
    content: str
    is_core: bool
    priority: int
