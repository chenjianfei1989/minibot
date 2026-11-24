"""配置结构定义。"""

from dataclasses import dataclass, field, replace as dataclass_replace
import math
from pathlib import Path
from typing import Any, Literal


@dataclass
class LLMConfig:
    """LLM 客户端配置。"""
    base_url: str | None = None
    api_key: str | None = None
    model: str = "gpt-4.1-mini"
    max_tokens: int = 8000
    max_context_tokens: int = 100000
    stream_enabled: bool = True
    max_tool_output_chars: int = 16000

    def __post_init__(self):
        """校验单条模型工具输出的字符上限。"""
        if type(self.max_tool_output_chars) is not int or self.max_tool_output_chars < 32:
            raise ValueError("llm.max_tool_output_chars must be an integer of at least 32")


MAX_ARTIFACT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class ContextOffloadingConfig:
    """大型文本工具结果的本地存储限制。"""

    enabled: bool = True
    threshold_chars: int | None = None
    max_artifact_bytes: int = 8 * 1024 * 1024

    def __post_init__(self):
        """校验上下文卸载的启用开关、触发阈值与单个产物的字节上限。"""
        if type(self.enabled) is not bool:
            raise ValueError("context_offloading.enabled must be a boolean")
        threshold = self.threshold_chars
        if threshold is not None and (type(threshold) is not int or threshold < 1):
            raise ValueError("context_offloading.threshold_chars must be a positive integer or null")
        maximum = self.max_artifact_bytes
        if type(maximum) is not int or not 1 <= maximum <= MAX_ARTIFACT_BYTES:
            raise ValueError("context_offloading.max_artifact_bytes must be between 1 byte and 64 MiB")


