"""
Quiz Scores tab for Streamlit app.
Displays and manages quiz score data.
"""

import time
import logging
import streamlit as st

from core.auth import setup_session
from core.api import fetch_quiz_scores_all, get_quizzes, get_available_groups
from core.persistence import (
    load_csv_from_disk, save_csv_to_disk, 
    save_meta, dataframe_to_csv
)
from streamlit_modules.ui.components import show_data_status, show_fresh_status

logger = logging.getLogger(__name__)


@st.cache_data(ttl=300, show_spinner=False)
def get_cached_quiz_groups(_session_id, course_id):
    """Cache quiz list and course groups for 5 minutes to avoid repeated API calls.
    
    Note: _session_id is prefixed with underscore to prevent Streamlit from hashing it.
    Uses get_course_groups which returns group names WITH member counts from Moodle.
    """
    from core.api import get_course_groups
    session = setup_session(_session_id)
    quizzes_list = get_quizzes(session, course_id)
    if not quizzes_list:
        return None, []
    # Use get_course_groups which gets full group list with member counts
    groups = get_course_groups(session, course_id)
    return quizzes_list, groups or []


def render_quiz_tab(course, meta):
    """Render the Quiz Scores tab content"""
    st.subheader("Practice Quiz Scores")
    
    # Use global group from sidebar (if selected)
    selected_quiz_group_id = None
    if st.session_state.selected_group:
        selected_quiz_group_id = st.session_state.selected_group['id']
        st.info(f"📌 Filtering by: {st.session_state.selected_group['name']}")
    else:
        st.caption("💡 Select a group in the sidebar to filter results")
    
    # Construct filename based on group
    quiz_filename = f"quiz_scores_{course['id']}"
    if selected_quiz_group_id:
        quiz_filename += f"_grp{selected_quiz_group_id}"
    quiz_filename += ".csv"
    
    quiz_meta_key = 'quiz'
    if selected_quiz_group_id:
        quiz_meta_key += f"_grp{selected_quiz_group_id}"

    # Check if current loaded data matches selected group
    if 'quiz_loaded_group_id' not in st.session_state:
        st.session_state.quiz_loaded_group_id = None
        
    if st.session_state.quiz_data is None or st.session_state.quiz_loaded_group_id != selected_quiz_group_id:
        disk_data = load_csv_from_disk(course['id'], quiz_filename)
        if disk_data:
            st.session_state.quiz_data = disk_data
            st.session_state.quiz_loaded_from_disk = True
            st.session_state.quiz_loaded_group_id = selected_quiz_group_id
        elif st.session_state.quiz_loaded_group_id != selected_quiz_group_id:
            # Group changed but no data on disk, clear current view
            st.session_state.quiz_data = None
            st.session_state.quiz_loaded_from_disk = False
            st.session_state.quiz_loaded_group_id = selected_quiz_group_id
    
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.session_state.quiz_loaded_from_disk and quiz_meta_key in meta:
            show_data_status(meta, quiz_meta_key, 'Quiz')
        elif st.session_state.quiz_data:
            show_fresh_status(len(st.session_state.quiz_data))
    
    with col2:
        fetch_quiz = st.button(
            "🔄 Refresh" if st.session_state.quiz_data else "📥 Fetch",
            key="fetch_quiz",
            use_container_width=True
        )
    
    if fetch_quiz:
        progress_bar = st.progress(0, text="Fetching quiz scores...")
        
        def update_progress(value):
            progress_bar.progress(value, text=f"Fetching quiz scores... {int(value * 100)}%")
        
        quiz_names, rows = fetch_quiz_scores_all(
            st.session_state.session_id, course['id'], selected_quiz_group_id, update_progress
        )
        
        progress_bar.progress(1.0, text="Complete!")
        
        if rows:
            logger.info(f"Fetch complete. Found scores for {len(rows)} students.")
            st.session_state.quiz_data = rows
            st.session_state.quiz_loaded_from_disk = False
            st.session_state.quiz_loaded_group_id = selected_quiz_group_id
            
            # Save to disk
            save_csv_to_disk(course['id'], quiz_filename, rows)
            save_meta(course['id'], quiz_meta_key, len(rows))
            
            st.success(f"✓ Fetched scores for {len(rows)} students → Saved to `output/course_{course['id']}/`")
            st.rerun()
        else:
            st.warning("No quiz data found (no practice quizzes or no attempts)")
    
    if st.session_state.quiz_data:
        st.dataframe(
            st.session_state.quiz_data,
            use_container_width=True,
            hide_index=True
        )
        
        csv_data = dataframe_to_csv(st.session_state.quiz_data)
        st.download_button(
            label="📥 Download CSV",
            data=csv_data,
            file_name=quiz_filename,
            mime="text/csv"
        )
