---
name: skill-creator
description: 设计或更新 MiniBot 技能。适用于创建新技能、改进现有技能，或组织 SKILL.md、脚本、参考资料和资源文件。
---

# 创建技能

创建或修改 MiniBot 技能时使用本技能。目标是用简洁的说明补充 Agent 难以自行推断的工作流程。

## 辅助脚本

- `scripts/init_skill.py` 创建技能目录和初始 `SKILL.md`。默认使用用户的 MiniBot 技能目录。可选创建 `scripts/`、`references/` 和 `assets/`，并放入示例文件。
- `scripts/quick_validate.py` 对技能目录进行结构校验。在完成新建或编辑前运行。

## 技能目录

- `SKILL.md` 必须包含 `name` 和 `description` 头部元数据。
- 可选的 `scripts/` 存放可重复执行的辅助脚本。
- 可选的 `references/` 存放按需加载的参考资料。
- 可选的 `assets/` 存放模板或输出资源。

## 编写与验证

1. 先查看附近的技能，沿用一致的命名和布局。
2. 默认在用户技能目录创建。用户明确需要项目共享技能时，使用项目的 `skills/`。
3. 确定触发技能的任务，用具体的 `description` 写清楚这些场景。
4. 在 `SKILL.md` 中保留简短、按步骤编排的核心流程。将长资料放入 `references/`。需要确定性行为或经常重复编写同一代码时，使用 `scripts/`。
5. 用 `/skills list` 或 `/api/skills` 确认技能可见，再运行 `scripts/quick_validate.py <skill_dir>`。
6. 用一个实际场景的提示词验证触发和执行，改进含糊的说明。

每个技能专注一套流程。采用直接指令、明确的验证步骤和稳定的辅助脚本命名。完成前核对头部元数据、触发描述、引用文件及当前工具环境是否支持这套流程。

## 更新现有技能

除非触发意图已变，否则沿用原技能名。删除过时说明，避免加入互相矛盾的指令。技能有多个变体时，在 `SKILL.md` 说明如何选择，并把各变体细节放入独立参考文件。
