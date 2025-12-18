"""
Submissions tab for Streamlit app.
Displays and manages assignment submission data.
"""

import logging
from datetime import datetime, timedelta
import streamlit as st

from core.api import fetch_submissions, fetch_tasks_list, get_assignment_dates, update_assignment_dates
from core.auth import setup_session
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
        
        # Show task description if available
        if selected_task and selected_task.get('description'):
            with st.expander("📋 Task Description", expanded=False):
                st.markdown(selected_task['description'])
        
        # =========================================================================
        # DATE EDITING SECTION (Lazy loaded when user expands)
        # =========================================================================
        if selected_task:
            module_id = selected_task['Module ID']
            with st.expander("📅 Edit Assignment Dates", expanded=False):
                # Use session state to track if dates are loaded for this module
                dates_key = f"dates_info_{module_id}"
                
                # Check if we have cached dates for this specific module
                if dates_key not in st.session_state:
                    st.session_state[dates_key] = None
                
                # Show load button if dates not yet loaded
                if st.session_state[dates_key] is None:
                    st.caption("Click to load date settings from Paatshala")
                    if st.button("🔄 Load Date Settings", key=f"load_dates_{module_id}"):
                        with st.spinner("Loading..."):
                            session = setup_session(st.session_state.session_id)
                            dates_info = get_assignment_dates(session, module_id)
                            if dates_info:
                                st.session_state[dates_key] = dates_info
                                st.rerun()
                            else:
                                st.error("Could not load assignment dates.")
                else:
                    dates_info = st.session_state[dates_key]
                    st.caption("Modify due date and cut-off date for this assignment")
                    
                    # Reload button
                    if st.button("🔄 Reload", key=f"reload_dates_{module_id}"):
                        session = setup_session(st.session_state.session_id)
                        dates_info = get_assignment_dates(session, module_id)
                        if dates_info:
                            st.session_state[dates_key] = dates_info
                            st.rerun()
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("**Due Date**")
                        due_enabled = st.checkbox(
                            "Enable Due Date",
                            value=dates_info['due_date_enabled'],
                            key=f"due_date_enabled_{module_id}"
                        )
                        
                        if due_enabled:
                            current_due = dates_info['due_date'] if dates_info['due_date'] else datetime.now() + timedelta(days=7)
                            new_due_date = st.date_input(
                                "Date",
                                value=current_due.date(),
                                key=f"due_date_picker_{module_id}"
                            )
                            new_due_time = st.time_input(
                                "Time",
                                value=current_due.time(),
                                key=f"due_time_picker_{module_id}"
                            )
                    
                    with col2:
                        st.markdown("**Cut-off Date**")
                        cutoff_enabled = st.checkbox(
                            "Enable Cut-off Date",
                            value=dates_info['cutoff_date_enabled'],
                            key=f"cutoff_date_enabled_{module_id}"
                        )
                        
                        if cutoff_enabled:
                            current_cutoff = dates_info['cutoff_date'] if dates_info['cutoff_date'] else datetime.now() + timedelta(days=14)
                            new_cutoff_date = st.date_input(
                                "Date",
                                value=current_cutoff.date(),
                                key=f"cutoff_date_picker_{module_id}"
                            )
                            new_cutoff_time = st.time_input(
                                "Time",
                                value=current_cutoff.time(),
                                key=f"cutoff_time_picker_{module_id}"
                            )
                    
                    # Quick actions row
                    st.divider()
                    st.markdown("**Quick Actions**")
                    qcol1, qcol2, qcol3 = st.columns(3)
                    with qcol1:
                        if st.button("➕ Extend 1 Day", key=f"extend_1d_{module_id}", use_container_width=True):
                            if dates_info['due_date']:
                                session = setup_session(st.session_state.session_id)
                                new_due = dates_info['due_date'] + timedelta(days=1)
                                # Also extend cut-off if enabled
                                new_cutoff = None
                                if dates_info['cutoff_date_enabled'] and dates_info['cutoff_date']:
                                    new_cutoff = dates_info['cutoff_date'] + timedelta(days=1)
                                if update_assignment_dates(session, module_id, 
                                                          due_date=new_due, due_date_enabled=True,
                                                          cutoff_date=new_cutoff, cutoff_date_enabled=dates_info['cutoff_date_enabled']):
                                    st.session_state[dates_key] = None  # Clear cache to reload
                                    st.success("✓ Extended by 1 day!")
                                    st.rerun()
                                else:
                                    st.error("Failed to update")
                    with qcol2:
                        if st.button("➕ Extend 1 Week", key=f"extend_1w_{module_id}", use_container_width=True):
                            if dates_info['due_date']:
                                session = setup_session(st.session_state.session_id)
                                new_due = dates_info['due_date'] + timedelta(weeks=1)
                                # Also extend cut-off if enabled
                                new_cutoff = None
                                if dates_info['cutoff_date_enabled'] and dates_info['cutoff_date']:
                                    new_cutoff = dates_info['cutoff_date'] + timedelta(weeks=1)
                                if update_assignment_dates(session, module_id,
                                                          due_date=new_due, due_date_enabled=True,
                                                          cutoff_date=new_cutoff, cutoff_date_enabled=dates_info['cutoff_date_enabled']):
                                    st.session_state[dates_key] = None  # Clear cache to reload
                                    st.success("✓ Extended by 1 week!")
                                    st.rerun()
                                else:
                                    st.error("Failed to update")
                    with qcol3:
                        if st.button("🚫 Disable Cut-off", key=f"disable_cutoff_{module_id}", use_container_width=True):
                            session = setup_session(st.session_state.session_id)
                            if update_assignment_dates(session, module_id, cutoff_date_enabled=False):
                                st.session_state[dates_key] = None  # Clear cache to reload
                                st.success("✓ Cut-off disabled!")
                                st.rerun()
                            else:
                                st.error("Failed to update")
                    
                    # Save button
                    st.divider()
                    if st.button("💾 Save Changes", type="primary", key=f"save_dates_{module_id}"):
                        # Build datetime objects
                        new_due = None
                        new_cutoff = None
                        
                        if due_enabled:
                            new_due = datetime.combine(new_due_date, new_due_time)
                        
                        if cutoff_enabled:
                            new_cutoff = datetime.combine(new_cutoff_date, new_cutoff_time)
                        
                        session = setup_session(st.session_state.session_id)
                        success = update_assignment_dates(
                            session, module_id,
                            due_date=new_due,
                            due_date_enabled=due_enabled,
                            cutoff_date=new_cutoff,
                            cutoff_date_enabled=cutoff_enabled
                        )
                        
                        if success:
                            st.session_state[dates_key] = None  # Clear cache to reload
                            st.success("✓ Assignment dates updated!")
                            st.rerun()
                        else:
                            st.error("Failed to update dates. Check console for details.")
                    
                    # Link to Moodle
                    st.markdown(f"[🔗 Open in Paatshala](https://paatshala.ictkerala.org/course/modedit.php?update={module_id}&return=1)", unsafe_allow_html=True)
        
        # =========================================================================
        # SUBMISSIONS DATA SECTION
        # =========================================================================
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
                    key=f"fetch_submissions_{module_id}_{selected_group_id}",
                    use_container_width=True
                )
            
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
                        st.session_state.submissions_module_id = module_id
                        st.session_state.submissions_group_id = selected_group_id
                        
                        # Save to disk
                        save_csv_to_disk(course['id'], submissions_filename, rows)
                        save_meta(course['id'], meta_key, len(rows))
                        
                        # Save persistence
                        save_last_session({'last_module_id': module_id})
                        
                        st.success(f"✓ Fetched {len(rows)} submissions → Saved to `output/course_{course['id']}/`")
                        st.rerun()
                    else:
                        st.warning("No submission data found")
            
            # Display data - but only if it matches current task/group
            display_data = None
            
            # Check if session data matches current selection
            if st.session_state.submissions_data:
                stored_mod_id = st.session_state.get('submissions_module_id')
                stored_group_id = st.session_state.get('submissions_group_id')
                if str(stored_mod_id) == str(module_id) and stored_group_id == selected_group_id:
                    display_data = st.session_state.submissions_data
            
            # Fallback: load from disk if session data doesn't match
            if display_data is None and existing_data:
                display_data = existing_data
                # Update session state
                st.session_state.submissions_data = existing_data
                st.session_state.submissions_module_id = module_id
                st.session_state.submissions_group_id = selected_group_id
            
            if display_data:
                st.dataframe(
                    display_data,
                    width="stretch",
                    hide_index=True
                )
                
                csv_data = dataframe_to_csv(display_data)
                st.download_button(
                    label="📥 Download CSV",
                    data=csv_data,
                    file_name=f"submissions_{course['id']}_mod{module_id}.csv",
                    mime="text/csv",
                    key=f"download_submissions_{module_id}_{selected_group_id}"
                )
