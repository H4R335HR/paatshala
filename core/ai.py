"""
AI module for Gemini-powered features.
Handles rubric generation, and future scoring/feedback functionality.
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from core.persistence import get_config

logger = logging.getLogger(__name__)

# Output directory for rubrics
RUBRICS_DIR = "rubrics"


def get_gemini_client():
    """
    Initialize and return a Gemini client.
    
    Returns:
        Gemini GenerativeModel or None if API key not configured
    """
    api_key = get_config("gemini_api_key")
    if not api_key:
        logger.warning("Gemini API key not configured")
        return None
    
    try:
        from google import genai
        
        client = genai.Client(api_key=api_key)
        return client
    except ImportError:
        logger.error("google-genai package not installed")
        return None
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}")
        return None


def generate_rubric(task_description: str) -> Optional[List[Dict[str, Any]]]:
    """
    Generate a scoring rubric from a task description using Gemini API.
    
    Args:
        task_description: The task description text
    
    Returns:
        List of rubric criteria dicts with keys: criterion, description, weight_percent
        Returns None on error
    """
    client = get_gemini_client()
    if not client:
        return None
    
    prompt = f"""Analyze this task description and create a scoring rubric for evaluating student submissions.

Task Description:
{task_description}

Create a rubric with 3-6 clear criteria. Each criterion should have:
- criterion: A short name (e.g., "Code Quality", "Functionality", "Documentation")
- description: What specifically to evaluate (1-2 sentences)
- weight_percent: Percentage weight (integer, all must sum to exactly 100)

Return ONLY a valid JSON array, no markdown formatting, no explanation. Example format:
[
  {{"criterion": "Code Quality", "description": "Clean, readable, well-structured code", "weight_percent": 30}},
  {{"criterion": "Functionality", "description": "Program works correctly as specified", "weight_percent": 40}}
]"""

    try:
        # Get model from config or use default
        model = get_config("gemini_model") or "gemini-2.5-flash"
        
        response = client.models.generate_content(
            model=model,
            contents=prompt
        )
        
        # Parse the response - it should be JSON
        response_text = response.text.strip()
        
        # Remove any markdown code fencing if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            # Remove first and last lines (code fence markers)
            response_text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        
        rubric = json.loads(response_text)
        
        # Validate the rubric structure
        if not isinstance(rubric, list):
            logger.error("Rubric response is not a list")
            return None
        
        # Validate each criterion
        required_keys = {"criterion", "description", "weight_percent"}
        for item in rubric:
            if not isinstance(item, dict):
                logger.error("Rubric item is not a dict")
                return None
            if not required_keys.issubset(item.keys()):
                logger.error(f"Rubric item missing required keys: {item}")
                return None
        
        # Validate weights sum to 100
        total_weight = sum(item.get("weight_percent", 0) for item in rubric)
        if total_weight != 100:
            logger.warning(f"Rubric weights sum to {total_weight}, not 100. Normalizing...")
            # Normalize weights
            if total_weight > 0:
                for item in rubric:
                    item["weight_percent"] = round(item["weight_percent"] * 100 / total_weight)
                # Adjust rounding errors
                diff = 100 - sum(item["weight_percent"] for item in rubric)
                if diff != 0 and rubric:
                    rubric[0]["weight_percent"] += diff
        
        return rubric
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response as JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Error generating rubric: {e}")
        return None


def refine_rubric(current_rubric: List[Dict], instructions: str, task_description: str = "") -> Optional[List[Dict[str, Any]]]:
    """
    Refine an existing rubric based on user instructions using Gemini API.
    
    Args:
        current_rubric: The current rubric criteria list
        instructions: User instructions for how to modify the rubric
        task_description: Optional task description for context
    
    Returns:
        Modified rubric criteria list or None on error
    """
    client = get_gemini_client()
    if not client:
        return None
    
    # Format current rubric as readable text
    rubric_text = json.dumps(current_rubric, indent=2)
    
    prompt = f"""You have an existing scoring rubric that needs to be modified based on user instructions.

Current Rubric:
{rubric_text}

{"Task Description (for context):" + chr(10) + task_description + chr(10) if task_description else ""}
User Instructions:
{instructions}

