"""用于加载 SKILL.md 文件的技能加载器。"""

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any


class SkillLoader:
    """从 SKILL.md 文件加载并管理技能。

    一个技能对应一个目录，可包含以下内容。
    - SKILL.md（必需），包含 YAML 头部元数据和 Markdown 说明。
    - scripts/（可选），存放辅助脚本。
    - references/（可选），存放补充资料。
    - assets/（可选），存放模板和输出所需文件。
    """

    BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent.parent / "builtin_skills"
    COMMON_SKILL_DIRS = (Path("~/.claude/skills"),)

    def __init__(
        self,
        skills_dir: Path | Iterable[Path],
        *,
        disabled_skills: Iterable[str] | None = None,
        include_defaults: bool = True,
    ):
        """规范化技能目录和禁用名单，然后加载当前可用技能。"""
        self.skills_dirs = self._normalize_dirs(skills_dir, include_defaults=include_defaults)
        self.disabled_skills = {str(name) for name in (disabled_skills or [])}
        self.skills: dict[str, dict[str, Any]] = {}
        self.load_skills()

    def _normalize_dirs(self, skills_dir: Path | Iterable[Path], *, include_defaults: bool) -> list[Path]:
        """将单个或多个技能目录转换为统一的路径列表。"""
        if isinstance(skills_dir, (str, Path)):
            dirs = [Path(skills_dir)]
        else:
            dirs = [Path(path) for path in skills_dir]

        if include_defaults:
            dirs.extend((self.BUILTIN_SKILLS_DIR, *self.COMMON_SKILL_DIRS))

        normalized: list[Path] = []
        for path in dirs:
            expanded = path.expanduser()
            if expanded not in normalized:
                normalized.append(expanded)

        return normalized

    def parse_skill_md(self, path: Path) -> dict | None:
        """解析 SKILL.md 文件，提取元数据和正文。"""
        content = path.read_text(encoding="utf-8")

        # 匹配两行 --- 之间的 YAML 头部元数据。
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        if not match:
            return None

        frontmatter, body = match.groups()

        # 解析形如 YAML 的头部元数据，只支持简单的键值对。
        metadata = {}
        for line in frontmatter.strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip("\"'")

        # 要求提供 name 和 description。
        if "name" not in metadata or "description" not in metadata:
            return None

        return {
            "name": metadata["name"],
            "description": metadata["description"],
            "body": body.strip(),
            "path": path,
            "dir": path.parent,
        }

    def load_skills(self) -> None:
        """扫描技能目录并加载所有有效的 SKILL.md 文件。"""
        for skills_dir in self.skills_dirs:
            if not skills_dir.exists():
                continue

            for skill_dir in skills_dir.iterdir():
                if not skill_dir.is_dir():
                    continue

                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue

                skill = self.parse_skill_md(skill_md)
                if not skill:
                    continue
                if skill["name"] in self.disabled_skills:
                    continue
                if skill["name"] not in self.skills:
                    self.skills[skill["name"]] = skill

    def get_descriptions(self) -> str:
        """生成系统提示词中的技能描述。"""
        if not self.skills:
            return "(no skills available)"

        return "\n".join(
            f"- {name}: {skill['description']}"
            for name, skill in self.skills.items()
        )

    def get_skill_content(self, name: str) -> str | None:
        """获取待注入的完整技能内容。"""
        if name not in self.skills:
            return None

        skill = self.skills[name]
        content = f"# Skill: {skill['name']}\n\n{skill['body']}"

        # 列出可用资源。
        resources = []
        for folder, label in [
            ("scripts", "Scripts"),
            ("references", "References"),
            ("assets", "Assets"),
        ]:
            folder_path = skill["dir"] / folder
            if folder_path.exists():
                files = list(folder_path.glob("*"))
                if files:
                    resources.append(f"{label}: {', '.join(f.name for f in files)}")

        if resources:
            content += f"\n\n**Available resources in {skill['dir']}:**\n"
            content += "\n".join(f"- {r}" for r in resources)

        return content

    def list_skills(self) -> list[str]:
        """返回可用技能的名称列表。"""
        return list(self.skills.keys())
