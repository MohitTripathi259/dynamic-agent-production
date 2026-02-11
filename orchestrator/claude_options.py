"""
orchestrator/claude_options.py
------------------------------
ClaudeAgentOptions wrapper for our DynamicAgent implementation.

This provides an API-compatible interface similar to the official claude-agent-sdk,
while keeping our custom MCP client implementation underneath.

This allows us to:
1. Match the official SDK's ClaudeAgentOptions structure
2. Keep our working dynamic MCP discovery implementation
3. Provide an easy migration path to the official SDK later if needed
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Literal
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Type aliases matching the official SDK
PermissionMode = Literal["auto", "ask", "manual"]
SystemPromptPreset = Literal["default", "minimal", "custom"]


@dataclass
class McpServerConfig:
    """
    MCP Server configuration matching official SDK structure.
    Maps to entries in .claude/settings.json
    """
    httpUrl: str
    authProviderType: str = "none"
    description: str = ""
    enabled: bool = True


@dataclass
class ClaudeAgentOptions:
    """
    Agent configuration options matching the official claude-agent-sdk structure.

    This dataclass wraps our DynamicAgent implementation while providing
    an interface compatible with the official SDK's ClaudeAgentOptions.

    Key parameters:
        mcp_servers: Dict of MCP server configurations (loaded from settings.json)
        allowed_tools: List of tool names to allow (None = all tools)
        system_prompt: Custom system prompt or preset
        permission_mode: Tool execution permission mode
        model: Claude model to use
        max_turns: Maximum conversation turns
        api_key: Anthropic API key
        settings_path: Path to .claude/settings.json
    """

    # Core configuration
    api_key: str = field(repr=False)  # Don't print API key
    settings_path: str = ".claude/settings.json"

    # MCP server configuration
    mcp_servers: Optional[Dict[str, McpServerConfig]] = None

    # Tool configuration
    allowed_tools: Optional[List[str]] = None
    enable_mcp_servers: bool = True

    # S3 Skills configuration
    load_s3_skills: bool = True
    s3_skills_bucket: str = "cerebricks-studio-agent-skills"
    s3_skills_prefix: str = "skills_phase3/"

    # System prompt
    system_prompt: Optional[str] = None
    system_prompt_preset: Optional[SystemPromptPreset] = None

    # Permissions and safety
    permission_mode: PermissionMode = "auto"

    # Model configuration
    model: str = "claude-sonnet-4-20250514"
    max_turns: int = 25
    max_tokens: int = 4096
    temperature: float = 1.0

    # Working directory and context
    cwd: Optional[str] = None

    # Logging and debugging
    verbose: bool = False
    log_tool_calls: bool = True

    def __post_init__(self):
        """Validate and normalize configuration after initialization."""
        # Ensure settings_path is absolute
        if not Path(self.settings_path).is_absolute():
            # Make relative to current working directory or cwd
            base = Path(self.cwd) if self.cwd else Path.cwd()
            self.settings_path = str(base / self.settings_path)

        # Load MCP servers from settings.json if not explicitly provided
        if self.mcp_servers is None and self.enable_mcp_servers:
            self._load_mcp_servers_from_settings()

        # Validate model
        if not self.model.startswith("claude-"):
            logger.warning(f"Model '{self.model}' doesn't appear to be a Claude model")

        # Log configuration
        if self.verbose:
            logger.info(f"ClaudeAgentOptions initialized:")
            logger.info(f"  - Model: {self.model}")
            logger.info(f"  - Settings: {self.settings_path}")
            logger.info(f"  - MCP Servers: {len(self.mcp_servers or {})}")
            logger.info(f"  - Max Turns: {self.max_turns}")

    def _load_mcp_servers_from_settings(self):
        """Load MCP server configuration from settings.json."""
        import json

        settings_file = Path(self.settings_path)
        if not settings_file.exists():
            logger.warning(f"Settings file not found: {self.settings_path}")
            self.mcp_servers = {}
            return

        try:
            with open(settings_file, 'r') as f:
                config = json.load(f)

            mcp_servers_config = config.get("mcpServers", {})

            # Convert to McpServerConfig objects
            self.mcp_servers = {}
            for name, server_config in mcp_servers_config.items():
                self.mcp_servers[name] = McpServerConfig(
                    httpUrl=server_config.get("httpUrl", ""),
                    authProviderType=server_config.get("authProviderType", "none"),
                    description=server_config.get("description", ""),
                    enabled=server_config.get("enabled", True)
                )

            if self.verbose:
                logger.info(f"Loaded {len(self.mcp_servers)} MCP servers from {self.settings_path}")

        except Exception as e:
            logger.error(f"Failed to load MCP servers from settings: {e}")
            self.mcp_servers = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert options to dictionary for serialization."""
        return {
            "settings_path": self.settings_path,
            "mcp_servers": {
                name: {
                    "httpUrl": server.httpUrl,
                    "authProviderType": server.authProviderType,
                    "description": server.description,
                    "enabled": server.enabled
                }
                for name, server in (self.mcp_servers or {}).items()
            },
            "allowed_tools": self.allowed_tools,
            "enable_mcp_servers": self.enable_mcp_servers,
            "system_prompt": self.system_prompt,
            "system_prompt_preset": self.system_prompt_preset,
            "permission_mode": self.permission_mode,
            "model": self.model,
            "max_turns": self.max_turns,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "cwd": self.cwd,
            "verbose": self.verbose,
            "log_tool_calls": self.log_tool_calls,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], api_key: str) -> "ClaudeAgentOptions":
        """Create ClaudeAgentOptions from dictionary."""
        # Convert mcp_servers dict to McpServerConfig objects
        mcp_servers = None
        if "mcp_servers" in data and data["mcp_servers"]:
            mcp_servers = {
                name: McpServerConfig(**server_config)
                for name, server_config in data["mcp_servers"].items()
            }

        return cls(
            api_key=api_key,
            settings_path=data.get("settings_path", ".claude/settings.json"),
            mcp_servers=mcp_servers,
            allowed_tools=data.get("allowed_tools"),
            enable_mcp_servers=data.get("enable_mcp_servers", True),
            system_prompt=data.get("system_prompt"),
            system_prompt_preset=data.get("system_prompt_preset"),
            permission_mode=data.get("permission_mode", "auto"),
            model=data.get("model", "claude-sonnet-4-20250514"),
            max_turns=data.get("max_turns", 25),
            max_tokens=data.get("max_tokens", 4096),
            temperature=data.get("temperature", 1.0),
            cwd=data.get("cwd"),
            verbose=data.get("verbose", False),
            log_tool_calls=data.get("log_tool_calls", True),
        )


