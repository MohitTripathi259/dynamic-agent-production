"""
Claude Computer-Use Agent.

Uses Anthropic's built-in computer-use tool types directly.
Tool calls are executed against the ECS container's HTTP API.

Flow:
  Anthropic API  →  tool_use (computer/bash/text_editor)
                 →  execute on container (ECS URL)
                 →  tool_result back to API
                 →  repeat until done
"""

import os
import json
import logging
import time
import uuid
import asyncio
from typing import Any, Dict, Optional, Callable, List

import anthropic
import httpx

from .config import config

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger("COMPUTER_USE_AGENT")


# ── Anthropic built-in computer-use tool types ───────────────────────
# These are the ONLY tool IDs needed — provided by Anthropic, not us.
# Ref: https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool

TOOLS = [
    {
        "type": "computer_20250124",
        "name": "computer",
        "display_width_px": config.display_width,
        "display_height_px": config.display_height,
        "display_number": 1,
    },
    {
        "type": "bash_20250124",
        "name": "bash",
    },
    {
        "type": "text_editor_20250728",
        "name": "str_replace_based_edit_tool",
    },
    {
        "name": "browser",
        "description": "Control a Playwright-powered Chromium browser for web navigation and interaction. Use this tool to navigate to URLs, interact with web pages, and capture browser state. The browser runs in a headless environment with full JavaScript support.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["navigate", "click", "type", "screenshot", "scroll", "get_content", "wait", "go_back", "go_forward", "refresh", "get_url", "get_title", "evaluate"],
                    "description": "The browser action to perform"
                },
                "params": {
                    "type": "object",
                    "description": "Parameters for the action. For navigate: {url, wait_until?, timeout?}. For click: {selector?, text?, x?, y?}. For type: {text, selector?, clear?}. For scroll: {direction, amount?}. For get_content: {text?, html?, links?}. For wait: {selector?, seconds?, navigation?}. For evaluate: {script}.",
                    "default": {}
                }
            },
            "required": ["action"]
        }
    },
]

MAX_TURNS = 100  # safety limit (increased for complex CI workflows)


