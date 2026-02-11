"""
orchestrator/agent_runner.py
----------------------------
Dynamic Agent Runner with MCP Support + S3 Skills

Loads .claude/settings.json to discover MCP servers dynamically.
Loads skills from S3 and injects into system prompt.
Works with ANY MCP server added to settings.json - fully marketplace-ready.

Architecture:
    .claude/settings.json → agent_runner.py → Multiple MCP Servers
                         ↓                   → Anthropic Claude (orchestrates)
    S3 Skills (loaded into system prompt)
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx
import anthropic
from dataclasses import dataclass

# Import S3 skill loader
try:
    from .skill_loader import get_skill_loader
    SKILL_LOADER_AVAILABLE = True
except ImportError:
    try:
        from skill_loader import get_skill_loader
        SKILL_LOADER_AVAILABLE = True
    except ImportError:
        SKILL_LOADER_AVAILABLE = False
        logger = logging.getLogger(__name__)
        logger.warning("S3 Skill Loader not available - skills will not be loaded")

logger = logging.getLogger(__name__)


@dataclass
class MCPServer:
    """Represents an MCP server configuration."""
    name: str
    url: str
    description: str
    enabled: bool
    tools: List[Dict[str, Any]] = None


class MCPClient:
    """
    MCP Client that connects to multiple MCP servers.
    Discovers tools dynamically from all enabled servers.
    """

    def __init__(self, settings_path: str = ".claude/settings.json"):
        self.settings_path = Path(settings_path)
        self.servers: Dict[str, MCPServer] = {}
        self.all_tools: List[Dict[str, Any]] = []

    def load_settings(self) -> Dict[str, Any]:
        """Load MCP server configuration from settings.json."""
        if not self.settings_path.exists():
            logger.warning(f"Settings file not found: {self.settings_path}")
            return {"mcpServers": {}}

        with open(self.settings_path, 'r') as f:
            config = json.load(f)

        logger.info(f"Loaded settings from {self.settings_path}")
        return config

    def connect_to_servers(self):
        """
        Connect to all enabled MCP servers and discover their tools.
        This makes the system dynamic - any server in settings.json is discovered.
        """
        config = self.load_settings()
        mcp_servers = config.get("mcpServers", {})

        if not mcp_servers:
            logger.warning("No MCP servers configured in settings.json")
            return

        for server_name, server_config in mcp_servers.items():
            enabled = server_config.get("enabled", True)
            if not enabled:
                logger.info(f"Skipping disabled server: {server_name}")
                continue

            url = server_config.get("httpUrl")
            if not url:
                logger.warning(f"No URL for server: {server_name}")
                continue

            logger.info(f"Connecting to MCP server '{server_name}' at {url}")

            try:
                # Discover tools from this server
                tools = self._discover_tools(url)

                server = MCPServer(
                    name=server_name,
                    url=url,
                    description=server_config.get("description", ""),
                    enabled=enabled,
                    tools=tools
                )

                self.servers[server_name] = server

                # Add tools to global list (with server reference)
                for tool in tools:
                    tool["_mcp_server"] = server_name
                    self.all_tools.append(tool)

                logger.info(f"✓ Connected to '{server_name}': {len(tools)} tools discovered")

            except Exception as e:
                logger.error(f"✗ Failed to connect to '{server_name}': {e}")

    def _make_mcp_request(self, url: str, method: str, params: Optional[Dict] = None) -> Dict:
        """Make JSON-RPC request to MCP server."""
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": 1
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                url,
                json=request,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            return response.json()

    def _discover_tools(self, url: str) -> List[Dict[str, Any]]:
        """Discover tools from an MCP server."""
        try:
            response = self._make_mcp_request(url, "tools/list")
            tools = response.get("result", {}).get("tools", [])
            return tools
        except Exception as e:
            logger.error(f"Failed to discover tools from {url}: {e}")
            return []

    def call_tool(self, tool_name: str, arguments: Optional[Dict] = None) -> Any:
        """
        Call a tool on its MCP server.
        Automatically finds the right server based on tool name.
        """
        # Find which server has this tool
        target_server = None
        for server in self.servers.values():
            tool_names = [t["name"] for t in (server.tools or [])]
            if tool_name in tool_names:
                target_server = server
                break

        if not target_server:
            raise ValueError(f"Tool '{tool_name}' not found in any MCP server")

        logger.debug(f"Calling tool '{tool_name}' on server '{target_server.name}'")

        # Call the tool via MCP
        response = self._make_mcp_request(
            target_server.url,
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}}
        )

        # Parse result
        content = response.get("result", {}).get("content", [])
        if content and content[0].get("type") == "text":
            return content[0].get("text", "")

        return str(content)

    def get_tools_for_anthropic(self) -> List[Dict[str, Any]]:
        """
        Get tools in Anthropic's tool format.
        Converts MCP tool schema to Anthropic's format.
        """
        anthropic_tools = []

        for tool in self.all_tools:
            # Convert MCP tool format to Anthropic format
            anthropic_tool = {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": tool.get("inputSchema", {
                    "type": "object",
                    "properties": {},
                    "required": []
                })
            }
            anthropic_tools.append(anthropic_tool)

        return anthropic_tools


class DynamicAgent:
    """
    Dynamic Agent that works with ANY MCP servers configured in settings.json.

    This is the core of the marketplace platform - add a new MCP server to
    settings.json and it automatically becomes available!
    """

    def __init__(
        self,
        anthropic_api_key: str,
        settings_path: str = ".claude/settings.json",
        model: str = "claude-sonnet-4-20250514",
        load_s3_skills: bool = True,
        s3_skills_bucket: str = "cerebricks-studio-agent-skills",
        s3_skills_prefix: str = "skills_phase3/"
    ):
        self.api_key = anthropic_api_key
        self.model = model
        self.anthropic_client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)

        # Initialize MCP client (loads all MCP servers from settings.json)
        self.mcp_client = MCPClient(settings_path)
        self.mcp_client.connect_to_servers()

        # Get all discovered tools
        self.tools = self.mcp_client.get_tools_for_anthropic()

        # Load S3 skills (optional)
        self.skill_loader = None
        self.skills_loaded = False

        if load_s3_skills and SKILL_LOADER_AVAILABLE:
            try:
                logger.info(f"Loading skills from S3: s3://{s3_skills_bucket}/{s3_skills_prefix}")
                self.skill_loader = get_skill_loader(
                    s3_bucket=s3_skills_bucket,
                    s3_prefix=s3_skills_prefix
                )
                skills = self.skill_loader.get_skills()
                self.skills_loaded = len(skills) > 0
                if self.skills_loaded:
                    logger.info(f"✓ Loaded {len(skills)} skills from S3: {list(skills.keys())}")

                    # Add S3 skill tool definitions to tools list (so Claude can call them)
                    skill_tools = self.skill_loader.get_skill_tool_definitions()
                    self.tools.extend(skill_tools)
                    logger.info(f"✓ Added {len(skill_tools)} S3 skills as callable tools")
                else:
                    logger.warning("No skills found in S3")
            except Exception as e:
                logger.error(f"Failed to load S3 skills: {e}")
                self.skill_loader = None

        # Track if computer tools are enabled
        self.computer_tools_enabled = False

        logger.info(f"✓ Dynamic Agent initialized")
        logger.info(f"  - MCP servers: {len(self.mcp_client.servers)}")
        logger.info(f"  - Tools discovered: {len(self.tools)}")
        logger.info(f"  - Skills loaded: {self.skills_loaded}")
        for server_name, server in self.mcp_client.servers.items():
            logger.info(f"    • {server_name}: {len(server.tools or [])} tools")

    def enable_computer_tools(self):
        """
        Enable Anthropic's computer use tools.
        These are special native tools with specific type IDs required by Anthropic API.

        Tools:
        - computer: Screen, mouse, keyboard control (custom tool)
        - bash_20250124: Execute bash commands (native)
        - text_editor_20250728: File read/write operations (native)
        """
        computer_tools = [
            {
                "type": "custom",
                "name": "computer",
                "description": "Control computer screen, mouse, and keyboard. Capture screenshots, move mouse, click, type text.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["screenshot", "mouse_move", "left_click", "right_click", "double_click", "middle_click", "type", "key", "cursor_position"],
                            "description": "Action to perform"
                        },
                        "coordinate": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "X, Y coordinates for mouse actions"
                        },
                        "text": {
                            "type": "string",
                            "description": "Text to type or key name to press"
                        }
                    },
                    "required": ["action"]
                }
            },
            {
                "type": "bash_20250124",
                "name": "bash"
            },
            {
                "type": "text_editor_20250728",
                "name": "str_replace_based_edit_tool"
            }
        ]

        # Add computer tools to the tools list (avoid duplicates)
        existing_tool_names = {tool.get("name") for tool in self.tools}
        for tool in computer_tools:
            if tool["name"] not in existing_tool_names:
                self.tools.append(tool)
            else:
                logger.debug(f"Tool '{tool['name']}' already exists, skipping")

        # Set flag to include computer use guidance in system prompt
        self.computer_tools_enabled = True

        logger.info(f"✓ Computer use tools enabled ({len(computer_tools)} tools added)")
        logger.info(f"   Note: Computer tool (screenshots, mouse/keyboard) provided via MCP server")
        return len(computer_tools)

    def _build_system_prompt(self) -> str:
        """
        Build system prompt with all available tools + S3 skills.
        Dynamically generated based on:
        1. Discovered MCP servers (tools)
        2. S3 skills (documentation + scripts)
        """
        prompt = "You are an AI agent with access to multiple tools across different MCP servers"
        if self.skills_loaded:
            prompt += " and pre-loaded skills from S3"
        prompt += ".\n\n"

        # Add S3 Skills section FIRST (for Claude's context)
        if self.skill_loader and self.skills_loaded:
            skills_section = self.skill_loader.get_skills_prompt_section()
            if skills_section:
                prompt += skills_section
                prompt += "\n\n"

        prompt += "## Available Tools\n\n"

        # Group tools by MCP server
        for server_name, server in self.mcp_client.servers.items():
            prompt += f"### {server_name}\n"
            prompt += f"{server.description}\n\n"

            if server.tools:
                prompt += "Tools:\n"
                for tool in server.tools:
                    prompt += f"- **{tool['name']}**: {tool.get('description', '')}\n"
            prompt += "\n"

        prompt += """
