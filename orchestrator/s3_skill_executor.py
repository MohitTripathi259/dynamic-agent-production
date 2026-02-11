"""
S3 Skill Executor

Executes Python-based skills loaded from S3.
"""

import json
import logging
import sys
import importlib
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def execute_s3_skill(skill_loader, skill_name: str, tool_input: Dict[str, Any]) -> str:
    """
    Execute an S3 skill by dynamically importing and running its Python code.

    Args:
        skill_loader: S3SkillLoader instance with loaded skills
        skill_name: Name of the skill to execute
        tool_input: Input parameters from Claude

    Returns:
        Execution result as string (JSON or text)
    """
    try:
        logger.info(f"Executing S3 skill: {skill_name}")

        # Get skill from cache
        skills = skill_loader.get_skills()
        if skill_name not in skills:
            return json.dumps({"error": f"Skill '{skill_name}' not found in cache"})

        skill_data = skills[skill_name]
        skill_dir = skill_loader.cache_dir / skill_name

        if not skill_dir.exists():
            return json.dumps({"error": f"Skill directory not found: {skill_dir}"})

        # Add parent cache directory to Python path to support package imports
        # This allows proper relative imports within the skill package
        cache_dir_str = str(skill_loader.cache_dir)
        if cache_dir_str not in sys.path:
            sys.path.insert(0, cache_dir_str)

        try:
            # Generic skill execution - works for all skills
            return _execute_generic_skill(skill_dir, skill_name, tool_input)

        finally:
            # Clean up sys.path
            if cache_dir_str in sys.path:
                sys.path.remove(cache_dir_str)

    except Exception as e:
        logger.error(f"Error executing S3 skill {skill_name}: {e}", exc_info=True)
        return json.dumps({"error": f"Skill execution failed: {str(e)}"})


def _execute_generic_skill(skill_dir: Path, skill_name: str, tool_input: Dict[str, Any]) -> str:
    """
    Execute a generic S3 skill with dynamic imports.
    Supports multiple skill patterns:
    1. Module with execute() or run() function
    2. Module with a Generator/Executor class (auto-detected)
    """
    try:
        # Look for main execution file
        scripts_dir = skill_dir / "scripts"

        if not scripts_dir.exists():
            return json.dumps({"error": f"Scripts directory not found for skill: {skill_name}"})

        # Try importing from the skill package (supports relative imports)
        # Try multiple import patterns to support different skill structures
        skill_module = None
        import_errors = []

        # Pattern 1: Import from skill package (uses scripts/__init__.py exports)
        try:
            module_path = f"{skill_name}.scripts"
            skill_module = importlib.import_module(module_path)
            logger.info(f"Successfully imported {module_path}")
        except ImportError as e:
            import_errors.append(f"{module_path}: {str(e)}")
            logger.info(f"Failed to import {module_path}: {e}")

        # Pattern 2: Import scripts.scripts module (if it exists)
        if skill_module is None:
            try:
                module_path = f"{skill_name}.scripts.scripts"
                skill_module = importlib.import_module(module_path)
                logger.info(f"Successfully imported {module_path}")
            except ImportError as e:
                import_errors.append(f"{module_path}: {str(e)}")
                logger.info(f"Failed to import {module_path}: {e}")

        # Pattern 3: Import scripts.main module (fallback)
        if skill_module is None:
            try:
                module_path = f"{skill_name}.scripts.main"
                skill_module = importlib.import_module(module_path)
                logger.info(f"Successfully imported {module_path}")
            except ImportError as e:
                import_errors.append(f"{module_path}: {str(e)}")
                logger.error(f"Failed to import skill module: {e}")
                return json.dumps({
                    "error": f"No main module found in scripts/ for skill: {skill_name}",
                    "details": "; ".join(import_errors)
                })

        if skill_module is None:
            return json.dumps({
                "error": f"Failed to import skill module",
                "details": str(import_error)
            })

        # Pattern 1: Look for execute() or run() function
        if hasattr(skill_module, 'execute'):
            logger.info(f"Calling skill_module.execute() for {skill_name}")
            result = skill_module.execute(tool_input)
            return _format_result(result)

        if hasattr(skill_module, 'run'):
            logger.info(f"Calling skill_module.run() for {skill_name}")
            result = skill_module.run(tool_input)
            return _format_result(result)

        # Pattern 2: Look for common generator/executor class patterns
        # Try to find a class that ends with Generator, Executor, Handler, or Processor
        generator_class = _find_executor_class(skill_module)

        if generator_class:
            logger.info(f"Found executor class: {generator_class.__name__}")
            return _execute_via_class(generator_class, tool_input)

        # No supported pattern found
        return json.dumps({
            "error": f"No supported execution pattern found in skill: {skill_name}",
            "details": "Skill must provide either: execute()/run() function, or a Generator/Executor/Handler/Processor class",
            "available_attrs": [attr for attr in dir(skill_module) if not attr.startswith('_')]
        })

    except Exception as e:
        logger.error(f"Generic skill execution error: {e}", exc_info=True)
        return json.dumps({
            "error": f"Skill execution failed: {str(e)}",
            "success": False
        })


