"""
Workshop tab for Streamlit app.
Displays and manages workshop submission and peer assessment data.
"""

import logging
import streamlit as st

from core.api import get_workshops, fetch_workshop_submissions, switch_workshop_phase, WORKSHOP_PHASES
from core.auth import setup_session
from core.persistence import (
    load_csv_from_disk, save_csv_to_disk, 
    load_last_session, save_last_session,
    save_meta, dataframe_to_csv
)
from streamlit_modules.ui.components import show_data_status, show_fresh_status

logger = logging.getLogger(__name__)


def render_workshop_tab(course, meta):
    """Render the Workshop tab content"""
    st.subheader("Workshop Submissions")
    
    # Try to load workshops list if not loaded
    if st.session_state.workshops_data is None:
        # Try loading from disk
        disk_data = load_csv_from_disk(course['id'], f"workshops_{course['id']}.csv")
        if disk_data:
            st.session_state.workshops_data = disk_data
            st.session_state.workshops_loaded_from_disk = True
    
    # If still no workshops, offer to fetch them
    if not st.session_state.workshops_data:
        st.info("⚠️ No workshops loaded. Fetch workshops to see available workshop activities.")
        
        if st.button("📥 Fetch Workshops", key="fetch_workshops_list"):
            with st.spinner("Fetching workshops from course..."):
                session = setup_session(st.session_state.session_id)
                workshops = get_workshops(session, course['id'])
                
                if workshops:
                    # Convert to list of dicts for consistency
                    # Now includes Restricted Group field
                    workshop_rows = [
                        {
                            "Workshop Name": name,
                            "Module ID": mid,
                            "URL": url,
                            "Restricted Group": restricted_group or ""
                        }
                        for name, mid, url, restricted_group in workshops
                    ]
                    st.session_state.workshops_data = workshop_rows
                    st.session_state.workshops_loaded_from_disk = False
                    
                    # Save to disk
                    save_csv_to_disk(course['id'], f"workshops_{course['id']}.csv", workshop_rows)
                    save_meta(course['id'], 'workshops', len(workshop_rows))
                    
                    st.success(f"✓ Found {len(workshops)} workshops")
                    st.rerun()
                else:
                    st.warning("No workshops found in this course")
        return
    
    # Filter workshops based on selected group
    all_workshops = st.session_state.workshops_data
    
    # Get selected group name for filtering
    selected_group_name = None
    if st.session_state.selected_group:
        selected_group_name = st.session_state.selected_group['name']
    
    # Filter: show only workshops that are either unrestricted OR match the selected group
    if selected_group_name:
        # Use substring matching since group names may have slight variations
        filtered_workshops = [
            w for w in all_workshops
            if not w.get('Restricted Group') or 
               selected_group_name in w.get('Restricted Group', '') or
               w.get('Restricted Group', '') in selected_group_name
        ]
    else:
        # No group selected - show all workshops
        filtered_workshops = all_workshops
    
    if not filtered_workshops:
        st.warning("No workshops available for the selected group.")
        return
    
    # Workshop selector
    workshop_options = {
        f"{w['Workshop Name']} (ID: {w['Module ID']})": w
        for w in filtered_workshops
    }
    
    # Try to pre-select from last session
    pre_select_index = 0
    last = load_last_session()
    if last.get('last_workshop_id'):
        for i, (name, w) in enumerate(workshop_options.items()):
            if str(w['Module ID']) == str(last['last_workshop_id']):
                pre_select_index = i
                break

    selected_workshop_name = st.selectbox(
        "Select Workshop",
        options=list(workshop_options.keys()),
        index=pre_select_index,
        key="workshop_selector"
    )
    
    selected_workshop = workshop_options.get(selected_workshop_name)
    
    # Use global group from sidebar (if selected)
    selected_group_id = None
    if st.session_state.selected_group:
        selected_group_id = st.session_state.selected_group['id']
        st.info(f"📌 Filtering by: {st.session_state.selected_group['name']}")
    else:
        st.caption("💡 Select a group in the sidebar to filter results")
    
    if selected_workshop:
        module_id = selected_workshop['Module ID']
        
        # Build filename for caching
        submissions_filename = f"workshop_submissions_{course['id']}_mod{module_id}"
        if selected_group_id:
            submissions_filename += f"_grp{selected_group_id}"
        submissions_filename += ".csv"
        
        meta_key = f"workshop_{module_id}"
        if selected_group_id:
            meta_key += f"_grp{selected_group_id}"
        
        # Try to load existing data
        existing_data = load_csv_from_disk(course['id'], submissions_filename)
        
        # Show status if data exists
        col1, col2 = st.columns([3, 1])
        with col1:
            if existing_data and meta_key in meta:
                show_data_status(meta, meta_key, 'Workshop submissions')
        
        with col2:
            fetch_btn = st.button(
                "🔄 Refresh" if existing_data else "📥 Fetch",
                key="fetch_workshop_submissions",
                use_container_width=True
            )
        
        # Load existing or fetch new
        if existing_data and not fetch_btn:
            # Only load if not already loaded for this module
            should_load = True
            if st.session_state.workshop_submissions_data:
                # Check if loaded data belongs to current module
                try:
                    # Check by looking at metadata or comparing length
                    current_mod = st.session_state.get('_workshop_current_module')
                    current_group = st.session_state.get('_workshop_current_group')
                    if current_mod == str(module_id) and current_group == str(selected_group_id):
                        should_load = False
                except:
                    pass
            
            if should_load:
                st.session_state.workshop_submissions_data = existing_data
                st.session_state._workshop_current_module = str(module_id)
                st.session_state._workshop_current_group = str(selected_group_id)
                # Try to get phase from first row if available
                if existing_data and existing_data[0].get('Phase'):
                    st.session_state._workshop_phase = existing_data[0].get('Phase')
                # Save persistence for auto-load next time
                save_last_session({'last_workshop_id': module_id})
        
        if fetch_btn:
            with st.spinner("Fetching workshop submissions..."):
                phase, rows = fetch_workshop_submissions(
                    st.session_state.session_id,
                    module_id,
                    selected_group_id
                )
                
                if rows:
                    st.session_state.workshop_submissions_data = rows
                    st.session_state._workshop_current_module = str(module_id)
                    st.session_state._workshop_current_group = str(selected_group_id)
                    st.session_state._workshop_phase = phase
                    
                    # Save to disk
                    save_csv_to_disk(course['id'], submissions_filename, rows)
                    save_meta(course['id'], meta_key, len(rows))
                    
                    # Save persistence
                    save_last_session({'last_workshop_id': module_id})
                    
                    st.success(f"✓ Fetched {len(rows)} submissions ({phase} phase) → Saved to disk")
                    st.rerun()
                else:
                    phase_msg = f" (Phase: {phase})" if phase else ""
                    st.warning(f"No submission data found{phase_msg}")
        
        # Phase switcher section
        current_phase = st.session_state.get('_workshop_phase')
        if current_phase and st.session_state.workshop_submissions_data:
            st.divider()
            st.markdown("##### 🔄 Switch Workshop Phase")
            
            # Create phase buttons in a row
            phase_cols = st.columns(5)
            phase_order = ["Setup", "Submission", "Assessment", "Grading Evaluation", "Closed"]
            
            for i, phase_name in enumerate(phase_order):
                with phase_cols[i]:
                    is_current = (phase_name == current_phase)
                    btn_type = "primary" if is_current else "secondary"
                    
                    if st.button(
                        f"{'✓ ' if is_current else ''}{phase_name}",
                        key=f"phase_btn_{phase_name}",
                        type=btn_type,
                        use_container_width=True,
                        disabled=is_current
                    ):
                        with st.spinner(f"Switching to {phase_name}..."):
                            phase_code = WORKSHOP_PHASES[phase_name]
                            success = switch_workshop_phase(
                                st.session_state.session_id,
                                module_id,
                                phase_code
                            )
                            if success:
                                # Auto-refresh: fetch new data after phase switch
                                new_phase, rows = fetch_workshop_submissions(
                                    st.session_state.session_id,
                                    module_id,
                                    selected_group_id
                                )
                                if rows:
                                    st.session_state.workshop_submissions_data = rows
                                    st.session_state._workshop_phase = new_phase
                                    st.session_state._workshop_current_module = str(module_id)
                                    st.session_state._workshop_current_group = str(selected_group_id)
                                    st.success(f"✓ Switched to {new_phase} phase")
                                else:
                                    st.session_state.workshop_submissions_data = None
                                    st.session_state._workshop_phase = new_phase
                                    st.warning(f"Switched to {new_phase} phase (no data)")
                                st.rerun()
                            else:
                                st.error("Failed to switch phase. Check permissions.")
    
    # Display the data
    if st.session_state.workshop_submissions_data:
        st.divider()
        
        # Get current phase for column naming
        current_phase = st.session_state.get('_workshop_phase', '')
        is_assessment_phase = (current_phase == "Assessment")
        is_grading_phase = current_phase in ("Grading Evaluation", "Closed")
        
        # Helper function to calculate average from comma-separated grades
        def calc_average(grades_str):
            if not grades_str or grades_str == "-":
                return "-"
            try:
                grades = [float(g.strip()) for g in grades_str.split(",") if g.strip() and g.strip() != "-"]
                if grades:
                    return f"{sum(grades) / len(grades):.1f}"
            except:
                pass
            return "-"
        
        # Helper function to calculate total from two grade values
        def calc_total(grade1, grade2):
            try:
                g1 = float(grade1) if grade1 and grade1 != "-" else 0
                g2 = float(grade2) if grade2 and grade2 != "-" else 0
                if grade1 == "-" and grade2 == "-":
                    return "-"
                return f"{g1 + g2:.0f}"
            except:
                return "-"
        
        # Prepare display data with phase-appropriate column names
        display_data = []
        for row in st.session_state.workshop_submissions_data:
            if is_assessment_phase:
                # Assessment phase: use "Grades Received", "Grades Given", and "Average Grade"
                grades_received = row.get("Submission Grade", "-")
                display_row = {
                    "Student Name": row.get("Student Name", ""),
                    "Submission Title": row.get("Submission Title", ""),
                    "Last Modified": row.get("Last Modified", ""),
                    "Grades Received": grades_received,
                    "Grades Given": row.get("Assessment Grade", "-"),
                    "Average Grade": calc_average(grades_received)
                }
            elif is_grading_phase:
                # Grading/Closed phases: use "Submission Grade", "Assessment Grade", and "Total Grade"
                sub_grade = row.get("Submission Grade", "-")
                assess_grade = row.get("Assessment Grade", "-")
                display_row = {
                    "Student Name": row.get("Student Name", ""),
                    "Submission Title": row.get("Submission Title", ""),
                    "Last Modified": row.get("Last Modified", ""),
                    "Submission Grade": sub_grade,
                    "Assessment Grade": assess_grade,
                    "Total Grade": calc_total(sub_grade, assess_grade)
                }
            else:
                # Other phases: just basic columns
                display_row = {
                    "Student Name": row.get("Student Name", ""),
                    "Submission Title": row.get("Submission Title", ""),
                    "Last Modified": row.get("Last Modified", ""),
                    "Submission Grade": row.get("Submission Grade", "-"),
                    "Assessment Grade": row.get("Assessment Grade", "-")
                }
            display_data.append(display_row)
        
        # Column config based on phase
        if is_assessment_phase:
            column_config = {
                "Grades Received": st.column_config.TextColumn("Grades Received"),
                "Grades Given": st.column_config.TextColumn("Grades Given"),
                "Average Grade": st.column_config.TextColumn("Average Grade")
            }
        elif is_grading_phase:
            column_config = {
                "Submission Grade": st.column_config.TextColumn("Submission Grade"),
                "Assessment Grade": st.column_config.TextColumn("Assessment Grade"),
                "Total Grade": st.column_config.TextColumn("Total Grade")
            }
        else:
            column_config = {
                "Submission Grade": st.column_config.TextColumn("Submission Grade"),
                "Assessment Grade": st.column_config.TextColumn("Assessment Grade")
            }
        
        st.dataframe(
            display_data,
            use_container_width=True,
            hide_index=True,
            column_config=column_config
        )
        
        # Buttons row: Download CSV and Open in Paatshala
        btn_col1, btn_col2, _ = st.columns([1, 1, 2])
        
        csv_data = dataframe_to_csv(st.session_state.workshop_submissions_data)
        with btn_col1:
            st.download_button(
                label="📥 Download CSV",
                data=csv_data,
                file_name=f"workshop_submissions_{course['id']}.csv",
                mime="text/csv",
                use_container_width=True
            )
        
        with btn_col2:
            workshop_url = selected_workshop.get('URL', '') if selected_workshop else ''
            if workshop_url:
                # Add group parameter if a group is selected
                if selected_group_id:
                    workshop_url = f"{workshop_url}&group={selected_group_id}"
                st.link_button(
                    label="🔗 Open in Paatshala",
                    url=workshop_url,
                    use_container_width=True
                )
