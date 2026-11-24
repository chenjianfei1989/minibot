"""子 Agent 类型注册表。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from ..config.schema import SubagentsConfig


SubagentHandler = Callable[[str, str, "AgentType"], Awaitable[str]]


@dataclass
class AgentType:
    """一种子 Agent 类型的定义。"""
    name: str
    description: str
    tools: list[str] | Literal["*"]
    prompt: str
    skills_enabled: bool = False
    enabled: bool = True
    metadata: dict[str, Any] | None = None
    handler: SubagentHandler | None = None


class AgentRegistry:
    """子 Agent 类型注册表。"""

    DEFAULT_AGENTS = {
        "explore": AgentType(
            name="explore",
            description="Read-only agent for inspecting workspace files",
            tools=["read_file"],
            prompt="You are an exploration agent. Read the relevant workspace files and return a concise summary.",
        ),
        "code": AgentType(
            name="code",
            description="Full agent for implementing features and fixing bugs",
            tools="*",
            prompt="You are a coding agent. Implement the requested changes efficiently.",
        ),
        "plan": AgentType(
            name="plan",
            description="Planning agent for designing implementation strategies",
            tools=["read_file"],
            prompt="You are a planning agent. Analyze the codebase and output a numbered implementation plan. Do NOT make changes.",
        ),
    }

    DEFAULT_AGENT_NAMES: frozenset[str] = frozenset(DEFAULT_AGENTS.keys())

    def __init__(self):
        """复制默认子 Agent 类型，隔离不同注册表实例的运行时修改。"""
        self._agents: dict[str, AgentType] = deepcopy(self.DEFAULT_AGENTS)

    def apply_config(self, config: "SubagentsConfig") -> None:
        """用覆盖配置更新已注册的 Agent。"""
        for name, agent_cfg in config.agents.items():
            agent = self._agents.get(name)
            if agent is None:
                # 配置提供足够信息时，注册自定义 Agent。
                if agent_cfg.description is not None and agent_cfg.prompt is not None:
                    tools = agent_cfg.tools if agent_cfg.tools is not None else ["bash", "read_file"]
                    agent = AgentType(
                        name=name,
                        description=agent_cfg.description,
                        tools=tools,
                        prompt=agent_cfg.prompt,
                        skills_enabled=agent_cfg.skills_enabled,
                        enabled=agent_cfg.enabled,
                    )
                    self._agents[name] = agent
                continue
            if agent_cfg.description is not None:
                agent.description = agent_cfg.description
            if agent_cfg.tools is not None:
                agent.tools = agent_cfg.tools
            if agent_cfg.prompt is not None:
                agent.prompt = agent_cfg.prompt
            agent.skills_enabled = agent_cfg.skills_enabled
            agent.enabled = agent_cfg.enabled

    def register(self, agent: AgentType) -> None:
        """注册一种 Agent 类型。"""
        self._agents[agent.name] = agent

    def unregister(self, name: str) -> bool:
        """移除非默认 Agent，成功移除时返回 True。"""
        if name in self.DEFAULT_AGENT_NAMES:
            return False
        return self._agents.pop(name, None) is not None

    def enable(self, name: str) -> bool:
        """启用 Agent，找到时返回 True。"""
        agent = self._agents.get(name)
        if agent is None:
            return False
        agent.enabled = True
        return True

    def disable(self, name: str) -> bool:
        """禁用 Agent，找到时返回 True。"""
        agent = self._agents.get(name)
        if agent is None:
            return False
        agent.enabled = False
        return True

    def get(self, name: str) -> AgentType | None:
        """按名称获取 Agent 类型。"""
        return self._agents.get(name)

    def list_all(self) -> list[AgentType]:
        """列出所有 Agent 类型及其完整详情。"""
        return list(self._agents.values())

    def list_names(self) -> list[str]:
        """列出所有 Agent 类型名称。"""
        return list(self._agents.keys())

    def list_enabled_names(self) -> list[str]:
        """列出已启用的 Agent 类型名称。"""
        return [name for name, agent in self._agents.items() if agent.enabled]

    def get_descriptions(self) -> str:
        """获取已启用 Agent 的格式化描述，供系统提示词使用。"""
        return "\n".join(
            f"- {name}: {agent.description}"
            for name, agent in self._agents.items()
            if agent.enabled
        )

    def to_config_dict(self) -> dict[str, dict]:
        """将所有 Agent 序列化为可写回 YAML 的字典。"""
        result: dict[str, dict] = {}
        for name, agent in self._agents.items():
            entry: dict = {"enabled": agent.enabled, "skills_enabled": agent.skills_enabled}
            default = self.DEFAULT_AGENTS.get(name)
            if default is None or agent.description != default.description:
                entry["description"] = agent.description
            if default is None or agent.tools != default.tools:
                entry["tools"] = agent.tools
            if default is None or agent.prompt != default.prompt:
                entry["prompt"] = agent.prompt
            result[name] = entry
        return result
