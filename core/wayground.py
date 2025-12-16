"""
Wayground (formerly Quizizz) Authentication and Report Download Module
"""

import requests
import logging
from pathlib import Path
from .persistence import read_wayground_config, write_wayground_config

logger = logging.getLogger(__name__)

WAYGROUND_BASE = "https://wayground.com"
WAYGROUND_HOST = "wayground.com"

# Known report endpoints
REPORT_TYPES = {
    "quiz_session": "/admin/reports/quiz_session.xlsx",
    "quiz_user": "/admin/reports/quiz_user.xlsx",
}


def wayground_login(email: str, password: str):
    """
    Login to Wayground and return session with auth cookies.
    
    Returns:
        tuple: (session, user_info) or (None, None) on failure
    """
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'Origin': WAYGROUND_BASE,
            'Referer': f'{WAYGROUND_BASE}/login'
        })
        
        # Login request
        login_url = f"{WAYGROUND_BASE}/_authserver/public/public/v1/auth/login/local"
        payload = {
            "username": email,
            "password": password,
            "requestId": ""
        }
        
        logger.info(f"Attempting Wayground login for {email}")
        resp = session.post(login_url, json=payload, timeout=30)
        
        if resp.ok:
            data = resp.json()
            if data.get('success'):
                user_info = data.get('data', {}).get('user', {})
                logger.info(f"Wayground login successful for {user_info.get('firstName', email)}")
                return session, user_info
            else:
                logger.error(f"Wayground login failed: {data}")
                return None, None
        else:
            logger.error(f"Wayground login HTTP error: {resp.status_code}")
            return None, None
            
    except Exception as e:
        logger.error(f"Wayground login error: {e}")
        return None, None


def validate_wayground_session(session):
    """
    Check if a Wayground session is valid.
    
    Returns:
        bool: True if session is valid
    """
    try:
        resp = session.get(f"{WAYGROUND_BASE}/admin/reports", timeout=15, allow_redirects=False)
        # If we get redirected to login, session is invalid
        if resp.status_code == 302 or 'login' in resp.url:
            return False
        return resp.ok
    except Exception as e:
        logger.error(f"Wayground session validation error: {e}")
        return False


def get_available_reports(session):
    """
    Get list of available game reports from Wayground API.
    
    Returns:
        list: List of report dicts with 'id', 'name', and 'date' keys
    """
    try:
        import json
        
        # Fetch games list from the API
        api_url = f"{WAYGROUND_BASE}/_gameapi/main/public/v1/games"
        
        # Get CSRF token from cookies
        csrf_token = session.cookies.get('x-csrf-token', '')
        
        # Add required headers for API calls (matching browser requests)
        session.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'X-Csrf-Token': csrf_token,
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': f'{WAYGROUND_BASE}/admin/reports'
        })
        
        # Parameters as captured from the actual Wayground API
        filter_list = {
            "gameState": ["completed", "running", "waiting", "stopped", "scheduled", "paused", "archived"],
            "quizId": []
        }
        range_filter = {
            "createdAt": {"from": None, "to": None}
        }
        
        params = {
            'query': '',
            'from': 0,
            'size': 50,  # Get up to 50 games
            'filterList': json.dumps(filter_list),
            'groupIds': '[]',
            'rangeFilter': json.dumps(range_filter),
            'hostedBy': '[]',
            'mock': 'false'
        }
        
        resp = session.get(api_url, params=params, timeout=30)
        
        if not resp.ok:
            logger.error(f"Failed to fetch games list: {resp.status_code}")
            logger.error(f"Response body: {resp.text[:500] if resp.text else 'empty'}")
            return []
        
        data = resp.json()
        
        if not data.get('success'):
            logger.error(f"Games API error: {data}")
            return []
        
        games = data.get('data', {}).get('games', [])
        
        reports = []
        for game in games:
            game_id = game.get('_id', '')
            
            # The API returns name directly at the game level (e.g., "Day 6 - Live Cyber")
            # There's also quizName which contains the same value
            game_name = (
                game.get('name') or
                game.get('quizName') or
                game.get('info', {}).get('name') or
                'Unnamed Quiz'
            )
            
            created_at = game.get('createdAt', '')
            
            # Log the game structure for debugging if name is still missing
            if game_name == 'Unnamed Quiz':
                logger.debug(f"Game structure keys for {game_id}: {list(game.keys())}")
            
            if game_id:
                reports.append({
                    'id': game_id,
                    'name': game_name,
                    'date': created_at[:10] if created_at else '',
                })
        
        logger.info(f"Found {len(reports)} Wayground games/reports")
        return reports
        
    except Exception as e:
        logger.error(f"Error getting Wayground reports: {e}")
        return []


