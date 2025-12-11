"""
Submissions tab for Streamlit app.
Displays and manages assignment submission data.
"""

import logging
import streamlit as st

from core.api import fetch_submissions, fetch_tasks_list
from core.persistence import (
    load_csv_from_disk, save_csv_to_disk, 
    load_last_session, save_last_session,
    save_meta, dataframe_to_csv
)
from streamlit_modules.ui.components import show_data_status

logger = logging.getLogger(__name__)


def render_submissions_tab(course, meta):
    """Render the Submissions tab content"""
    st.subheader("Assignment Submissions")
    
    # Need tasks first
    if not st.session_state.tasks_data:
        # Try loading from disk
        disk_data = load_csv_from_disk(course['id'], f"tasks_{course['id']}.csv")
        if disk_data:
            st.session_state.tasks_data = disk_data
            st.session_state.tasks_loaded_from_disk = True
            st.rerun()
        else:
            st.info("⚠️ Please fetch tasks first (in Tasks tab) to see available assignments.")
            
            if st.button("Quick Fetch Tasks", key="quick_fetch_tasks"):
                with st.spinner("Fetching tasks..."):
                    rows = fetch_tasks_list(st.session_state.session_id, course['id'])
                    if rows:
                        st.session_state.tasks_data = rows
                        save_csv_to_disk(course['id'], f"tasks_{course['id']}.csv", rows)
                        save_meta(course['id'], 'tasks', len(rows))
                        st.success(f"✓ Fetched {len(rows)} tasks")
                        st.rerun()
    else:
        # Task selector
        task_options = {
            f"{t['Task Name']} (ID: {t['Module ID']})": t
            for t in st.session_state.tasks_data
        }
        
        # Try to pre-select from last session
        pre_select_index = 0
        last = load_last_session()
        if last.get('last_module_id'):
            for i, (name, t) in enumerate(task_options.items()):
                if str(t['Module ID']) == str(last['last_module_id']):
                    pre_select_index = i
                    break

        selected_task_name = st.selectbox(
            "Select Assignment",
            options=list(task_options.keys()),
            index=pre_select_index
        )
        
        selected_task = task_options.get(selected_task_name)
        
        # Use global group from sidebar (if selected)
        selected_group_id = None
        if st.session_state.selected_group:
            selected_group_id = st.session_state.selected_group['id']
            st.info(f"📌 Filtering by: {st.session_state.selected_group['name']}")
        else:
            st.caption("💡 Select a group in the sidebar to filter results")
        
        if selected_task:
            
            # Check for existing data
            module_id = selected_task['Module ID']
            submissions_filename = f"submissions_{course['id']}_mod{module_id}"
            if selected_group_id:
                submissions_filename += f"_grp{selected_group_id}"
            submissions_filename += ".csv"
            
            meta_key = f"submissions_{module_id}"
            if selected_group_id:
                meta_key += f"_grp{selected_group_id}"
            
            # Try to load existing data
            existing_data = load_csv_from_disk(course['id'], submissions_filename)
            
            # Show status if data exists
            col1, col2 = st.columns([3, 1])
            with col1:
                if existing_data and meta_key in meta:
                    show_data_status(meta, meta_key, 'Submissions')
            
            with col2:
                fetch_btn = st.button(
                    "🔄 Refresh" if existing_data else "📥 Fetch",
                    key="fetch_submissions",
                    use_container_width=True
                )
            
            # Load existing or fetch new
            if existing_data and not fetch_btn:
                # Only load if not already loaded for this module
                should_load = True
                if st.session_state.submissions_data:
                    # Check if loaded data belongs to current module
                    try:
                        current_data_mod_id = str(st.session_state.submissions_data[0].get('Module ID', ''))
                        if current_data_mod_id == str(module_id):
                            should_load = False
                    except:
                        pass
                
                if should_load:
                    st.session_state.submissions_data = existing_data
                    # Save persistence for auto-load next time
                    save_last_session({'last_module_id': module_id})
            
            if fetch_btn:
                with st.spinner("Fetching submissions..."):
                    rows = fetch_submissions(
                        st.session_state.session_id,
                        selected_task['Module ID'],
                        selected_group_id
                    )
                    
                    if rows:
                        # Add task info to rows
                        for row in rows:
                            row['Task Name'] = selected_task['Task Name']
                            row['Module ID'] = selected_task['Module ID']
                        
                        st.session_state.submissions_data = rows
                        st.session_state.submissions_loaded_from_disk = False
                        
                        # Save to disk
                        save_csv_to_disk(course['id'], submissions_filename, rows)
                        save_meta(course['id'], meta_key, len(rows))
                        
                        # Save persistence
                        save_last_session({'last_module_id': module_id})
                        
                        st.success(f"✓ Fetched {len(rows)} submissions → Saved to `output/course_{course['id']}/`")
                        st.rerun()
                    else:
                        st.warning("No submission data found")
        
        if st.session_state.submissions_data:
            st.dataframe(
                st.session_state.submissions_data,
                width="stretch",
                hide_index=True
            )
            
            csv_data = dataframe_to_csv(st.session_state.submissions_data)
            st.download_button(
                label="📥 Download CSV",
                data=csv_data,
                file_name=f"submissions_{course['id']}.csv",
                mime="text/csv"
            )
