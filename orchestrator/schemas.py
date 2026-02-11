"""
Pydantic schemas for the Orchestrator API.

Defines request/response models for all API endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class SessionStatus(str, Enum):
    """Status of an agent session."""
    STARTING = "starting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


class CreateSessionRequest(BaseModel):
    """Request to create a new agent session."""
    name: Optional[str] = Field(
        None,
        description="Optional friendly name for the session"
    )
    container_config: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional container configuration overrides"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "name": "my-research-session"
            }
        }


class CreateSessionResponse(BaseModel):
    """Response with created session details."""
    session_id: str = Field(..., description="Unique session identifier")
    status: SessionStatus = Field(..., description="Current session status")
    container_url: Optional[str] = Field(
        None,
        description="URL of the container's tool server"
    )
    created_at: datetime = Field(..., description="Session creation timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "abc12345",
                "status": "running",
                "container_url": "http://localhost:8080",
                "created_at": "2025-01-20T12:00:00Z"
            }
        }


class RunTaskRequest(BaseModel):
    """Request to run a task in a session."""
    task: str = Field(
        ...,
        description="Task description for the agent",
        min_length=1,
        max_length=10000
    )

    class Config:
        json_schema_extra = {
            "example": {
                "task": "Navigate to example.com and take a screenshot"
            }
        }


class DynamicTaskRequest(BaseModel):
    """Request to run a task using Dynamic Agent with MCP servers."""
    task: str = Field(
        ...,
        description="Task description for the agent",
        min_length=1,
        max_length=10000
    )
    enable_mcp_servers: Optional[bool] = Field(
        True,
        description="Whether to load and use MCP servers from settings.json"
    )
    max_turns: Optional[int] = Field(
        25,
        description="Maximum conversation turns"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "task": "Query retail products and create a report",
                "enable_mcp_servers": True,
                "max_turns": 25
            }
        }


class DynamicTaskResponse(BaseModel):
    """Response from Dynamic Agent task execution."""
    task: str = Field(..., description="Original task description")
    result: str = Field(..., description="Final result from the agent")
    status: str = Field(..., description="Task completion status")
    tool_calls: int = Field(0, description="Number of tool calls made")
    turns: int = Field(0, description="Number of conversation turns used")
    mcp_servers_used: List[str] = Field(
        default_factory=list,
        description="List of MCP servers that were used"
    )
    error: Optional[str] = Field(None, description="Error message if failed")

    class Config:
        json_schema_extra = {
            "example": {
                "task": "Query retail products",
                "result": "Found 150 products in the snacks category...",
                "status": "completed",
                "tool_calls": 5,
                "turns": 3,
                "mcp_servers_used": ["computer-use", "retail-data"]
            }
        }


class TaskResult(BaseModel):
    """Result from a completed task."""
    output: str = Field(..., description="Final agent output")
    iterations: int = Field(..., description="Number of iterations used")
    tool_calls: List[str] = Field(
        default_factory=list,
        description="List of tools called during execution"
    )


class RunTaskResponse(BaseModel):
    """Response from running a task."""
    session_id: str = Field(..., description="Session ID")
    task: str = Field(..., description="Original task description")
    result: str = Field(..., description="Final result from the agent")
    tool_calls: int = Field(0, description="Number of tool calls made (approximate)")
    status: str = Field(..., description="Task completion status")
    error: Optional[str] = Field(None, description="Error message if failed")
    screenshot_urls: List[str] = Field(
        default_factory=list,
        description="URLs of screenshots uploaded to S3"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "abc12345",
                "task": "Navigate to example.com",
                "result": "Successfully navigated to example.com and captured the page.",
                "tool_calls": 5,
                "status": "completed",
                "screenshot_urls": ["https://bucket.s3.region.amazonaws.com/screenshots/..."]
            }
        }


class SessionInfo(BaseModel):
    """Detailed information about a session."""
    session_id: str = Field(..., description="Unique session identifier")
    name: Optional[str] = Field(None, description="Friendly name")
    status: SessionStatus = Field(..., description="Current status")
    container_url: Optional[str] = Field(None, description="Container URL")
    task_arn: Optional[str] = Field(None, description="ECS task ARN (if using ECS)")
    created_at: datetime = Field(..., description="Creation timestamp")
    task_count: int = Field(0, description="Number of tasks executed")
    last_activity: Optional[datetime] = Field(None, description="Last activity timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "abc12345",
                "name": "research-session",
                "status": "running",
                "container_url": "http://localhost:8080",
                "created_at": "2025-01-20T12:00:00Z",
                "task_count": 3,
                "last_activity": "2025-01-20T12:15:00Z"
            }
        }


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service health status")
    version: str = Field("1.0.0", description="API version")
    sessions_active: int = Field(0, description="Number of active sessions")


class ContainerHealthResponse(BaseModel):
    """Container health check response."""
    session_id: str
    container_url: str
    healthy: bool
    details: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")
    code: Optional[str] = Field(None, description="Error code")
