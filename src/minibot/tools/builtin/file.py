"""文件操作工具。"""

import json
from pathlib import Path
from typing import Any

from ..base import ResultTool
from ..result import ToolOutcome
from ...core.artifacts import current_artifacts
from ...file_checkpoints import GitFileCheckpoints
from ...teams.context import get_team_execution_context
from .workspace_backend import LocalBackend, WorkspaceBackend, WorkspacePath
from .workspace_files import FileOutputLimit


class WorkspaceFileTool(ResultTool):
    def __init__(
        self, workdir: Path, *, checkpoints: GitFileCheckpoints | None = None, backend: WorkspaceBackend | None = None,
    ):
        """初始化文件工具使用的工作目录和后端。"""
        self.workdir = workdir
        self.backend = backend if backend is not None else LocalBackend(workdir, checkpoints=checkpoints)

    def permission_target(self, path: str) -> WorkspacePath:
        """为权限检查取得后端解析后的操作目标。"""
        return self.backend.target(path)

    async def _file_lock_conflict(self, path: str, target: WorkspacePath) -> ToolOutcome | None:
        """检查目标文件是否与团队成员持有的锁冲突。"""
        team_ctx = get_team_execution_context()
        if team_ctx is None or team_ctx.role != "teammate" or team_ctx.runtime is None or not team_ctx.member_id:
            return None
        if target.host_path is None:
            return ToolOutcome("Error: Team file locks require a trusted local workspace", "refused")
        ok, owner = await team_ctx.runtime.acquire_file_lock(member_id=team_ctx.member_id, path=str(target.host_path))
        if not ok:
            return ToolOutcome(f"Error: File lock conflict for '{path}'. Current owner: {owner}", "refused")
        return None


class ReadFileTool(WorkspaceFileTool):
    """读取文件内容。"""

    name = "read_file"
    description = "Read file contents."

    @property
    def input_schema(self) -> dict[str, Any]:
        """声明要读取的文件路径及可选的行数限制。"""
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read",
                },
            },
            "required": ["path"],
        }

    async def execute_result(self, path: str, limit: int | None = None) -> ToolOutcome:
        """读取一个文件。"""
        scope = current_artifacts.get()
        try:
            text = await self.backend.read_file(path, limit=limit, max_bytes=scope.capture_bytes if scope else None)
            if scope is not None and len(text) <= scope.threshold_chars:
                text = "\n".join(text.splitlines())
            return ToolOutcome(text[:50000] if scope is None else text, "success")
        except FileOutputLimit as exc:
            if scope is None:
                return ToolOutcome(f"Error: {exc}", "error", artifact_eligible=False)
            detail = f"File output exceeds the {scope.store.max_bytes}-byte artifact limit."
            return ToolOutcome(scope.failure(detail), "error", artifact_eligible=False)
        except TimeoutError:
            return ToolOutcome("Error: File read timed out", "timeout")
        except Exception as exc:
            return ToolOutcome(f"Error: {exc}", "error")


class WriteFileTool(WorkspaceFileTool):
    """将内容写入文件。"""

    name = "write_file"
    description = "Write to file."

    @property
    def input_schema(self) -> dict[str, Any]:
        """声明写入所需的目标路径与文本内容。"""
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write",
                },
            },
            "required": ["path", "content"],
        }

    async def execute_result(self, path: str, content: str) -> ToolOutcome:
        """将内容写入一个文件。"""
        try:
            target = self.backend.target(path)
            conflict = await self._file_lock_conflict(path, target)
            if conflict is not None:
                return conflict
            await self.backend.write_file(target, content)
            return ToolOutcome(f"Wrote {len(content)} bytes to {path}", "success")
        except TimeoutError:
            return ToolOutcome("Error: File write timed out", "timeout")
        except Exception as exc:
            return ToolOutcome(f"Error: {exc}", "error")


class EditFileTool(WorkspaceFileTool):
    """替换文件中的文本。"""

    name = "edit_file"
    description = "Replace text in file."

    @property
    def input_schema(self) -> dict[str, Any]:
        """声明编辑所需的路径、原文本与替换文本。"""
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to edit",
                },
                "old_text": {
                    "type": "string",
                    "description": "Text to find and replace",
                },
                "new_text": {
                    "type": "string",
                    "description": "Replacement text",
                },
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute_result(self, path: str, old_text: str, new_text: str) -> ToolOutcome:
        """替换一个文件中的文本。"""
        try:
            target = self.backend.target(path)
            conflict = await self._file_lock_conflict(path, target)
            if conflict is not None:
                return conflict
            if not await self.backend.edit_file(target, old_text, new_text):
                return ToolOutcome(f"Error: Text not found in {path}", "error")
            return ToolOutcome(f"Edited {path}", "success")
        except TimeoutError:
            return ToolOutcome("Error: File edit timed out", "timeout")
        except Exception as exc:
            return ToolOutcome(f"Error: {exc}", "error")


class ListDirTool(WorkspaceFileTool):
    """列出指定工作区目录的直接条目。"""

    name = "list_dir"
    description = "List the names in a directory. Use '.' for the workspace root."

    @property
    def input_schema(self) -> dict[str, Any]:
        """声明列举目录所需的工作区路径。"""
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Path to the directory to list"}},
            "required": ["path"],
        }

    async def execute_result(self, path: str) -> ToolOutcome:
        """调用工作区后端列出目录条目，并将结果转换成工具输出。"""
        try:
            names = await self.backend.list_dir(path)
            return ToolOutcome(json.dumps(names, ensure_ascii=True), "success")
        except TimeoutError:
            return ToolOutcome("Error: Directory listing timed out", "timeout")
        except Exception as exc:
            return ToolOutcome(f"Error: {exc}", "error")
