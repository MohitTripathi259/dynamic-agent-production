"""
Session Manager.

Manages active agent sessions, including creation, lookup, and cleanup.
"""

import uuid
from datetime import datetime
from typing import Dict, Optional, List
import logging

from .schemas import SessionStatus, SessionInfo

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages active agent sessions.

    Provides methods for creating, looking up, updating, and cleaning up
    sessions. Sessions are stored in-memory (for a production system,
    you'd want to use Redis or a database).
    """

    def __init__(self):
        """Initialize the session manager."""
        self.sessions: Dict[str, SessionInfo] = {}
        logger.info("SessionManager initialized")

    def create_session(
        self,
        container_url: Optional[str] = None,
        name: Optional[str] = None,
        task_arn: Optional[str] = None
    ) -> SessionInfo:
        """
        Create a new session.

        Args:
            container_url: URL of the container's tool server
            name: Optional friendly name for the session
            task_arn: Optional ECS task ARN

        Returns:
            SessionInfo object for the new session
        """
        # Generate short session ID
        session_id = str(uuid.uuid4())[:8]

        # Ensure unique ID
        while session_id in self.sessions:
            session_id = str(uuid.uuid4())[:8]

        session = SessionInfo(
            session_id=session_id,
            name=name,
            status=SessionStatus.STARTING,
            container_url=container_url,
            task_arn=task_arn,
            created_at=datetime.utcnow(),
            task_count=0,
            last_activity=None
        )

        self.sessions[session_id] = session
        logger.info(f"Created session: {session_id}")

        return session

    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        """
        Get a session by ID.

        Args:
            session_id: Session identifier

        Returns:
            SessionInfo if found, None otherwise
        """
        return self.sessions.get(session_id)

    def update_session(self, session_id: str, **kwargs) -> Optional[SessionInfo]:
        """
        Update session attributes.

        Args:
            session_id: Session identifier
            **kwargs: Attributes to update

        Returns:
            Updated SessionInfo if found, None otherwise
        """
        if session_id not in self.sessions:
            return None

        session = self.sessions[session_id]

        # Update allowed fields
        allowed_fields = {
            'status', 'container_url', 'task_arn', 'task_count',
            'last_activity', 'name'
        }

        for key, value in kwargs.items():
            if key in allowed_fields:
                setattr(session, key, value)

        # Always update last_activity on any update
        session.last_activity = datetime.utcnow()

        logger.debug(f"Updated session {session_id}: {kwargs}")
        return session

    def increment_task_count(self, session_id: str) -> Optional[SessionInfo]:
        """
        Increment the task count for a session.

        Args:
            session_id: Session identifier

        Returns:
            Updated SessionInfo if found
        """
        if session_id in self.sessions:
            self.sessions[session_id].task_count += 1
            self.sessions[session_id].last_activity = datetime.utcnow()
            return self.sessions[session_id]
        return None

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False if not found
        """
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"Deleted session: {session_id}")
            return True
        return False

    def list_sessions(
        self,
        status: Optional[SessionStatus] = None
    ) -> List[SessionInfo]:
        """
        List all sessions, optionally filtered by status.

        Args:
            status: Optional status filter

        Returns:
            List of SessionInfo objects
        """
        sessions = list(self.sessions.values())

        if status:
            sessions = [s for s in sessions if s.status == status]

        # Sort by creation time (newest first)
        sessions.sort(key=lambda s: s.created_at, reverse=True)

        return sessions

    def get_active_count(self) -> int:
        """
        Get the count of active sessions.

        Returns:
            Number of sessions with RUNNING status
        """
        return sum(
            1 for s in self.sessions.values()
            if s.status == SessionStatus.RUNNING
        )

    def cleanup_stale_sessions(self, max_age_hours: int = 24) -> int:
        """
        Clean up sessions older than max_age_hours.

        Args:
            max_age_hours: Maximum session age in hours

        Returns:
            Number of sessions cleaned up
        """
        now = datetime.utcnow()
        stale_ids = []

        for session_id, session in self.sessions.items():
            age = now - session.created_at
            if age.total_seconds() > max_age_hours * 3600:
                stale_ids.append(session_id)

        for session_id in stale_ids:
            del self.sessions[session_id]
            logger.info(f"Cleaned up stale session: {session_id}")

        return len(stale_ids)
