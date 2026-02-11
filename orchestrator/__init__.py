"""
Orchestrator package for the Computer-Use Agent.

Provides the API for managing agent sessions and running tasks.
"""

from .main import app
from .schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    RunTaskRequest,
    RunTaskResponse,
    SessionStatus,
    SessionInfo
)
from .session_manager import SessionManager
from .ecs_manager import ECSManager

__all__ = [
    'app',
    'CreateSessionRequest',
    'CreateSessionResponse',
    'RunTaskRequest',
    'RunTaskResponse',
    'SessionStatus',
    'SessionInfo',
    'SessionManager',
    'ECSManager'
]
