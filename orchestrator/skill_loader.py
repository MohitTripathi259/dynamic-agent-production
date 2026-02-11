"""
S3 Skill Loader for Marketplace Platform

Downloads skills from S3, caches them in memory, and makes them available to:
1. DynamicAgent system prompt (for Claude context)
2. Skills MCP Server (for tool discovery)

S3 Structure:
  s3://{bucket}/{prefix}/
    <skill-name>/
      skill.md              - Skill documentation with YAML frontmatter
      config_schema.json    - JSON schema for configuration
      __init__.py           - Python package init
      scripts/              - Python modules
        *.py                - Implementation files

Example:
  s3://cerebricks-studio-agent-skills/skills_phase3/
    pdf_report_generator/
      skill.md
      config_schema.json
      scripts/generator.py
"""

import os
import json
import logging
import time
from typing import Dict, List, Optional
from pathlib import Path
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3SkillLoader:
    """
    Loads skills from S3 and caches them in memory.

    Skills are downloaded on first access and cached for subsequent requests.
    Supports cache refresh for updated skills.
    """

    def __init__(
        self,
        s3_bucket: str,
        s3_prefix: str,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_region: str = "us-west-2",
        cache_dir: Optional[str] = None
    ):
        """
        Initialize S3 Skill Loader.

        Args:
            s3_bucket: S3 bucket name (e.g., 'cerebricks-studio-agent-skills')
            s3_prefix: S3 key prefix (e.g., 'skills_phase3/')
            aws_access_key_id: AWS access key (optional, uses IAM role if None)
            aws_secret_access_key: AWS secret key (optional)
            aws_region: AWS region
            cache_dir: Local cache directory (default: .claude/skills_cache/)
        """
        self.s3_bucket = s3_bucket
        self.s3_prefix = s3_prefix.rstrip('/') + '/'
        self.aws_region = aws_region

        # Initialize S3 client
        if aws_access_key_id and aws_secret_access_key:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                region_name=aws_region
            )
        else:
            # Use IAM role or environment credentials
            self.s3_client = boto3.client('s3', region_name=aws_region)

        # Cache directory
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path.cwd() / ".claude" / "skills_cache"

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache
        self._skills_cache: Dict[str, Dict] = {}
        self._last_refresh: Optional[float] = None

        logger.info(f"S3SkillLoader initialized: s3://{s3_bucket}/{s3_prefix}")

    def get_available_skills(self) -> List[str]:
        """
        List all available skill names in S3.

        Returns:
            List of skill names (folder names)
        """
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.s3_bucket,
                Prefix=self.s3_prefix,
                Delimiter='/'
            )

            skill_names = []
            for prefix in response.get('CommonPrefixes', []):
                skill_folder = prefix['Prefix'].replace(self.s3_prefix, '').rstrip('/')
                if skill_folder:
                    skill_names.append(skill_folder)

            logger.info(f"Found {len(skill_names)} skills in S3: {skill_names}")
            return skill_names

        except ClientError as e:
            logger.error(f"Error listing skills from S3: {e}")
            return []

    def download_skill(self, skill_name: str) -> bool:
        """
        Download a skill from S3 to local cache.

        Args:
            skill_name: Name of the skill to download

        Returns:
            True if successful, False otherwise
        """
        skill_cache_dir = self.cache_dir / skill_name
        skill_cache_dir.mkdir(parents=True, exist_ok=True)

        skill_s3_prefix = f"{self.s3_prefix}{skill_name}/"

        try:
            # List all objects in skill folder
            response = self.s3_client.list_objects_v2(
                Bucket=self.s3_bucket,
                Prefix=skill_s3_prefix
            )

            if 'Contents' not in response:
                logger.warning(f"No files found for skill: {skill_name}")
                return False

            # Download each file
            for obj in response['Contents']:
                s3_key = obj['Key']
                relative_path = s3_key.replace(skill_s3_prefix, '')

                if not relative_path:  # Skip the folder itself
                    continue

                local_file = skill_cache_dir / relative_path
                local_file.parent.mkdir(parents=True, exist_ok=True)

                logger.debug(f"Downloading: {s3_key} -> {local_file}")
                self.s3_client.download_file(
                    self.s3_bucket,
                    s3_key,
                    str(local_file)
                )

            logger.info(f"Downloaded skill: {skill_name}")
            return True

        except ClientError as e:
            logger.error(f"Error downloading skill {skill_name}: {e}")
            return False

    def load_skill_content(self, skill_name: str) -> Optional[Dict]:
        """
        Load skill content from cache.

        Returns a dict with:
        - name: Skill name
        - description: From YAML frontmatter
        - skill_md: Full skill.md content
        - config_schema: JSON schema (if exists)
        - scripts: Dict of script name -> content

        Args:
            skill_name: Name of the skill

        Returns:
            Dict with skill content or None if error
        """
        skill_dir = self.cache_dir / skill_name

        if not skill_dir.exists():
            logger.warning(f"Skill not in cache: {skill_name}")
            return None

        skill_data = {
            "name": skill_name,
            "description": "",
            "skill_md": "",
            "config_schema": None,
            "scripts": {},
            "metadata": {}
        }

        # Read skill.md
        skill_md_path = skill_dir / "skill.md"
        if skill_md_path.exists():
            with open(skill_md_path, 'r', encoding='utf-8') as f:
                content = f.read()
                skill_data["skill_md"] = content

                # Parse YAML frontmatter
                if content.startswith('---'):
                    try:
                        import yaml
                        parts = content.split('---', 2)
                        if len(parts) >= 3:
                            frontmatter = yaml.safe_load(parts[1])
                            skill_data["metadata"] = frontmatter
                            skill_data["description"] = frontmatter.get("description", "")
                    except Exception as e:
                        logger.warning(f"Error parsing frontmatter for {skill_name}: {e}")

        # Read config_schema.json
        config_schema_path = skill_dir / "config_schema.json"
        if config_schema_path.exists():
            with open(config_schema_path, 'r', encoding='utf-8') as f:
                skill_data["config_schema"] = json.load(f)

        # Read scripts
        scripts_dir = skill_dir / "scripts"
        if scripts_dir.exists():
            for script_file in scripts_dir.glob("*.py"):
                if script_file.name == "__init__.py":
                    continue

                with open(script_file, 'r', encoding='utf-8') as f:
                    script_content = f.read()
                    skill_data["scripts"][script_file.name] = script_content

        return skill_data

    def preload_skills(self, force_refresh: bool = False) -> Dict[str, Dict]:
        """
        Pre-load all skills into memory cache.

        Args:
            force_refresh: If True, re-download from S3 even if cached

        Returns:
            Dict mapping skill name to skill data
        """
        start_time = time.time()

        # Get available skills from S3
        skill_names = self.get_available_skills()

        logger.info(f"Pre-loading {len(skill_names)} skills from S3...")

        loaded_count = 0
        for skill_name in skill_names:
            # Check if already cached locally
            skill_cache_dir = self.cache_dir / skill_name / "skill.md"

            if force_refresh or not skill_cache_dir.exists():
                logger.info(f"Downloading skill: {skill_name}")
                if not self.download_skill(skill_name):
                    logger.error(f"Failed to download skill: {skill_name}")
                    continue
            else:
                logger.debug(f"Using cached skill: {skill_name}")

            # Load skill content
            skill_data = self.load_skill_content(skill_name)
            if skill_data:
                self._skills_cache[skill_name] = skill_data
                loaded_count += 1
                logger.info(f"Loaded skill: {skill_name}")

        elapsed = time.time() - start_time
        self._last_refresh = time.time()

        logger.info(f"Pre-loaded {loaded_count}/{len(skill_names)} skills in {elapsed:.2f}s")

        return self._skills_cache

    def get_skills(self, force_refresh: bool = False) -> Dict[str, Dict]:
        """
        Get all skills (cached or fresh).

        Args:
            force_refresh: If True, re-download from S3

        Returns:
            Dict mapping skill name to skill data
        """
        if not self._skills_cache or force_refresh:
            return self.preload_skills(force_refresh=force_refresh)
        return self._skills_cache

    def get_skills_prompt_section(self) -> str:
        """
        Generate system prompt section with full skill content.

        This creates a formatted section that can be injected into
        the Claude system prompt to give context about available skills.

        Returns:
            Formatted markdown section for system prompt
        """
        skills = self.get_skills()

        if not skills:
            return ""

        skill_names = list(skills.keys())

        prompt_section = f"""
## Available Skills ({len(skill_names)} skills loaded from S3)

The following skills are available for use. Each skill can be invoked via MCP or used as context for generating responses.

**Skills**: {', '.join(skill_names)}

---

"""

        # Add each skill's full documentation
        for skill_name, skill_data in skills.items():
            prompt_section += f"### SKILL: {skill_name}\n\n"

            # Add metadata
            if skill_data["metadata"]:
                metadata = skill_data["metadata"]
                prompt_section += f"**Description**: {metadata.get('description', 'N/A')}\n"
                prompt_section += f"**Version**: {metadata.get('version', 'N/A')}\n"
                prompt_section += f"**Allowed Tools**: {', '.join(metadata.get('allowed-tools', []))}\n\n"

            # Add skill documentation
            prompt_section += skill_data["skill_md"]
            prompt_section += "\n\n"

            # Add scripts (if any)
            if skill_data["scripts"]:
                prompt_section += "#### Available Scripts\n\n"
                for script_name, script_content in skill_data["scripts"].items():
                    prompt_section += f"**{script_name}**:\n"
                    prompt_section += f"```python\n# {script_name}\n{script_content[:500]}...\n```\n\n"

            prompt_section += "---\n\n"

        return prompt_section

    def get_skill_tool_definitions(self) -> List[Dict]:
        """
        Convert skills to MCP tool definitions.

        Each skill becomes an MCP tool that can be discovered and invoked.

        Returns:
            List of MCP tool definitions
        """
        skills = self.get_skills()
        tool_definitions = []

        for skill_name, skill_data in skills.items():
            metadata = skill_data.get("metadata", {})

            # Base tool definition (Anthropic custom tool format)
            tool_def = {
                "type": "custom",  # Required by Anthropic API
                "name": skill_name,
                "description": metadata.get("description", f"Skill: {skill_name}"),
                "input_schema": {  # snake_case required by Anthropic
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "Action to perform with this skill"
                        },
                        "parameters": {
                            "type": "object",
                            "description": "Parameters for the skill action"
                        }
                    },
                    "required": ["action"]
                }
            }

            # If config_schema exists, use it for parameters
            if skill_data.get("config_schema"):
                tool_def["input_schema"]["properties"]["parameters"] = skill_data["config_schema"]

            tool_definitions.append(tool_def)

        return tool_definitions