## Guidelines

1. **Skills**: Pre-loaded skills provide context and documentation - use them to understand capabilities
2. **Tools**: Use appropriate tools based on the task
3. **Combination**: Skills from S3 + Tools from MCP servers can be combined
4. Always verify tool execution results
5. Handle errors gracefully
"""

        # Add computer use specific guidance if enabled
        if self.computer_tools_enabled:
            prompt += """
## Computer Use Tools Best Practices

**CRITICAL: Prefer SINGLE aggregated commands over multiple iterative calls.**

### Bash Tool Efficiency:
- ✅ **DO**: Use PowerShell for complex Windows operations (counting lines, sorting files, aggregation)
- ✅ **DO**: Combine operations with pipes: `command1 | command2 | sort | head -n 3`
- ✅ **DO**: Use loops and aggregation in a single command
- ❌ **DON'T**: Call bash repeatedly for each individual file
- ❌ **DON'T**: Create temporary script files unless absolutely necessary

### Examples:

**BAD** (inefficient - multiple turns):
```bash
# Turn 1
find /c /v "" file1.py
# Turn 2
find /c /v "" file2.py
# Turn 3
find /c /v "" file3.py
# ... many more turns
```

**GOOD** (efficient - single command):
```powershell
powershell -Command "Get-ChildItem *.py -Recurse | ForEach-Object { [PSCustomObject]@{File=$_.Name; Lines=(Get-Content $_.FullName | Measure-Object -Line).Lines} } | Sort-Object Lines -Descending | Select-Object -First 3"
```

