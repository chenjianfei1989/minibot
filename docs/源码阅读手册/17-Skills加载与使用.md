# 第 17 讲 Skills加载与使用

理解技能文件的信息何时进入提示词，以及怎样手动验证加载结果。

## 知道技能存在与加载技能正文

假设你写了一个「整理发布说明」技能，里面既有概要也有步骤。要理解模型何时能遵循它，先从 `SkillLoader` 看如何扫描目录、提取名称和描述，再找 `Agent._build_system_prompt()` 怎样说明可用技能。具体技能被调用时，`SkillTool` 才按名称读取内容并作为结果返回。给描述写清楚适用情形，才能让模型在恰当的任务中发现它。

## 跟踪重名和禁用

当项目技能与内置技能同名时，在测试里观察最终显示的描述和来源。查看加载器处理多个目录的顺序，结合实际传给 SDK 的 `skills_dir` 判断谁覆盖谁。禁用名单变更后，Agent 会刷新技能加载器和依赖它的提示词或执行组件。受限工作区的技能来源也受当前策略约束。

练习时可将同名技能放在两个临时目录，分别写不同描述。使用 `/skills list` 或受控加载测试先验证选中项，再观察实际工具返回的内容。持续使用同名技能时，要把保存位置和启用状态记入笔记。

**思考与答案**　系统提示词列出一个技能，是否等于模型已读完它的全部步骤？列表可以只有名称和描述，正文由具体的加载和调用链提供。

## 源码索引

[skills/loader.py](../../src/minibot/skills/loader.py) · [tools/meta/skill.py](../../src/minibot/tools/meta/skill.py) · [builtin_skills/skill-creator/SKILL.md](../../src/minibot/builtin_skills/skill-creator/SKILL.md) · [builtin_skills/skill-installer/SKILL.md](../../src/minibot/builtin_skills/skill-installer/SKILL.md)

## 配置核对

核对 skills_dir、SDK 的 disabled_skills 和加载器的内置技能开关。比较用户、项目、内置来源，以及同名时哪个目录生效。

## 使用与验证

运行 /skills list 查看加载结果。用测试创建一个同名技能，观察描述和正文是否使用指定来源。

在仓库根目录运行本讲的定向测试。测试可在未配置真实模型凭证的环境中执行。

```powershell
uv run --with pytest --with pytest-asyncio python -m pytest -q tests/test_skill_loader.py::test_explicit_skill_dir_overrides_builtin_skill
```

## 阅读验收

能从一个 SKILL.md 解释它如何被加载、何时交给模型、如何定位同名覆盖。

[阅读总纲](00-阅读总纲.md) · [上一讲](16-追踪回归测试与模型评估.md) · [下一讲](18-MCP外部工具.md)