class ComputerUseAgent:
    """
    Claude agent using Anthropic's built-in computer-use tools.

    The only configuration it needs is the ECS container URL
    (where actions are physically executed).
    """

    def __init__(
        self,
        container_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        print("\n" + "=" * 70)
        print("  COMPUTER USE AGENT — INITIALIZING")
        print("=" * 70)

        self.api_key = api_key or config.anthropic_api_key
        if not self.api_key:
            print("[ERROR] ANTHROPIC_API_KEY is missing!")
            raise ValueError("ANTHROPIC_API_KEY is required")
        print(f"  [OK] API key loaded (ends with ...{self.api_key[-6:]})")

        self.container_url = container_url or config.container_url
        print(f"  [OK] Container URL: {self.container_url}")

        self.model = model or config.model
        print(f"  [OK] Model: {self.model}")

        self.anthropic = anthropic.AsyncAnthropic(api_key=self.api_key)
        print(f"  [OK] Anthropic async client created")

        self.http = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0))
        print(f"  [OK] HTTP client created (timeout=180s, connect=10s)")

        self.conversation_history: List[Dict] = []
        self.last_tool_count = 0  # Track tool calls from last run

        print(f"  [OK] Tools registered: {[t['name'] for t in TOOLS]}")
        print(f"  [OK] Display: {config.display_width}x{config.display_height}")
        print(f"  [OK] Max turns: {MAX_TURNS}")
        print("=" * 70)
        print("  AGENT READY")
        print("=" * 70 + "\n")

        logger.info(f"Agent ready  model={self.model}  container={self.container_url}")

    # ── Public API ───────────────────────────────────────────────────

    async def run(
        self,
        task: str,
        on_iteration: Optional[Callable[[int, str], None]] = None,
        send_approach_callback: Optional[Callable[[Dict], None]] = None,
    ) -> str:
        """
        Execute *task* using Anthropic's built-in computer-use tools.

        The loop:
          1. Send messages to Claude with the 3 tool types
          2. Claude returns tool_use blocks
          3. Execute each tool call against the container
          4. Send tool_results back
          5. Repeat until Claude stops requesting tools
        """
        start = time.time()
        cid = f"AGENT-{uuid.uuid4().hex[:8].upper()}"

        print("\n" + "#" * 70)
        print(f"  NEW TASK  [{cid}]")
        print("#" * 70)
        print(f"  Task: {task[:200]}")
        print(f"  Model: {self.model}")
        print(f"  Container: {self.container_url}")
        print(f"  Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("#" * 70 + "\n")

        logger.info(f"[{cid}] Task: {task[:120]}...")

        messages: List[Dict] = [{"role": "user", "content": task}]
        tool_count = 0

        for turn in range(MAX_TURNS):
            print(f"\n{'─' * 60}")
            print(f"  TURN {turn + 1}/{MAX_TURNS}  [{cid}]")
            print(f"{'─' * 60}")
            print(f"  Messages in conversation: {len(messages)}")
            print(f"  Total tool calls so far: {tool_count}")
            print(f"  Elapsed: {time.time() - start:.1f}s")

            # ── Call Anthropic API ────────────────────────────────
            print(f"\n  >> Calling Anthropic API ({self.model})...")
            print(f"     Beta flags: ['computer-use-2025-01-24']")
            print(f"     Tools: {[t['name'] for t in TOOLS]}")
            print(f"     Max tokens: 4096")

            api_start = time.time()
            try:
                response = await self.anthropic.beta.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    tools=TOOLS,
                    messages=messages,
                    betas=["computer-use-2025-01-24"],
                    system=(
                        "You are a computer-use agent with a Linux desktop and Chromium browser.\n\n"
                        "BROWSER NAVIGATION (EASY METHOD):\n"
                        "A 'browse' command is available for easy navigation:\n"
                        "1. In bash, run: browse https://example.com\n"
                        "2. Wait 5 seconds: sleep 5\n"
                        "3. Take screenshot to see the loaded page\n"
                        "4. Scroll if needed and take more screenshots\n\n"
                        "Example workflow:\n"
                        "  bash: browse https://www.google.com\n"
                        "  bash: sleep 5\n"
                        "  computer: screenshot\n"
                        "  computer: scroll down (if needed)\n"
                        "  computer: screenshot\n\n"
                        "DATA EXTRACTION (use bash for reliability):\n"
                        "- For extracting structured data (titles, text), use 'curl <url>' + grep/sed\n"
                        "- Bash extraction is more reliable than visual parsing\n\n"
                        "Available tools:\n"
                        "- computer: screenshot, click(x,y), type text, key press, scroll\n"
                        "- bash: all shell commands (curl, grep, sleep, date, file ops, BROWSE)\n"
                        "- str_replace_based_edit_tool: create/edit/view files in /workspace/\n\n"
                        "WORKFLOW: Use browse+screenshots for VISUAL verification, curl for DATA extraction.\n"
                        "Be methodical. Always wait after navigation before screenshots."
                    ),
                )
                api_elapsed = time.time() - api_start
                print(f"  << API responded in {api_elapsed:.1f}s")
                print(f"     Stop reason: {response.stop_reason}")
                print(f"     Content blocks: {len(response.content)}")
                print(f"     Usage: input={response.usage.input_tokens} output={response.usage.output_tokens} tokens")
            except Exception as api_err:
                api_elapsed = time.time() - api_start
                print(f"  [API ERROR] after {api_elapsed:.1f}s: {api_err}")
                logger.error(f"[{cid}] API call failed: {api_err}")
                raise

            # Log content blocks
            for i, block in enumerate(response.content):
                if hasattr(block, "text"):
                    text_preview = block.text[:150].replace("\n", " ")
                    print(f"     Block[{i}] text: \"{text_preview}...\"")
                elif block.type == "tool_use":
                    print(f"     Block[{i}] tool_use: {block.name} (id={block.id[:12]}...)")
                    print(f"                input: {json.dumps(block.input)[:200]}")
                else:
                    print(f"     Block[{i}] type={block.type}")

            # Add assistant turn to conversation
            messages.append({"role": "assistant", "content": response.content})

            # ── If Claude is done (no more tool calls) ────────────
            if response.stop_reason != "tool_use":
                text = "".join(
                    block.text for block in response.content
                    if hasattr(block, "text")
                )
                elapsed = time.time() - start

                print(f"\n{'*' * 60}")
                print(f"  TASK COMPLETE  [{cid}]")
                print(f"{'*' * 60}")
                print(f"  Stop reason: {response.stop_reason}")
                print(f"  Total turns: {turn + 1}")
                print(f"  Total tool calls: {tool_count}")
                print(f"  Total time: {elapsed:.1f}s")
                print(f"  Final response length: {len(text)} chars")
                print(f"  Final response preview: {text[:300]}...")
                print(f"{'*' * 60}\n")

                logger.info(f"[{cid}] Done in {elapsed:.1f}s  tools={tool_count}")
                self.conversation_history.append({"role": "user", "content": task})
                self.conversation_history.append({"role": "assistant", "content": text})
                self.last_tool_count = tool_count  # Store for orchestrator
                return text or "Task completed."

            # ── Execute each tool call ────────────────────────────
            tool_results = []
            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            print(f"\n  Tool calls to execute this turn: {len(tool_blocks)}")

            for idx, block in enumerate(tool_blocks):
                if block.type != "tool_use":
                    continue

                tool_count += 1
                print(f"\n  {'>' * 40}")
                print(f"  TOOL CALL #{tool_count}  (turn {turn + 1}, item {idx + 1}/{len(tool_blocks)})")
                print(f"  {'>' * 40}")
                print(f"    Tool name: {block.name}")
                print(f"    Tool ID:   {block.id}")
                print(f"    Input:     {json.dumps(block.input, indent=2)[:500]}")

                logger.info(
                    f"[{cid}] Tool #{tool_count}: {block.name} "
                    f"{json.dumps(block.input)[:100]}"
                )
                if on_iteration:
                    on_iteration(tool_count, f"executing_{block.name}")

                tool_start = time.time()
                result = await self._execute_tool(block.name, block.input)
                tool_elapsed = time.time() - tool_start

                # Log the result
                if isinstance(result, list) and result and isinstance(result[0], dict) and result[0].get("type") == "image":
                    print(f"    Result: [screenshot image, base64 len={len(result[0]['source']['data'])}]")
                elif isinstance(result, str):
                    result_preview = result[:300].replace("\n", "\\n")
                    print(f"    Result: \"{result_preview}\"")
                else:
                    print(f"    Result: {str(result)[:300]}")
                print(f"    Execution time: {tool_elapsed:.2f}s")
                print(f"  {'<' * 40}")

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            print(f"\n  Sending {len(tool_results)} tool result(s) back to Claude...")
            messages.append({"role": "user", "content": tool_results})

        # Safety: hit MAX_TURNS
        elapsed = time.time() - start
        print(f"\n[WARNING] Hit max turns ({MAX_TURNS}) after {elapsed:.1f}s")
        logger.warning(f"[{cid}] Hit max turns ({MAX_TURNS})")
        return "Reached maximum turns. Task may be incomplete."

    # ── Tool dispatch ────────────────────────────────────────────────

    async def _execute_tool(self, name: str, tool_input: Dict) -> Any:
        """Route a tool call to the correct container endpoint."""
        print(f"    [dispatch] Routing tool '{name}' to container {self.container_url}")
        try:
            if name == "computer":
                return await self._exec_computer(tool_input)
            elif name == "bash":
                return await self._exec_bash(tool_input)
            elif name == "str_replace_based_edit_tool":
                return await self._exec_editor(tool_input)
            elif name == "browser":
                return await self._exec_browser(tool_input)
            else:
                print(f"    [dispatch] Unknown tool: {name}")
                return f"Unknown tool: {name}"
        except Exception as e:
            print(f"    [dispatch] ERROR executing {name}: {e}")
            logger.error(f"Tool error ({name}): {e}")
            return f"Error: {e}"

    # ── computer tool ────────────────────────────────────────────────

    async def _exec_computer(self, inp: Dict) -> Any:
        action = inp.get("action")
        print(f"    [computer] Action: {action}")

        if action == "screenshot":
            print(f"    [computer] Taking screenshot via GET {self.container_url}/tools/screenshot")
            resp = await self.http.get(f"{self.container_url}/tools/screenshot")
            resp.raise_for_status()
            data = resp.json()
            b64_len = len(data.get("image_base64", ""))
            print(f"    [computer] Screenshot received: base64 length={b64_len}, "
                  f"dimensions={data.get('width', '?')}x{data.get('height', '?')}")
            return [{
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": data["image_base64"],
                },
            }]

        if action in ("left_click", "right_click", "double_click"):
            coord = inp.get("coordinate", [0, 0])
            button = "right" if action == "right_click" else "left"
            clicks = 2 if action == "double_click" else 1
            print(f"    [computer] {action}: coordinate=({coord[0]}, {coord[1]}), "
                  f"button={button}, clicks={clicks}")
            for click_num in range(clicks):
                print(f"    [computer] Sending click {click_num + 1}/{clicks} to "
                      f"POST {self.container_url}/tools/browser")
                await self.http.post(
                    f"{self.container_url}/tools/browser",
                    json={"action": "click", "params": {"x": coord[0], "y": coord[1], "button": button}},
                )
            print(f"    [computer] {action} completed at ({coord[0]}, {coord[1]})")
            return f"{action} at ({coord[0]}, {coord[1]})"

        if action == "type":
            text = inp.get("text", "")
            print(f"    [computer] Typing text: \"{text[:80]}{'...' if len(text) > 80 else ''}\" "
                  f"(length={len(text)})")
            print(f"    [computer] POST {self.container_url}/tools/browser")
            await self.http.post(
                f"{self.container_url}/tools/browser",
                json={"action": "type", "params": {"text": text}},
            )
            print(f"    [computer] Type completed")
            return f"Typed text"

        if action == "key":
            key = inp.get("key", "")
            mapped = {"Return": "Enter", "BackSpace": "Backspace", "space": " "}.get(key, key)
            payload = mapped if len(mapped) == 1 else f"[{mapped}]"
            print(f"    [computer] Key press: '{key}' → mapped='{mapped}' → payload='{payload}'")
            print(f"    [computer] POST {self.container_url}/tools/browser")
            await self.http.post(
                f"{self.container_url}/tools/browser",
                json={"action": "type", "params": {"text": payload}},
            )
            print(f"    [computer] Key press completed")
            return f"Pressed key: {key}"

        if action == "scroll":
            direction = inp.get("scroll_direction", "down")
            raw_amount = inp.get("scroll_amount", 3)
            amount = raw_amount * 100
            print(f"    [computer] Scroll: direction={direction}, raw_amount={raw_amount}, "
                  f"pixels={amount}")
            print(f"    [computer] POST {self.container_url}/tools/browser")
            await self.http.post(
                f"{self.container_url}/tools/browser",
                json={"action": "scroll", "params": {"direction": direction, "amount": amount}},
            )
            print(f"    [computer] Scroll completed")
            return f"Scrolled {direction}"

        if action == "mouse_move":
            coord = inp.get("coordinate", [0, 0])
            print(f"    [computer] Mouse move to ({coord[0]}, {coord[1]})")
            return f"Moved mouse to ({coord[0]}, {coord[1]})"

        if action == "cursor_position":
            print(f"    [computer] Getting cursor position")
            return "Cursor position: (960, 540)"

        if action == "left_click_drag":
            print(f"    [computer] Left click drag")
            return "Drag executed"

        if action == "wait":
            print(f"    [computer] Waiting 1 second...")
            await asyncio.sleep(1)
            print(f"    [computer] Wait completed")
            return "Waited 1 second"

        # NEW: Add URL navigation support (navigates via Playwright browser tool)
        if action == "navigate" or action == "goto":
            url = inp.get("url", "")
            if not url:
                return "Error: URL is required for navigation"
            print(f"    [computer] Navigating to URL: {url}")
            print(f"    [computer] POST {self.container_url}/tools/browser (navigate action)")
            try:
                resp = await self.http.post(
                    f"{self.container_url}/tools/browser",
                    json={"action": "navigate", "params": {"url": url, "wait_until": "networkidle", "timeout": 30000}},
                    timeout=35.0
                )
                resp.raise_for_status()
                data = resp.json()
                print(f"    [computer] Navigation completed: {data.get('url', url)}")
                # Wait additional 2 seconds for page to fully render
                await asyncio.sleep(2)
                print(f"    [computer] Page render wait completed")
                return f"Navigated to {url}"
            except Exception as e:
                print(f"    [computer] Navigation failed: {e}")
                return f"Error navigating to {url}: {str(e)}"

        print(f"    [computer] Unknown action: {action}")
        return f"Unknown computer action: {action}"

    # ── bash tool ────────────────────────────────────────────────────

    async def _exec_bash(self, inp: Dict) -> str:
        if inp.get("restart"):
            print(f"    [bash] Shell restart requested")
            return "Shell restarted"

        command = inp.get("command", "")
        print(f"    [bash] Executing command: \"{command[:200]}\"")
        print(f"    [bash] POST {self.container_url}/tools/bash")

        resp = await self.http.post(
            f"{self.container_url}/tools/bash",
            json={"command": command, "timeout": 120},
        )
        resp.raise_for_status()
        data = resp.json()

        print(f"    [bash] Return code: {data.get('return_code', '?')}")
        if data.get("stdout"):
            stdout_preview = data["stdout"][:300].replace("\n", "\\n")
            print(f"    [bash] STDOUT: \"{stdout_preview}\"")
        if data.get("stderr"):
            stderr_preview = data["stderr"][:300].replace("\n", "\\n")
            print(f"    [bash] STDERR: \"{stderr_preview}\"")

        parts = []
        if data.get("stdout"):
            parts.append(data["stdout"])
        if data.get("stderr"):
            parts.append(f"STDERR:\n{data['stderr']}")
        if data.get("return_code", 0) != 0:
            parts.append(f"\nExit code: {data['return_code']}")

        result = "\n".join(parts) if parts else "(no output)"
        print(f"    [bash] Final result length: {len(result)} chars")
        return result

    # ── browser tool ─────────────────────────────────────────────────

    async def _exec_browser(self, inp: Dict) -> str:
        """Execute browser action via container's browser tool."""
        action = inp.get("action", "")
        params = inp.get("params", {})

        print(f"    [browser] Action: {action}")
        print(f"    [browser] Params: {json.dumps(params, indent=2)[:200]}")
        print(f"    [browser] POST {self.container_url}/tools/browser")

        try:
            resp = await self.http.post(
                f"{self.container_url}/tools/browser",
                json={"action": action, "params": params},
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()

            status = data.get("status", "unknown")
            print(f"    [browser] Status: {status}")

            if status == "error":
                error_msg = data.get("error", "Unknown browser error")
                print(f"    [browser] ERROR: {error_msg}")
                return f"Browser action '{action}' failed: {error_msg}"

            # Handle successful response
            result_data = data.get("data", {})

            # Special handling for screenshot action (returns base64 image)
            if action == "screenshot" and "image_base64" in result_data:
                print(f"    [browser] Screenshot captured (base64 len={len(result_data['image_base64'])})")
                # Return structured response for screenshots
                return json.dumps({
                    "success": True,
                    "action": "screenshot",
                    "message": "Screenshot captured successfully",
                    "image_available": True
                })

            # For other actions, return formatted result
            if result_data:
                result_preview = json.dumps(result_data, indent=2)[:500]
                print(f"    [browser] Result: {result_preview}")
                return json.dumps({"success": True, "action": action, "data": result_data})
            else:
                return json.dumps({"success": True, "action": action, "message": f"{action} completed"})

        except Exception as e:
            error_msg = f"Browser tool error: {str(e)}"
            print(f"    [browser] EXCEPTION: {error_msg}")
            return error_msg

    # ── text_editor tool ─────────────────────────────────────────────

    async def _exec_editor(self, inp: Dict) -> str:
        command = inp.get("command")
        path = inp.get("path", "")
        if not path.startswith("/workspace"):
            path = f"/workspace/{path.lstrip('/')}"

        print(f"    [editor] Command: {command}")
        print(f"    [editor] Path: {path}")

        if command == "view":
            print(f"    [editor] Reading file via POST {self.container_url}/tools/file/read")
            resp = await self.http.post(
                f"{self.container_url}/tools/file/read", json={"path": path},
            )
            if resp.status_code == 404:
                print(f"    [editor] File not found: {path}")
                return f"Error: File not found: {path}"
            resp.raise_for_status()
            content = resp.json().get("content", "")
            lines = content.split("\n")
            print(f"    [editor] File read OK: {len(lines)} lines, {len(content)} chars")
            print(f"    [editor] Content preview: {content[:200]}")
            return "\n".join(f"{i+1:4d}\t{line}" for i, line in enumerate(lines))

        if command == "create":
            file_text = inp.get("file_text", "")
            print(f"    [editor] Creating file: {path} ({len(file_text)} chars)")
            print(f"    [editor] POST {self.container_url}/tools/file/write")
            resp = await self.http.post(
                f"{self.container_url}/tools/file/write",
                json={"path": path, "content": file_text},
            )
            resp.raise_for_status()
            print(f"    [editor] File created successfully: {path}")
            return f"Created file: {path}"

        if command == "str_replace":
            old = inp.get("old_str", "")
            new = inp.get("new_str", "")
            print(f"    [editor] str_replace in {path}")
            print(f"    [editor]   old_str: \"{old[:100]}\"")
            print(f"    [editor]   new_str: \"{new[:100]}\"")
            print(f"    [editor] Reading file first...")

            read = await self.http.post(
                f"{self.container_url}/tools/file/read", json={"path": path},
            )
            if read.status_code == 404:
                print(f"    [editor] File not found: {path}")
                return f"Error: File not found: {path}"
            read.raise_for_status()
            content = read.json().get("content", "")
            print(f"    [editor] File read: {len(content)} chars")

            if old not in content:
                print(f"    [editor] ERROR: old_str not found in file")
                return "Error: String not found in file"
            if content.count(old) > 1:
                count = content.count(old)
                print(f"    [editor] ERROR: old_str appears {count} times (must be unique)")
                return f"Error: String appears {count} times. Be more specific."

            print(f"    [editor] Replacing and writing back...")
            await self.http.post(
                f"{self.container_url}/tools/file/write",
                json={"path": path, "content": content.replace(old, new, 1)},
            )
            print(f"    [editor] Replacement complete in {path}")
            return f"Replaced text in {path}"

        if command == "insert":
            idx = inp.get("insert_line", 0)
            new_str = inp.get("new_str", "")
            print(f"    [editor] Insert at line {idx} in {path}")
            print(f"    [editor] Text to insert: \"{new_str[:100]}\"")

            read = await self.http.post(
                f"{self.container_url}/tools/file/read", json={"path": path},
            )
            if read.status_code == 404:
                print(f"    [editor] File not found: {path}")
                return f"Error: File not found: {path}"
            read.raise_for_status()

            lines = read.json().get("content", "").split("\n")
            print(f"    [editor] File has {len(lines)} lines, inserting at {idx}")

            if idx <= 0:
                lines.insert(0, new_str)
            elif idx >= len(lines):
                lines.append(new_str)
            else:
                lines.insert(idx, new_str)

            await self.http.post(
                f"{self.container_url}/tools/file/write",
                json={"path": path, "content": "\n".join(lines)},
            )
            print(f"    [editor] Insert complete at line {idx}")
            return f"Inserted text at line {idx}"

        if command == "undo_edit":
            print(f"    [editor] Undo requested (not supported)")
            return "Undo is not supported."

        print(f"    [editor] Unknown command: {command}")
        return f"Unknown editor command: {command}"

    # ── Helpers ──────────────────────────────────────────────────────

    def reset_conversation(self):
        print(f"  [agent] Conversation history reset (was {len(self.conversation_history)} entries)")
        self.conversation_history = []

    def get_conversation_history(self) -> List[Dict]:
        print(f"  [agent] Returning conversation history ({len(self.conversation_history)} entries)")
        return self.conversation_history.copy()

    async def cleanup(self):
        print(f"  [agent] Cleaning up HTTP client...")
        await self.http.aclose()
        print(f"  [agent] Cleanup complete")
        logger.info("Agent cleaned up")


__all__ = ["ComputerUseAgent"]
