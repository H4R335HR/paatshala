"""
Session state management for Streamlit app.
Centralizes session state initialization and access.
"""

import streamlit as st


def init_session_state():
    """Initialize all session state variables"""
    defaults = {
        'authenticated': False,
        'session_id': None,
        'auth_source': None,  # 'config', 'manual', 'cookie'
        'courses': [],
        'selected_course': None,
        'course_groups': [],  # Groups for the selected course
        'selected_group': None,  # Currently selected group (dict with 'id', 'name')
        'tasks_data': None,
        'tasks_loaded_from_disk': False,
        'quiz_data': None,
        'quiz_loaded_from_disk': False,
        'quiz_loaded_group_id': None,
        'submissions_data': None,
        'submissions_loaded_from_disk': False,
        'auto_login_attempted': False,
        'selected_task_for_submissions': None,
        # Workshop tab state
        'workshops_data': None,
        'workshops_loaded_from_disk': False,
        'workshop_submissions_data': None,
        'selected_workshop': None,
        # Feedback tab state
        'feedbacks_data': None,
        'feedbacks_loaded_from_disk': False,
        'feedback_responses_data': None,
        'feedback_non_respondents_data': None,
        'feedback_overview_data': None,
        'selected_feedback': None,
        # TryHackMe tab state
        'tryhackme_data': None,
        # Quizizz tab state
        'quizizz_data': None,  # Combined data from all uploaded files
        'quizizz_name_mappings': {},  # Manual name mappings {quizizz_name: moodle_name}
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def get_session_id():
    """Get the current session ID"""
    return st.session_state.get('session_id')


def get_selected_course():
    """Get the currently selected course"""
    return st.session_state.get('selected_course')


def is_authenticated():
    """Check if user is authenticated"""
    return st.session_state.get('authenticated', False)


def clear_course_data():
    """Clear all course-related data from session state"""
    st.session_state.course_groups = []
    st.session_state.selected_group = None
    st.session_state.tasks_data = None
    st.session_state.tasks_loaded_from_disk = False
    st.session_state.quiz_data = None
    st.session_state.quiz_loaded_from_disk = False
    st.session_state.quiz_loaded_group_id = None
    st.session_state.submissions_data = None
    st.session_state.submissions_loaded_from_disk = False
    # Workshop state
    st.session_state.workshops_data = None
    st.session_state.workshops_loaded_from_disk = False
    st.session_state.workshop_submissions_data = None
    st.session_state.selected_workshop = None
    # Feedback state
    st.session_state.feedbacks_data = None
    st.session_state.feedbacks_loaded_from_disk = False
    st.session_state.feedback_responses_data = None
    st.session_state.feedback_non_respondents_data = None
    st.session_state.feedback_overview_data = None
    st.session_state.selected_feedback = None
    # TryHackMe state
    st.session_state.tryhackme_data = None
    # Quizizz state
    st.session_state.quizizz_data = None
    st.session_state.quizizz_name_mappings = {}


def logout():
    """Clear authentication and all related data"""
    st.session_state.authenticated = False
    st.session_state.session_id = None
    st.session_state.auth_source = None
    st.session_state.courses = []
    st.session_state.selected_course = None
    clear_course_data()
