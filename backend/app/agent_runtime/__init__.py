"""Agent runtime package for multi-role orchestration.

The runtime is intentionally thin: it routes user intent, wraps existing
business services, and records execution lineage without replacing the current
market, prediction, news, or playbook implementations.
"""

from .task_manager_agent import TaskManagerAgent
from .executor import AgentRuntimeExecutor

__all__ = ["TaskManagerAgent", "AgentRuntimeExecutor"]