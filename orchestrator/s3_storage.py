"""
S3 Storage utilities for screenshots and artifacts.

Uploads screenshots from container to S3 for persistence.
"""

import boto3
import os
import logging
from datetime import datetime
from typing import Optional, List, Dict
import httpx

logger = logging.getLogger(__name__)

# S3 Configuration
S3_BUCKET = os.getenv("S3_SCREENSHOT_BUCKET", "computer-use-screenshots-061051242847")
S3_REGION = os.getenv("AWS_REGION", "us-west-2")

# Initialize S3 client
s3_client = boto3.client("s3", region_name=S3_REGION)


def generate_s3_key(session_id: str, filename: str) -> str:
    """Generate S3 key with date-based partitioning."""
    now = datetime.utcnow()
    date_prefix = now.strftime("%Y/%m/%d")
    timestamp = now.strftime("%H%M%S")

    # Clean filename
    clean_filename = filename.replace("/workspace/", "").replace("/", "_")

    return f"screenshots/{date_prefix}/{session_id}/{timestamp}_{clean_filename}"


async def fetch_screenshot_from_container(
    container_url: str,
    http_client: httpx.AsyncClient
) -> Optional[bytes]:
    """Fetch current screenshot from container."""
    try:
        response = await http_client.get(
            f"{container_url}/tools/screenshot",
            timeout=30.0
        )
        if response.status_code == 200:
            data = response.json()
            if "image_base64" in data:
                import base64
                return base64.b64decode(data["image_base64"])
    except Exception as e:
        logger.error(f"Failed to fetch screenshot from container: {e}")
    return None


def upload_screenshot_to_s3(
    image_bytes: bytes,
    session_id: str,
    filename: str = "screenshot.png"
) -> Optional[str]:
    """
    Upload screenshot bytes to S3.

    Returns:
        Presigned URL if successful, None otherwise
    """
    try:
        s3_key = generate_s3_key(session_id, filename)

        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=image_bytes,
            ContentType="image/png",
            Metadata={
                "session_id": session_id,
                "uploaded_at": datetime.utcnow().isoformat()
            }
        )

        logger.info(f"Screenshot uploaded to S3: {s3_key}")

        # Generate presigned URL (valid for 1 hour)
        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": S3_BUCKET,
                "Key": s3_key
            },
            ExpiresIn=3600  # 1 hour
        )

        return presigned_url

    except Exception as e:
        logger.error(f"Failed to upload screenshot to S3: {e}")
        return None


async def upload_task_screenshots(
    container_url: str,
    session_id: str,
    http_client: httpx.AsyncClient
) -> List[str]:
    """
    Fetch and upload screenshots after task completion.

    Returns:
        List of S3 URLs for uploaded screenshots
    """
    uploaded_urls = []

    # Fetch current screenshot from container
    screenshot_bytes = await fetch_screenshot_from_container(container_url, http_client)

    if screenshot_bytes:
        url = upload_screenshot_to_s3(
            screenshot_bytes,
            session_id,
            "final_screenshot.png"
        )
        if url:
            uploaded_urls.append(url)

    return uploaded_urls


def list_session_screenshots(session_id: str) -> List[Dict]:
    """List all screenshots for a session from S3."""
    try:
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=f"screenshots/",
        )

        screenshots = []
        for obj in response.get("Contents", []):
            if session_id in obj["Key"]:
                screenshots.append({
                    "key": obj["Key"],
                    "url": f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{obj['Key']}",
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat()
                })

        return screenshots

    except Exception as e:
        logger.error(f"Failed to list screenshots: {e}")
        return []


def generate_presigned_url(s3_key: str, expiration: int = 3600) -> Optional[str]:
    """Generate a presigned URL for accessing a screenshot."""
    try:
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": S3_BUCKET,
                "Key": s3_key
            },
            ExpiresIn=expiration
        )
        return url
    except Exception as e:
        logger.error(f"Failed to generate presigned URL: {e}")
        return None