### Text Editor Tool:
- Use for viewing files, creating new files, or making targeted edits
- NOT for tasks better suited to bash (like aggregating data from multiple files)

### Computer Tool (Screen, Mouse, Keyboard):
- **screenshot**: Capture current screen state (returns base64 image)
- **mouse_move**: Move cursor to [x, y] coordinates
- **left_click**: Click at current position or specified coordinates
- **type**: Type text string
- **key**: Press keyboard key (Enter, Tab, Escape, etc.)

**Browser Automation Workflow:**
1. Take screenshot to see current state
2. Identify element positions visually
3. Move mouse to element coordinates
4. Click or type as needed
5. Take another screenshot to verify action

**Tips:**
- Always take screenshot first to understand current state
- Use coordinate [x, y] relative to 1024×768 display
- Chain actions: screenshot → mouse_move → left_click → screenshot

**Think before acting**: Can this task be solved with ONE powerful command instead of many simple ones?
"""

        prompt += """
## Execution Strategy

1. Check if a pre-loaded skill provides context for the task
2. Use appropriate MCP tools to execute actions
3. Combine multiple tools/skills for complex workflows
4. Return structured results

When you need to use a tool, invoke it with the appropriate parameters.
Multiple tools can be used in sequence to accomplish complex tasks.
"""

        return prompt

    async def execute_task(self, task: str, max_turns: int = 25) -> Dict[str, Any]:
        """
        Execute a task using available MCP tools.

        The agent will:
        1. Understand the task
        2. Decide which tools to use (from any MCP server)
        3. Execute tools
        4. Analyze results
        5. Repeat until task is complete

        Args:
            task: The task to execute
            max_turns: Maximum conversation turns

        Returns:
            Dict with result, tool_calls, status, etc.
        """
        logger.info(f"Executing task: {task[:100]}...")

        # Build system prompt with all discovered tools
        system_prompt = self._build_system_prompt()

        # Initialize conversation
        conversation_history = [
            {
                "role": "user",
                "content": task
            }
        ]

        tool_call_count = 0

        # Agent loop
        for turn in range(max_turns):
            logger.debug(f"Turn {turn + 1}/{max_turns}")

            try:
                # Call Claude with all available tools
                response = await self.anthropic_client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=system_prompt,
                    messages=conversation_history,
                    tools=self.tools if self.tools else []
                )

                # Check stop reason
                if response.stop_reason == "end_turn":
                    # Task complete
                    final_text = ""
                    for block in response.content:
                        if hasattr(block, "text"):
                            final_text += block.text

                    logger.info(f"✓ Task completed in {turn + 1} turns, {tool_call_count} tool calls")

                    return {
                        "status": "completed",
                        "result": final_text,
                        "tool_calls": tool_call_count,
                        "turns": turn + 1,
                        "mcp_servers_used": list(self.mcp_client.servers.keys())
                    }

                elif response.stop_reason == "tool_use":
                    # Execute tools
                    tool_results = []

                    for block in response.content:
                        if block.type == "tool_use":
                            tool_call_count += 1
                            tool_name = block.name
                            tool_input = block.input

                            logger.info(f"  → Calling tool: {tool_name}")

                            try:
                                # Call tool via MCP client
                                result = self.mcp_client.call_tool(tool_name, tool_input)

                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": str(result)
                                })

                                logger.debug(f"  ✓ Tool result: {str(result)[:100]}...")

                            except Exception as e:
                                logger.error(f"  ✗ Tool execution failed: {e}")
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": f"Error: {str(e)}",
                                    "is_error": True
                                })

                    # Add assistant response and tool results to conversation
                    conversation_history.append({
                        "role": "assistant",
                        "content": response.content
                    })

                    conversation_history.append({
                        "role": "user",
                        "content": tool_results
                    })

                else:
                    # Unexpected stop reason
                    logger.warning(f"Unexpected stop reason: {response.stop_reason}")
                    break

            except Exception as e:
                logger.error(f"Error in agent loop: {e}", exc_info=True)
                return {
                    "status": "error",
                    "error": str(e),
                    "tool_calls": tool_call_count,
                    "turns": turn + 1
                }

        # Max turns reached
        logger.warning(f"Max turns ({max_turns}) reached")
        return {
            "status": "max_turns_reached",
            "result": "Task incomplete - max turns reached",
            "tool_calls": tool_call_count,
            "turns": max_turns
        }
