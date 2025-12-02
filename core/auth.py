import requests
import streamlit as st
from .persistence import read_config, write_config

BASE = "https://paatshala.ictkerala.org"
PAATSHALA_HOST = "paatshala.ictkerala.org"

def login_and_get_cookie(username, password):
    """Login to Paathshala and extract session cookie"""
    try:
        response = requests.post(
            f"https://{PAATSHALA_HOST}/login/index.php",
            data={'username': username, 'password': password},
            allow_redirects=False,
            timeout=10
        )
        
        if 'MoodleSession' in response.cookies:
            return response.cookies['MoodleSession']
        return None
    except Exception:
        return None

def validate_session(session_id):
    """Check if a session cookie is valid"""
    try:
        s = requests.Session()
        s.cookies.set("MoodleSession", session_id, domain=PAATSHALA_HOST)
        s.headers.update({'User-Agent': 'Mozilla/5.0'})
        resp = s.get(f"{BASE}/my/", timeout=10)
        return resp.ok and 'login' not in resp.url.lower()
    except Exception:
        return False

def setup_session(session_id):
    """Create a requests session with auth cookie"""
    s = requests.Session()
    s.cookies.set("MoodleSession", session_id, domain=PAATSHALA_HOST)
    s.headers.update({'User-Agent': 'Mozilla/5.0'})
    return s

def attempt_auto_login():
    """Try to auto-login from config file"""
    if st.session_state.get('auto_login_attempted'):
        return False
    
    st.session_state.auto_login_attempted = True
    
    cookie, username, password = read_config()
    
    # Try cookie first
    if cookie:
        if validate_session(cookie):
            st.session_state.session_id = cookie
            st.session_state.authenticated = True
            st.session_state.auth_source = 'config_cookie'
            return True
    
    # Try credentials
    if username and password:
        session_id = login_and_get_cookie(username, password)
        if session_id:
            st.session_state.session_id = session_id
            st.session_state.authenticated = True
            st.session_state.auth_source = 'config_credentials'
            # Save new cookie for faster login next time
            write_config(cookie=session_id)
            return True
    
    return False