def _find_executor_class(module):
    """
    Find an executor class in the module.
    Looks for classes ending with common patterns: Generator, Executor, Handler, Processor.
    """
    for attr_name in dir(module):
        if attr_name.startswith('_'):
            continue
        attr = getattr(module, attr_name)
        if not isinstance(attr, type):  # Skip non-classes
            continue
        # Check for common class naming patterns
        if any(attr_name.endswith(suffix) for suffix in ['Generator', 'Executor', 'Handler', 'Processor', 'Manager']):
            return attr
    return None


def _execute_via_class(executor_class, tool_input: Dict[str, Any]) -> str:
    """
    Execute a skill via an executor class.
    Handles common patterns like ReportGenerator, DataProcessor, etc.
    """
    try:
        # Instantiate the class (most classes have no-arg constructors)
        try:
            executor = executor_class()
        except TypeError:
            # If constructor requires args, try passing tool_input
            executor = executor_class(tool_input)

        # Extract parameters from tool_input
        parameters = tool_input.get("parameters", tool_input)

        # Pattern A: Class has generate() method (e.g., ReportGenerator)
        if hasattr(executor, 'generate'):
            logger.info(f"Calling {executor_class.__name__}.generate()")

            # Extract common parameters
            data = {}
            title = parameters.get("title")
            template = parameters.get("template", "generic")

            # Collect all data fields
            for key, value in parameters.items():
                if key not in ["action", "title", "template", "format"]:
                    data[key] = value

            result = executor.generate(data=data, title=title, template=template)
            return _format_result(result)

        # Pattern B: Class has execute() method
        if hasattr(executor, 'execute'):
            logger.info(f"Calling {executor_class.__name__}.execute()")
            result = executor.execute(parameters)
            return _format_result(result)

        # Pattern C: Class has run() method
        if hasattr(executor, 'run'):
            logger.info(f"Calling {executor_class.__name__}.run()")
            result = executor.run(parameters)
            return _format_result(result)

        # Pattern D: Class has process() method
        if hasattr(executor, 'process'):
            logger.info(f"Calling {executor_class.__name__}.process()")
            result = executor.process(parameters)
            return _format_result(result)

        return json.dumps({
            "error": f"Executor class {executor_class.__name__} has no supported method",
            "details": "Class must have one of: generate(), execute(), run(), or process() method",
            "available_methods": [m for m in dir(executor) if not m.startswith('_') and callable(getattr(executor, m))]
        })

    except Exception as e:
        logger.error(f"Class execution error: {e}", exc_info=True)
        return json.dumps({
            "error": f"Failed to execute via class: {str(e)}",
            "success": False
        })


def _format_result(result) -> str:
    """Format execution result as JSON string."""
    if isinstance(result, str):
        return result
    else:
        return json.dumps(result, indent=2)
