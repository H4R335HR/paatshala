"""
Tasks tab for Streamlit app.
Displays and manages assignment tasks data.
"""

import time
import logging
import streamlit as st

from core.api import fetch_tasks_list, get_course_activity_restrictions
from core.auth import setup_session
from core.grading_pipeline import is_task_permitted_for_group
from core.persistence import (
    load_csv_from_disk, save_csv_to_disk, 
    load_meta, save_meta, dataframe_to_csv
)
from streamlit_modules.ui.components import show_data_status, show_fresh_status

logger = logging.getLogger(__name__)


@st.cache_data
def convert_to_csv(data):
    """Cached wrapper for CSV conversion"""
    return dataframe_to_csv(data)


def render_tasks_tab(course, meta):
    """Render the Tasks tab content"""
    st.subheader("Assignment Tasks")
    
    # Try to load from disk if not loaded
    if st.session_state.tasks_data is None:
        disk_data = load_csv_from_disk(course['id'], f"tasks_{course['id']}.csv")
        if disk_data:
            st.session_state.tasks_data = disk_data
            st.session_state.tasks_loaded_from_disk = True
    
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.session_state.tasks_loaded_from_disk and 'tasks' in meta:
            show_data_status(meta, 'tasks', 'Tasks')
        elif st.session_state.tasks_data:
            show_fresh_status(len(st.session_state.tasks_data))
    
    with col2:
        fetch_tasks = st.button(
            "🔄 Refresh" if st.session_state.tasks_data else "📥 Fetch",
            key="fetch_tasks",
            width="stretch"
        )
    
    if fetch_tasks:
        progress_bar = st.progress(0, text="Fetching tasks...")
        
        def update_progress(value):
            progress_bar.progress(value, text=f"Fetching tasks... {int(value * 100)}%")
        
        logger.info("Starting task fetch...")
        rows = fetch_tasks_list(st.session_state.session_id, course['id'], update_progress)
        logger.info(f"Task fetch complete. Found {len(rows)} tasks.")
        
        progress_bar.progress(1.0, text="Complete!")
        
        if rows:
            st.session_state.tasks_data = rows
            st.session_state.tasks_loaded_from_disk = False
            
            # Save to disk
            save_csv_to_disk(course['id'], f"tasks_{course['id']}.csv", rows)
            save_meta(course['id'], 'tasks', len(rows))
            
            st.success(f"✓ Fetched {len(rows)} tasks → Saved to `output/course_{course['id']}/`")
            st.rerun()
        else:
            st.warning("No tasks found")
    
    if st.session_state.tasks_data:
        restr_map = {}
        try:
            session = setup_session(st.session_state.session_id)
            restr_map = get_course_activity_restrictions(session, course['id'])
        except Exception as e:
            logger.debug(f"Could not load restrictions: {e}")

        show_all = True
        displayed_tasks = st.session_state.tasks_data

        if st.session_state.selected_group:
            filter_col1, filter_col2 = st.columns([3, 2])
            with filter_col1:
                st.info(f"📌 Active Batch: **{st.session_state.selected_group['name']}**")
            with filter_col2:
                show_all = st.checkbox(
                    "Show all assignments (include other batches)",
                    value=False,
                    key=f"tasks_show_all_{course['id']}",
                    help="Uncheck to hide activities restricted to other batches or hidden"
                )

            if not show_all:
                filtered = [
                    t for t in st.session_state.tasks_data
                    if is_task_permitted_for_group(t, st.session_state.selected_group, restr_map)
                ]
                if filtered:
                    displayed_tasks = filtered
                st.caption(f"🎯 Showing **{len(displayed_tasks)}** of **{len(st.session_state.tasks_data)}** assignments permitted for **{st.session_state.selected_group['name']}**")
        else:
            st.caption(f"Showing all **{len(st.session_state.tasks_data)}** assignments (select a group in sidebar to filter by batch)")

        st.dataframe(
            displayed_tasks,
            width="stretch",
            hide_index=True,
            column_config={
                "URL": st.column_config.LinkColumn("URL", display_text="Open")
            }
        )
        
        csv_data = convert_to_csv(displayed_tasks)
        st.download_button(
            label="📥 Download CSV" if show_all else f"📥 Download Filtered CSV ({len(displayed_tasks)} tasks)",
            data=csv_data,
            file_name=f"tasks_{course['id']}.csv",
            mime="text/csv"
        )
