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

# AI Debug log file
AI_DEBUG_LOG_FILE = Path("output") / "ai_debug_log.json"

# API Key usage stats file
API_KEY_STATS_FILE = Path("output") / "api_key_stats.json"


def resize_image_bytes(image_bytes: bytes, max_dimension: int = 800) -> bytes:
    """
    Resize an image if it exceeds max_dimension, preserving aspect ratio.
    
    Args:
        image_bytes: Raw image bytes
        max_dimension: Maximum width or height in pixels. 0 = no resizing.
    
    Returns:
        Resized image bytes (PNG format) or original if no resize needed
    """
    if max_dimension <= 0:
        return image_bytes
    
    try:
        from PIL import Image
        import io
        
        img = Image.open(io.BytesIO(image_bytes))
        
        # Check if resize needed
        if img.width <= max_dimension and img.height <= max_dimension:
            return image_bytes
        
        # Calculate new size preserving aspect ratio
        ratio = min(max_dimension / img.width, max_dimension / img.height)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        
        # Resize
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Convert to PNG bytes
        output = io.BytesIO()
        img.save(output, format='PNG', optimize=True)
        return output.getvalue()
        
    except Exception as e:
        logger.debug(f"Failed to resize image: {e}")
        return image_bytes


def log_ai_call(
    function_name: str,
    model: str,
    prompt: str,
    response: str,
    duration_ms: int,
    success: bool = True,
    error: str = None,
    num_images: int = 0
) -> None:
    """
    Log an AI API call for debugging purposes.
    
    Args:
        function_name: Name of the calling function
        model: Gemini model used
        prompt: The prompt sent to the AI
        response: The AI response text
        duration_ms: Time taken in milliseconds
        success: Whether the call succeeded
        error: Error message if failed
        num_images: Number of images sent (for multimodal)
    """
    try:
        # Ensure output directory exists
        AI_DEBUG_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing logs
        logs = []
        if AI_DEBUG_LOG_FILE.exists():
            try:
                with open(AI_DEBUG_LOG_FILE, "r", encoding="utf-8") as f:
                    logs = json.load(f)
            except (json.JSONDecodeError, IOError):
                logs = []
        
        # Create log entry
        entry = {
            "id": len(logs) + 1,
            "timestamp": datetime.now().isoformat(),
            "function": function_name,
            "model": model,
            "prompt_preview": prompt[:500] + "..." if len(prompt) > 500 else prompt,
            "prompt_full": prompt,
            "response_preview": response[:500] + "..." if len(response) > 500 else response,
            "response_full": response,
            "duration_ms": duration_ms,
            "num_images": num_images,
            "success": success,
            "error": error
        }
        
        logs.append(entry)
        
        # Keep only last 200 logs to prevent unbounded growth
        if len(logs) > 200:
            logs = logs[-200:]
        
        # Save logs
        with open(AI_DEBUG_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
            
    except Exception as e:
        logger.debug(f"Failed to log AI call: {e}")


def get_ai_logs(limit: int = 50) -> List[Dict]:
    """
    Get AI debug log entries.
    
    Args:
        limit: Maximum number of entries to return (most recent first)
    
    Returns:
        List of log entry dicts
    """
    try:
        if AI_DEBUG_LOG_FILE.exists():
            with open(AI_DEBUG_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
            # Return most recent first
            return list(reversed(logs[-limit:]))
    except Exception as e:
        logger.debug(f"Failed to load AI logs: {e}")
    return []


def clear_ai_logs() -> bool:
    """
    Clear all AI debug logs.
    
    Returns:
        True if cleared successfully
    """
    try:
        if AI_DEBUG_LOG_FILE.exists():
            AI_DEBUG_LOG_FILE.unlink()
        return True
    except Exception as e:
        logger.error(f"Failed to clear AI logs: {e}")
        return False


def _load_key_stats() -> Dict:
    """Load key stats from file, resetting daily counters if needed."""
    try:
        if API_KEY_STATS_FILE.exists():
            with open(API_KEY_STATS_FILE, "r", encoding="utf-8") as f:
                stats = json.load(f)
            
            # Check if we need to reset daily counters
            today = datetime.now().strftime("%Y-%m-%d")
            if stats.get("last_reset_date") != today:
                # Reset daily counters for all keys
                for key_name in stats.get("keys", {}):
                    stats["keys"][key_name]["call_count_today"] = 0
                    stats["keys"][key_name]["error_count_today"] = 0
                stats["last_reset_date"] = today
                _save_key_stats(stats)
            
            return stats
    except Exception as e:
        logger.debug(f"Failed to load key stats: {e}")
    
    return {"last_reset_date": datetime.now().strftime("%Y-%m-%d"), "keys": {}, "active_key": None}


def _save_key_stats(stats: Dict) -> None:
    """Save key stats to file."""
    try:
        API_KEY_STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(API_KEY_STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"Failed to save key stats: {e}")


def log_key_usage(key_name: str, success: bool = True, error_message: str = None, is_quota_error: bool = False) -> None:
    """
    Log usage of an API key.
    
    Args:
        key_name: Name of the API key used
        success: Whether the call succeeded
        error_message: Error message if failed
        is_quota_error: True if this was a quota/rate limit error
    """
    try:
        stats = _load_key_stats()
        
        # Initialize key stats if not exists
        if key_name not in stats.get("keys", {}):
            stats.setdefault("keys", {})[key_name] = {
                "call_count_today": 0,
                "error_count_today": 0,
                "last_used": None,
                "last_error": None,
                "total_calls": 0,
                "total_errors": 0,
                "last_quota_error": None,
                "quota_exhausted": False
            }
        
        key_stats = stats["keys"][key_name]
        now = datetime.now().isoformat()
        
        key_stats["total_calls"] += 1
        key_stats["call_count_today"] += 1
        
        if success:
            key_stats["last_used"] = now
            key_stats["quota_exhausted"] = False
            stats["active_key"] = key_name
        else:
            key_stats["total_errors"] += 1
            key_stats["error_count_today"] += 1
            key_stats["last_error"] = {"time": now, "message": error_message}
            
            if is_quota_error:
                key_stats["last_quota_error"] = now
                key_stats["quota_exhausted"] = True
        
        _save_key_stats(stats)
        
    except Exception as e:
        logger.debug(f"Failed to log key usage: {e}")


def get_key_stats() -> Dict:
    """
    Get usage statistics for all API keys.
    
    Returns:
        Dict with 'keys' containing per-key stats and 'active_key' for the last used key
    """
    stats = _load_key_stats()
    
    # Merge with configured keys to ensure all keys appear
    configured_keys = get_api_keys()
    for key_info in configured_keys:
        key_name = key_info.get("name", "Unknown")
        if key_name not in stats.get("keys", {}):
            stats.setdefault("keys", {})[key_name] = {
                "call_count_today": 0,
                "error_count_today": 0,
                "last_used": None,
                "last_error": None,
                "total_calls": 0,
                "total_errors": 0,
                "last_quota_error": None,
                "quota_exhausted": False
            }
    
    return stats


def get_active_key() -> Optional[str]:
    """
    Get the name of the most recently successfully used API key.
    
    Returns:
        Key name or None if no key has been used yet
    """
    stats = _load_key_stats()
    return stats.get("active_key")


def reset_daily_key_stats() -> bool:
    """
    Reset daily counters for all API keys.
    
    Returns:
        True if reset successfully
    """
    try:
        stats = _load_key_stats()
        for key_name in stats.get("keys", {}):
            stats["keys"][key_name]["call_count_today"] = 0
            stats["keys"][key_name]["error_count_today"] = 0
            stats["keys"][key_name]["quota_exhausted"] = False
        stats["last_reset_date"] = datetime.now().strftime("%Y-%m-%d")
        _save_key_stats(stats)
        return True
    except Exception as e:
        logger.error(f"Failed to reset key stats: {e}")
        return False


def get_api_keys() -> list:
    """
    Get list of configured Gemini API keys.
    
    Returns:
        List of dicts with 'name' and 'key' fields
    """
    import json
    
    # Try new multi-key format first
    api_keys_json = get_config("gemini_api_keys")
    if api_keys_json:
        try:
            return json.loads(api_keys_json)
        except:
            pass
    
    # Fallback to old single key format
    single_key = get_config("gemini_api_key")
    if single_key:
        return [{"name": "Default", "key": single_key}]
    
    return []


def get_gemini_client(api_key: str = None):
    """
    Initialize and return a Gemini client.
    
    Args:
        api_key: Optional specific API key to use. If None, uses first configured key.
    
    Returns:
        Gemini Client or None if API key not configured
    """
    if not api_key:
        keys = get_api_keys()
        if not keys:
            logger.warning("Gemini API key not configured")
            return None
        api_key = keys[0].get("key")
    
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


def call_gemini_with_fallback(model: str, contents, start_key_index: int = 0):
    """
    Call Gemini API with automatic fallback to next API key on quota errors.
    
    Args:
        model: Model name to use
        contents: The prompt/contents to send
        start_key_index: Index of first key to try (for retry scenarios)
    
    Returns:
        Tuple of (response, key_name_used, key_index_used) or raises exception
    """
    keys = get_api_keys()
    
    if not keys:
        raise ValueError("No Gemini API keys configured")
    
    last_error = None
    
    for i in range(start_key_index, len(keys)):
        key_info = keys[i]
        key_name = key_info.get("name", f"Key {i+1}")
        api_key = key_info.get("key")
        
        if not api_key:
            continue
        
        try:
            from google import genai
            
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model,
                contents=contents
            )
            
            logger.info(f"Gemini call succeeded using '{key_name}'")
            # Log successful key usage
            log_key_usage(key_name, success=True)
            return response, key_name, i
            
        except Exception as e:
            error_str = str(e)
            last_error = e
            
            # Check if it's a quota/rate limit error (429)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
                logger.warning(f"API key '{key_name}' hit quota limit, trying next key...")
                # Log quota error
                log_key_usage(key_name, success=False, error_message=error_str, is_quota_error=True)
                continue
            else:
                # Non-quota error - log and re-raise immediately
                log_key_usage(key_name, success=False, error_message=error_str, is_quota_error=False)
                raise
    
    # All keys exhausted
    raise last_error or ValueError("All API keys exhausted")


def extract_pdf_text(pdf_source, max_chars: int = 100000) -> str:
    """
    Extract text content from a PDF file using PyMuPDF.
    
    Args:
        pdf_source: Path to the PDF file (str) OR raw PDF bytes
        max_chars: Maximum characters to extract (default 100KB)
    
    Returns:
        Extracted text content, or error message if extraction fails
    """
    try:
        import fitz  # PyMuPDF
        
        # Handle both path and bytes
        if isinstance(pdf_source, bytes):
            doc = fitz.open(stream=pdf_source, filetype="pdf")
        else:
            doc = fitz.open(pdf_source)
        text_parts = []
        total_chars = 0
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = page.get_text()
            
            if total_chars + len(page_text) > max_chars:
                # Truncate to fit limit
                remaining = max_chars - total_chars
                if remaining > 0:
                    text_parts.append(page_text[:remaining])
                    text_parts.append(f"\n\n[Truncated at {max_chars} characters - PDF has {len(doc)} pages]")
                break
            else:
                text_parts.append(f"--- Page {page_num + 1} ---\n{page_text}")
                total_chars += len(page_text)
        
        doc.close()
        
        full_text = "\n".join(text_parts)
        if not full_text.strip():
            return "(PDF contains no extractable text - may be a scanned image)"
        
        return full_text
        
    except ImportError:
        logger.error("PyMuPDF not installed - cannot extract PDF text")
        return "(PDF extraction unavailable - PyMuPDF not installed)"
    except Exception as e:
        logger.error(f"Failed to extract PDF text: {e}")
        return f"(Error extracting PDF text: {e})"


def extract_pdf_images(pdf_source, max_pages: int = 5, dpi: int = 150) -> List[bytes]:
    """
    Convert PDF pages to images for multimodal AI input.
    
    Args:
        pdf_source: Path to the PDF file (str) OR raw PDF bytes
        max_pages: Maximum number of pages to convert (default 5)
        dpi: Resolution for rendering (default 150 for balance of quality/size)
    
    Returns:
        List of PNG image bytes, one per page
    """
    try:
        import fitz  # PyMuPDF
        
        # Handle both path and bytes
        if isinstance(pdf_source, bytes):
            doc = fitz.open(stream=pdf_source, filetype="pdf")
        else:
            doc = fitz.open(pdf_source)
        
        images = []
        num_pages = min(len(doc), max_pages)
        
        for page_num in range(num_pages):
            page = doc[page_num]
            # Render page to image at specified DPI
            mat = fitz.Matrix(dpi / 72, dpi / 72)  # 72 is default DPI
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            images.append(img_bytes)
        
        doc.close()
        return images
        
    except ImportError:
        logger.error("PyMuPDF not installed - cannot extract PDF images")
        return []
    except Exception as e:
        logger.error(f"Failed to extract PDF images: {e}")
        return []


def extract_docx_text(docx_source, max_chars: int = 100000) -> str:
    """
    Extract content from a DOCX file as semantic HTML using mammoth.
    
    This preserves document structure (headings, lists, tables, emphasis)
    which gives the AI better context for evaluation compared to plain text.
    
    Args:
        docx_source: Path to the DOCX file (str) OR raw DOCX bytes
        max_chars: Maximum characters to extract (default 100KB)
    
    Returns:
        HTML content, or error message if extraction fails
    """
    try:
        import mammoth
        import io
        
        # Handle both path and bytes
        if isinstance(docx_source, bytes):
            docx_file = io.BytesIO(docx_source)
            result = mammoth.convert_to_html(docx_file)
        else:
            with open(docx_source, "rb") as f:
                result = mammoth.convert_to_html(f)
        
        html_content = result.value
        
        # Log any conversion warnings
        if result.messages:
            for msg in result.messages[:5]:  # Limit logged warnings
                logger.debug(f"Mammoth conversion warning: {msg}")
        
        if not html_content.strip():
            return "(DOCX contains no extractable content)"
        
        # Truncate if too long
        if len(html_content) > max_chars:
            html_content = html_content[:max_chars] + f"\n\n[Truncated at {max_chars} characters]"
        
        return html_content
        
    except ImportError:
        logger.error("mammoth not installed - cannot extract DOCX content")
        return "(DOCX extraction unavailable - mammoth not installed)"
    except Exception as e:
        logger.error(f"Failed to extract DOCX content: {e}")
        return f"(Error extracting DOCX content: {e})"


def convert_docx_to_pdf_images(docx_bytes: bytes, max_pages: int = 10, dpi: int = 150) -> tuple[str, List[bytes]]:
    """
    Convert DOCX to PDF, then render pages as images for multimodal AI.
    
    This approach preserves the full document layout including embedded images,
    which allows Gemini to see all screenshots and content in context.
    
    Args:
        docx_bytes: Raw bytes of the DOCX file
        max_pages: Maximum number of pages to render as images
        dpi: Resolution for rendered images
    
    Returns:
        Tuple of (text_content, list_of_page_images)
        - text_content: Extracted text for fallback/context
        - list_of_page_images: PNG bytes for each page
    """
    import io
    
    text_content = ""
    images = []
    
    try:
        import mammoth
        
        # Step 1: DOCX → HTML with embedded base64 images
        result = mammoth.convert_to_html(io.BytesIO(docx_bytes))
        html_content = result.value
        
        if not html_content.strip():
            return "(DOCX contains no content)", []
        
        # Also extract plain text for AI context
        import re
        text_content = re.sub(r'<[^>]+>', ' ', html_content)
        text_content = re.sub(r'\s+', ' ', text_content).strip()[:10000]
        
        # Step 2: HTML → PDF using xhtml2pdf
        styled_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>body{{font-family:Arial,sans-serif;margin:20px}}img{{max-width:100%;height:auto}}</style>
</head><body>{html_content}</body></html>"""
        
        try:
            from xhtml2pdf import pisa
            pdf_buffer = io.BytesIO()
            pisa_status = pisa.CreatePDF(styled_html, dest=pdf_buffer)
            if pisa_status.err:
                logger.warning("xhtml2pdf conversion had errors")
            pdf_bytes = pdf_buffer.getvalue()
        except ImportError:
            logger.error("xhtml2pdf not installed - cannot convert DOCX to PDF images")
            return text_content, []
        
        # Step 3: PDF → Images using PyMuPDF
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            
            for page_num in range(min(len(doc), max_pages)):
                page = doc[page_num]
                mat = fitz.Matrix(dpi/72, dpi/72)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                images.append(img_bytes)
            
            doc.close()
            logger.debug(f"Converted DOCX to {len(images)} page images")
            
        except ImportError:
            logger.error("PyMuPDF not installed - cannot render PDF pages")
            return text_content, []
        
        return text_content, images
        
    except ImportError:
        logger.error("mammoth not installed - cannot process DOCX")
        return "(mammoth not installed)", []
    except Exception as e:
        logger.error(f"Failed to convert DOCX to PDF images: {e}")
        return f"(Error converting DOCX: {e})", []


def extract_zip_images(zip_path: str, password: str = "ictkerala.org", max_images: int = 10) -> List[bytes]:
    """
    Extract images from a ZIP archive for multimodal AI input.
    
    Extracts direct images, renders PDF pages, and converts DOCX to page images.
    For encrypted ZIPs, uses the known password.
    
    Args:
        zip_path: Path to the ZIP file
        password: Password to try for encrypted ZIPs
        max_images: Maximum number of images to extract
    
    Returns:
        List of image bytes
    """
    try:
        with open(zip_path, 'rb') as f:
            zip_bytes = f.read()
        return extract_zip_images_from_bytes(zip_bytes, password, max_images)
    except FileNotFoundError:
        logger.error(f"ZIP file not found: {zip_path}")
        return []
    except Exception as e:
        logger.error(f"Failed to read ZIP file: {e}")
        return []


def extract_zip_listing(zip_path: str, password: str = "ictkerala.org") -> str:
    """
    Extract file listing and content from a ZIP archive for AI context.
    
    For encrypted ZIPs, uses the known password.
    For DOCX files inside the ZIP, converts to PDF for full visual content.
    
    Args:
        zip_path: Path to the ZIP file
        password: Password to try for encrypted ZIPs
    
    Returns:
        File listing string with content, or error message if extraction fails
    """
    try:
        with open(zip_path, 'rb') as f:
            zip_bytes = f.read()
        return extract_zip_listing_from_bytes(zip_bytes, password)
    except FileNotFoundError:
        return "(ZIP file not found)"
    except Exception as e:
        logger.error(f"Failed to read ZIP file: {e}")
        return f"(Error reading ZIP: {e})"


def generate_rubric(task_description: str) -> Optional[List[Dict[str, Any]]]:
    """
    Generate a scoring rubric from a task description using Gemini API.
    
    Args:
        task_description: The task description text
    
    Returns:
        List of rubric criteria dicts with keys: criterion, description, weight_percent
        Returns None on error
    """
    if not get_api_keys():
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
        
        import time
        start_time = time.time()
        
        response, key_used, _ = call_gemini_with_fallback(
            model=model,
            contents=prompt
        )
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Parse the response - it should be JSON
        response_text = response.text.strip()
        
        # Log the AI call
        log_ai_call(
            function_name="generate_rubric",
            model=model,
            prompt=prompt,
            response=response_text,
            duration_ms=duration_ms,
            success=True
        )
        
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
        log_ai_call(
            function_name="generate_rubric",
            model=model if 'model' in dir() else "unknown",
            prompt=prompt,
            response=response_text if 'response_text' in dir() else "",
            duration_ms=duration_ms if 'duration_ms' in dir() else 0,
            success=False,
            error=str(e)
        )
        return None
    except Exception as e:
        logger.error(f"Error generating rubric: {e}")
        log_ai_call(
            function_name="generate_rubric",
            model=model if 'model' in dir() else "unknown",
            prompt=prompt,
            response="",
            duration_ms=int((time.time() - start_time) * 1000) if 'start_time' in dir() else 0,
            success=False,
            error=str(e)
        )
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
    if not get_api_keys():
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
        
        import time
        start_time = time.time()
        
        response, key_used, _ = call_gemini_with_fallback(
            model=model,
            contents=prompt
        )
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        response_text = response.text.strip()
        
        # Log the AI call
        log_ai_call(
            function_name="refine_rubric",
            model=model,
            prompt=prompt,
            response=response_text,
            duration_ms=duration_ms,
            success=True
        )
        
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
        log_ai_call(
            function_name="refine_rubric",
            model=model if 'model' in dir() else "unknown",
            prompt=prompt,
            response=response_text if 'response_text' in dir() else "",
            duration_ms=duration_ms if 'duration_ms' in dir() else 0,
            success=False,
            error=str(e)
        )
        return None
    except Exception as e:
        logger.error(f"Error refining rubric: {e}")
        log_ai_call(
            function_name="refine_rubric",
            model=model if 'model' in dir() else "unknown",
            prompt=prompt,
            response="",
            duration_ms=int((time.time() - start_time) * 1000) if 'start_time' in dir() else 0,
            success=False,
            error=str(e)
        )
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


# =============================================================================
# AI SCORING FUNCTIONS
# =============================================================================

EVALUATIONS_DIR = "evaluations"


def fetch_github_content(repo_url: str, pat: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch README, file listing, and key file contents from a GitHub repository.
    
    For ZIPs and PDFs in the repo, downloads and extracts their content.
    
    Args:
        repo_url: GitHub repository URL
        pat: Optional Personal Access Token for higher rate limits
    
    Returns:
        Dict with 'readme', 'files', 'file_contents', 'images', 'error' keys
    """
    import requests
    import re
    import base64
    
    result = {
        "readme": "",
        "files": [],
        "file_contents": [],  # Extracted text from files
        "images": [],  # Images for multimodal scoring
        "error": None
    }
    
    # Extract owner/repo from URL
    # Handles: github.com/owner/repo, github.com/owner/repo.git, etc.
    match = re.search(r'github\.com/([^/]+)/([^/\s]+)', repo_url)
    if not match:
        result["error"] = "Could not parse GitHub URL"
        return result
    
    owner = match.group(1)
    repo = match.group(2).removesuffix('.git').rstrip('/')
    
    # Set up headers
    headers = {"Accept": "application/vnd.github.v3+json"}
    if pat:
        headers["Authorization"] = f"token {pat}"
    
    try:
        # Fetch README
        readme_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
        readme_resp = requests.get(readme_url, headers=headers, timeout=10)
        
        if readme_resp.status_code == 200:
            readme_data = readme_resp.json()
            # Decode base64 content
            if readme_data.get("encoding") == "base64":
                result["readme"] = base64.b64decode(readme_data.get("content", "")).decode("utf-8", errors="ignore")
            else:
                result["readme"] = readme_data.get("content", "")
        elif readme_resp.status_code == 404:
            result["readme"] = "(No README found)"
        elif readme_resp.status_code == 403:
            result["error"] = "GitHub API rate limit reached"
            return result
        
        # Fetch file listing
        contents_url = f"https://api.github.com/repos/{owner}/{repo}/contents"
        contents_resp = requests.get(contents_url, headers=headers, timeout=10)
        
        if contents_resp.status_code == 200:
            files = contents_resp.json()
            result["files"] = [
                {"name": f.get("name"), "type": f.get("type"), "size": f.get("size", 0), "download_url": f.get("download_url")}
                for f in files if isinstance(f, dict)
            ]
            
            # Download and extract important files for AI scoring
            for file_info in result["files"]:
                fname = file_info.get("name", "")
                download_url = file_info.get("download_url")
                file_size = file_info.get("size", 0)
                
                if not download_url or file_size > 10 * 1024 * 1024:  # Skip files > 10MB
                    continue
                
                ext = Path(fname).suffix.lower()
                
                # Download ZIP files and extract contents
                if ext == '.zip':
                    try:
                        zip_resp = requests.get(download_url, timeout=30)
                        if zip_resp.status_code == 200:
                            import io
                            import zipfile
                            
                            zip_bytes = zip_resp.content
                            
                            # Extract listing and text content
                            zip_listing = extract_zip_listing_from_bytes(zip_bytes)
                            result["file_contents"].append(f"--- {fname} (ZIP Archive) ---\n{zip_listing}")
                            
                            # Extract images for multimodal
                            zip_images = extract_zip_images_from_bytes(zip_bytes)
                            result["images"].extend(zip_images[:5])
                    except Exception as e:
                        logger.debug(f"Failed to download ZIP {fname}: {e}")
                
                # Download PDF files and extract text/images
                elif ext == '.pdf':
                    try:
                        pdf_resp = requests.get(download_url, timeout=30)
                        if pdf_resp.status_code == 200:
                            pdf_bytes = pdf_resp.content
                            
                            # Extract text
                            pdf_text = extract_pdf_text(pdf_bytes, max_chars=15000)
                            result["file_contents"].append(f"--- {fname} (PDF) ---\n{pdf_text}")
                            
                            # Extract images for multimodal
                            pdf_images = extract_pdf_images(pdf_bytes, max_pages=3)
                            result["images"].extend(pdf_images)
                    except Exception as e:
                        logger.debug(f"Failed to download PDF {fname}: {e}")
                
                # Download text/code files
                elif ext in ['.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.csv', 
                             '.php', '.rs', '.go', '.java', '.rb', '.c', '.cpp', '.h', '.hpp',
                             '.ts', '.tsx', '.jsx', '.vue', '.svelte', '.sh', '.bash', '.zsh',
                             '.sql', '.xml', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
                             '.r', '.scala', '.kt', '.swift', '.m', '.pl', '.lua', '.dart'] and file_size < 50000:
                    try:
                        txt_resp = requests.get(download_url, timeout=10)
                        if txt_resp.status_code == 200:
                            text_content = txt_resp.text[:10000]
                            result["file_contents"].append(f"--- {fname} ---\n{text_content}")
                    except Exception as e:
                        logger.debug(f"Failed to download text file {fname}: {e}")
                
                # Download image files for multimodal AI
                elif ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'] and file_size < 5 * 1024 * 1024:
                    try:
                        img_resp = requests.get(download_url, timeout=15)
                        if img_resp.status_code == 200:
                            # Resize image to save tokens
                            try:
                                max_dim = int(get_config("max_image_dimension") or "800")
                            except (ValueError, TypeError):
                                max_dim = 800
                            resized_bytes = resize_image_bytes(img_resp.content, max_dim)
                            result["images"].append(resized_bytes)
                            result["file_contents"].append(f"--- {fname} ---\n(Screenshot/Image, {len(resized_bytes) / 1024:.1f} KB - sent as visual for AI)")
                    except Exception as e:
                        logger.debug(f"Failed to download image {fname}: {e}")
            
            # Recursively fetch subdirectory contents (up to 5 levels deep)
            CODE_EXTENSIONS = [
                '.txt', '.md', '.py', '.js', '.html', '.css', '.json', '.csv',
                '.php', '.rs', '.go', '.java', '.rb', '.c', '.cpp', '.h', '.hpp',
                '.ts', '.tsx', '.jsx', '.vue', '.svelte', '.sh', '.bash', '.zsh',
                '.sql', '.xml', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
                '.r', '.scala', '.kt', '.swift', '.m', '.pl', '.lua', '.dart'
            ]
            
            def fetch_directory_recursive(dir_path, depth=0, max_depth=5):
                """Recursively fetch directory contents up to max_depth."""
                if depth >= max_depth:
                    return
                
                dir_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{dir_path}"
                try:
                    dir_resp = requests.get(dir_url, headers=headers, timeout=10)
                    if dir_resp.status_code != 200:
                        return
                    
                    dir_files = dir_resp.json()
                    for df in dir_files:
                        if not isinstance(df, dict):
                            continue
                        
                        df_name = df.get("name", "")
                        df_type = df.get("type", "")
                        df_path = f"{dir_path}/{df_name}"
                        
                        if df_type == "file":
                            df_url = df.get("download_url")
                            df_size = df.get("size", 0)
                            df_ext = Path(df_name).suffix.lower()
                            
                            if df_url and df_size < 50000 and df_ext in CODE_EXTENSIONS:
                                try:
                                    sub_resp = requests.get(df_url, timeout=10)
                                    if sub_resp.status_code == 200:
                                        text_content = sub_resp.text[:10000]
                                        result["file_contents"].append(f"--- {df_path} ---\n{text_content}")
                                except Exception as e:
                                    logger.debug(f"Failed to download {df_path}: {e}")
                        
                        elif df_type == "dir":
                            # Recursively fetch subdirectory
                            fetch_directory_recursive(df_path, depth + 1, max_depth)
                            
                except Exception as e:
                    logger.debug(f"Failed to fetch directory {dir_path}: {e}")
            
            # Fetch all top-level directories recursively
            # Get max depth from config (default 5)
            try:
                max_recursive_depth = int(get_config("github_recursive_depth") or "5")
            except (ValueError, TypeError):
                max_recursive_depth = 5
            
            for file_info in files:
                if isinstance(file_info, dict) and file_info.get("type") == "dir":
                    dir_name = file_info.get("name", "")
                    fetch_directory_recursive(dir_name, depth=0, max_depth=max_recursive_depth)
                        
        elif contents_resp.status_code == 403:
            result["error"] = "GitHub API rate limit reached"
            
    except requests.exceptions.RequestException as e:
        result["error"] = f"Network error: {str(e)}"
    except Exception as e:
        result["error"] = f"Error fetching GitHub content: {str(e)}"
    
    return result


def extract_zip_listing_from_bytes(zip_bytes: bytes, password: str = "ictkerala.org") -> str:
    """Extract file listing and content from ZIP bytes (for GitHub downloads)."""
    import zipfile
    import io
    
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
            # Check if encrypted
            is_encrypted = any(info.flag_bits & 0x1 for info in zf.infolist())
            pwd = password.encode() if is_encrypted else None
            
            if is_encrypted:
                try:
                    zf.setpassword(pwd)
                except:
                    pass
            
            file_list = []
            content_sections = []
            total_size = 0
            
            for info in zf.infolist():
                if not info.is_dir():
                    total_size += info.file_size
                    size_str = f"{info.file_size / 1024:.1f} KB" if info.file_size > 0 else "—"
                    file_list.append(f"- {info.filename} ({size_str})")
                    
                    ext = Path(info.filename).suffix.lower()
                    try:
                        file_bytes = zf.read(info.filename, pwd=pwd)
                        
                        # Text files
                        if ext in ['.txt', '.md', '.csv', '.log', '.py', '.js', '.html', '.css', '.json']:
                            text_content = file_bytes.decode('utf-8', errors='ignore')
                            if text_content.strip():
                                content_sections.append(f"\n--- Content of {info.filename} ---\n{text_content[:10000]}")
                        
                        # DOCX files - convert to PDF pages for full visual content
                        elif ext in ['.docx']:
                            text_content, docx_images = convert_docx_to_pdf_images(file_bytes)
                            if text_content:
                                content_sections.append(f"\n--- Content of {info.filename} (Word Document, {len(docx_images)} pages rendered as images for AI) ---\n{text_content[:15000]}")
                        
                        # PDF files
                        elif ext == '.pdf':
                            pdf_text = extract_pdf_text(file_bytes, max_chars=15000)
                            content_sections.append(f"\n--- Content of {info.filename} (PDF) ---\n{pdf_text}")
                        
                        # Image files - note their presence for AI context
                        elif ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg']:
                            size_kb = len(file_bytes) / 1024
                            content_sections.append(f"\n--- {info.filename} ---\n(Screenshot/Image file, {size_kb:.1f} KB. Visual evidence of completed work.)")
                            
                    except Exception as e:
                        logger.debug(f"Could not extract {info.filename}: {e}")
            
            if file_list:
                listing = f"ZIP Archive Contents ({len(file_list)} files, {total_size / 1024:.1f} KB total):\n"
                listing += "\n".join(file_list[:50])
                if content_sections:
                    listing += "\n\n" + "\n".join(content_sections)
                return listing
            else:
                return "(Empty ZIP archive)"
                
    except Exception as e:
        return f"(Error reading ZIP: {e})"


def extract_zip_images_from_bytes(zip_bytes: bytes, password: str = "ictkerala.org", max_images: int = 5) -> List[bytes]:
    """Extract images from ZIP bytes (for GitHub downloads)."""
    import zipfile
    import io
    
    images = []
    
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
            # Check if encrypted
            is_encrypted = any(info.flag_bits & 0x1 for info in zf.infolist())
            pwd = password.encode() if is_encrypted else None
            
            if is_encrypted:
                try:
                    zf.setpassword(pwd)
                except:
                    pass
            
            for info in zf.infolist():
                if len(images) >= max_images:
                    break
                    
                if info.is_dir():
                    continue
                    
                ext = Path(info.filename).suffix.lower()
                
                try:
                    file_bytes = zf.read(info.filename, pwd=pwd)
                    
                    # Direct image files
                    if ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
                        images.append(file_bytes)
                    
                    # PDF files - render pages as images
                    elif ext == '.pdf':
                        pdf_images = extract_pdf_images(file_bytes, max_pages=3)
                        for img in pdf_images:
                            if len(images) < max_images:
                                images.append(img)
                    
                    # DOCX files - convert to PDF and render pages as images
                    elif ext == '.docx':
                        _, docx_images = convert_docx_to_pdf_images(file_bytes, max_pages=5)
                        for img in docx_images:
                            if len(images) < max_images:
                                images.append(img)
                                
                except Exception as e:
                    logger.debug(f"Could not extract image from {info.filename}: {e}")
    
    except Exception as e:
        logger.debug(f"Failed to extract images from ZIP: {e}")
    
    return images


def fetch_submission_content(row: Dict, course_id: int = None) -> Dict[str, Any]:
    """
    Extract evaluable content from a submission based on its type.
    
    Args:
        row: Submission row dict
        course_id: Course ID for file path construction
    
    Returns:
        Dict with 'type', 'content', 'summary', 'error' keys
    """
    import re
    import ast
    
    result = {
        "type": "unknown",
        "content": "",
        "summary": "",
        "images": [],  # List of image bytes for multimodal AI
        "error": None
    }
    
    submission_text = row.get("Submission", "")
    submission_type = row.get("Submission_Type", "")
    submission_files = row.get("Submission_Files", [])
    
    # Parse submission files if it's a string
    if isinstance(submission_files, str) and submission_files.startswith('['):
        try:
            submission_files = ast.literal_eval(submission_files)
        except:
            submission_files = []
    
    # Determine type if not set
    if not submission_type:
        if submission_files:
            submission_type = "file"
        elif "http" in submission_text.lower():
            submission_type = "link"
        elif submission_text.strip():
            submission_type = "text"
        else:
            submission_type = "empty"
    
    result["type"] = submission_type
    
    if submission_type == "empty" or not submission_text.strip():
        result["summary"] = "No submission"
        result["content"] = ""
        return result
    
    if submission_type == "link":
        # Extract URL
        url_match = re.search(r'(https?://[^\s]+)', submission_text)
        if url_match:
            url = url_match.group(1)
            result["summary"] = f"Link submission: {url}"
            
            if "github.com" in url:
                # Fetch GitHub content
                pat = get_config("github_pat")
                github_content = fetch_github_content(url, pat)
                
                if github_content.get("error"):
                    result["error"] = github_content["error"]
                    result["content"] = f"GitHub URL: {url}\n\n(Could not fetch content: {github_content['error']})"
                else:
                    files_list = "\n".join([f"- {f['name']} ({f['type']})" for f in github_content.get("files", [])])
                    
                    # Include extracted file contents
                    file_contents_text = "\n\n".join(github_content.get("file_contents", []))
                    
                    result["content"] = f"""GitHub Repository: {url}

## Files in Repository:
{files_list or "(empty)"}

## README:
{github_content.get('readme', '(No README)')}

## Extracted File Contents:
{file_contents_text or "(No downloadable content extracted)"}
"""
                    # Transfer images for multimodal scoring
                    result["images"].extend(github_content.get("images", []))
            else:
                # Non-GitHub link - can't fetch content
                result["content"] = f"Submitted URL: {url}\n\n(Cannot fetch content from non-GitHub URLs)"
        else:
            result["content"] = submission_text
            result["summary"] = "Text with no valid URL"
    
    elif submission_type == "file":
        # File submission
        if submission_files:
            file_names = [f[0] if isinstance(f, (list, tuple)) else str(f) for f in submission_files]
            result["summary"] = f"File submission: {', '.join(file_names)}"
            
            # Try to read downloaded files
            file_contents = []
            for f in submission_files:
                fname = f[0] if isinstance(f, (list, tuple)) else str(f)
                file_contents.append(f"File: {fname}")
                
                # Check if file is downloaded locally
                if course_id:
                    safe_student = "".join([c for c in row.get('Name', 'Unknown') if c.isalnum() or c in (' ', '-', '_')]).strip()
                    safe_filename = "".join([c for c in fname if c.isalnum() or c in (' ', '-', '_', '.')]).strip()
                    local_path = Path(f"output/course_{course_id}/downloads/{safe_student}/{safe_filename}")
                    
                    if local_path.exists():
                        try:
                            file_size = local_path.stat().st_size
                            
                            # Handle PDFs specially - extract text AND images
                            if local_path.suffix.lower() == '.pdf':
                                pdf_text = extract_pdf_text(str(local_path))
                                file_contents.append(f"--- Content of {fname} (PDF) ---\n{pdf_text}")
                                # Also extract images for multimodal scoring
                                pdf_images = extract_pdf_images(str(local_path), max_pages=5)
                                result["images"].extend(pdf_images)
                            # Handle DOCX files
                            elif local_path.suffix.lower() in ['.docx', '.doc']:
                                docx_text = extract_docx_text(str(local_path))
                                file_contents.append(f"--- Content of {fname} (Word Document) ---\n{docx_text}")
                            # Handle ZIP archives - extract listing AND images
                            elif local_path.suffix.lower() == '.zip':
                                zip_listing = extract_zip_listing(str(local_path))
                                file_contents.append(f"--- {fname} ---\n{zip_listing}")
                                # Also extract images for multimodal scoring
                                zip_images = extract_zip_images(str(local_path), max_images=5)
                                result["images"].extend(zip_images)
                            # Read text files up to 100KB
                            elif local_path.suffix.lower() in ['.txt', '.py', '.js', '.html', '.css', '.md', '.json', '.xml', '.csv', '.java', '.c', '.cpp', '.h', '.sh', '.bat', '.ps1', '.yaml', '.yml', '.ini', '.cfg', '.conf', '.log', '.sql']:
                                if file_size > 100000:
                                    file_contents.append(f"(File too large: {file_size / 1024:.1f}KB - content not loaded)")
                                else:
                                    with open(local_path, 'r', encoding='utf-8', errors='ignore') as fp:
                                        content = fp.read()
                                        file_contents.append(f"--- Content of {fname} ---\n{content}")
                            # Handle images - extract for multimodal scoring
                            elif local_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
                                file_contents.append(f"(Image file: {fname} - {file_size / 1024:.1f}KB)")
                                # Read image bytes for multimodal scoring
                                with open(local_path, 'rb') as img_f:
                                    result["images"].append(img_f.read())
                            else:
                                file_contents.append(f"(Binary file - cannot read content)")
                        except Exception as e:
                            file_contents.append(f"(Error reading file: {e})")
                    else:
                        file_contents.append(f"(File not downloaded locally)")
            
            result["content"] = "\n\n".join(file_contents)
        else:
            result["summary"] = "File submission (no files listed)"
            result["content"] = submission_text
    
    elif submission_type == "text":
        result["summary"] = f"Text submission ({len(submission_text)} chars)"
        result["content"] = submission_text
    
    return result


def score_submission(
    submission_content: Dict[str, Any],
    rubric: List[Dict],
    task_description: str,
    student_name: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Score a submission using Gemini AI against the provided rubric.
    
    Args:
        submission_content: Dict from fetch_submission_content()
        rubric: List of rubric criteria dicts
        task_description: The task/assignment description
        student_name: Optional student name for context
    
    Returns:
        Dict with 'total_score', 'criteria_scores', 'comments', 'error'
    """
    if not get_api_keys():
        return {"error": "Gemini API not configured"}
    
    # Handle empty submissions
    if submission_content.get("type") == "empty" or not submission_content.get("content"):
        return {
            "total_score": 0,
            "criteria_scores": [
                {"criterion": c["criterion"], "score": 0, "max_score": c["weight_percent"], "comment": "No submission"}
                for c in rubric
            ],
            "comments": "No submission was provided for this assignment.",
            "error": None
        }
    
    # Build rubric text for prompt
    rubric_text = "\n".join([
        f"- {c['criterion']} ({c['weight_percent']}%): {c['description']}"
        for c in rubric
    ])
    
    prompt = f"""You are evaluating a student submission for an assignment.

## Task Description:
{task_description}

## Scoring Rubric:
{rubric_text}

## Student Submission:
Type: {submission_content.get('type', 'unknown')}
Summary: {submission_content.get('summary', '')}
Deadline: {submission_content.get('deadline', 'Not specified')}
Submitted on Time: {'Yes' if submission_content.get('on_time') else 'No' if submission_content.get('on_time') is False else 'Unknown'}

Content:
{submission_content.get('content', '(No content available)')[:8000]}

## Instructions:
1. Evaluate the submission against EACH criterion in the rubric
2. Assign a score (0 to the max weight) for each criterion
3. Provide brief constructive feedback

Return ONLY a valid JSON object with this structure (no markdown):
{{
  "criteria_scores": [
    {{"criterion": "Criterion Name", "score": 25, "max_score": 30, "comment": "Brief feedback"}},
    ...
  ],
  "overall_comments": "2-3 sentences of overall feedback for the student"
}}

Be fair but thorough. If content couldn't be fetched, base your evaluation on what's available.

If images are provided below, examine them carefully as they may contain screenshots demonstrating completed work."""

    try:
        model = get_config("gemini_model") or "gemini-2.5-flash"
        
        import time
        start_time = time.time()
        num_images_sent = 0
        
        # Build multimodal content if images are available
        images = submission_content.get("images", [])
        
        if images:
            # Build multimodal content: [image1, image2, ..., text_prompt]
            from google.genai import types
            
            contents = []
            
            # Get max images from config (default 10)
            try:
                max_images = int(get_config("max_images_for_scoring") or "10")
            except (ValueError, TypeError):
                max_images = 10
            
            # Add images up to the configured limit
            images_to_use = images[:max_images]
            for i, img_bytes in enumerate(images_to_use):
                try:
                    # Create image part
                    image_part = types.Part.from_bytes(
                        data=img_bytes,
                        mime_type="image/png"
                    )
                    contents.append(image_part)
                    num_images_sent += 1
                except Exception as e:
                    logger.debug(f"Failed to add image {i+1}: {e}")
            
            # Add text prompt
            final_prompt = prompt + f"\n\n(Note: {len(images_to_use)} screenshot(s) are provided above - examine them for evidence of completed work)"
            contents.append(final_prompt)
            
            response, key_used, _ = call_gemini_with_fallback(
                model=model,
                contents=contents
            )
        else:
            final_prompt = prompt
            # Text-only content
            response, key_used, _ = call_gemini_with_fallback(
                model=model,
                contents=prompt
            )
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        response_text = response.text.strip()
        
        # Log the AI call
        log_ai_call(
            function_name="score_submission",
            model=model,
            prompt=final_prompt,
            response=response_text,
            duration_ms=duration_ms,
            success=True,
            num_images=num_images_sent
        )
        
        # Remove markdown code fencing if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        
        # Clean up JSON - extract just the JSON object (handle AI hallucinations)
        # Find first { and last }
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            response_text = response_text[start_idx:end_idx + 1]
        
        # Try to parse, with fallback for common issues
        try:
            result = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to fix common issues: remove stray text between JSON elements
            import re
            # Remove any text between closing brace/bracket and comma or next element
            cleaned = re.sub(r'"\s*\n\s*[a-zA-Z][a-zA-Z0-9_]*\.?\s*\n\s*}', '"\n    }', response_text)
            cleaned = re.sub(r'"\s+[a-zA-Z][a-zA-Z0-9_]*\.?\s+,', '",', cleaned)
            result = json.loads(cleaned)
        
        # Calculate total score
        criteria_scores = result.get("criteria_scores", [])
        total_score = sum(c.get("score", 0) for c in criteria_scores)
        
        return {
            "total_score": total_score,
            "criteria_scores": criteria_scores,
            "comments": result.get("overall_comments", ""),
            "error": None
        }
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse scoring response: {e}")
        log_ai_call(
            function_name="score_submission",
            model=model if 'model' in dir() else "unknown",
            prompt=final_prompt if 'final_prompt' in dir() else prompt,
            response=response_text if 'response_text' in dir() else "",
            duration_ms=duration_ms if 'duration_ms' in dir() else 0,
            success=False,
            error=str(e),
            num_images=num_images_sent if 'num_images_sent' in dir() else 0
        )
        return {"error": f"Failed to parse AI response: {e}"}
    except Exception as e:
        logger.error(f"Error scoring submission: {e}")
        log_ai_call(
            function_name="score_submission",
            model=model if 'model' in dir() else "unknown",
            prompt=final_prompt if 'final_prompt' in dir() else prompt,
            response="",
            duration_ms=int((time.time() - start_time) * 1000) if 'start_time' in dir() else 0,
            success=False,
            error=str(e),
            num_images=num_images_sent if 'num_images_sent' in dir() else 0
        )
        return {"error": f"Scoring error: {e}"}


def save_evaluation(course_id: int, module_id: int, student_name: str, evaluation: Dict, group_id: Optional[int] = None) -> bool:
    """
    Save an evaluation result to disk.
    
    Args:
        course_id: Course ID
        module_id: Assignment module ID
        student_name: Student name (used in filename)
        evaluation: Evaluation result dict
        group_id: Optional group ID
    
    Returns:
        True if saved successfully
    """
    try:
        eval_dir = Path("output") / f"course_{course_id}" / EVALUATIONS_DIR / f"mod{module_id}"
        if group_id:
            eval_dir = eval_dir / f"grp{group_id}"
        eval_dir.mkdir(parents=True, exist_ok=True)
        
        # Sanitize student name for filename
        safe_name = "".join([c for c in student_name if c.isalnum() or c in (' ', '-', '_')]).strip().replace(' ', '_')
        filename = f"eval_{safe_name}.json"
        filepath = eval_dir / filename
        
        doc = {
            "student_name": student_name,
            "module_id": module_id,
            "group_id": group_id,
            "evaluated_at": datetime.now().isoformat(),
            **evaluation
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved evaluation to {filepath}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to save evaluation: {e}")
        return False


def load_evaluation(course_id: int, module_id: int, student_name: str, group_id: Optional[int] = None) -> Optional[Dict]:
    """
    Load an evaluation result from disk.
    
    Args:
        course_id: Course ID
        module_id: Assignment module ID
        student_name: Student name
        group_id: Optional group ID
    
    Returns:
        Evaluation dict or None if not found
    """
    eval_dir = Path("output") / f"course_{course_id}" / EVALUATIONS_DIR / f"mod{module_id}"
    if group_id:
        eval_dir = eval_dir / f"grp{group_id}"
    
    safe_name = "".join([c for c in student_name if c.isalnum() or c in (' ', '-', '_')]).strip().replace(' ', '_')
    filename = f"eval_{safe_name}.json"
    filepath = eval_dir / filename
    
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load evaluation: {e}")
    
    return None


def refine_evaluation(
    current_evaluation: Dict,
    instructions: str,
    submission_content: Dict,
    rubric: List[Dict],
    task_description: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Refine an existing evaluation based on user feedback/questions.
    
    Args:
        current_evaluation: The current evaluation dict with scores and comments
        instructions: User's questions, clarifications, or adjustment requests
        submission_content: The original submission content
        rubric: The rubric criteria
        task_description: The task description for context
    
    Returns:
        Updated evaluation dict with 'total_score', 'criteria_scores', 'comments', 'conversation'
    """
    if not get_api_keys():
        return {"error": "Gemini API not configured"}
    
    # Format current evaluation
    eval_summary = f"Total Score: {current_evaluation.get('total_score', 0)}/100\n\n"
    for cs in current_evaluation.get('criteria_scores', []):
        eval_summary += f"- {cs.get('criterion')}: {cs.get('score')}/{cs.get('max_score')} - {cs.get('comment', '')}\n"
    eval_summary += f"\nOverall Comments: {current_evaluation.get('comments', '')}"
    
    # Format rubric
    rubric_text = "\n".join([
        f"- {c['criterion']} ({c['weight_percent']}%): {c['description']}"
        for c in rubric
    ])
    
    # Get conversation history if exists
    conversation_history = current_evaluation.get('conversation', [])
    conversation_text = ""
    if conversation_history:
        for msg in conversation_history[-5:]:  # Last 5 exchanges
            conversation_text += f"\n{msg['role'].upper()}: {msg['content']}"
    
    prompt = f"""You are helping a teacher review and potentially adjust an AI-generated evaluation of a student submission.

## Task Description:
{task_description}

## Rubric:
{rubric_text}

## Submission Summary:
Type: {submission_content.get('type', 'unknown')}
{submission_content.get('summary', '')}

## Current Evaluation:
{eval_summary}
{f"## Previous Discussion:{conversation_text}" if conversation_text else ""}

## Teacher's Message:
{instructions}

## Instructions:
1. If the teacher is asking a question, answer it directly and explain your reasoning
2. If the teacher requests score adjustments, update the scores accordingly with justification
3. If the teacher provides additional context, incorporate it into your evaluation
4. Always be helpful and explain your reasoning

Return a JSON object with this structure (no markdown):
{{
  "criteria_scores": [
    {{"criterion": "Criterion Name", "score": 25, "max_score": 30, "comment": "Updated feedback"}},
    ...
  ],
  "overall_comments": "Updated overall feedback",
  "response_to_teacher": "Your direct response to the teacher's question/request"
}}

If no score changes are needed (just answering a question), keep the original scores."""

    try:
        model = get_config("gemini_model") or "gemini-2.5-flash"
        
        import time
        start_time = time.time()
        
        response, key_used, _ = call_gemini_with_fallback(
            model=model,
            contents=prompt
        )
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        response_text = response.text.strip()
        
        # Log the AI call
        log_ai_call(
            function_name="refine_evaluation",
            model=model,
            prompt=prompt,
            response=response_text,
            duration_ms=duration_ms,
            success=True
        )
        
        # Remove markdown code fencing if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        
        result = json.loads(response_text)
        
        # Calculate total score
        criteria_scores = result.get("criteria_scores", [])
        total_score = sum(c.get("score", 0) for c in criteria_scores)
        
        # Update conversation history
        new_conversation = conversation_history.copy()
        new_conversation.append({"role": "teacher", "content": instructions})
        new_conversation.append({"role": "ai", "content": result.get("response_to_teacher", "")})
        
        return {
            "total_score": total_score,
            "criteria_scores": criteria_scores,
            "comments": result.get("overall_comments", current_evaluation.get("comments", "")),
            "response_to_teacher": result.get("response_to_teacher", ""),
            "conversation": new_conversation,
            "error": None
        }
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse refinement response: {e}")
        log_ai_call(
            function_name="refine_evaluation",
            model=model if 'model' in dir() else "unknown",
            prompt=prompt,
            response=response_text if 'response_text' in dir() else "",
            duration_ms=duration_ms if 'duration_ms' in dir() else 0,
            success=False,
            error=str(e)
        )
        return {"error": f"Failed to parse AI response: {e}"}
    except Exception as e:
        logger.error(f"Error refining evaluation: {e}")
        log_ai_call(
            function_name="refine_evaluation",
            model=model if 'model' in dir() else "unknown",
            prompt=prompt,
            response="",
            duration_ms=int((time.time() - start_time) * 1000) if 'start_time' in dir() else 0,
            success=False,
            error=str(e)
        )
        return {"error": f"Refinement error: {e}"}
