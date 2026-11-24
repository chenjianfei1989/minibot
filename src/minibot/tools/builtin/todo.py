"""待办事项管理工具。"""

from datetime import datetime, UTC
from typing import Any

from ..base import ResultTool
from ..result import ToolOutcome


class TodoManager:
    """带约束的任务列表管理器。"""

    def __init__(self):
        """初始化空的待办列表。"""
        self.items: list[dict] = []
        self.completed_at: str | None = None

    def update(self, items: list[dict]) -> str:
        """更新待办事项列表。"""
        validated = []
        in_progress = 0

        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            active = str(item.get("activeForm", "")).strip()

            if not content or not active:
                raise ValueError(f"Item {i}: content and activeForm required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {i}: invalid status")
            if status == "in_progress":
                in_progress += 1

            validated.append({
                "content": content,
                "status": status,
                "activeForm": active,
            })

        if in_progress > 1:
            raise ValueError("Only one task can be in_progress")

        self.items = validated[:20]
        if self.items and all(item["status"] == "completed" for item in self.items):
            self.completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        else:
            self.completed_at = None
        return self.render()

    def render(self) -> str:
        """将待办事项列表渲染为文本。"""
        if not self.items:
            return "No todos."

        lines = []
        for t in self.items:
            if t["status"] == "completed":
                mark = "[x]"
            elif t["status"] == "in_progress":
                mark = "[>]"
            else:
                mark = "[ ]"
            lines.append(f"{mark} {t['content']}")

        done = sum(1 for t in self.items if t["status"] == "completed")
        return "\n".join(lines) + f"\n({done}/{len(self.items)} done)"

    def get_active_task(self) -> dict | None:
        """获取当前正在进行的任务。"""
        for item in self.items:
            if item["status"] == "in_progress":
                return item
        return None

    def snapshot(self) -> dict[str, Any]:
        """返回可用于界面实时渲染的结构化快照。"""
        status_map = {
            "pending": "pending",
            "in_progress": "active",
            "completed": "done",
        }
        items = []
        for index, item in enumerate(self.items, start=1):
            entry = {
                "id": f"todo-{index}",
                "label": item["content"],
                "status": status_map[item["status"]],
            }
            detail = item.get("activeForm")
            if detail:
                entry["detail"] = str(detail)
            items.append(entry)

        completed = sum(1 for item in self.items if item["status"] == "completed")
        return {
            "title": "Current plan",
            "items": items,
            "completed": completed,
            "total": len(self.items),
            "visible": bool(self.items),
            "completed_at": self.completed_at,
        }


class TodoWriteTool(ResultTool):
    """更新任务列表。"""

    name = "TodoWrite"
    description = "Update task list."

    def __init__(self, todo_manager: TodoManager):
        """绑定工具要操作的待办列表管理器。"""
        self.todo_manager = todo_manager

    @property
    def input_schema(self) -> dict[str, Any]:
        """声明待办条目的内容、状态及活跃任务描述等输入字段。"""
        return {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                            },
                            "activeForm": {"type": "string"},
                        },
                        "required": ["content", "status", "activeForm"],
                    },
                }
            },
            "required": ["items"],
        }

    async def execute_result(self, items: list[dict]) -> ToolOutcome:
        """更新待办事项列表。"""
        try:
            return ToolOutcome(self.todo_manager.update(items), "success")
        except Exception as e:
            return ToolOutcome(f"Error: {e}", "error")
