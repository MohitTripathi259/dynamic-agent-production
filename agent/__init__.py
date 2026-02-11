"""
Claude Computer-Use Agent package.

Uses Anthropic's built-in computer-use tool types directly
against a containerized Linux environment.
"""

from .computer_use_agent import ComputerUseAgent
from .config import config, AgentConfig

__all__ = [
    "ComputerUseAgent",
    "config",
    "AgentConfig",
]