@dataclass(frozen=True)
class RuntimeBudgetConfig:
    """单个活跃执行片段的累计限制。"""

    max_llm_calls: int = 30
    max_tool_calls: int = 100
    max_wall_time: int | float = 600
    max_input_tokens: int = 200_000
    max_output_tokens: int = 50_000

    def __post_init__(self):
        """校验模型调用、工具调用、时间和 token 预算的取值。"""
        for name in ("max_llm_calls", "max_tool_calls", "max_input_tokens", "max_output_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"runtime_budget.{name} must be a positive integer")
        limit = self.max_wall_time
        if type(limit) not in (int, float) or not 0 < limit < math.inf:
            raise ValueError("runtime_budget.max_wall_time must be a positive finite number")


ToolPermission = Literal["allow", "deny", "ask"]


@dataclass(frozen=True)
class ToolPermissionsConfig:
    """模型请求调用工具时适用的执行策略。"""

    mode: Literal["off", "manual", "auto_review"] = "off"
    default: ToolPermission = "ask"
    rules: dict[str, ToolPermission] = field(default_factory=dict)
    auto_review_paths: tuple[str, ...] = ()
    timeout: int | float = 120

    def __post_init__(self):
        """核对审批模式、默认策略、规则、路径及等待时长，并规范化可变配置。"""
        choices = ("allow", "deny", "ask")
        if self.mode not in ("off", "manual", "auto_review"):
            raise ValueError("tool_permissions.mode must be off, manual, or auto_review")
        if self.default not in choices:
            raise ValueError("tool_permissions.default must be allow, deny, or ask")
        if not isinstance(self.rules, dict) or any(
            not isinstance(name, str) or not name.strip() or decision not in choices
            for name, decision in self.rules.items()
        ):
            raise ValueError("tool_permissions.rules must map tool names to allow, deny, or ask")
        paths = self.auto_review_paths
        if not isinstance(paths, (tuple, list)) or any(
            not isinstance(path, str) or not path.strip() or "\\" in path
            or path.startswith("/") or any(part in ("", ".", "..") for part in path.split("/"))
            for path in paths
        ):
            raise ValueError("tool_permissions.auto_review_paths must contain workspace-relative glob patterns")
        if type(self.timeout) not in (int, float) or not 0 < self.timeout <= 3600:
            raise ValueError("tool_permissions.timeout must be in (0, 3600] seconds")
        object.__setattr__(self, "rules", dict(self.rules))
        object.__setattr__(self, "auto_review_paths", tuple(paths))


def _validate_docker_limits(config: "BashConfig | WorkspaceConfig", prefix: str) -> None:
    """校验 Docker 的内存、CPU 和进程数资源限制。"""
    if not isinstance(config.image, str) or not config.image.strip() or config.image.startswith("-"):
        raise ValueError(f"{prefix}.image must be a nonempty image reference")
    for name in ("memory_mb", "pids_limit"):
        value = getattr(config, name)
        if type(value) is not int or value <= 0:
            raise ValueError(f"{prefix}.{name} must be a positive integer")
    cpus = config.cpus
    if type(cpus) not in (int, float) or not math.isfinite(cpus) or cpus <= 0:
        raise ValueError(f"{prefix}.cpus must be a positive finite number")


@dataclass(frozen=True)
class BashConfig:
    """Bash 执行策略，默认仍在本地执行。"""
    backend: Literal["disabled", "local", "docker"] = "local"
    image: str = "debian:bookworm"
    memory_mb: int = 512
    cpus: float = 1.0
    pids_limit: int = 128

    def __post_init__(self):
        """校验 Bash 后端、可用镜像与 Docker 资源限制。"""
        if self.backend not in ("disabled", "local", "docker"):
            raise ValueError("tools.bash.backend must be disabled, local, or docker")
        _validate_docker_limits(self, "tools.bash")


@dataclass(frozen=True)
class WorkspaceConfig:
    """整个工作区的执行策略，Docker 模式适用于 Shell 和文件工具。"""

    backend: Literal["local", "docker"] = "local"
    image: str = "python:3.12-slim"
    memory_mb: int = 512
    cpus: float = 1.0
    pids_limit: int = 128
    network: Literal["none", "bridge"] = "none"
    timeout: int | float | None = None

    def __post_init__(self):
        """校验工作区后端、网络模式、超时和容器资源限制。"""
        if self.backend not in ("local", "docker"):
            raise ValueError("workspace.backend must be local or docker")
        _validate_docker_limits(self, "workspace")
        if self.network not in ("none", "bridge"):
            raise ValueError("workspace.network must be none or bridge")
        if self.timeout is not None and (
            type(self.timeout) not in (int, float) or not math.isfinite(self.timeout) or self.timeout <= 0
        ):
            raise ValueError("workspace.timeout must be a positive finite number or null")

    @property
    def restricted(self) -> bool:
        """判断是否将工作区命令和文件操作交给受限 Docker 后端。"""
        return self.backend == "docker"


@dataclass
class ToolsConfig:
    """工具配置。"""
    enabled: list[str] = field(default_factory=lambda: ["*"])
    disabled: list[str] = field(default_factory=list)
    timeout: int | float = 60
    bash: BashConfig = field(default_factory=BashConfig)

    def __post_init__(self):
        """校验工具超时和 Bash 子配置。"""
        if type(self.timeout) not in (int, float) or not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("tools.timeout must be a positive finite number")
        if not isinstance(self.bash, BashConfig):
            raise ValueError("tools.bash must be a BashConfig")


@dataclass
class HookDefinition:
    """单个钩子的定义。"""
    event: str
    handler: str  # 脚本路径或 module:function 格式的函数引用。
    timeout: int = 30
    enabled: bool = True


@dataclass
class HooksConfig:
    """钩子系统配置。"""
    enabled: bool = True
    hooks_dir: Path = field(default_factory=lambda: Path("hooks"))
    hooks: list[HookDefinition] = field(default_factory=list)


@dataclass
class MCPServerConfig:
    """单个 MCP 服务配置。"""
    name: str
    transport: str = "stdio"  # 可选值为 stdio、sse 或 streamable_http。
    command: str | None = None  # 用于 stdio。
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None  # 用于 sse 和 streamable_http。
    enabled: bool = True
    headers: dict[str, str] = field(default_factory=dict, repr=False)


@dataclass
class MemoryConfig:
    """记忆系统配置。"""
    enabled: bool = True
    memory_dir: str = "memory"
    backend: str = "sqlite"
    database_url: str | None = None
    active_namespace: str | None = None
    long_term_max_lines: int = 200
    daily_lookback_days: int = 1


@dataclass
class MCPConfig:
    """MCP 客户端配置。"""
    enabled: bool = True
    servers: list[MCPServerConfig] = field(default_factory=list)


@dataclass
class TeamsConfig:
    """Agent 团队配置。"""

    enabled: bool = True
    max_members: int = 6
    default_members: int = 3
    log_dir: str = ".minibot/teams"
    wait_timeout_sec: int = 30
    quiet_teammates: bool = True
    debug_teammate_output: bool = False


@dataclass
class SubagentConfig:
    """单种子 Agent 类型的覆盖配置。"""
    description: str | None = None
    tools: list[str] | None = None
    prompt: str | None = None
    skills_enabled: bool = False
    enabled: bool = True


@dataclass
class SubagentsConfig:
    """子 Agent 配置。"""
    agents: dict[str, SubagentConfig] = field(default_factory=dict)


@dataclass
class SessionConfig:
    """会话持久化配置。"""
    enabled: bool = True
    sessions_dir: str = "sessions"  # 相对于 app_home。


@dataclass
class Config:
    """主配置。"""
    workdir: Path = field(default_factory=Path.cwd)
    app_home: Path | None = None
    project_root: Path | None = None
    skills_dir: Path = field(default_factory=lambda: Path("skills"))
    llm: LLMConfig = field(default_factory=LLMConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    hooks: HooksConfig = field(default_factory=HooksConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    teams: TeamsConfig = field(default_factory=TeamsConfig)
    subagents: SubagentsConfig = field(default_factory=SubagentsConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    trace_dir: str | Path | None = None
    runtime_budget: RuntimeBudgetConfig = field(default_factory=RuntimeBudgetConfig)
    tool_permissions: ToolPermissionsConfig = field(default_factory=ToolPermissionsConfig)
    file_checkpoints: bool = False
    durable_execution: bool = False
    context_offloading: ContextOffloadingConfig = field(default_factory=ContextOffloadingConfig)

    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    durable_child_workspace: WorkspaceConfig = field(default_factory=lambda: WorkspaceConfig(backend="docker"))

    def __post_init__(self):
        """校验持久化开关和持久化子运行的工作区隔离配置。"""
        if not isinstance(self.workspace, WorkspaceConfig):
            raise ValueError("workspace must be a WorkspaceConfig")
        child_workspace = self.durable_child_workspace
        if not isinstance(child_workspace, WorkspaceConfig) or not child_workspace.restricted or child_workspace.network != "none":
            raise ValueError("durable_child_workspace requires the Docker backend with network disabled")
        if not isinstance(self.context_offloading, ContextOffloadingConfig):
            raise ValueError("context_offloading must be a ContextOffloadingConfig")
        if type(self.durable_execution) is not bool:
            raise ValueError("durable_execution must be a boolean")
        if type(self.file_checkpoints) is not bool:
            raise ValueError("file_checkpoints must be a boolean")
        if not isinstance(self.tool_permissions, ToolPermissionsConfig):
            raise ValueError("tool_permissions must be a ToolPermissionsConfig")
        if isinstance(self.workdir, str):
            self.workdir = Path(self.workdir)
        if isinstance(self.app_home, str):
            self.app_home = Path(self.app_home)
        if isinstance(self.project_root, str):
            self.project_root = Path(self.project_root)
        if isinstance(self.skills_dir, str):
            self.skills_dir = Path(self.skills_dir)
        if self.project_root is None:
            self.project_root = self.workdir
        if self.app_home is None:
            self.app_home = self.workdir / ".minibot"
        if self.workspace.restricted:
            sessions_dir = Path(self.session.sessions_dir).expanduser()
            if not sessions_dir.is_absolute():
                self.session = dataclass_replace(self.session, sessions_dir=str(self.app_home / sessions_dir))
        if self.trace_dir is not None:
            trace_path = Path(self.trace_dir).expanduser()
            self.trace_dir = trace_path if trace_path.is_absolute() else self.app_home / trace_path
