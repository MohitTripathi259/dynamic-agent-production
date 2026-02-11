"""
Agent Configuration.

Single source of truth for settings loaded from environment variables.
"""

import os
from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    """Configuration for the Claude Computer-Use Agent."""

    # Anthropic API
    anthropic_api_key: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )

    # Model
    model: str = field(
        default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
    )

    # Container URL — the only place this default is defined
    container_url: str = field(
        default_factory=lambda: os.getenv(
            "CONTAINER_URL",
            os.getenv("LOCAL_CONTAINER_URL", "http://localhost:8080"),
        )
    )

    # Display settings (must match container's virtual display)
    display_width: int = field(
        default_factory=lambda: int(os.getenv("DISPLAY_WIDTH", "1920"))
    )
    display_height: int = field(
        default_factory=lambda: int(os.getenv("DISPLAY_HEIGHT", "1080"))
    )

    # Logging
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )

    def validate(self) -> bool:
        """Validate required configuration."""
        if not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")
        return True


# Global config instance
config = AgentConfig()
