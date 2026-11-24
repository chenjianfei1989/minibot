"""用于把持久化运行接回原工作区的稳定标识。"""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import stat

from ..config.schema import BashConfig, Config


@dataclass(frozen=True)
class WorkspaceIdentity:
    value: str

    @classmethod
    def from_root(
        cls, root: Path, backend: str = "local", *, profile: tuple[str, ...] = (),
    ) -> "WorkspaceIdentity":
        """哈希规范化根路径、后端和执行配置，生成工作区标识。"""
        identity = json.dumps([1, str(root.resolve()), backend, profile], ensure_ascii=True)
        return cls(sha256(identity.encode("ascii")).hexdigest())


@dataclass(frozen=True)
class DockerContainer:
    name: str
    container_id: str | None


def legacy_workspace_identity(config: Config) -> WorkspaceIdentity:
    """根据规范化路径生成兼容旧记录的工作区标识。"""
    return trusted_workspace_identity(config.workdir, config.tools.bash)


def trusted_workspace_identity(root: Path, bash: BashConfig) -> WorkspaceIdentity:
    """为可信本地工作区生成稳定标识。"""
    profile = ("bash", bash.backend)
    if bash.backend == "docker":
        profile += (bash.image, str(bash.memory_mb), str(float(bash.cpus)), str(bash.pids_limit))
    return WorkspaceIdentity.from_root(root, profile=profile)


def restricted_root_key(root: Path) -> tuple[int, int]:
    """取得受限工作区根目录的文件系统标识，用于检测目录是否被替换。"""
    try:
        current = root.lstat()
    except OSError as exc:
        raise ValueError("The restricted Docker workspace directory is unavailable.") from exc
    if not stat.S_ISDIR(current.st_mode) or root.resolve() != root:
        raise ValueError("The restricted Docker workspace must resolve to its original directory.")
    return current.st_dev, current.st_ino


def configured_workspace_identity(config: Config) -> WorkspaceIdentity:
    """按当前工作区配置选择受限或可信本地模式的标识方案。"""
    policy = config.workspace
    if not policy.restricted:
        return legacy_workspace_identity(config)
    root = config.workdir.resolve()
    device, inode = restricted_root_key(root)
    return WorkspaceIdentity.from_root(
        root, "docker",
        profile=(
            "workspace-v1", str(device), str(inode), policy.image, policy.network,
            str(policy.memory_mb), str(float(policy.cpus)),
            str(policy.pids_limit), str(float(policy.timeout or config.tools.timeout)),
            "bash-disabled" if config.tools.bash.backend == "disabled" else "bash-enabled",
        ),
    )
