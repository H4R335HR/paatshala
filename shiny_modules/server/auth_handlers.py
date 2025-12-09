"""
Authentication handlers for Shiny app.

This module contains login and auto-authentication logic,
extracted from the main shiny_app.py for better organization.
"""
from shiny import reactive, ui
from core.auth import login_and_get_cookie, validate_session
from core.persistence import read_config, write_config, save_cache, load_cache
import logging

logger = logging.getLogger(__name__)


def register_auth_handlers(
    input,
    auth_initialized,
    user_session_id,
    user_authenticated,
    current_username
):
    """
    Register authentication handlers.
    
    Args:
        input: Shiny input object
        auth_initialized: reactive.Value(False)
        user_session_id: reactive.Value(None)
        user_authenticated: reactive.Value(False)
        current_username: reactive.Value("")
    """
    
    @reactive.Effect
    def auto_authenticate():
        """Attempt auto-login from config on first load (runs once)"""
        if auth_initialized():
            return  # Already initialized
        
        auth_initialized.set(True)  # Mark as done
        
        loaded_cookie, loaded_user, loaded_pwd = read_config()
        
        if loaded_cookie:
            # Check if we validated recently (within 1 hour) - skip network call
            from datetime import datetime, timedelta
            cached_validation = load_cache("session_validation")
            skip_validation = False
            
            if cached_validation:
                try:
                    last_validated = datetime.fromisoformat(cached_validation.get("timestamp", ""))
                    cached_cookie = cached_validation.get("cookie", "")
                    # Skip if same cookie and validated within 1 hour
                    if cached_cookie == loaded_cookie and datetime.now() - last_validated < timedelta(hours=1):
                        skip_validation = True
                        logger.info("Session validated recently, skipping network check")
                except:
                    pass
            
            if skip_validation:
                # Trust the cached validation
                user_session_id.set(loaded_cookie)
                user_authenticated.set(True)
                current_username.set(loaded_user if loaded_user else "User")
                ui.notification_show("Session restored!", type="message", duration=2)
                return
            
            # Need to validate via network
            ui.notification_show("Validating saved session...", duration=2)
            if validate_session(loaded_cookie):
                user_session_id.set(loaded_cookie)
                user_authenticated.set(True)
                current_username.set(loaded_user if loaded_user else "User")
                # Cache this validation
                save_cache("session_validation", {
                    "timestamp": datetime.now().isoformat(),
                    "cookie": loaded_cookie
                })
                ui.notification_show("Session restored!", type="message", duration=2)
                return
        
        if loaded_user and loaded_pwd:
            ui.notification_show("Logging in...", duration=2)
            sid = login_and_get_cookie(loaded_user, loaded_pwd)
            if sid:
                user_session_id.set(sid)
                user_authenticated.set(True)
                current_username.set(loaded_user)
                # Save the new cookie for faster startup next time
                write_config(cookie=sid)
                # Also cache this validation
                from datetime import datetime
                save_cache("session_validation", {
                    "timestamp": datetime.now().isoformat(),
                    "cookie": sid
                })
                ui.notification_show("Login successful!", type="message", duration=2)
                return
        
        # If we get here, no auto-auth worked - user will see login form
    
    @reactive.Effect
    @reactive.event(input.login_btn)
    def do_login():
        if input.username() and input.password():
            ui.notification_show("Authenticating...", duration=1)
            sid = login_and_get_cookie(input.username(), input.password())
            if sid:
                user_session_id.set(sid)
                user_authenticated.set(True)
                current_username.set(input.username())
            else:
                ui.notification_show("Invalid credentials", type="error")