def download_report(session, game_id: str, save_path: Path = None):
    """
    Download a game report as Excel file.
    
    Args:
        session: Authenticated Wayground session
        game_id: The game/quiz ID to download report for
        save_path: Optional path to save file
        
    Returns:
        tuple: (bytes, filename) or (None, None) on failure
    """
    try:
        import urllib.parse
        import time
        
        logger.info(f"Requesting Excel export for game {game_id}")
        
        # Get CSRF token from cookies for the API request
        csrf_token = session.cookies.get('x-csrf-token', '')
        
        # Add required headers for API calls (matching browser requests)
        session.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'X-Csrf-Token': csrf_token,
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': f'{WAYGROUND_BASE}/admin/reports'
        })
        
        # Step 1: Request the Excel export URL from the download API
        # Format: /_gameapi/main/public/v1/games/{gameId}/download?offset=GMT%2B0530&_=12345
        # The offset should be like "GMT+0530" (no colon!) - browser encodes as GMT%2B0530
        offset = time.strftime('%z')  # Returns something like "+0530" or "-0800"
        if len(offset) >= 5:
            # Format as GMT+0530 (no colon between hours/minutes)
            offset_str = f"GMT{offset}"  # e.g., "GMT+0530"
        else:
            offset_str = "GMT+0000"
        
        download_api_url = f"{WAYGROUND_BASE}/_gameapi/main/public/v1/games/{game_id}/download"
        params = {
            'offset': offset_str,  # Will be URL-encoded automatically (+ becomes %2B)
            '_': str(int(time.time() * 1000) % 100000)  # Cache buster
        }
        
        resp = session.get(download_api_url, params=params, timeout=60)
        
        if not resp.ok:
            logger.error(f"Failed to get export URL: {resp.status_code}")
            return None, None
        
        data = resp.json()
        
        if not data.get('success'):
            logger.error(f"Export API error: {data}")
            return None, None
        
        excel_url = data.get('data', {}).get('link')
        
        if not excel_url:
            logger.error("No Excel link in response")
            return None, None
        
        logger.info(f"Got Excel URL: {excel_url}")
        
        # Step 2: Download the actual Excel file from the URL
        # The URL redirects from quizizz.com to wayground.com
        excel_resp = session.get(excel_url, timeout=120, allow_redirects=True)
        
        if not excel_resp.ok:
            logger.error(f"Failed to download Excel: {excel_resp.status_code}")
            return None, None
        
        # Get filename from URL
        filename = excel_url.split('/')[-1]
        content = excel_resp.content
        
        # Save to file if path provided
        if save_path:
            save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(content)
            logger.info(f"Saved report to {save_path}")
        
        return content, filename
        
    except Exception as e:
        logger.error(f"Error downloading report: {e}")
        return None, None


def fetch_wayground_reports(email: str, password: str, output_dir: Path):
    """
    Login to Wayground and download all available reports.
    
    Args:
        email: Wayground email
        password: Wayground password
        output_dir: Directory to save reports
        
    Returns:
        list: List of saved file paths
    """
    session, user_info = wayground_login(email, password)
    if not session:
        return []
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    saved_files = []
    reports = get_available_reports(session)
    
    for report in reports:
        # Generate filename from report name
        safe_name = "".join(c if c.isalnum() or c in '-_' else '_' for c in report['name'])
        save_path = output_dir / f"{safe_name}.xlsx"
        content, filename = download_report(session, report['id'], save_path)
        if content:
            saved_files.append(save_path)
    
    return saved_files


def attempt_wayground_auto_login():
    """
    Try to auto-login using config credentials.
    
    Returns:
        tuple: (session, user_info) or (None, None)
    """
    email, password = read_wayground_config()
    if email and password:
        return wayground_login(email, password)
    return None, None
