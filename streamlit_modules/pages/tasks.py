"""
Tasks tab for Streamlit app.
Displays and manages assignment tasks data.
"""

import time
import logging
import streamlit as st

from core.api import fetch_tasks_list
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
            use_container_width=True
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
        st.dataframe(
            st.session_state.tasks_data,
            use_container_width=True,
            hide_index=True,
            column_config={
                "URL": st.column_config.LinkColumn("URL", display_text="Open")
            }
        )
        
        csv_data = convert_to_csv(st.session_state.tasks_data)
        st.download_button(
            label="📥 Download CSV",
            data=csv_data,
            file_name=f"tasks_{course['id']}.csv",
            mime="text/csv"
        )
