# 持久化沙箱子 Agent

在可信的本地父 Agent 上启用持久化执行。启动本地 Docker 守护进程，并预先加载配置指定的子 Agent 镜像。镜像须提供 `/bin/sh` 和 `python3`。MiniBot 创建子运行时会记录镜像 ID。

```yaml
durable_execution: true
workspace:
  backend: local
durable_child_workspace:
  image: python:3.12-slim
  timeout: 60
```

父 Agent 调用 `Task` 时，MiniBot 在同一个 SQLite 事务中提交子运行、子会话、工作区标识和父步骤。子工作区初始为空。请在提示词中提供所需输入，并通过可选的 `deliverables` 数组声明要交付的文件。子 Agent 共享父运行的模型连接和执行预算，在独立的 Docker 挂载中使用文件和 Bash 工具。容器禁用网络，工具范围由子 Agent 类型限定。

最多可通过 `TaskBatch` 同时委派四项相互独立的任务。`tasks` 数组中每项的字段与 `Task` 相同。各任务使用独立工作区，交付凭据按输入顺序返回。存在依赖的任务应在后续模型调用中委派，使父 Agent 能先检查已有结果。未启用持久化的 `Task` 仍由原有子 Agent 执行器处理。

## 恢复运行与人工处理

重启后打开原父工作区、应用主目录和会话。委派步骤尚未完成时，父运行处于 `waiting_child`。恢复父运行会接回原子运行，复用已经完成的结果或已提交的交付凭据。列出子运行时看到的是最后提交的状态。恢复会先验证 Docker 清理结果，再更新状态。

```python
for run in bot.list_runs(incomplete_only=True):
    for child in bot.list_child_runs(run.run_id):
        print(child.run.run_id, child.run.status, child.parent_step_id)
    result = await bot.resume_run(run.run_id)
```

`pause_run(parent_run_id)` 通知活跃的子运行停止，并在父运行结束前等待清理。可以用 `pause_child_run(parent_run_id, child_run_id)` 单独请求暂停一个子运行。两个方法都会记录请求。应等活跃执行返回后，再启动新的执行片段。

如果中断的工具可能已经改变状态，先用 `list_child_run_steps(parent_run_id, child_run_id)` 查看步骤，再核实实际效果。在恢复父运行前，用 `await bot.resolve_child_run_step(parent_run_id, child_run_id, step_id, output)` 记录结果。确认已停止子运行的工作区和 Docker 清理状态后，可用 `await bot.abandon_child_run(parent_run_id, child_run_id)` 放弃该子运行。放弃父运行之前，应处理完尚未解决的子运行。

MiniBot 在恢复前检查已记录的工作区标识和本地 Docker 守护进程。工作区被替换或清理无法核实时，系统会阻止继续执行。恢复原工作区或守护进程后可重试。如果 Docker 创建请求可能尚未结束，而且找不到对应的容器或无法确认其 ID，子运行会保持阻塞，直到清理可验证。

## 交付与应用文件

成功导出的文件包含工作区相对路径、SHA-256、字节数和产物 ID。父 Agent 可以在委派运行中用 `ReadChildArtifact` 查看交付文件。SDK 调用方也能独立于运行中的 Docker 容器检查和验证同一产物。

```python
for artifact in bot.list_child_artifacts(parent_run_id, child_run_id):
    text = bot.read_child_artifact(parent_run_id, child_run_id, artifact.path)
    print(artifact.sha256, text)

installed = bot.apply_child_artifact(
    parent_run_id, child_run_id, "report.txt", "reports/child-report.txt",
)
```

导出支持配置大小上限内的普通 UTF-8 文件。应用产物是显式的 POSIX SDK 操作，目标目录必须已存在。文件会原子创建。如果目标已有相同内容，返回 `False`。内容冲突或路径涉及符号链接时会拒绝操作。要编辑现有文件，请先读取已验证的产物并检查差异，再修改父工作区中的文件。

使用脚本化模型和实际 Docker 进程的测试可通过以下命令运行。

```bash
MINIBOT_TEST_DOCKER=1 python -m pytest tests/test_durable_sandbox_child.py tests/test_durable_child_batch.py
```
