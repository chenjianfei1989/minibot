"""配置写入工具，将运行时修改持久化到 YAML 文件。

按配置项来源回写，识别它来自全局目录（~/.minibot/config/）还是项目目录（project/config/），并写回对应文件。
"""

from pathlib import Path
from typing import Any

import yaml


def _load_raw(path: Path) -> dict:
    """加载 YAML，保留全部顶层结构。"""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_raw(path: Path, data: dict) -> None:
    """将字典写回 YAML，保留易于阅读的格式。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """递归合并映射配置，将补丁字段写入目标并保留无关键。"""
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
            continue
        target[key] = value
    return target


def update_default_config(config_path: Path, patch: dict[str, Any]) -> dict[str, Any]:
    """更新全局默认 YAML 配置并返回保存的数据。"""
    data = _load_raw(config_path)
    _deep_merge(data, patch)
    _save_raw(config_path, data)
    return data


def upsert_env_value(env_path: Path, key: str, value: str | None) -> None:
    """新增或更新一个 dotenv 键，保留其他行。"""
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    rendered = None if value is None else f"{key}={value}"
    updated: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            if rendered is not None:
                updated.append(rendered)
            replaced = True
        else:
            updated.append(line)

    if not replaced and rendered is not None:
        updated.append(rendered)

    output = "\n".join(updated).rstrip()
    if output:
        env_path.write_text(output + "\n", encoding="utf-8")
    elif env_path.exists():
        env_path.unlink()


def save_subagents_config(
    config_path: Path,
    agents: dict[str, dict[str, Any]],
) -> None:
    """将子 Agent 配置段写入配置文件。"""
    data = _load_raw(config_path)
    data["subagents"] = agents
    _save_raw(config_path, data)


def save_mcp_server_enabled(
    config_path: Path,
    server_name: str,
    enabled: bool,
) -> None:
    """切换配置文件中单个 MCP 服务的 ``enabled`` 状态。"""
    data = _load_raw(config_path)
    servers = data.get("servers", [])
    for server in servers:
        if isinstance(server, dict) and server.get("name") == server_name:
            server["enabled"] = enabled
            break
    data["servers"] = servers
    _save_raw(config_path, data)


def update_mcp_server_config(
    config_path: Path,
    server_name: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """更新配置文件中单个 MCP 服务的配置块，返回保存后的映射。"""
    data = _load_raw(config_path)
    servers = data.get("servers", [])

    for server in servers:
        if not isinstance(server, dict) or server.get("name") != server_name:
            continue
        for key in ("command", "url"):
            if key in patch:
                server[key] = patch.get(key)
        if "args" in patch:
            server["args"] = list(patch.get("args") or [])
        if "enabled" in patch:
            server["enabled"] = bool(patch.get("enabled"))
        data["servers"] = servers
        _save_raw(config_path, data)
        return dict(server)

    raise ValueError(f"Unknown MCP server: {server_name}")