# Singleton instance (for caching across invocations)
_skill_loader_instance: Optional[S3SkillLoader] = None


def get_skill_loader(
    s3_bucket: str = "cerebricks-studio-agent-skills",
    s3_prefix: str = "skills_phase3/",
    force_new: bool = False
) -> S3SkillLoader:
    """
    Get singleton skill loader instance.

    Args:
        s3_bucket: S3 bucket name
        s3_prefix: S3 key prefix
        force_new: Create new instance even if one exists

    Returns:
        S3SkillLoader instance
    """
    global _skill_loader_instance

    if _skill_loader_instance is None or force_new:
        _skill_loader_instance = S3SkillLoader(
            s3_bucket=s3_bucket,
            s3_prefix=s3_prefix
        )

    return _skill_loader_instance


# CLI for testing
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    # Test loading skills from S3
    loader = S3SkillLoader(
        s3_bucket="cerebricks-studio-agent-skills",
        s3_prefix="skills_phase3/"
    )

    print("\nAvailable skills:")
    print(loader.get_available_skills())

    print("\nPre-loading skills...")
    skills = loader.preload_skills(force_refresh=True)

    print(f"\nLoaded {len(skills)} skills:")
    for name, data in skills.items():
        print(f"\n--- {name} ---")
        print(f"Description: {data['description']}")
        print(f"Scripts: {list(data['scripts'].keys())}")
        print(f"Content preview: {data['skill_md'][:200]}...")

    print("\n\nSystem Prompt Section:")
    print("=" * 60)
    prompt_section = loader.get_skills_prompt_section()
    print(prompt_section[:1000])
    print("...")

    print("\n\nMCP Tool Definitions:")
    print("=" * 60)
    tools = loader.get_skill_tool_definitions()
    for tool in tools:
        print(json.dumps(tool, indent=2))
