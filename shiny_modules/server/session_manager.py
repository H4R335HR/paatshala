"""
Centralized session management for Moodle API calls.

This module eliminates 25+ repetitions of setup_session(user_session_id()).
"""
from core.auth import setup_session


class SessionManager:
    """
    Manages Moodle session state with optional caching.
    
    Usage:
        session_mgr = SessionManager(lambda: user_session_id())
        s = session_mgr.get()  # Returns configured requests.Session
    """
    
    def __init__(self, user_session_id_getter):
        """
        Initialize session manager.
        
        Args:
            user_session_id_getter: Callable that returns the current user session ID
        """
        self._getter = user_session_id_getter
        self._session_cache = None
    
    def get(self):
        """
        Get Moodle session (creates new if not cached).
        
        Returns:
            requests.Session configured with Moodle cookies
        """
        if self._session_cache is None:
            self._session_cache = setup_session(self._getter())
        return self._session_cache
    
    def get_fresh(self):
        """
        Get a fresh session (bypasses cache).
        
        Returns:
            requests.Session configured with Moodle cookies
        """
        self._session_cache = setup_session(self._getter())
        return self._session_cache
    
    def invalidate(self):
        """Invalidate cached session (forces refresh on next get)."""
        self._session_cache = None