def create_agent_with_options(options: ClaudeAgentOptions):
    """
    Create a DynamicAgent instance using ClaudeAgentOptions.

    This is the bridge between our ClaudeAgentOptions wrapper and
    the underlying DynamicAgent implementation.

    Args:
        options: ClaudeAgentOptions configuration

    Returns:
        Configured DynamicAgent instance
    """
    from orchestrator.agent_runner import DynamicAgent

    # Create agent with options (including S3 skills)
    agent = DynamicAgent(
        anthropic_api_key=options.api_key,
        settings_path=options.settings_path,
        model=options.model,
        load_s3_skills=options.load_s3_skills,
        s3_skills_bucket=options.s3_skills_bucket,
        s3_skills_prefix=options.s3_skills_prefix
    )

    # Apply additional options
    if options.allowed_tools is not None:
        # Filter tools to only allowed ones
        agent.tools = [
            tool for tool in agent.tools
            if tool["name"] in options.allowed_tools
        ]
        if options.verbose:
            logger.info(f"Filtered to {len(agent.tools)} allowed tools")

    # Store options on agent for reference
    agent.options = options

    return agent


async def query(
    task: str,
    options: ClaudeAgentOptions
) -> Dict[str, Any]:
    """
    Execute a single task with the agent.

    This provides an interface similar to the official SDK's query() function.

    Args:
        task: Task description
        options: Agent configuration options

    Returns:
        Task execution result
    """
    # Create agent
    agent = create_agent_with_options(options)

    # Execute task
    result = await agent.execute_task(
        task=task,
        max_turns=options.max_turns
    )

    return result


class ClaudeAgentClient:
    """
    Client for continuous conversations with Claude agent.

    Similar to ClaudeSDKClient in the official SDK, this maintains
    conversation context across multiple interactions.
    """

    def __init__(self, options: ClaudeAgentOptions):
        """
        Initialize agent client.

        Args:
            options: Agent configuration options
        """
        self.options = options
        self.agent = create_agent_with_options(options)
        self.conversation_history: List[Dict[str, Any]] = []

    async def query(self, task: str) -> Dict[str, Any]:
        """
        Execute a task while maintaining conversation context.

        Args:
            task: Task description

        Returns:
            Task execution result
        """
        # Execute task
        result = await self.agent.execute_task(
            task=task,
            max_turns=self.options.max_turns
        )

        # Update conversation history
        self.conversation_history.append({
            "task": task,
            "result": result.get("result", ""),
            "tool_calls": result.get("tool_calls", 0),
            "turns": result.get("turns", 0)
        })

        return result

    def reset_conversation(self):
        """Clear conversation history and reset agent."""
        self.conversation_history = []
        # Recreate agent to reset state
        self.agent = create_agent_with_options(self.options)

    def get_conversation_summary(self) -> Dict[str, Any]:
        """Get summary of conversation history."""
        total_tool_calls = sum(h.get("tool_calls", 0) for h in self.conversation_history)
        total_turns = sum(h.get("turns", 0) for h in self.conversation_history)

        return {
            "total_interactions": len(self.conversation_history),
            "total_tool_calls": total_tool_calls,
            "total_turns": total_turns,
            "history": self.conversation_history
        }
