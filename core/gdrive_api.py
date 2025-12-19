"""
Google Drive API integration for fetching video files.
Supports both OAuth and service account credentials.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def get_videos_from_folder_api(folder_id: str, credentials_path: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Fetch video files from Google Drive folder using API.
    Supports both OAuth and service account credentials.
    
    Args:
        folder_id: Google Drive folder ID
        credentials_path: Path to credentials JSON file (OAuth or service account)
    
    Returns:
        List of dicts with keys: 'name', 'file_id', 'embed_url'
    """
    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        logger.error("Google API client not installed. Run: pip install google-api-python-client google-auth google-auth-oauthlib")
        return []
    
    # Get credentials path from config if not provided
    if not credentials_path:
        from core.persistence import get_config
        credentials_path = get_config('google_drive_credentials')
        
        if not credentials_path:
            logger.error("No Google Drive credentials configured")
            return []
    
    # Check if credentials file exists
    creds_file = Path(credentials_path)
    if not creds_file.exists():
        logger.error(f"Credentials file not found: {credentials_path}")
        return []
    
    try:
        # Load credentials file to determine type
        with open(creds_file, 'r') as f:
            creds_data = json.load(f)
        
        credentials = None
        
        # Check if it's a service account or OAuth credentials
        if creds_data.get('type') == 'service_account':
            # Service account credentials
            logger.info("Using service account credentials")
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=['https://www.googleapis.com/auth/drive.readonly']
            )
        elif 'installed' in creds_data or 'web' in creds_data:
            # OAuth client credentials - need to do OAuth flow
            logger.info("Using OAuth credentials")
            
            # Check if we have a token file
            token_path = Path(credentials_path).parent / "gdrive_token.json"
            
            if token_path.exists():
                # Load existing token
                credentials = Credentials.from_authorized_user_file(
                    str(token_path),
                    ['https://www.googleapis.com/auth/drive.readonly']
                )
            
            # If no valid credentials, do OAuth flow
            if not credentials or not credentials.valid:
                flow = InstalledAppFlow.from_client_secrets_file(
                    credentials_path,
                    ['https://www.googleapis.com/auth/drive.readonly']
                )
                credentials = flow.run_local_server(port=0)
                
                # Save token for future use
                with open(token_path, 'w') as token:
                    token.write(credentials.to_json())
        else:
            logger.error("Unknown credentials format")
            return []
        
        # Build Drive API service
        service = build('drive', 'v3', credentials=credentials)
        
        # Query for video files in the folder
        query = f"'{folder_id}' in parents and trashed=false"
        query += " and (mimeType contains 'video/' or name contains '.mp4' or name contains '.mkv' or name contains '.avi' or name contains '.mov' or name contains '.webm')"
        
        results = service.files().list(
            q=query,
            pageSize=1000,  # Max results per page
            fields="files(id, name, mimeType)",
            orderBy="name"
        ).execute()
        
        files = results.get('files', [])
        
        # Convert to our format
        videos = []
        for file in files:
            # Filter for video files
            name = file.get('name', '')
            if name.lower().endswith(('.mp4', '.mkv', '.avi', '.mov', '.webm')):
                videos.append({
                    'name': name,
                    'file_id': file.get('id'),
                    'embed_url': f"https://drive.google.com/file/d/{file.get('id')}/preview"
                })
        
        logger.info(f"Found {len(videos)} videos in folder {folder_id}")
        return videos
        
    except Exception as e:
        logger.error(f"Error fetching videos from Google Drive API: {e}")
        return []


def test_credentials(credentials_path: str) -> bool:
    """
    Test if Google Drive credentials are valid.
    
    Args:
        credentials_path: Path to credentials JSON file
    
    Returns:
        bool: True if credentials are valid
    """
    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        from google.oauth2.credentials import Credentials
    except ImportError:
        return False
    
    creds_file = Path(credentials_path)
    if not creds_file.exists():
        return False
    
    try:
        # Load and check credentials type
        with open(creds_file, 'r') as f:
            creds_data = json.load(f)
        
        if creds_data.get('type') == 'service_account':
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=['https://www.googleapis.com/auth/drive.readonly']
            )
        else:
            # For OAuth, check if token exists
            token_path = Path(credentials_path).parent / "gdrive_token.json"
            if token_path.exists():
                credentials = Credentials.from_authorized_user_file(
                    str(token_path),
                    ['https://www.googleapis.com/auth/drive.readonly']
                )
            else:
                # Token doesn't exist yet, but credentials file is valid
                return True
        
        # Try to build service
        service = build('drive', 'v3', credentials=credentials)
        
        # Try a simple API call
        service.files().list(pageSize=1).execute()
        
        return True
    except Exception as e:
        logger.error(f"Credentials test failed: {e}")
        return False
