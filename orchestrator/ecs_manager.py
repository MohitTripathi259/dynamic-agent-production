"""
ECS Task Manager.

Manages ECS tasks for spawning compute containers. Supports both
local development (using docker-compose) and AWS ECS deployment.
"""

import boto3
import os
import asyncio
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)


class ECSManager:
    """
    Manages ECS tasks for agent compute environments.

    In local mode, returns localhost URLs.
    In AWS mode, spawns actual ECS Fargate tasks.
    """

    def __init__(self):
        """Initialize the ECS manager."""
        self.use_local = os.getenv("USE_LOCAL_CONTAINER", "true").lower() == "true"
        self.local_container_url = os.getenv(
            "LOCAL_CONTAINER_URL",
            "http://localhost:8080"
        )

        logger.info(f"ECSManager initialized (local_mode={self.use_local})")

        if not self.use_local:
            self._init_ecs_client()

    def _init_ecs_client(self):
        """Initialize AWS ECS client and configuration."""
        self.region = os.getenv("AWS_REGION", "us-east-1")
        self.ecs = boto3.client('ecs', region_name=self.region)

        self.cluster = os.getenv("ECS_CLUSTER", "computer-use-cluster")
        self.task_definition = os.getenv("ECS_TASK_DEFINITION", "computer-use-agent")

        # Network configuration
        subnets = os.getenv("ECS_SUBNETS", "")
        security_groups = os.getenv("ECS_SECURITY_GROUPS", "")

        self.subnets = [s.strip() for s in subnets.split(",") if s.strip()]
        self.security_groups = [s.strip() for s in security_groups.split(",") if s.strip()]

        if not self.subnets or not self.security_groups:
            logger.warning(
                "ECS networking not configured. Set ECS_SUBNETS and "
                "ECS_SECURITY_GROUPS environment variables."
            )

    async def spawn_container(self, session_id: str) -> Dict:
        """
        Spawn a new container for an agent session.

        Args:
            session_id: Session identifier for tagging

        Returns:
            Dict with:
            - container_url: URL to access the container
            - task_arn: ECS task ARN (None for local mode)
        """
        if self.use_local:
            logger.info(f"Using local container for session {session_id}")
            return {
                "container_url": self.local_container_url,
                "task_arn": None
            }

        return await self._spawn_ecs_task(session_id)

    async def _spawn_ecs_task(self, session_id: str) -> Dict:
        """Spawn an ECS Fargate task."""
        logger.info(f"Spawning ECS task for session {session_id}")

        if not self.subnets or not self.security_groups:
            raise ValueError(
                "ECS networking not configured. "
                "Set ECS_SUBNETS and ECS_SECURITY_GROUPS."
            )

        try:
            response = self.ecs.run_task(
                cluster=self.cluster,
                taskDefinition=self.task_definition,
                launchType='FARGATE',
                networkConfiguration={
                    'awsvpcConfiguration': {
                        'subnets': self.subnets,
                        'securityGroups': self.security_groups,
                        'assignPublicIp': 'ENABLED'
                    }
                },
                overrides={
                    'containerOverrides': [{
                        'name': 'computer-use-container',
                        'environment': [
                            {'name': 'SESSION_ID', 'value': session_id}
                        ]
                    }]
                },
                tags=[
                    {'key': 'SessionId', 'value': session_id},
                    {'key': 'Application', 'value': 'computer-use-agent'}
                ]
            )

            if not response.get('tasks'):
                failures = response.get('failures', [])
                raise Exception(f"Failed to start task: {failures}")

            task = response['tasks'][0]
            task_arn = task['taskArn']

            logger.info(f"Task started: {task_arn}")

            # Wait for task to be running and get IP
            container_url = await self._wait_for_task(task_arn)

            return {
                "container_url": container_url,
                "task_arn": task_arn
            }

        except Exception as e:
            logger.error(f"Failed to spawn ECS task: {e}")
            raise

    async def _wait_for_task(
        self,
        task_arn: str,
        max_wait_seconds: int = 120,
        poll_interval: int = 5
    ) -> str:
        """
        Wait for ECS task to be running and return its URL.

        Args:
            task_arn: Task ARN to wait for
            max_wait_seconds: Maximum wait time
            poll_interval: Seconds between polls

        Returns:
            URL to access the task's container
        """
        logger.info(f"Waiting for task {task_arn} to start...")

        elapsed = 0
        while elapsed < max_wait_seconds:
            response = self.ecs.describe_tasks(
                cluster=self.cluster,
                tasks=[task_arn]
            )

            if not response.get('tasks'):
                raise Exception("Task not found")

            task = response['tasks'][0]
            status = task.get('lastStatus')

            logger.debug(f"Task status: {status}")

            if status == 'RUNNING':
                # Get the private IP from the network attachment
                for attachment in task.get('attachments', []):
                    if attachment.get('type') == 'ElasticNetworkInterface':
                        for detail in attachment.get('details', []):
                            if detail.get('name') == 'privateIPv4Address':
                                ip = detail['value']
                                url = f"http://{ip}:8080"
                                logger.info(f"Task running at {url}")
                                return url

                raise Exception("Could not find task IP address")

            elif status in ['STOPPED', 'DEPROVISIONING']:
                reason = task.get('stoppedReason', 'Unknown')
                raise Exception(f"Task stopped: {reason}")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise Exception(f"Timeout waiting for task after {max_wait_seconds}s")

    async def stop_container(self, task_arn: str) -> bool:
        """
        Stop an ECS task.

        Args:
            task_arn: Task ARN to stop

        Returns:
            True if successful
        """
        if self.use_local:
            logger.info("Local mode - no container to stop")
            return True

        if not task_arn:
            return False

        try:
            logger.info(f"Stopping task: {task_arn}")

            self.ecs.stop_task(
                cluster=self.cluster,
                task=task_arn,
                reason='Session ended'
            )

            logger.info(f"Task stopped: {task_arn}")
            return True

        except Exception as e:
            logger.error(f"Failed to stop task: {e}")
            return False

    async def get_task_status(self, task_arn: str) -> Optional[str]:
        """
        Get the status of an ECS task.

        Args:
            task_arn: Task ARN to check

        Returns:
            Task status string or None if not found
        """
        if self.use_local or not task_arn:
            return "RUNNING" if self.use_local else None

        try:
            response = self.ecs.describe_tasks(
                cluster=self.cluster,
                tasks=[task_arn]
            )

            if response.get('tasks'):
                return response['tasks'][0].get('lastStatus')

            return None

        except Exception as e:
            logger.error(f"Failed to get task status: {e}")
            return None

    def is_local_mode(self) -> bool:
        """Check if running in local mode."""
        return self.use_local
