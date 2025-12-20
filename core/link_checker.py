"""
Link status checker for activity URLs.

Provides functions to check URL accessibility and cache results.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

logger = logging.getLogger(__name__)

# Cache directory
CACHE_DIR = Path(".cache")


def check_url_status(url: str, session=None, timeout=5) -> dict:
    """
    Check if a URL is accessible.
    
    Args:
        url: URL to check
        session: Optional requests session (for authenticated requests)
        timeout: Request timeout in seconds
    
    Returns:
        dict with status, code, message
    """
    if not url:
        return {"status": "unknown", "code": 0, "message": "No URL"}
    
    try:
        # Use session if provided (for internal Moodle links)
        req = session if session else requests
        
        # Try HEAD first (faster)
        try:
            resp = req.head(url, timeout=timeout, allow_redirects=True)
        except:
            # Some servers don't support HEAD, try GET
            resp = req.get(url, timeout=timeout, allow_redirects=True, stream=True)
            resp.close()
        
        code = resp.status_code
        
        if code == 200:
            return {"status": "ok", "code": code, "message": "OK"}
        elif code in (301, 302, 303, 307, 308):
            return {"status": "redirect", "code": code, "message": f"Redirects to {resp.headers.get('Location', 'unknown')}"}
        elif code == 401 or code == 403:
            return {"status": "auth_required", "code": code, "message": "Authentication required"}
        elif code == 404:
            return {"status": "error", "code": code, "message": "Not found (404)"}
        elif code >= 500:
            return {"status": "error", "code": code, "message": f"Server error ({code})"}
        else:
            return {"status": "error", "code": code, "message": f"HTTP {code}"}
            
    except requests.Timeout:
        return {"status": "error", "code": 0, "message": "Timeout"}
    except requests.ConnectionError:
        return {"status": "error", "code": 0, "message": "Connection failed"}
    except Exception as e:
        logger.warning(f"Error checking URL {url}: {e}")
        return {"status": "error", "code": 0, "message": str(e)[:50]}


def check_urls_batch(urls: list, session=None, max_workers=5) -> dict:
    """
    Check multiple URLs in parallel.
    
    Args:
        urls: List of URLs to check
        session: Optional requests session
        max_workers: Max parallel threads
    
    Returns:
        dict mapping URL -> status dict
    """
    results = {}
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {
            executor.submit(check_url_status, url, session): url
            for url in urls if url
        }
        
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                results[url] = future.result()
            except Exception as e:
                results[url] = {"status": "error", "code": 0, "message": str(e)[:50]}
    
    return results


def get_cache_path(course_id: str) -> Path:
    """Get cache file path for a course."""
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"link_status_{course_id}.json"


def get_cached_status(course_id: str) -> dict:
    """
    Load cached link statuses for a course.
    
    Returns:
        dict mapping URL -> {status, code, message, checked_at}
    """
    cache_file = get_cache_path(course_id)
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error loading link cache: {e}")
    return {}


def save_cached_status(course_id: str, statuses: dict):
    """
    Save link statuses to cache with timestamp.
    
    Args:
        course_id: Course ID
        statuses: dict mapping URL -> status dict
    """
    cache_file = get_cache_path(course_id)
    
    # Load existing cache and merge
    existing = get_cached_status(course_id)
    
    # Add timestamp to new statuses
    now = datetime.now().isoformat()
    for url, status in statuses.items():
        status["checked_at"] = now
        existing[url] = status
    
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving link cache: {e}")


def format_time_ago(iso_timestamp: str) -> str:
    """
    Format timestamp as human-readable "X ago" string.
    
    Args:
        iso_timestamp: ISO format timestamp
    
    Returns:
        Human-readable string like "5 minutes ago"
    """
    if not iso_timestamp:
        return "Never"
    
    try:
        checked = datetime.fromisoformat(iso_timestamp)
        now = datetime.now()
        delta = now - checked
        
        seconds = int(delta.total_seconds())
        
        if seconds < 60:
            return "Just now"
        elif seconds < 3600:
            mins = seconds // 60
            return f"{mins} min{'s' if mins > 1 else ''} ago"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        else:
            days = seconds // 86400
            return f"{days} day{'s' if days > 1 else ''} ago"
    except:
        return "Unknown"
