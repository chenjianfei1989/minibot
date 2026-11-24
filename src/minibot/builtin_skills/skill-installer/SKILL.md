---
name: skill-installer
description: 安装、更新、移除或检查 MiniBot 技能。适用于从本地目录或 GitHub 仓库添加技能，以及查询技能安装位置。
---

# 安装技能

用户想安装或管理 MiniBot 技能时使用本技能。

## 技能目录和安装

技能目录包含带有 `name` 和 `description` 元数据的 `SKILL.md`，也可以包含 `scripts/`、`references/` 和 `assets/`。

1. 修改前检查已生效的技能目录。默认使用用户技能目录。用户明确要求项目共享时，才使用项目的 `skills/`。
2. 从本地安装时，先验证源目录的 `SKILL.md`，再复制完整目录。通常让目录名与技能名一致。
3. 从 GitHub 安装时，优先使用随附脚本。条件允许时只获取所需技能目录，保留随附脚本、资料和资源。需要凭证或网络访问时，明确告知用户。
4. 用户明确要求替换时才覆盖已存在的目录。安装后验证当前运行时可以找到技能。

## 辅助脚本

- `scripts/list-skills.py` 列出 GitHub 仓库路径中的可用技能，并标记已安装项。默认来源为 `openai/skills` 的 `skills/.curated`。
- `scripts/install-skill-from-github.py` 把一个或多个 GitHub 技能目录安装到当前技能目录。支持公开仓库直接下载及 Git 稀疏检出回退。
- `scripts/github_utils.py` 提供安装脚本共用的 GitHub 和 MiniBot 路径解析功能。

这些脚本可能需要网络访问。环境受沙箱限制时，运行前请求所需权限。

## 优先级、更新和移除

- 名称冲突时，高优先级目录覆盖低优先级目录。内置技能可被同名的用户或项目技能覆盖。
- 更新时先比较来源和已安装目录。用户要求更新或确认替换后再操作，并指出是否会覆盖本地定制。
- 移除时优先禁用。只有用户明确要求从磁盘移除时才删除目录。

## 验证

安装或移除后任选一项验证。

- TUI 的 `/skills list`
- Web API `/api/skills`
- Python 的 `SkillLoader(...).list_skills()`
- `scripts/list-skills.py --format json`

汇报使用的生效目录，以及该技能是否覆盖内置或优先级较低的同名技能。
