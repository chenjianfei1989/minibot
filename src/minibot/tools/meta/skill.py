"""用于加载领域知识的 Skill 工具。"""

from typing import Any, TYPE_CHECKING

from ..base import ResultTool
from ..result import ToolOutcome

if TYPE_CHECKING:
    from ...skills.loader import SkillLoader


class SkillTool(ResultTool):
    """加载技能，获取执行任务所需的专门知识。"""

    name = "Skill"

    def __init__(self, skill_loader: "SkillLoader"):
        """绑定用于查找和读取技能的加载器。"""
        self.skill_loader = skill_loader

    @property
    def description(self) -> str:
        """根据当前可用技能生成提供给模型的工具描述。"""
        skills_desc = self.skill_loader.get_descriptions()
        return f"""Load a skill to gain specialized knowledge for a task.

Available skills:
{skills_desc}

When to use:
- IMMEDIATELY when user task matches a skill description
- Before attempting domain-specific work (PDF, MCP, etc.)

The skill content will be injected into the conversation, giving you
detailed instructions and access to resources."""

    @property
    def input_schema(self) -> dict[str, Any]:
        """声明要加载的技能名参数。"""
        return {
            "type": "object",
            "properties": {
                "skill": {
                    "type": "string",
                    "description": "Name of the skill to load",
                }
            },
            "required": ["skill"],
        }

    async def execute_result(self, skill: str) -> ToolOutcome:
        """加载技能并将其内容注入对话。"""
        content = self.skill_loader.get_skill_content(skill)

        if content is None:
            available = ", ".join(self.skill_loader.list_skills()) or "none"
            return ToolOutcome(f"Error: Unknown skill '{skill}'. Available: {available}", "error")

        return ToolOutcome(f"""<skill-loaded name="{skill}">
{content}
</skill-loaded>

Follow the instructions in the skill above to complete the user's task.""", "success")