Modify the rubric according to the user's instructions. Keep the same JSON structure:
- criterion: A short name
- description: What to evaluate (1-2 sentences)
- weight_percent: Percentage weight (all must sum to exactly 100)

Return ONLY a valid JSON array with the modified rubric, no markdown formatting, no explanation."""

    try:
        model = get_config("gemini_model") or "gemini-2.5-flash"
        
        response = client.models.generate_content(
            model=model,
            contents=prompt
        )
        
        response_text = response.text.strip()
        
        # Remove markdown code fencing if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        
        rubric = json.loads(response_text)
        
        if not isinstance(rubric, list):
            logger.error("Refined rubric response is not a list")
            return None
        
        # Validate structure
        required_keys = {"criterion", "description", "weight_percent"}
        for item in rubric:
            if not isinstance(item, dict) or not required_keys.issubset(item.keys()):
                logger.error(f"Invalid rubric item: {item}")
                return None
        
        # Normalize weights if needed
        total_weight = sum(item.get("weight_percent", 0) for item in rubric)
        if total_weight != 100 and total_weight > 0:
            for item in rubric:
                item["weight_percent"] = round(item["weight_percent"] * 100 / total_weight)
            diff = 100 - sum(item["weight_percent"] for item in rubric)
            if diff != 0 and rubric:
                rubric[0]["weight_percent"] += diff
        
        return rubric
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse refined rubric as JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Error refining rubric: {e}")
        return None


def save_rubric(course_id: int, module_id: int, rubric_data: List[Dict], group_id: Optional[int] = None) -> bool:
    """
    Save a rubric to disk.
    
    Args:
        course_id: Course ID
        module_id: Assignment module ID
        rubric_data: List of rubric criteria
        group_id: Optional group ID for batch-specific rubric
    
    Returns:
        True if saved successfully
    """
    try:
        # Create rubrics directory
        rubric_dir = Path("output") / f"course_{course_id}" / RUBRICS_DIR
        rubric_dir.mkdir(parents=True, exist_ok=True)
        
        # Determine filename
        if group_id:
            filename = f"rubric_mod{module_id}_grp{group_id}.json"
        else:
            filename = f"rubric_mod{module_id}.json"
        
        filepath = rubric_dir / filename
        
        # Create rubric document
        doc = {
            "module_id": module_id,
            "group_id": group_id,
            "generated_at": datetime.now().isoformat(),
            "criteria": rubric_data
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved rubric to {filepath}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to save rubric: {e}")
        return False


def load_rubric(course_id: int, module_id: int, group_id: Optional[int] = None) -> Optional[Dict]:
    """
    Load a rubric from disk.
    
    Args:
        course_id: Course ID
        module_id: Assignment module ID
        group_id: Optional group ID for batch-specific rubric
    
    Returns:
        Rubric document dict or None if not found
    """
    rubric_dir = Path("output") / f"course_{course_id}" / RUBRICS_DIR
    
    # Try group-specific rubric first if group_id provided
    if group_id:
        group_file = rubric_dir / f"rubric_mod{module_id}_grp{group_id}.json"
        if group_file.exists():
            try:
                with open(group_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load group rubric: {e}")
    
    # Fall back to default rubric
    default_file = rubric_dir / f"rubric_mod{module_id}.json"
    if default_file.exists():
        try:
            with open(default_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load default rubric: {e}")
    
    return None


def delete_rubric(course_id: int, module_id: int, group_id: Optional[int] = None) -> bool:
    """
    Delete a rubric from disk.
    
    Args:
        course_id: Course ID
        module_id: Assignment module ID
        group_id: Optional group ID for batch-specific rubric
    
    Returns:
        True if deleted successfully
    """
    rubric_dir = Path("output") / f"course_{course_id}" / RUBRICS_DIR
    
    if group_id:
        filepath = rubric_dir / f"rubric_mod{module_id}_grp{group_id}.json"
    else:
        filepath = rubric_dir / f"rubric_mod{module_id}.json"
    
    try:
        if filepath.exists():
            filepath.unlink()
            logger.info(f"Deleted rubric: {filepath}")
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to delete rubric: {e}")
        return False
