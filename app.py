#!/usr/bin/env python3
"""
Paatshala Tool - Refactored GUI Version (Streamlit)
"""

import logging
import streamlit as st

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

from core.auth import (
    login_and_get_cookie, validate_session, setup_session, attempt_auto_login
)
from core.api import get_courses, get_course_groups
from core.persistence import (
    write_config, clear_config,
    load_last_session, save_last_session,
    load_meta,
    OUTPUT_DIR, get_output_dir
)
from streamlit_modules.ui.styles import apply_custom_css
from streamlit_modules.session import init_session_state, clear_course_data
# Tab renderers are now lazy-loaded via tab_registry for better performance
from streamlit_modules.pages.config import render_config_page

# ============================================================================
# PAGE CONFIG
# ============================================================================

st.set_page_config(
    page_title="Paatshala Tool",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

apply_custom_css()

# Initialize session state
init_session_state()

# ============================================================================
# MAIN APP
# ============================================================================

def main():
    # Attempt auto-login on first load
    if not st.session_state.authenticated and not st.session_state.auto_login_attempted:
        logger.info("Attempting auto-login...")
        if attempt_auto_login():
            logger.info("Auto-login successful")
            st.rerun()
        else:
            logger.info("Auto-login failed or no credentials")
    
    # Header
    st.markdown('<p class="main-header">🎓 Paatshala Tool</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Extract data from ICT Academy Kerala\'s Moodle LMS</p>', unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        if not st.session_state.authenticated:
            # Login form - keep expanded for non-logged users
            st.header("🔐 Login")
            
            auth_method = st.radio(
                "Login method",
                ["Credentials", "Session Cookie"],
                horizontal=True,
                label_visibility="collapsed"
            )
            
            if auth_method == "Credentials":
                username = st.text_input("Username", label_visibility="collapsed", placeholder="Username")
                password = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="Password")
                remember_me = st.checkbox("Remember me", value=True)
                
                if st.button("Login", type="primary", use_container_width=True):
                    if username and password:
                        with st.spinner("Logging in..."):
                            logger.info(f"Attempting manual login for user: {username}")
                            session_id = login_and_get_cookie(username, password)
                            if session_id:
                                st.session_state.session_id = session_id
                                st.session_state.authenticated = True
                                st.session_state.auth_source = 'manual'
                                
                                if remember_me:
                                    write_config(cookie=session_id, username=username, password=password)
                                else:
                                    write_config(cookie=session_id)
                                
                                st.success("✓ Logged in!")
                                st.rerun()
                            else:
                                st.error("✗ Login failed")
                    else:
                        st.warning("Enter username and password")
            
            else:  # Cookie method
                cookie = st.text_input("Cookie", type="password", label_visibility="collapsed", placeholder="MoodleSession Cookie")
                remember_cookie = st.checkbox("Save cookie", value=True)
                
                if st.button("Validate & Login", type="primary", use_container_width=True):
                    if cookie:
                        with st.spinner("Validating..."):
                            if validate_session(cookie):
                                st.session_state.session_id = cookie
                                st.session_state.authenticated = True
                                st.session_state.auth_source = 'cookie'
                                
                                if remember_cookie:
                                    write_config(cookie=cookie)
                                
                                st.success("✓ Valid!")
                                st.rerun()
                            else:
                                st.error("✗ Invalid cookie")
                    else:
                        st.warning("Enter cookie")
        
        else:
            # === COMPACT LOGGED-IN SIDEBAR ===
            
            # Status + Logout in one line
            col_status, col_logout = st.columns([3, 1])
            with col_status:
                st.caption(f"✓ Logged in")
            with col_logout:
                if st.button("↩️", help="Logout", key="logout_btn"):
                    st.session_state.authenticated = False
                    st.session_state.session_id = None
                    st.session_state.auth_source = None
                    st.session_state.courses = []
                    st.session_state.selected_course = None
                    clear_course_data()
                    st.rerun()
            
            # Load courses if not loaded
            if not st.session_state.courses:
                last = load_last_session()
                if last.get('courses'):
                    st.session_state.courses = last['courses']
                    if last.get('course_id'):
                        for c in st.session_state.courses:
                            if c['id'] == last['course_id']:
                                st.session_state.selected_course = c
                                break
                    st.rerun()
                else:
                    if st.button("Load Courses", type="primary", use_container_width=True):
                        with st.spinner("Loading..."):
                            session = setup_session(st.session_state.session_id)
                            st.session_state.courses = get_courses(session)
                            if st.session_state.courses:
                                save_last_session({'courses': st.session_state.courses})
                                st.rerun()
                            else:
                                st.warning("No courses found")
            
            if st.session_state.courses:
                # 📚 Course Dropdown (compact)
                course_options = {
                    f"{'⭐ ' if c['starred'] else ''}{c['name']}": c
                    for c in st.session_state.courses
                }
                
                current_index = 0
                if st.session_state.selected_course:
                    for i, (name, course) in enumerate(course_options.items()):
                        if course['id'] == st.session_state.selected_course['id']:
                            current_index = i
                            break
                
                selected_name = st.selectbox(
                    "📚 Course",
                    options=list(course_options.keys()),
                    index=current_index,
                    help="Select a course to work with"
                )
                
                if selected_name:
                    new_course = course_options[selected_name]
                    if st.session_state.selected_course is None or new_course['id'] != st.session_state.selected_course['id']:
                        logger.info(f"Selected course: {new_course['name']} ({new_course['id']})")
                        st.session_state.selected_course = new_course
                        clear_course_data()
                        save_last_session({
                            'course_id': new_course['id'],
                            'course_name': new_course['name']
                        })
                        st.rerun()
                
                # 👥 Group Dropdown (compact, shows "All" by default)
                if st.session_state.selected_course:
                    current_course_id = st.session_state.selected_course['id']
                    
                    # Load groups if not loaded OR if they're for a different course
                    groups_need_refresh = (
                        not st.session_state.course_groups or
                        st.session_state.get('_groups_course_id') != current_course_id
                    )
                    
                    if groups_need_refresh:
                        session = setup_session(st.session_state.session_id)
                        st.session_state.course_groups = get_course_groups(session, current_course_id)
                        st.session_state._groups_course_id = current_course_id  # Track which course these belong to
                        
                        # Restore last selected group for this course
                        if st.session_state.course_groups and st.session_state.selected_group is None:
                            last = load_last_session()
                            last_group_id = last.get('group_id')
                            if last_group_id:
                                for g in st.session_state.course_groups:
                                    if g['id'] == last_group_id:
                                        st.session_state.selected_group = g
                                        logger.info(f"Restored last selected group: {g['name']}")
                                        break
                    
                    if st.session_state.course_groups:
                        group_options = {"All": None}
                        group_options.update({
                            g['name']: g
                            for g in st.session_state.course_groups
                        })
                        
                        current_group_index = 0
                        if st.session_state.selected_group:
                            for i, (name, group) in enumerate(group_options.items()):
                                if group and group['id'] == st.session_state.selected_group['id']:
                                    current_group_index = i
                                    break
                        
                        selected_group_name = st.selectbox(
                            "👥 Group",
                            options=list(group_options.keys()),
                            index=current_group_index,
                            help="Filter by group (All = no filter)"
                        )
                        
                        new_group = group_options.get(selected_group_name)
                        if (st.session_state.selected_group is None and new_group is not None) or \
                           (st.session_state.selected_group is not None and new_group is None) or \
                           (st.session_state.selected_group is not None and new_group is not None and 
                            st.session_state.selected_group['id'] != new_group['id']):
                            st.session_state.selected_group = new_group
                            st.session_state.quiz_data = None
                            st.session_state.quiz_loaded_from_disk = False
                            st.session_state.submissions_data = None
                            st.session_state.submissions_loaded_from_disk = False
                            save_last_session({
                                'group_id': new_group['id'] if new_group else None,
                                'group_name': new_group['name'] if new_group else None
                            })
                            st.rerun()
            
            # Tab Manager (expandable dropdown with live updates)
            st.divider()
            from streamlit_modules.tab_registry import TAB_REGISTRY, get_all_tab_ids
            from core.persistence import get_enabled_tabs, set_enabled_tabs
            
            enabled_tabs = get_enabled_tabs()
            all_tab_ids = get_all_tab_ids()
            
            with st.expander(f"📑 Manage Tabs ({len(enabled_tabs)}/{len(all_tab_ids)})", expanded=False):
                st.caption("Check/uncheck to show/hide tabs instantly")
                
                # Individual tab checkboxes with live updates
                # IMPORTANT: Loop through enabled_tabs first to preserve order, then disabled tabs
                new_enabled = []
                
                # First show enabled tabs in their current order
                for tab_id in enabled_tabs:
                    tab_info = TAB_REGISTRY[tab_id]
                    is_enabled = st.checkbox(
                        f"{tab_info['name']}",
                        value=True,
                        key=f"tab_toggle_{tab_id}",
                        help=tab_info['description']
                    )
                    if is_enabled:
                        new_enabled.append(tab_id)
                
                # Then show disabled tabs
                for tab_id in all_tab_ids:
                    if tab_id not in enabled_tabs:
                        tab_info = TAB_REGISTRY[tab_id]
                        is_enabled = st.checkbox(
                            f"{tab_info['name']}",
                            value=False,
                            key=f"tab_toggle_{tab_id}",
                            help=tab_info['description']
                        )
                        if is_enabled:
                            new_enabled.append(tab_id)
                
                # Auto-save if changed
                if new_enabled != enabled_tabs:
                    set_enabled_tabs(new_enabled)
                    st.rerun()
            
            # Action buttons row (compact icons)
            st.divider()
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                if st.button("🔄", help="Refresh courses", use_container_width=True):
                    with st.spinner("..."):
                        session = setup_session(st.session_state.session_id)
                        st.session_state.courses = get_courses(session)
                        if st.session_state.courses:
                            save_last_session({'courses': st.session_state.courses})
                        st.rerun()
            with col2:
                from core.persistence import clear_cache
                if st.button("🧹", help="Clear cache", use_container_width=True):
                    clear_cache()
                    st.toast("Cache cleared")
            with col3:
                from core.persistence import clear_output
                if st.button("📂", help="Clear output folder", use_container_width=True):
                    clear_output()
                    st.toast("Output folder cleared")
            with col4:
                if st.button("⚙️", help="Configuration", use_container_width=True):
                    st.session_state.show_config_page = True
                    st.rerun()
    
    # Main content area
    if not st.session_state.authenticated:
        st.info("👈 Please login using the sidebar to get started.")
        
        st.markdown("### Features")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("#### 📋 Tasks")
            st.write("Fetch all assignments with due dates, grades, and submission statistics.")
        
        with col2:
            st.markdown("#### 📊 Quiz Scores")
            st.write("Scrape practice quiz scores for all students in a course.")
        
        with col3:
            st.markdown("#### 📝 Submissions")
            st.write("Get detailed grading data for specific assignments with group filtering.")
        
        return
    
    if not st.session_state.courses:
        st.info("👈 Click 'Load Courses' in the sidebar to get started.")
        return
    
    # Check if config page is requested
    if st.session_state.get('show_config_page'):
        # Back button
        if st.button("← Back to Dashboard"):
            st.session_state.show_config_page = False
            st.rerun()
        render_config_page()
        return
    
    if not st.session_state.selected_course:
        st.info("👈 Select a course from the sidebar.")
        return
    
    # Course is selected
    course = st.session_state.selected_course
    meta = load_meta(course['id'])
    
    st.markdown(f"### 📖 {course['name']}")
    st.caption(f"Course ID: {course['id']} | Category: {course['category'] or 'N/A'}")
    
    st.divider()
    
    # Dynamic tabs based on configuration
    from streamlit_modules.tab_registry import TAB_REGISTRY, get_tab_renderer
    from core.persistence import get_enabled_tabs, set_enabled_tabs
    
    enabled_tab_ids = get_enabled_tabs()
    
    # Validate tab IDs against registry (preserves order from config)
    # To reorder tabs, edit the order in .config file: enabled_tabs=evaluation,tasks,quiz,...
    valid_tab_ids = [tid for tid in enabled_tab_ids if tid in TAB_REGISTRY]
    
    if not valid_tab_ids:
        # No tabs enabled - show helpful message
        st.info("📭 No tabs are currently enabled.")
        st.markdown("""
        **To enable tabs:**
        1. Open the **📑 Manage Tabs** dropdown in the sidebar
        2. Check the tabs you want to use
        3. Tabs will appear instantly!
        
        Or use the quick actions below:
        """)
        
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            if st.button("✨ Enable Default Tabs", type="primary"):
                from streamlit_modules.tab_registry import DEFAULT_ENABLED_TABS
                set_enabled_tabs(DEFAULT_ENABLED_TABS.copy())
                st.rerun()
        with col2:
            if st.button("✅ Enable All Tabs"):
                from streamlit_modules.tab_registry import get_all_tab_ids
                set_enabled_tabs(get_all_tab_ids())
                st.rerun()
    else:
        # Build tab names for enabled tabs
        tab_names = [TAB_REGISTRY[tid]['name'] for tid in valid_tab_ids]
        
        # Create tabs dynamically
        tabs = st.tabs(tab_names)
        
        # Render each tab with lazy loading
        for i, tab_id in enumerate(valid_tab_ids):
            with tabs[i]:
                renderer = get_tab_renderer(tab_id)
                if renderer:
                    try:
                        renderer(course, meta)
                    except Exception as e:
                        st.error(f"Error rendering tab: {e}")
                        logger.error(f"Error in tab {tab_id}: {e}", exc_info=True)
                else:
                    st.error(f"Failed to load tab renderer for: {tab_id}")


if __name__ == "__main__":
    main()
