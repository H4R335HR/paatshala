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
from streamlit_modules.pages import (
    render_tasks_tab,
    render_quiz_tab,
    render_submissions_tab,
    render_evaluation_tab,
    render_workshop_tab
)

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
            
            # Action buttons row (compact icons)
            st.divider()
            col1, col2, col3 = st.columns(3)
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
    
    if not st.session_state.selected_course:
        st.info("👈 Select a course from the sidebar.")
        return
    
    # Course is selected
    course = st.session_state.selected_course
    meta = load_meta(course['id'])
    
    st.markdown(f"### 📖 {course['name']}")
    st.caption(f"Course ID: {course['id']} | Category: {course['category'] or 'N/A'}")
    
    st.divider()
    
    # Tabs - now using modular page renderers
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📋 Tasks", "📊 Quiz Scores", "📝 Submissions", "🔍 Evaluation", "🔧 Workshops"])
    
    with tab1:
        render_tasks_tab(course, meta)
    
    with tab2:
        render_quiz_tab(course, meta)
    
    with tab3:
        render_submissions_tab(course, meta)
    
    with tab4:
        render_evaluation_tab(course, meta)
    
    with tab5:
        render_workshop_tab(course, meta)


if __name__ == "__main__":
    main()
