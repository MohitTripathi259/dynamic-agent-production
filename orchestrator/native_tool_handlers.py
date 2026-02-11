"""
Native Anthropic Tool Handlers

Execution handlers for Anthropic's native computer use tools:
- computer_20241022: Screen, mouse, keyboard control
- bash_20250124: Execute shell commands
- text_editor_20250728: File read/write operations
"""

import subprocess
import os
import logging
import base64
import datetime
import httpx
from pathlib import Path
from typing import Dict, Any, Optional
from io import BytesIO

logger = logging.getLogger(__name__)

# Try to import computer control libraries (optional)
try:
    import pyautogui
    import mss
    COMPUTER_CONTROL_AVAILABLE = True
    logger.info("✓ Computer control libraries available (pyautogui, mss)")
except ImportError:
    COMPUTER_CONTROL_AVAILABLE = False
    logger.warning("⚠ Computer control libraries not available. Install: pip install pyautogui mss pillow")


class NativeToolHandler:
    """Handler for Anthropic's native computer use tools"""

    def __init__(self, working_dir: Optional[str] = None):
        """
        Initialize handler

        Args:
            working_dir: Working directory for command execution (default: current dir)
        """
        self.working_dir = working_dir or os.getcwd()
        logger.info(f"Native tool handler initialized (working_dir: {self.working_dir})")

    def handle_bash(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute bash command

        Args:
            tool_input: {"command": "ls -la", "timeout": 30}

        Returns:
            {"output": "...", "exit_code": 0}
        """
        command = tool_input.get("command", "")
        timeout = tool_input.get("timeout", 30)

        if not command:
            return {
                "error": "No command provided",
                "exit_code": 1
            }

        logger.info(f"Executing bash command: {command[:100]}...")

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"

            logger.info(f"Command completed with exit code: {result.returncode}")

            return {
                "output": output,
                "exit_code": result.returncode
            }

        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out after {timeout}s")
            return {
                "error": f"Command timed out after {timeout} seconds",
                "exit_code": 124
            }
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return {
                "error": str(e),
                "exit_code": 1
            }

    def handle_text_editor(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle text editor operations

        Args:
            tool_input: {
                "command": "view" | "create" | "str_replace" | "insert",
                "path": "file.txt",
                "file_text": "content",
                "old_str": "old",
                "new_str": "new",
                ...
            }

        Returns:
            {"output": "...", "success": true}
        """
        command = tool_input.get("command", "")
        path = tool_input.get("path", "")

        if not command:
            return {"error": "No command provided", "success": False}

        if not path:
            return {"error": "No path provided", "success": False}

        # Resolve path relative to working directory
        full_path = Path(self.working_dir) / path

        logger.info(f"Text editor: {command} on {path}")

        try:
            if command == "view":
                return self._view_file(full_path)
            elif command == "create":
                return self._create_file(full_path, tool_input.get("file_text", ""))
            elif command == "str_replace":
                return self._str_replace(
                    full_path,
                    tool_input.get("old_str", ""),
                    tool_input.get("new_str", "")
                )
            elif command == "insert":
                return self._insert(
                    full_path,
                    tool_input.get("insert_line", 0),
                    tool_input.get("new_str", "")
                )
            else:
                return {"error": f"Unknown command: {command}", "success": False}

        except Exception as e:
            logger.error(f"Text editor operation failed: {e}")
            return {"error": str(e), "success": False}

    def _view_file(self, path: Path) -> Dict[str, Any]:
        """Read and return file contents"""
        if path.is_dir():
            # List directory contents
            try:
                files = list(path.iterdir())
                output = f"Directory: {path}\n\n"
                output += "\n".join(f"  {f.name}{'/' if f.is_dir() else ''}" for f in sorted(files))
                return {"output": output, "success": True}
            except Exception as e:
                return {"error": f"Cannot list directory: {e}", "success": False}

        if not path.exists():
            return {"error": f"File not found: {path}", "success": False}

        try:
            content = path.read_text(encoding='utf-8')
            return {"output": content, "success": True}
        except Exception as e:
            return {"error": f"Cannot read file: {e}", "success": False}

    def _create_file(self, path: Path, content: str) -> Dict[str, Any]:
        """Create or overwrite file with content"""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            return {
                "output": f"File created: {path} ({len(content)} chars)",
                "success": True
            }
        except Exception as e:
            return {"error": f"Cannot create file: {e}", "success": False}

    def _str_replace(self, path: Path, old_str: str, new_str: str) -> Dict[str, Any]:
        """Replace string in file"""
        if not path.exists():
            return {"error": f"File not found: {path}", "success": False}

        try:
            content = path.read_text(encoding='utf-8')

            if old_str not in content:
                return {
                    "error": f"String not found in file: {old_str[:50]}...",
                    "success": False
                }

            new_content = content.replace(old_str, new_str, 1)  # Replace first occurrence
            path.write_text(new_content, encoding='utf-8')

            return {
                "output": f"Replaced in {path}",
                "success": True
            }
        except Exception as e:
            return {"error": f"Cannot modify file: {e}", "success": False}

    def _insert(self, path: Path, line_num: int, text: str) -> Dict[str, Any]:
        """Insert text at line number"""
        if not path.exists():
            return {"error": f"File not found: {path}", "success": False}

        try:
            lines = path.read_text(encoding='utf-8').splitlines(keepends=True)

            if line_num < 0 or line_num > len(lines):
                return {
                    "error": f"Invalid line number: {line_num} (file has {len(lines)} lines)",
                    "success": False
                }

            lines.insert(line_num, text + "\n")
            path.write_text("".join(lines), encoding='utf-8')

            return {
                "output": f"Inserted at line {line_num} in {path}",
                "success": True
            }
        except Exception as e:
            return {"error": f"Cannot insert text: {e}", "success": False}

    def handle_computer(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle computer use operations (screen, mouse, keyboard)

        Actions supported:
        - screenshot: Capture screen
        - mouse_move: Move cursor to coordinates
        - left_click: Click at current position
        - right_click: Right click
        - double_click: Double click
        - middle_click: Middle click
        - type: Type text string
        - key: Press key(s)
        - cursor_position: Get current cursor position

        Args:
            tool_input: {
                "action": "screenshot" | "mouse_move" | "left_click" | "type" | ...,
                "coordinate": [x, y],  # for mouse_move, left_click_drag
                "text": "string",      # for type action
                "key": "Enter"         # for key action
            }

        Returns:
            {
                "output": "...",
                "base64_image": "..." (for screenshot),
                "success": true
            }
        """
        action = tool_input.get("action", "")

        if not action:
            return {"error": "No action provided", "success": False}

        logger.info(f"Computer tool: {action}")

        # Computer use container URL (Docker container on localhost:8080)
        container_url = os.getenv("COMPUTER_USE_CONTAINER_URL", "http://localhost:8080")

        try:
            if action == "screenshot":
                return self._computer_screenshot(container_url)

            elif action == "mouse_move":
                coordinate = tool_input.get("coordinate", [0, 0])
                return self._computer_mouse_move(container_url, coordinate)

            elif action == "left_click":
                coordinate = tool_input.get("coordinate")
                return self._computer_click(container_url, "left", coordinate)

            elif action == "right_click":
                coordinate = tool_input.get("coordinate")
                return self._computer_click(container_url, "right", coordinate)

            elif action == "double_click":
                coordinate = tool_input.get("coordinate")
                return self._computer_click(container_url, "double", coordinate)

            elif action == "middle_click":
                coordinate = tool_input.get("coordinate")
                return self._computer_click(container_url, "middle", coordinate)

            elif action == "type":
                text = tool_input.get("text", "")
                return self._computer_type(container_url, text)

            elif action == "key":
                key = tool_input.get("text", "")  # Anthropic uses "text" field for key name
                return self._computer_key(container_url, key)

            elif action == "cursor_position":
                return self._computer_cursor_position(container_url)

            else:
                return {"error": f"Unknown computer action: {action}", "success": False}

        except Exception as e:
            logger.error(f"Computer tool operation failed: {e}")
            return {"error": str(e), "success": False}

    def _computer_screenshot(self, container_url: str) -> Dict[str, Any]:
        """Capture screenshot (local or container)"""
        # Try local screenshot first (Windows with pyautogui/mss)
        if COMPUTER_CONTROL_AVAILABLE:
            try:
                with mss.mss() as sct:
                    # Capture all monitors
                    screenshot = sct.grab(sct.monitors[1])

                    # Convert to PIL Image
                    from PIL import Image
                    img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)

                    # Save to file instead of returning base64 (to avoid token limit)
                    import datetime
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    screenshot_path = Path(self.working_dir) / f"screenshot_{timestamp}.png"
                    img.save(screenshot_path)

                    logger.info(f"Screenshot saved to: {screenshot_path}")

                    return {
                        "output": f"Screenshot captured and saved to {screenshot_path.name}. Resolution: {img.width}x{img.height} pixels. The screenshot shows your current desktop state.",
                        "path": str(screenshot_path),
                        "width": img.width,
                        "height": img.height,
                        "success": True
                    }
            except Exception as e:
                logger.warning(f"Local screenshot failed, trying container: {e}")

        # Fallback to container (if available)
        try:
            response = httpx.get(f"{container_url}/screenshot", timeout=10)
            response.raise_for_status()

            data = response.json()
            return {
                "output": "Screenshot captured",
                "base64_image": data.get("base64_image", ""),
                "success": True
            }
        except Exception as e:
            return {"error": f"Screenshot failed: {e}", "success": False}

    def _computer_mouse_move(self, container_url: str, coordinate: list) -> Dict[str, Any]:
        """Move mouse to coordinates (local or container)"""
        x, y = coordinate[0], coordinate[1]

        # Try local mouse control first
        if COMPUTER_CONTROL_AVAILABLE:
            try:
                pyautogui.moveTo(x, y, duration=0.2)
                return {
                    "output": f"Moved mouse to ({x}, {y})",
                    "success": True
                }
            except Exception as e:
                logger.warning(f"Local mouse move failed, trying container: {e}")

        # Fallback to container
        try:
            response = httpx.post(
                f"{container_url}/mouse/move",
                json={"x": x, "y": y},
                timeout=5
            )
            response.raise_for_status()

            return {
                "output": f"Moved mouse to ({x}, {y})",
                "success": True
            }
        except Exception as e:
            return {"error": f"Mouse move failed: {e}", "success": False}

    def _computer_click(
        self,
        container_url: str,
        button: str,
        coordinate: Optional[list] = None
    ) -> Dict[str, Any]:
        """Click mouse at coordinate or current position (local or container)"""
        # Try local mouse control first
        if COMPUTER_CONTROL_AVAILABLE:
            try:
                if coordinate:
                    x, y = coordinate[0], coordinate[1]
                    pyautogui.click(x, y, button=button if button != "double" else "left",
                                   clicks=2 if button == "double" else 1)
                    location = f" at ({x}, {y})"
                else:
                    pyautogui.click(button=button if button != "double" else "left",
                                   clicks=2 if button == "double" else 1)
                    location = ""

                return {
                    "output": f"{button.capitalize()} click{location}",
                    "success": True
                }
            except Exception as e:
                logger.warning(f"Local click failed, trying container: {e}")

        # Fallback to container
        try:
            payload = {"button": button}
            if coordinate:
                payload["x"] = coordinate[0]
                payload["y"] = coordinate[1]

            response = httpx.post(
                f"{container_url}/mouse/click",
                json=payload,
                timeout=5
            )
            response.raise_for_status()

            location = f" at ({coordinate[0]}, {coordinate[1]})" if coordinate else ""
            return {
                "output": f"{button.capitalize()} click{location}",
                "success": True
            }
        except Exception as e:
            return {"error": f"Click failed: {e}", "success": False}

    def _computer_type(self, container_url: str, text: str) -> Dict[str, Any]:
        """Type text string (local or container)"""
        # Try local keyboard control first
        if COMPUTER_CONTROL_AVAILABLE:
            try:
                pyautogui.write(text, interval=0.05)
                return {
                    "output": f"Typed: {text[:50]}{'...' if len(text) > 50 else ''}",
                    "success": True
                }
            except Exception as e:
                logger.warning(f"Local type failed, trying container: {e}")

        # Fallback to container
        try:
            response = httpx.post(
                f"{container_url}/keyboard/type",
                json={"text": text},
                timeout=10
            )
            response.raise_for_status()

            return {
                "output": f"Typed: {text[:50]}{'...' if len(text) > 50 else ''}",
                "success": True
            }
        except Exception as e:
            return {"error": f"Type failed: {e}", "success": False}

    def _computer_key(self, container_url: str, key: str) -> Dict[str, Any]:
        """Press keyboard key (local or container)"""
        # Try local keyboard control first
        if COMPUTER_CONTROL_AVAILABLE:
            try:
                # Map common key names
                key_map = {
                    "Return": "enter",
                    "return": "enter",
                    "BackSpace": "backspace",
                    "Tab": "tab",
                    "Escape": "esc",
                    "Delete": "delete",
                    "space": " "
                }
                pyautogui.press(key_map.get(key, key.lower()))
                return {
                    "output": f"Pressed key: {key}",
                    "success": True
                }
            except Exception as e:
                logger.warning(f"Local key press failed, trying container: {e}")

        # Fallback to container
        try:
            response = httpx.post(
                f"{container_url}/keyboard/key",
                json={"key": key},
                timeout=5
            )
            response.raise_for_status()

            return {
                "output": f"Pressed key: {key}",
                "success": True
            }
        except Exception as e:
            return {"error": f"Key press failed: {e}", "success": False}

    def _computer_cursor_position(self, container_url: str) -> Dict[str, Any]:
        """Get current cursor position (local or container)"""
        # Try local mouse control first
        if COMPUTER_CONTROL_AVAILABLE:
            try:
                x, y = pyautogui.position()
                return {
                    "output": f"Cursor at ({x}, {y})",
                    "x": x,
                    "y": y,
                    "success": True
                }
            except Exception as e:
                logger.warning(f"Local cursor position failed, trying container: {e}")

        # Fallback to container
        try:
            response = httpx.get(f"{container_url}/mouse/position", timeout=5)
            response.raise_for_status()

            data = response.json()
            x, y = data.get("x", 0), data.get("y", 0)

            return {
                "output": f"Cursor at ({x}, {y})",
                "x": x,
                "y": y,
                "success": True
            }
        except Exception as e:
            return {"error": f"Get cursor position failed: {e}", "success": False}


# Singleton instance
_handler_instance: Optional[NativeToolHandler] = None


def get_handler(working_dir: Optional[str] = None) -> NativeToolHandler:
    """Get singleton handler instance"""
    global _handler_instance
    if _handler_instance is None:
        _handler_instance = NativeToolHandler(working_dir)
    return _handler_instance
