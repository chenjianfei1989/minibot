# 第 17 讲 Skills加载与使用

理解技能文件的信息何时进入提示词，以及怎样手动验证加载结果。

## 源码导读

沿 SkillLoader 的目录扫描和元数据解析看 name、description、正文以及重名处理。找出 Agent 构建提示词时使用的描述，以及 Skill 工具按名称返回的全文和资源列表。

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
