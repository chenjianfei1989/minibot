"""结构化记忆数据仓库。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import uuid
from typing import Any

from sqlalchemy import case, func
from sqlmodel import Session, select

from ..config.schema import MemoryConfig
from .db import MemoryDatabase, create_memory_db
from .db_models import (
    MemoryNamespaceRow,
    MemoryNodeRow,
    MemoryNodeVersionRow,
    MemorySearchDocumentRow,
    MemoryTriggerRow,
)
from .models import MemoryNamespace, MemoryNode


def _utc_now() -> str:
    """生成持久化时间字段使用的 UTC 时间戳。"""
    return datetime.now(UTC).isoformat()


def _new_id(prefix: str) -> str:
    """生成带类型前缀的记录 ID。"""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _normalize_term(term: str) -> str:
    """去除首尾空白、统一大小写并压缩术语内部空白。"""
    return " ".join(term.strip().lower().split())


@dataclass
class MemoryNodeBundle:
    node: MemoryNode
    parent_uri: str | None
    children: list[MemoryNode]
    triggers: list[str]


class MemoryRepository:
    """基于 SQLite 或 PostgreSQL 的轻量结构化记忆仓库。"""

    def __init__(self, *, backend: str, database: MemoryDatabase) -> None:
        """绑定记忆数据库及其后端类型。"""
        self.backend = backend
        self.database = database
        self.database_path = database.database_path

    @classmethod
    def from_config(cls, config: MemoryConfig, *, app_home: Path) -> "MemoryRepository":
        """根据记忆配置创建使用对应数据库后端的仓库。"""
        backend = (config.backend or "sqlite").strip().lower()
        database = create_memory_db(config, app_home=app_home)
        return cls(backend=backend, database=database)

    def create_namespace(self, *, slug: str, title: str, description: str | None = None) -> MemoryNamespace:
        """持久化一个新的记忆命名空间。"""
        with self.database.session_factory() as session:
            existing = self._get_namespace_row_by_slug(session, slug)
            if existing is not None:
                raise ValueError(f"Namespace already exists: {slug}")
            now = _utc_now()
            row = MemoryNamespaceRow(
                id=_new_id("ns"),
                slug=slug,
                title=title,
                description=description,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.commit()
            return self._row_to_namespace(row)

    def list_namespaces(self) -> list[MemoryNamespace]:
        """读取已存在的命名空间列表。"""
        with self.database.session_factory() as session:
            rows = session.exec(
                select(MemoryNamespaceRow).order_by(MemoryNamespaceRow.slug)
            ).all()
            return [self._row_to_namespace(row) for row in rows]

    def get_namespace_by_slug(self, slug: str) -> MemoryNamespace | None:
        """按 slug 查找命名空间。"""
        with self.database.session_factory() as session:
            row = self._get_namespace_row_by_slug(session, slug)
            if row is None:
                return None
            return self._row_to_namespace(row)

    def create_node(
        self,
        namespace_slug: str,
        *,
        parent_uri: str | None,
        slug: str,
        title: str,
        kind: str,
        node_type: str | None = None,
        content: str = "",
        is_core: bool = False,
        priority: int = 0,
    ) -> MemoryNode:
        """创建记忆节点并同步其版本和搜索索引。"""
        with self.database.session_factory() as session:
            namespace = self._require_namespace_row(session, namespace_slug)
            parent = self._require_parent(session, namespace.id, parent_uri)
            uri = self._compose_uri(parent.uri if parent else None, slug)
            self._ensure_uri_available(session, namespace.id, uri)
            now = _utc_now()
            row = MemoryNodeRow(
                id=_new_id("node"),
                namespace_id=namespace.id,
                parent_id=parent.id if parent else None,
                slug=slug,
                uri=uri,
                title=title,
                kind=kind,
                node_type=node_type,
                content=content,
                is_core=is_core,
                priority=priority,
                created_at=now,
                updated_at=now,
                last_accessed_at=None,
                deleted_at=None,
            )
            session.add(row)
            session.flush()
            node = self._row_to_node(row)
            self._upsert_search_document(session, node)
            self._record_version(session, node, operation="create", change={"created": True})
            session.commit()
            return node

    def update_node(self, namespace_slug: str, uri: str, **fields: Any) -> MemoryNode:
        """更新节点信息，按变更维护版本、URI 与索引。"""
        with self.database.session_factory() as session:
            node_row = self._require_node_row(session, namespace_slug, uri)
            parent_id = node_row.parent_id
            new_slug = node_row.slug
            if "slug" in fields and fields["slug"]:
                new_slug = str(fields["slug"])
            if "parent_uri" in fields:
                parent = self._require_parent(session, node_row.namespace_id, fields["parent_uri"])
                parent_id = parent.id if parent else None
                parent_uri = parent.uri if parent else None
            else:
                parent_uri = self._parent_uri_by_id(node_row.parent_id, session=session)
            new_uri = self._compose_uri(parent_uri, new_slug)
            if new_uri != node_row.uri:
                self._ensure_uri_available(
                    session,
                    node_row.namespace_id,
                    new_uri,
                    exclude_node_id=node_row.id,
                )
            node_row.parent_id = parent_id
            node_row.slug = new_slug
            node_row.uri = new_uri
            node_row.title = fields.get("title", node_row.title)
            node_row.node_type = fields.get("node_type", node_row.node_type)
            node_row.content = fields.get("content", node_row.content)
            node_row.is_core = bool(fields.get("is_core", node_row.is_core))
            node_row.priority = int(fields.get("priority", node_row.priority))
            node_row.updated_at = _utc_now()
            session.add(node_row)
            session.flush()
            if new_uri != uri:
                self._update_descendant_uris(session, node_row.namespace_id, node_row.id, uri, new_uri)
            node = self._row_to_node(node_row)
            self._upsert_search_document(session, node)
            self._record_version(session, node, operation="update", change=fields)
            session.commit()
            return node

    def delete_node(self, namespace_slug: str, uri: str) -> None:
        """删除指定节点及其子树和关联索引记录。"""
        with self.database.session_factory() as session:
            node_row = self._require_node_row(session, namespace_slug, uri)
            now = _utc_now()
            rows = session.exec(
                select(MemoryNodeRow)
                .where(
                    MemoryNodeRow.namespace_id == node_row.namespace_id,
                    MemoryNodeRow.deleted_at.is_(None),
                    (MemoryNodeRow.uri == node_row.uri) | (MemoryNodeRow.uri.like(f"{node_row.uri}/%")),
                )
                .order_by(func.length(MemoryNodeRow.uri).desc())
            ).all()
            for row in rows:
                row.deleted_at = now
                row.updated_at = now
                session.add(row)
                self._delete_search_document(session, row.id)
                triggers = session.exec(
                    select(MemoryTriggerRow).where(MemoryTriggerRow.node_id == row.id)
                ).all()
                for trigger in triggers:
                    session.delete(trigger)
                node = self._row_to_node(row)
                self._record_version(session, node, operation="delete", change={"deleted": True, "root_uri": uri})
            session.commit()

    def get_node_by_uri(self, namespace_slug: str, uri: str) -> MemoryNode | None:
        """在指定命名空间中按 URI 查询节点。"""
        with self.database.session_factory() as session:
            row = self._find_node_row(session, namespace_slug, uri)
            if row is None:
                return None
            return self._row_to_node(row)

    def get_node_bundle(self, namespace_slug: str, uri: str) -> MemoryNodeBundle | None:
        """读取节点以及渲染详情所需的版本、触发词等数据。"""
        with self.database.session_factory() as session:
            namespace = self._require_namespace_row(session, namespace_slug)
            row = session.exec(
                select(MemoryNodeRow).where(
                    MemoryNodeRow.namespace_id == namespace.id,
                    MemoryNodeRow.uri == uri,
                    MemoryNodeRow.deleted_at.is_(None),
                )
            ).first()
            if row is None:
                return None
            child_rows = session.exec(
                select(MemoryNodeRow)
                .where(
                    MemoryNodeRow.namespace_id == namespace.id,
                    MemoryNodeRow.parent_id == row.id,
                    MemoryNodeRow.deleted_at.is_(None),
                )
                .order_by(MemoryNodeRow.kind, MemoryNodeRow.priority.desc(), MemoryNodeRow.title)
            ).all()
            triggers = session.exec(
                select(MemoryTriggerRow.term)
                .where(MemoryTriggerRow.node_id == row.id)
                .order_by(MemoryTriggerRow.term)
            ).all()
            parent_uri = None
            if row.parent_id:
                parent_uri = session.exec(
                    select(MemoryNodeRow.uri).where(MemoryNodeRow.id == row.parent_id)
                ).first()
            return MemoryNodeBundle(
                node=self._row_to_node(row),
                parent_uri=parent_uri,
                children=[self._row_to_node(child_row) for child_row in child_rows],
                triggers=triggers,
            )

    def list_nodes(self, namespace_slug: str) -> list[MemoryNode]:
        """列出指定命名空间中的记忆节点。"""
        with self.database.session_factory() as session:
            namespace = self._require_namespace_row(session, namespace_slug)
            rows = session.exec(
                select(MemoryNodeRow)
                .where(
                    MemoryNodeRow.namespace_id == namespace.id,
                    MemoryNodeRow.deleted_at.is_(None),
                )
                .order_by(MemoryNodeRow.kind, MemoryNodeRow.priority.desc(), MemoryNodeRow.title)
            ).all()
            return [self._row_to_node(row) for row in rows]

    def list_children(self, namespace_slug: str, parent_uri: str | None = None) -> list[MemoryNode]:
        """读取指定父节点的直属子节点。"""
        with self.database.session_factory() as session:
            namespace = self._require_namespace_row(session, namespace_slug)
            statement = select(MemoryNodeRow).where(
                MemoryNodeRow.namespace_id == namespace.id,
                MemoryNodeRow.deleted_at.is_(None),
            )
            if parent_uri is None:
                statement = statement.where(MemoryNodeRow.parent_id.is_(None))
            else:
                parent = self._require_node_row(session, namespace_slug, parent_uri)
                statement = statement.where(MemoryNodeRow.parent_id == parent.id)
            rows = session.exec(
                statement.order_by(MemoryNodeRow.kind, MemoryNodeRow.priority.desc(), MemoryNodeRow.title)
            ).all()
            return [self._row_to_node(row) for row in rows]

    def list_core_nodes(self, namespace_slug: str) -> list[MemoryNode]:
        """读取指定命名空间中符合核心记忆条件的节点。"""
        with self.database.session_factory() as session:
            namespace = self._require_namespace_row(session, namespace_slug)
            rows = session.exec(
                select(MemoryNodeRow)
                .where(
                    MemoryNodeRow.namespace_id == namespace.id,
                    MemoryNodeRow.is_core.is_(True),
                    MemoryNodeRow.deleted_at.is_(None),
                )
                .order_by(MemoryNodeRow.priority.desc(), MemoryNodeRow.title)
            ).all()
            return [self._row_to_node(row) for row in rows]

    def list_recent_nodes(self, namespace_slug: str, *, limit: int = 5) -> list[MemoryNode]:
        """按最近访问或更新时间读取指定命名空间中的节点。"""
        with self.database.session_factory() as session:
            namespace = self._require_namespace_row(session, namespace_slug)
            recency = case(
                (
                    (MemoryNodeRow.last_accessed_at.is_(None)) | (MemoryNodeRow.updated_at > MemoryNodeRow.last_accessed_at),
                    MemoryNodeRow.updated_at,
                ),
                else_=MemoryNodeRow.last_accessed_at,
            )
            rows = session.exec(
                select(MemoryNodeRow)
                .where(
                    MemoryNodeRow.namespace_id == namespace.id,
                    MemoryNodeRow.deleted_at.is_(None),
                )
                .order_by(recency.desc())
                .limit(limit)
            ).all()
            return [self._row_to_node(row) for row in rows]

    def list_versions(self, node_id: str) -> list[dict[str, Any]]:
        """列出节点历史版本。"""
        with self.database.session_factory() as session:
            rows = session.exec(
                select(MemoryNodeVersionRow)
                .where(MemoryNodeVersionRow.node_id == node_id)
                .order_by(MemoryNodeVersionRow.version_no)
            ).all()
            return [
                {
                    "operation": row.operation,
                    "snapshot_uri": row.snapshot_uri,
                    "snapshot_title": row.snapshot_title,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    def list_triggers(self, namespace_slug: str, uri: str) -> list[str]:
        """列出指定节点已配置的触发词。"""
        with self.database.session_factory() as session:
            node = self._require_node_row(session, namespace_slug, uri)
            return self._trigger_terms(session, node.id)

    def glossary_entries(self, namespace_slug: str) -> list[dict[str, Any]]:
        """生成命名空间中的术语及其关联节点信息。"""
        with self.database.session_factory() as session:
            namespace = self._require_namespace_row(session, namespace_slug)
            rows = session.exec(
                select(MemoryTriggerRow.term, MemoryNodeRow.uri, MemoryTriggerRow.node_id)
                .join(MemoryNodeRow, MemoryNodeRow.id == MemoryTriggerRow.node_id)
                .where(
                    MemoryTriggerRow.namespace_id == namespace.id,
                    MemoryNodeRow.deleted_at.is_(None),
                )
                .order_by(MemoryTriggerRow.term)
            ).all()
            return [
                {"term": term, "uri": uri, "node_id": node_id}
                for term, uri, node_id in rows
            ]

    def update_triggers(
        self,
        namespace_slug: str,
        uri: str,
        *,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> list[str]:
        """添加或移除节点触发词，并同步该节点的搜索文档。"""
        add = add or []
        remove = remove or []
        with self.database.session_factory() as session:
            node_row = self._require_node_row(session, namespace_slug, uri)
            namespace_id = node_row.namespace_id
            for term in add:
                normalized = _normalize_term(term)
                if not normalized:
                    continue
                existing = session.exec(
                    select(MemoryTriggerRow).where(
                        MemoryTriggerRow.namespace_id == namespace_id,
                        MemoryTriggerRow.normalized_term == normalized,
                    )
                ).first()
                if existing is not None and existing.node_id != node_row.id:
                    raise ValueError(f"Trigger already assigned in this namespace: {term}")
                if existing is None:
                    session.add(
                        MemoryTriggerRow(
                            id=_new_id("trg"),
                            namespace_id=namespace_id,
                            node_id=node_row.id,
                            term=term.strip(),
                            normalized_term=normalized,
                            created_at=_utc_now(),
                        )
                    )
            for term in remove:
                normalized = _normalize_term(term)
                rows = session.exec(
                    select(MemoryTriggerRow).where(
                        MemoryTriggerRow.namespace_id == namespace_id,
                        MemoryTriggerRow.node_id == node_row.id,
                        MemoryTriggerRow.normalized_term == normalized,
                    )
                ).all()
                for row in rows:
                    session.delete(row)
            session.flush()
            node = self._row_to_node(node_row)
            self._upsert_search_document(session, node)
            self._record_version(
                session,
                node,
                operation="trigger_update",
                change={"add": add, "remove": remove},
            )
            session.commit()
            return self._trigger_terms(session, node_row.id)

    def search_documents(
        self,
        namespace_slug: str,
        *,
        node_types: list[str] | None = None,
        include_folders: bool = False,
    ) -> list[dict[str, Any]]:
        """获取符合命名空间和筛选条件的搜索文档。"""
        with self.database.session_factory() as session:
            namespace = self._require_namespace_row(session, namespace_slug)
            rows = session.exec(
                select(
                    MemorySearchDocumentRow.node_id,
                    MemorySearchDocumentRow.uri,
                    MemorySearchDocumentRow.title,
                    MemorySearchDocumentRow.kind,
                    MemorySearchDocumentRow.node_type,
                    MemorySearchDocumentRow.search_text,
                    MemoryNodeRow.parent_id,
                )
                .join(MemoryNodeRow, MemoryNodeRow.id == MemorySearchDocumentRow.node_id)
                .where(
                    MemorySearchDocumentRow.namespace_id == namespace.id,
                    MemoryNodeRow.deleted_at.is_(None),
                )
                .order_by(MemorySearchDocumentRow.title)
            ).all()
            filter_terms = {
                str(value).strip().lower()
                for value in (node_types or [])
                if str(value).strip()
            }
            filtered: list[dict[str, Any]] = []
            for node_id, uri, title, kind, node_type, search_text, parent_id in rows:
                if not include_folders and kind == "folder":
                    continue
                normalized_kind = kind.strip().lower()
                normalized_node_type = node_type.strip().lower() if node_type else None
                if (
                    filter_terms
                    and normalized_kind not in filter_terms
                    and normalized_node_type not in filter_terms
                ):
                    continue
                filtered.append(
                    {
                        "node_id": node_id,
                        "uri": uri,
                        "title": title,
                        "kind": kind,
                        "node_type": node_type,
                        "search_text": search_text,
                        "parent_uri": self._parent_uri_by_id(parent_id, session=session),
                        "triggers": self._trigger_terms(session, node_id),
                    }
                )
            return filtered

    def touch_node(self, namespace_slug: str, uri: str) -> None:
        """更新指定节点的最近访问时间。"""
        with self.database.session_factory() as session:
            row = self._require_node_row(session, namespace_slug, uri)
            row.last_accessed_at = _utc_now()
            session.add(row)
            session.commit()

    def _get_namespace_row_by_slug(self, session: Session, slug: str) -> MemoryNamespaceRow | None:
        """在已有数据库会话中按 slug 查询命名空间记录。"""
        return session.exec(
            select(MemoryNamespaceRow).where(MemoryNamespaceRow.slug == slug)
        ).first()

    def _require_namespace_row(self, session: Session, slug: str) -> MemoryNamespaceRow:
        """取得命名空间记录，找不到时抛出错误。"""
        namespace = self._get_namespace_row_by_slug(session, slug)
        if namespace is None:
            raise ValueError(f"Unknown namespace: {slug}")
        return namespace

    def _require_parent(
        self,
        session: Session,
        namespace_id: str,
        parent_uri: str | None,
    ) -> MemoryNodeRow | None:
        """校验指定父 URI 并取得对应节点，允许根节点没有父级。"""
        if parent_uri is None:
            return None
        row = session.exec(
            select(MemoryNodeRow).where(
                MemoryNodeRow.namespace_id == namespace_id,
                MemoryNodeRow.uri == parent_uri,
                MemoryNodeRow.deleted_at.is_(None),
            )
        ).first()
        if row is None:
            raise ValueError(f"Unknown parent URI: {parent_uri}")
        return row

    def _find_node_row(
        self,
        session: Session,
        namespace_slug: str,
        uri: str,
    ) -> MemoryNodeRow | None:
        """在指定命名空间中查询 URI 对应的节点记录。"""
        namespace = self._require_namespace_row(session, namespace_slug)
        return session.exec(
            select(MemoryNodeRow).where(
                MemoryNodeRow.namespace_id == namespace.id,
                MemoryNodeRow.uri == uri,
                MemoryNodeRow.deleted_at.is_(None),
            )
        ).first()

    def _require_node_row(self, session: Session, namespace_slug: str, uri: str) -> MemoryNodeRow:
        """取得指定 URI 的节点记录，找不到时抛出错误。"""
        row = self._find_node_row(session, namespace_slug, uri)
        if row is None:
            raise ValueError(f"Unknown memory URI: {uri}")
        return row

    def _ensure_uri_available(
        self,
        session: Session,
        namespace_id: str,
        uri: str,
        exclude_node_id: str | None = None,
    ) -> None:
        """检查候选 URI 是否能在该命名空间内使用。"""
        row = session.exec(
            select(MemoryNodeRow.id).where(
                MemoryNodeRow.namespace_id == namespace_id,
                MemoryNodeRow.uri == uri,
                MemoryNodeRow.deleted_at.is_(None),
            )
        ).first()
        if row is None:
            return
        if exclude_node_id is not None and row == exclude_node_id:
            return
        raise ValueError(f"Memory URI already exists: {uri}")

    def _compose_uri(self, parent_uri: str | None, slug: str) -> str:
        """根据父级 URI 和规范化标识拼出节点 URI。"""
        slug = slug.strip().strip("/")
        if not slug:
            raise ValueError("slug must be non-empty")
        if not parent_uri:
            return f"memory://{slug}"
        return f"{parent_uri.rstrip('/')}/{slug}"

    def _parent_uri_by_id(self, parent_id: str | None, *, session: Session | None = None) -> str | None:
        """按父节点 ID 查询其 URI。"""
        if not parent_id:
            return None
        if session is not None:
            return session.exec(
                select(MemoryNodeRow.uri).where(MemoryNodeRow.id == parent_id)
            ).first()
        with self.database.session_factory() as local_session:
            return local_session.exec(
                select(MemoryNodeRow.uri).where(MemoryNodeRow.id == parent_id)
            ).first()

    def _update_descendant_uris(
        self,
        session: Session,
        namespace_id: str,
        node_id: str,
        old_uri: str,
        new_uri: str,
    ) -> None:
        """节点路径变化后，同步更新后代节点的 URI。"""
        rows = session.exec(
            select(MemoryNodeRow)
            .where(
                MemoryNodeRow.namespace_id == namespace_id,
                MemoryNodeRow.id != node_id,
                MemoryNodeRow.deleted_at.is_(None),
                MemoryNodeRow.uri.like(f"{old_uri}/%"),
            )
            .order_by(func.length(MemoryNodeRow.uri))
        ).all()
        now = _utc_now()
        for row in rows:
            row.uri = row.uri.replace(old_uri, new_uri, 1)
            row.updated_at = now
            session.add(row)
            self._upsert_search_document(session, self._row_to_node(row))

    def _record_version(
        self,
        session: Session,
        node: MemoryNode,
        *,
        operation: str,
        change: dict[str, Any],
    ) -> None:
        """为当前节点状态写入一个新的历史版本。"""
        total = session.exec(
            select(func.count()).select_from(MemoryNodeVersionRow).where(MemoryNodeVersionRow.node_id == node.id)
        ).one()
        version_no = int(total) + 1
        session.add(
            MemoryNodeVersionRow(
                id=_new_id("ver"),
                node_id=node.id,
                version_no=version_no,
                operation=operation,
                snapshot_title=node.title,
                snapshot_parent_id=node.parent_id,
                snapshot_uri=node.uri,
                snapshot_kind=node.kind,
                snapshot_node_type=node.node_type,
                snapshot_content=node.content,
                snapshot_is_core=node.is_core,
                snapshot_priority=node.priority,
                snapshot_triggers_json=json.dumps(self._trigger_terms(session, node.id), ensure_ascii=False),
                change_json=json.dumps(change, ensure_ascii=False, sort_keys=True),
                created_at=_utc_now(),
            )
        )

    def _delete_search_document(self, session: Session, node_id: str) -> None:
        """删除指定节点已有的搜索文档。"""
        existing = session.exec(
            select(MemorySearchDocumentRow).where(MemorySearchDocumentRow.node_id == node_id)
        ).first()
        if existing is not None:
            session.delete(existing)

    def _upsert_search_document(self, session: Session, node: MemoryNode) -> None:
        """生成或更新包含节点和触发词的搜索文档。"""
        triggers = self._trigger_terms(session, node.id)
        search_text = " ".join(
            part for part in (node.uri, node.title, node.node_type or "", node.content, " ".join(triggers)) if part
        )
        existing = session.exec(
            select(MemorySearchDocumentRow).where(MemorySearchDocumentRow.node_id == node.id)
        ).first()
        if existing is None:
            session.add(
                MemorySearchDocumentRow(
                    id=_new_id("doc"),
                    namespace_id=node.namespace_id,
                    node_id=node.id,
                    uri=node.uri,
                    title=node.title,
                    kind=node.kind,
                    node_type=node.node_type,
                    search_text=search_text,
                    updated_at=_utc_now(),
                )
            )
            return
        existing.uri = node.uri
        existing.title = node.title
        existing.kind = node.kind
        existing.node_type = node.node_type
        existing.search_text = search_text
        existing.updated_at = _utc_now()
        session.add(existing)

    def _trigger_terms(self, session: Session, node_id: str) -> list[str]:
        """读取与节点关联的触发词文本。"""
        return session.exec(
            select(MemoryTriggerRow.term)
            .where(MemoryTriggerRow.node_id == node_id)
            .order_by(MemoryTriggerRow.term)
        ).all()

    def _row_to_namespace(self, row: MemoryNamespaceRow) -> MemoryNamespace:
        """把数据库中的命名空间记录转换为领域对象。"""
        return MemoryNamespace(
            id=row.id,
            slug=row.slug,
            title=row.title,
            description=row.description,
        )

    def _row_to_node(self, row: MemoryNodeRow) -> MemoryNode:
        """把数据库中的记忆节点记录转换为领域对象。"""
        return MemoryNode(
            id=row.id,
            namespace_id=row.namespace_id,
            parent_id=row.parent_id,
            slug=row.slug,
            uri=row.uri,
            title=row.title,
            kind=row.kind,
            node_type=row.node_type,
            content=row.content,
            is_core=bool(row.is_core),
            priority=int(row.priority),
        )
