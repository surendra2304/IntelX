"""INTELX Base Agent Architecture, Registry, and Prompt Security Delimiters."""

import logging
from abc import ABC, abstractmethod
from typing import Any

from intelx.models.gateway import ModelGateway, get_model_gateway

logger = logging.getLogger(__name__)


def format_external_document(document_id: str, source_id: str, text: str) -> str:
    """Format untrusted external document text within strict user-message security delimiters."""
    return (
        f"<<<EXTERNAL_DOCUMENT id={document_id} source={source_id}>>>\n"
        f"{text.strip()}\n"
        f"<<<END_EXTERNAL_DOCUMENT>>>"
    )


class BaseAgent(ABC):
    """Abstract base class for all typed INTELX worker agents."""

    def __init__(
        self,
        role: str,
        name: str | None = None,
        gateway: ModelGateway | None = None,
    ) -> None:
        self.role = role
        self.name = name or self.__class__.__name__
        self.gateway = gateway or get_model_gateway()

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """Execute the agent's core task workflow."""
        pass


class AgentRegistry:
    """Central registry for discovering and managing agent singletons."""

    _registry: dict[str, BaseAgent] = {}

    @classmethod
    def register(cls, agent: BaseAgent) -> None:
        """Register an agent instance by role and name."""
        cls._registry[agent.role] = agent
        cls._registry[agent.name.lower()] = agent

    @classmethod
    def get(cls, key: str) -> BaseAgent | None:
        """Retrieve registered agent by role or class name."""
        return cls._registry.get(key.lower())

    @classmethod
    def clear(cls) -> None:
        """Clear all registered agents."""
        cls._registry.clear()
