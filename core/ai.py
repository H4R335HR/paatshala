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


def extract_pdf_text(pdf_path: str, max_chars: int = 100000) -> str:
    """
    Extract text content from a PDF file using PyMuPDF.
    
    Args:
        pdf_path: Path to the PDF file
        max_chars: Maximum characters to extract (default 100KB)
    
    Returns:
        Extracted text content, or error message if extraction fails
    """
    try:
        import fitz  # PyMuPDF
        
        doc = fitz.open(pdf_path)
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


def extract_docx_text(docx_path: str, max_chars: int = 100000) -> str:
    """
    Extract content from a DOCX file as semantic HTML using mammoth.
    
    This preserves document structure (headings, lists, tables, emphasis)
    which gives the AI better context for evaluation compared to plain text.
    
    Args:
        docx_path: Path to the DOCX file
        max_chars: Maximum characters to extract (default 100KB)
    
    Returns:
        HTML content, or error message if extraction fails
    """
    try:
        import mammoth
        
        with open(docx_path, "rb") as docx_file:
            result = mammoth.convert_to_html(docx_file)
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


def extract_zip_listing(zip_path: str, password: str = "ictkerala.org") -> str:
    """
    Extract file listing and content from a ZIP archive for AI context.
    
    For encrypted ZIPs, uses the known password.
    For DOCX files inside the ZIP, extracts and converts to HTML for AI evaluation.
    
    Args:
        zip_path: Path to the ZIP file
        password: Password to try for encrypted ZIPs
    
    Returns:
        File listing string with content, or error message if extraction fails
    """
    try:
        import zipfile
        import io
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
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
                    
                    # Try to extract content from known file types
                    ext = Path(info.filename).suffix.lower()
                    try:
                        file_bytes = zf.read(info.filename, pwd=pwd)
                        
                        # DOCX files - convert to HTML with mammoth
                        if ext in ['.docx']:
                            try:
                                import mammoth
                                result = mammoth.convert_to_html(io.BytesIO(file_bytes))
                                # Strip HTML tags for cleaner AI input
                                import re
                                clean_text = re.sub(r'<[^>]+>', ' ', result.value)
                                clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                                if clean_text:
                                    content_sections.append(f"\n--- Content of {info.filename} ---\n{clean_text[:20000]}")
                            except Exception as e:
                                # DOCX might be password-protected itself
                                content_sections.append(f"\n--- {info.filename} ---\n(Could not read DOCX: {e})")
                        
                        # Plain text files
                        elif ext in ['.txt', '.md', '.csv', '.log', '.py', '.js', '.html', '.css', '.json']:
                            try:
                                text_content = file_bytes.decode('utf-8', errors='ignore')
                                if text_content.strip():
                                    content_sections.append(f"\n--- Content of {info.filename} ---\n{text_content[:10000]}")
                            except:
                                pass
                    except Exception as e:
                        logger.debug(f"Could not extract {info.filename}: {e}")
            
            if file_list:
                listing = f"ZIP Archive Contents ({len(file_list)} files, {total_size / 1024:.1f} KB total):\n"
                listing += "\n".join(file_list[:50])  # Limit to 50 files
                if len(file_list) > 50:
                    listing += f"\n... and {len(file_list) - 50} more files"
                
                # Add extracted content
                if content_sections:
                    listing += "\n\n" + "\n".join(content_sections)
                
                return listing
            else:
                return "(Empty ZIP archive)"
                
    except zipfile.BadZipFile:
        return "(Invalid or corrupted ZIP file)"
    except Exception as e:
        logger.error(f"Failed to list ZIP contents: {e}")
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


# =============================================================================
# AI SCORING FUNCTIONS
# =============================================================================

EVALUATIONS_DIR = "evaluations"


def fetch_github_content(repo_url: str, pat: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch README and file listing from a GitHub repository.
    
    Args:
        repo_url: GitHub repository URL
        pat: Optional Personal Access Token for higher rate limits
    
    Returns:
        Dict with 'readme', 'files', 'error' keys
    """
    import requests
    import re
    import base64
    
    result = {
        "readme": "",
        "files": [],
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
                {"name": f.get("name"), "type": f.get("type"), "size": f.get("size", 0)}
                for f in files if isinstance(f, dict)
            ]
        elif contents_resp.status_code == 403:
            result["error"] = "GitHub API rate limit reached"
            
    except requests.exceptions.RequestException as e:
        result["error"] = f"Network error: {str(e)}"
    except Exception as e:
        result["error"] = f"Error fetching GitHub content: {str(e)}"
    
    return result


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
                    result["content"] = f"""GitHub Repository: {url}

## Files in Repository:
{files_list or "(empty)"}

## README:
{github_content.get('readme', '(No README)')}
"""
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
                            
                            # Handle PDFs specially
                            if local_path.suffix.lower() == '.pdf':
                                pdf_text = extract_pdf_text(str(local_path))
                                file_contents.append(f"--- Content of {fname} (PDF) ---\n{pdf_text}")
                            # Handle DOCX files
                            elif local_path.suffix.lower() in ['.docx', '.doc']:
                                docx_text = extract_docx_text(str(local_path))
                                file_contents.append(f"--- Content of {fname} (Word Document) ---\n{docx_text}")
                            # Handle ZIP archives
                            elif local_path.suffix.lower() == '.zip':
                                zip_listing = extract_zip_listing(str(local_path))
                                file_contents.append(f"--- {fname} ---\n{zip_listing}")
                            # Read text files up to 100KB
                            elif local_path.suffix.lower() in ['.txt', '.py', '.js', '.html', '.css', '.md', '.json', '.xml', '.csv', '.java', '.c', '.cpp', '.h', '.sh', '.bat', '.ps1', '.yaml', '.yml', '.ini', '.cfg', '.conf', '.log', '.sql']:
                                if file_size > 100000:
                                    file_contents.append(f"(File too large: {file_size / 1024:.1f}KB - content not loaded)")
                                else:
                                    with open(local_path, 'r', encoding='utf-8', errors='ignore') as fp:
                                        content = fp.read()
                                        file_contents.append(f"--- Content of {fname} ---\n{content}")
                            # Handle images - just note they exist
                            elif local_path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg']:
                                file_contents.append(f"(Image file: {fname} - {file_size / 1024:.1f}KB)")
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
    client = get_gemini_client()
    if not client:
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

Be fair but thorough. If content couldn't be fetched, base your evaluation on what's available."""

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
        
        result = json.loads(response_text)
        
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
        return {"error": f"Failed to parse AI response: {e}"}
    except Exception as e:
        logger.error(f"Error scoring submission: {e}")
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
    client = get_gemini_client()
    if not client:
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
        
        response = client.models.generate_content(
            model=model,
            contents=prompt
        )
        
        response_text = response.text.strip()
        
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
        return {"error": f"Failed to parse AI response: {e}"}
    except Exception as e:
        logger.error(f"Error refining evaluation: {e}")
        return {"error": f"Refinement error: {e}"}
