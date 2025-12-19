"""
Google Drive Parser Module
Utilities for parsing Google Drive video filenames and generating embed HTML.
"""

import re
from typing import List, Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


def parse_video_filename(filename: str) -> Tuple[Optional[int], str]:
    """
    Parse video filename to extract session number and clean title.
    
    Example:
        Input:  "#1.1_-_what_is_cyber_security_v30 (720p).mp4"
        Output: (1, "What Is Cyber Security")
    
    Args:
        filename: Video filename
    
    Returns:
        Tuple of (session_number, clean_title)
        session_number is None if not found
    """
    # Extract session number from #X or #X.Y pattern
    session_match = re.search(r'#(\d+)', filename)
    session_number = int(session_match.group(1)) if session_match else None
    
    # Remove file extension
    name = re.sub(r'\.(mp4|mkv|avi|mov|webm)$', '', filename, flags=re.IGNORECASE)
    
    # Remove session number pattern (#1.1, #1, etc.)
    name = re.sub(r'#\d+\.?\d*', '', name)
    
    # Remove quality indicators (720p, 1080p, etc.)
    name = re.sub(r'\(?\d{3,4}p\)?', '', name, flags=re.IGNORECASE)
    
    # Remove version numbers (v30, v2.0, etc.)
    name = re.sub(r'v\d+\.?\d*', '', name, flags=re.IGNORECASE)
    
    # Remove leading/trailing underscores, hyphens, and spaces
    name = re.sub(r'^[_\-\s]+|[_\-\s]+$', '', name)
    
    # Replace underscores and multiple hyphens with spaces
    name = re.sub(r'_+', ' ', name)
    name = re.sub(r'-+', ' ', name)
    
    # Remove extra spaces
    name = re.sub(r'\s+', ' ', name).strip()
    
    # Title case
    name = name.title()
    
    return session_number, name


def generate_embed_html(file_id: str, width: int = 640, height: int = 480) -> str:
    """
    Generate iframe HTML for embedding Google Drive video.
    
    Args:
        file_id: Google Drive file ID
        width: Iframe width in pixels
        height: Iframe height in pixels
    
    Returns:
        HTML iframe string
    """
    return f'<iframe src="https://drive.google.com/file/d/{file_id}/preview" width="{width}" height="{height}" allow="autoplay"></iframe>'


def group_videos_by_session(videos: List[Dict[str, str]]) -> Dict[int, List[Dict[str, str]]]:
    """
    Group videos by session number.
    
    Args:
        videos: List of video dicts with 'name', 'file_id', 'embed_url'
    
    Returns:
        Dict mapping session_number -> list of videos
        Videos without session numbers are grouped under key 0
    """
    grouped = {}
    
    for video in videos:
        session_num, clean_title = parse_video_filename(video['name'])
        
        # Add parsed info to video dict
        video['session'] = session_num if session_num else 0
        video['clean_title'] = clean_title
        
        # Group by session
        if video['session'] not in grouped:
            grouped[video['session']] = []
        grouped[video['session']].append(video)
    
    # Sort videos within each session by filename
    for session in grouped:
        grouped[session].sort(key=lambda v: v['name'])
    
    return grouped


def extract_folder_id(folder_url: str) -> Optional[str]:
    """
    Extract folder ID from Google Drive URL.
    
    Args:
        folder_url: Google Drive folder URL
    
    Returns:
        Folder ID or None if not found
    """
    match = re.search(r'/folders/([a-zA-Z0-9_-]+)', folder_url)
    return match.group(1) if match else None
