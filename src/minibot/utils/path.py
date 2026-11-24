"""路径辅助函数。"""

import os
from pathlib import Path


def safe_path(workdir: Path, path: str) -> Path:
    """确保路径位于工作区内。"""
    resolved = (workdir / path).resolve()
    if not resolved.is_relative_to(workdir):
        raise ValueError(f"Path escapes workspace: {path}")
    return resolved


def resolve_project_root(cwd: Path) -> Path:
    """从当前工作目录向上查找 Git 根目录，以确定项目根目录。"""
    current = cwd.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def resolve_app_home() -> Path:
    """解析 MiniBot 的持久化主目录。"""
    home = os.getenv("MINIBOT_HOME", "").strip()
    if home:
        return Path(home).expanduser().resolve()

    xdg_config_home = os.getenv("XDG_CONFIG_HOME", "").strip()
    if xdg_config_home:
        return (Path(xdg_config_home).expanduser() / "minibot").resolve()

    return (Path.home() / ".minibot").resolve()
