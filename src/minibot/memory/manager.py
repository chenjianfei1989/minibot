"""管理项目级持久化记忆的管理器。"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..config.schema import MemoryConfig
from .render import render_markdown_links
from .repository import MemoryNodeBundle, MemoryRepository
from .search import SearchResult, rank_search_results


class MemoryManager:
    """管理长期记忆和每日记忆文件。"""

    def __init__(self, config: MemoryConfig, app_home: Path, project_root: Path):
        """初始化记忆路径、数据仓库和旧版记忆迁移状态。"""
        self.config = config
        self.app_home = app_home.resolve()
        self.project_root = project_root.resolve()
        self.memory_dir = self._resolve_memory_dir(config.memory_dir)
        self.long_term_file = self.memory_dir / "LONG_TERM.md"
        self.daily_dir = self.memory_dir / "daily"
        self.state_dir = self.app_home / "state"
        self.repository = MemoryRepository.from_config(config, app_home=self.app_home)
        self._migration_notice: str | None = None
        self._ensure_dirs()
        self._migrate_legacy_project_memory_once()

    def _resolve_memory_dir(self, configured_path: str) -> Path:
        """按配置解析记忆目录，处理相对路径和用户主目录。"""
        path = Path(configured_path).expanduser()
        if path.is_absolute():
            return path.resolve()
        return (self.app_home / path).resolve()

    def _ensure_dirs(self) -> None:
        """确保记忆目录存在。"""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _migration_state_path(self) -> Path:
        """返回用于记录项目迁移进度的状态文件路径。"""
        return self.state_dir / "migration_v1.json"

    def _read_migration_state(self) -> dict:
        """从磁盘读取已保存的旧版迁移状态。"""
        path = self._migration_state_path()
        if not path.exists():
            return {"migrated_projects": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"migrated_projects": []}
            migrated = data.get("migrated_projects")
            if not isinstance(migrated, list):
                return {"migrated_projects": []}
            return {"migrated_projects": [str(item) for item in migrated]}
        except Exception:
            return {"migrated_projects": []}

    def _write_migration_state(self, state: dict) -> None:
        """以 UTF-8 保存迁移状态。"""
        self._migration_state_path().write_text(
            json.dumps(state, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _legacy_memory_dir(self) -> Path:
        """返回旧版项目级记忆目录的位置。"""
        return self.project_root / ".minibot" / "memory"

    def _project_migration_key(self) -> str:
        """用当前项目的路径生成迁移记录键。"""
        return str(self.project_root)

    def _split_blocks(self, text: str) -> list[str]:
        """把记忆文本拆成可单独合并的文本块。"""
        text = text.strip()
        if not text:
            return []
        return [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]

    def _merge_block_text(self, existing: str, incoming: str) -> str:
        """将两个来源的记忆文本按块去重并合并。"""
        blocks: list[str] = []
        seen: set[str] = set()
        for text in (existing, incoming):
            for block in self._split_blocks(text):
                if block in seen:
                    continue
                seen.add(block)
                blocks.append(block)
        if not blocks:
            return ""
        return "\n\n".join(blocks) + "\n"

    def _merge_file(self, source: Path, target: Path) -> None:
        """读取源记忆文件并把内容合并到目标文件。"""
        incoming = source.read_text(encoding="utf-8")
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        merged = self._merge_block_text(existing, incoming)
        if merged:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(merged, encoding="utf-8")

    def _migrate_legacy_project_memory_once(self) -> None:
        """将旧版项目记忆合并到当前存储，并记录该项目的迁移结果。"""
        legacy_dir = self._legacy_memory_dir()
        if not legacy_dir.exists():
            return
        if legacy_dir.resolve() == self.memory_dir:
            return

        state = self._read_migration_state()
        key = self._project_migration_key()
        migrated_projects = set(state.get("migrated_projects", []))
        if key in migrated_projects:
            return

        try:
            legacy_long_term = legacy_dir / "LONG_TERM.md"
            if legacy_long_term.exists():
                self._merge_file(legacy_long_term, self.long_term_file)

            legacy_daily_dir = legacy_dir / "daily"
            if legacy_daily_dir.exists():
                for daily_file in sorted(legacy_daily_dir.glob("*.md")):
                    self._merge_file(daily_file, self.daily_dir / daily_file.name)

            migrated_projects.add(key)
            self._write_migration_state({"migrated_projects": sorted(migrated_projects)})
        except Exception as exc:
            self._migration_notice = (
                f"legacy memory migration failed for {legacy_dir}: {exc}"
            )

    def migration_notice(self) -> str | None:
        """返回当前实例生成的迁移提示。"""
        return self._migration_notice

    def _resolve_active_namespace(self) -> str | None:
        """返回当前命名空间，或在首次访问时选择已有的第一个。"""
        if not self.config.active_namespace:
            namespaces = self.repository.list_namespaces()
            if namespaces:
                self.config.active_namespace = namespaces[0].slug
        return self.config.active_namespace or None

    def _active_namespace(self) -> str:
        """确定当前读写应使用的记忆命名空间。"""
        namespace = self._resolve_active_namespace()
        if namespace is None:
            raise ValueError("No memory namespace is active.")
        return namespace

    @staticmethod
    def _slugify(value: str) -> str:
        """将输入文本规范化为可用的标识片段。"""
        value = value.strip().lower()
        value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value)
        return value.strip("-") or "node"

    def create_namespace(self, slug: str, title: str, description: str | None = None):
        """创建结构化记忆的命名空间。"""
        namespace = self.repository.create_namespace(slug=slug, title=title, description=description)
        if not self.config.active_namespace:
            self.config.active_namespace = slug
        return namespace

    def list_namespaces(self):
        """列出已创建的记忆命名空间。"""
        return self.repository.list_namespaces()

    def create_memory(
        self,
        *,
        parent_uri: str | None,
        title: str,
        kind: str,
        slug: str | None = None,
        node_type: str | None = None,
        content: str = "",
        is_core: bool = False,
        priority: int = 0,
    ):
        """在当前命名空间建立记忆节点。"""
        return self.repository.create_node(
            self._active_namespace(),
            parent_uri=parent_uri,
            slug=slug or self._slugify(title),
            title=title,
            kind=kind,
            node_type=node_type,
            content=content,
            is_core=is_core,
            priority=priority,
        )

    def update_memory(self, uri: str, **fields):
        """按 URI 更新当前命名空间中记忆节点的字段。"""
        return self.repository.update_node(self._active_namespace(), uri, **fields)

    def edit_memory(self, uri: str, *, operation: str, old_text: str | None = None, new_text: str | None = None, text: str | None = None):
        """读取节点内容并应用指定的文本编辑。"""
        node = self.repository.get_node_by_uri(self._active_namespace(), uri)
        if node is None:
            raise ValueError(f"Unknown memory URI: {uri}")
        if operation == "replace_text":
            if not old_text:
                raise ValueError("old_text is required for replace_text")
            replacement = new_text or ""
            content = node.content.replace(old_text, replacement)
            return self.update_memory(uri, content=content)
        if operation == "append_text":
            content = node.content + (text or "")
            return self.update_memory(uri, content=content)
        raise ValueError(f"Unsupported edit operation: {operation}")

    def delete_memory(self, uri: str) -> None:
        """按 URI 删除当前命名空间的节点。"""
        self.repository.delete_node(self._active_namespace(), uri)

    def delete_memories(self, uris: list[str]) -> dict[str, object]:
        """在当前命名空间批量删除指定节点。"""
        namespace_slug = self._active_namespace()
        deleted: list[str] = []
        pending: list[str] = []
        for uri in uris:
            normalized = str(uri or "").strip()
            if not normalized:
                continue
            if self.repository.get_node_by_uri(namespace_slug, normalized) is None:
                raise ValueError(f"Unknown memory URI: {normalized}")
            pending.append(normalized)
        for normalized in pending:
            self.repository.delete_node(namespace_slug, normalized)
            deleted.append(normalized)
        return {
            "deleted": bool(deleted),
            "deleted_count": len(deleted),
            "deleted_uris": deleted,
        }

    def manage_triggers(
        self,
        uri: str,
        *,
        add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> dict[str, object]:
        """更新指定记忆的触发词，并返回当前触发词。"""
        current = self.repository.update_triggers(
            self._active_namespace(),
            uri,
            add=add,
            remove=remove,
        )
        return {
            "uri": uri,
            "added": list(add or []),
            "removed": list(remove or []),
            "current_triggers": current,
        }

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        node_types: list[str] | None = None,
        include_folders: bool = False,
    ) -> list[SearchResult]:
        """查询当前记忆范围内的搜索文档，再按匹配程度排序。"""
        documents = self.repository.search_documents(
            self._active_namespace(),
            node_types=node_types,
            include_folders=include_folders,
        )
        return rank_search_results(query, documents)[:limit]

    def read(self, uri: str) -> str:
        """按 URI 读取普通记忆节点或系统视图。"""
        if uri == "system://boot":
            namespace = self._resolve_active_namespace()
            if namespace is None:
                return "# system://boot\nNo memory namespace is active. Continue without structured memory."
            return self._read_boot(namespace)
        namespace_slug = self._active_namespace()
        if uri == "system://index":
            return self._read_index(namespace_slug)
        if uri == "system://glossary":
            return self._read_glossary(namespace_slug)
        bundle = self.repository.get_node_bundle(namespace_slug, uri)
        if bundle is None:
            raise ValueError(f"URI not found in current namespace: {uri}")
        self.repository.touch_node(namespace_slug, uri)
        return self._render_node_bundle(namespace_slug, bundle)

    def node_detail(self, uri: str) -> dict[str, Any]:
        """按 URI 返回节点详情及相关结构化数据。"""
        namespace_slug = self._active_namespace()
        bundle = self.repository.get_node_bundle(namespace_slug, uri)
        if bundle is None:
            raise ValueError(f"Unknown memory URI: {uri}")
        self.repository.touch_node(namespace_slug, uri)
        node = bundle.node
        return {
            "id": node.id,
            "uri": node.uri,
            "title": node.title,
            "kind": node.kind,
            "node_type": node.node_type,
            "parent_uri": bundle.parent_uri,
            "is_core": node.is_core,
            "priority": node.priority,
            "content": node.content,
            "triggers": bundle.triggers,
            "children": [
                {"uri": child.uri, "title": child.title, "kind": child.kind, "node_type": child.node_type}
                for child in bundle.children
            ],
        }

    def _node_hierarchy_snapshot(self, namespace_slug: str) -> tuple[dict[str | None, list[Any]], dict[str, int]]:
        """读取指定命名空间的节点并构造层级快照。"""
        nodes = self.repository.list_nodes(namespace_slug)
        nodes_by_id = {node.id: node for node in nodes}
        nodes_by_parent: dict[str | None, list[Any]] = {}
        child_counts: dict[str, int] = {node.uri: 0 for node in nodes}
        for node in nodes:
            nodes_by_parent.setdefault(node.parent_id, []).append(node)
        for node in nodes:
            if node.parent_id and node.parent_id in nodes_by_id:
                parent = nodes_by_id[node.parent_id]
                child_counts[parent.uri] = child_counts.get(parent.uri, 0) + 1
        return nodes_by_parent, child_counts

    def _read_boot(self, namespace_slug: str) -> str:
        """为指定命名空间生成启动时使用的记忆视图。"""
        namespace = self.repository.get_namespace_by_slug(namespace_slug)
        if namespace is None:
            raise ValueError(f"Unknown namespace: {namespace_slug}")
        nodes_by_parent, child_counts = self._node_hierarchy_snapshot(namespace_slug)
        root_nodes = nodes_by_parent.get(None, [])
        core_nodes = [node for nodes in nodes_by_parent.values() for node in nodes if node.is_core]
        recent_nodes = self.repository.list_recent_nodes(namespace_slug, limit=5)
        lines = [
            "# system://boot",
            f"Namespace: {namespace.slug}",
            f"Title: {namespace.title}",
            "",
            "Core memories:",
        ]
        if core_nodes:
            for node in core_nodes:
                lines.append(f"- `{node.uri}` [{node.kind}] {node.title}")
        else:
            lines.append("- (none)")
        lines.extend(["", "Root summary:"])
        if root_nodes:
            for node in root_nodes:
                node_type = f" node_type: {node.node_type}" if node.node_type else ""
                lines.append(f"- `{node.uri}` [{node.kind}]{node_type} children: {child_counts.get(node.uri, 0)}")
        else:
            lines.append("- (empty)")
        lines.extend(["", "Recently active:"])
        if recent_nodes:
            for node in recent_nodes:
                lines.append(f"- `{node.uri}` [{node.kind}] {node.title}")
        else:
            lines.append("- (none)")
        return "\n".join(lines)

    def _read_index(self, namespace_slug: str) -> str:
        """将指定命名空间的记忆树渲染成目录索引。"""
        lines = ["# system://index", ""]
        nodes_by_parent, child_counts = self._node_hierarchy_snapshot(namespace_slug)

        def visit(parent_id: str | None, depth: int) -> None:
            """递归渲染当前父节点下的记忆及其子节点。"""
            for node in nodes_by_parent.get(parent_id, []):
                indent = "  " * depth
                node_type = f" node_type: {node.node_type}" if node.node_type else ""
                lines.append(
                    f"{indent}- `{node.uri}` [{node.kind}]{node_type} children: {child_counts.get(node.uri, 0)}"
                )
                visit(node.id, depth + 1)

        visit(None, 0)
        return "\n".join(lines)

    def _read_glossary(self, namespace_slug: str) -> str:
        """生成包含触发词和关联节点的术语表。"""
        entries = self.repository.glossary_entries(namespace_slug)
        lines = ["# system://glossary", ""]
        if not entries:
            lines.append("(empty)")
            return "\n".join(lines)
        for entry in entries:
            lines.append(f"- {entry['term']} -> {entry['uri']}")
        return "\n".join(lines)

    def _render_node_bundle(self, namespace_slug: str, bundle: MemoryNodeBundle) -> str:
        """把节点正文及其关联信息组织为可读文本。"""
        node = bundle.node
        child_lines = [f"- `{child.uri}` [{child.kind}] {child.title}" for child in bundle.children]
        lines = [
            f"URI: {node.uri}",
            f"Title: {node.title}",
            f"Kind: {node.kind}",
            f"Node Type: {node.node_type or '-'}",
            f"Parent URI: {bundle.parent_uri or '-'}",
            f"Children: {len(bundle.children)}",
            f"Is Core: {node.is_core}",
            f"Priority: {node.priority}",
            f"Triggers: {', '.join(bundle.triggers) if bundle.triggers else '-'}",
            "",
        ]
        if node.kind == "folder":
            lines.append(node.content or "(No description)")
        else:
            glossary = [
                {"term": entry["term"], "uri": entry["uri"]}
                for entry in self.repository.glossary_entries(namespace_slug)
                if entry["uri"] != node.uri
            ]
            lines.append(render_markdown_links(node.content, glossary) or "(Empty content)")
        lines.extend(["", "Children:"])
        if child_lines:
            lines.extend(child_lines)
        else:
            lines.append("- (none)")
        return "\n".join(lines)

    def _today_str(self) -> str:
        """按本地日期生成当天使用的文件名日期部分。"""
        return datetime.now().strftime("%Y-%m-%d")

    _DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    def _validate_date(self, date: str) -> str:
        """校验每日记忆日期的格式及日历有效性。"""
        if not self._DATE_RE.match(date):
            raise ValueError("expected YYYY-MM-DD")
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("invalid date value") from exc
        return date

    def _daily_path(self, date: str | None = None) -> Path:
        """返回指定日期的每日记忆路径，省略日期时使用当天。"""
        date = date or self._today_str()
        date = self._validate_date(date)
        return self.daily_dir / f"{date}.md"

    # --- 长期记忆 ---

    def read_long_term(self) -> str:
        """读取长期记忆，最多保留 max_lines 行。"""
        if not self.long_term_file.exists():
            return ""
        lines = self.long_term_file.read_text(encoding="utf-8").splitlines()
        if len(lines) > self.config.long_term_max_lines:
            lines = lines[: self.config.long_term_max_lines]
            lines.append(f"\n... (truncated at {self.config.long_term_max_lines} lines)")
        return "\n".join(lines)

    def write_long_term(self, content: str) -> str:
        """覆盖长期记忆。"""
        self.long_term_file.write_text(content, encoding="utf-8")
        return f"Long-term memory updated ({len(content)} chars)."

    def append_long_term(self, content: str) -> str:
        """向长期记忆追加内容。"""
        existing = (
            self.long_term_file.read_text(encoding="utf-8")
            if self.long_term_file.exists()
            else ""
        )
        separator = "\n" if existing and not existing.endswith("\n") else ""
        self.long_term_file.write_text(existing + separator + content, encoding="utf-8")
        return f"Appended to long-term memory ({len(content)} chars)."

    def _replace_text(self, existing: str, old: str, new: str) -> tuple[str, int]:
        """检查原文本的出现次数，再按参数执行替换。"""
        total = existing.count(old)
        if total == 0:
            return existing, 0
        return existing.replace(old, new), total

    def replace_long_term(self, old: str, new: str) -> str:
        """替换长期记忆中的文本。"""
        if not self.long_term_file.exists():
            return "Long-term memory is empty; no replacements."
        existing = self.long_term_file.read_text(encoding="utf-8")
        updated, replaced = self._replace_text(existing, old, new)
        if replaced == 0:
            return "No matches in long-term memory."
        self.long_term_file.write_text(updated, encoding="utf-8")
        return f"Replaced {replaced} occurrence(s) in long-term memory."

    # --- 每日记忆 ---

    def read_daily(self, date: str | None = None) -> str:
        """读取指定日期的每日记忆，默认读取当天。"""
        path = self._daily_path(date)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def write_daily(self, content: str, date: str | None = None) -> str:
        """覆盖指定日期的每日记忆，默认覆盖当天。"""
        path = self._daily_path(date)
        path.write_text(content, encoding="utf-8")
        date_label = date or self._today_str()
        return f"Daily memory for {date_label} updated ({len(content)} chars)."

    def append_daily(self, content: str, date: str | None = None) -> str:
        """向每日记忆追加内容。"""
        path = self._daily_path(date)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        separator = "\n" if existing and not existing.endswith("\n") else ""
        path.write_text(existing + separator + content, encoding="utf-8")
        date_label = date or self._today_str()
        return f"Appended to daily memory for {date_label}."

    def replace_daily(
        self,
        old: str,
        new: str,
        date: str | None = None,
    ) -> str:
        """替换每日记忆中的文本。"""
        path = self._daily_path(date)
        if not path.exists():
            date_label = date or self._today_str()
            return f"Daily memory for {date_label} is empty; no replacements."
        existing = path.read_text(encoding="utf-8")
        updated, replaced = self._replace_text(existing, old, new)
        if replaced == 0:
            return "No matches in daily memory."
        path.write_text(updated, encoding="utf-8")
        date_label = date or self._today_str()
        return f"Replaced {replaced} occurrence(s) in daily memory for {date_label}."

    # --- 系统提示词的上下文 ---

    def get_context_for_prompt(self) -> str:
        """生成注入系统提示词的记忆上下文。"""
        sections: list[str] = []

        # 长期记忆。
        long_term = self.read_long_term()
        if long_term:
            sections.append(f"### Long-term Memory\n{long_term}")

        # 当天的每日记忆。
        today = self._today_str()
        today_content = self.read_daily(today)
        if today_content:
            sections.append(f"### Daily Memory ({today})\n{today_content}")

        # 回溯范围内的近期每日记忆。
        for i in range(1, self.config.daily_lookback_days + 1):
            past_date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            past_content = self.read_daily(past_date)
            if past_content:
                sections.append(f"### Daily Memory ({past_date})\n{past_content}")

        return "\n\n".join(sections)

    def list_daily_files(self) -> list[str]:
        """按日期降序列出所有每日记忆文件的日期。"""
        files = sorted(self.daily_dir.glob("*.md"), reverse=True)
        return [f.stem for f in files]
