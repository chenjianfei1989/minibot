"""第二版记忆存储使用的 SQLModel 表定义。"""

from __future__ import annotations

from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlmodel import Field, SQLModel
from sqlmodel.sql.sqltypes import AutoString


_MYSQL_TABLE_OPTIONS = {
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
    "mysql_engine": "InnoDB",
}
# MySQL 下为正文和长路径保留空间，其他后端继续使用原有字符串类型。
_MYSQL_LONG_STRING = AutoString().with_variant(LONGTEXT(), "mysql")


class MemoryNamespaceRow(SQLModel, table=True):
    __tablename__ = "memory_namespaces"

    id: str = Field(primary_key=True)
    slug: str
    title: str = Field(sa_type=_MYSQL_LONG_STRING)
    description: str | None = Field(default=None, sa_type=_MYSQL_LONG_STRING)
    created_at: str
    updated_at: str

    __table_args__ = (
        UniqueConstraint("slug", name="uq_memory_namespaces_slug"),
        {**_MYSQL_TABLE_OPTIONS, "comment": "结构化记忆命名空间，保存空间名称和说明，用于隔离不同范围的记忆。"},
    )


class MemoryNodeRow(SQLModel, table=True):
    __tablename__ = "memory_nodes"

    id: str = Field(primary_key=True)
    namespace_id: str = Field(index=True)
    parent_id: str | None = Field(default=None, index=True)
    slug: str
    uri: str = Field(sa_type=_MYSQL_LONG_STRING)
    title: str = Field(sa_type=_MYSQL_LONG_STRING)
    kind: str
    node_type: str | None = None
    content: str = Field(sa_type=_MYSQL_LONG_STRING)
    is_core: bool = False
    priority: int = 0
    created_at: str
    updated_at: str
    last_accessed_at: str | None = None
    deleted_at: str | None = None

    __table_args__ = (
        Index("idx_memory_nodes_namespace_uri", "namespace_id", "uri", mysql_length={"uri": 255}),
        Index("idx_memory_nodes_parent", "namespace_id", "parent_id"),
        {**_MYSQL_TABLE_OPTIONS, "comment": "结构化记忆节点，保存目录层级、记忆正文和当前状态。"},
    )


class MemoryNodeVersionRow(SQLModel, table=True):
    __tablename__ = "memory_node_versions"
    __table_args__ = {
        **_MYSQL_TABLE_OPTIONS,
        "comment": "记忆节点的历史版本，保存每次变更时的快照和变更详情。",
    }

    id: str = Field(primary_key=True)
    node_id: str = Field(index=True)
    version_no: int
    operation: str
    snapshot_title: str = Field(sa_type=_MYSQL_LONG_STRING)
    snapshot_parent_id: str | None = None
    snapshot_uri: str = Field(sa_type=_MYSQL_LONG_STRING)
    snapshot_kind: str
    snapshot_node_type: str | None = None
    snapshot_content: str = Field(sa_type=_MYSQL_LONG_STRING)
    snapshot_is_core: bool
    snapshot_priority: int
    snapshot_triggers_json: str = Field(sa_type=_MYSQL_LONG_STRING)
    change_json: str | None = Field(default=None, sa_type=_MYSQL_LONG_STRING)
    created_at: str


class MemoryTriggerRow(SQLModel, table=True):
    __tablename__ = "memory_triggers"

    id: str = Field(primary_key=True)
    namespace_id: str = Field(index=True)
    node_id: str = Field(index=True)
    term: str
    normalized_term: str
    created_at: str

    __table_args__ = (
        UniqueConstraint("namespace_id", "normalized_term", name="uq_memory_triggers_namespace_term"),
        {**_MYSQL_TABLE_OPTIONS, "comment": "记忆触发词，记录关键词与记忆节点的关联，供检索匹配使用。"},
    )


class MemorySearchDocumentRow(SQLModel, table=True):
    __tablename__ = "memory_search_documents"

    id: str = Field(primary_key=True)
    namespace_id: str = Field(index=True)
    node_id: str
    uri: str = Field(sa_type=_MYSQL_LONG_STRING)
    title: str = Field(sa_type=_MYSQL_LONG_STRING)
    kind: str
    node_type: str | None = None
    search_text: str = Field(sa_type=_MYSQL_LONG_STRING)
    updated_at: str

    __table_args__ = (
        UniqueConstraint("node_id", name="uq_memory_search_documents_node"),
        {**_MYSQL_TABLE_OPTIONS, "comment": "结构化记忆检索文档，汇总标题、正文等内容用于搜索匹配。"},
    )
