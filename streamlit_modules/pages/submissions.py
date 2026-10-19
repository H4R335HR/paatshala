"""
Submissions tab for Streamlit app.
Displays and manages assignment submission data.
"""

import logging
from datetime import datetime, timedelta
import streamlit as st

from core.api import (
    fetch_submissions, fetch_tasks_list, get_assignment_dates,
    update_assignment_dates, clean_name, fetch_full_feedback,
    get_course_activity_restrictions
)
from core.auth import setup_session
from core.ai import load_evaluation, load_failed_queue
from core.persistence import (
    load_csv_from_disk, save_csv_to_disk, 
    load_last_session, save_last_session,
    save_meta
)
from core.grading_pipeline import (
    get_task_grading_status,
    run_batch_scoring,
    run_batch_moodle_submit,
    parse_moodle_grade,
    is_task_permitted_for_group
)
from streamlit_modules.components.inbox import show_rubric_approval_dialog
from streamlit_modules.ui.components import show_data_status

logger = logging.getLogger(__name__)


@st.dialog("Review Grades Before Submitting to Moodle", width="large")
def show_moodle_review_dialog(course, mod_id, grp_id, submissions, max_grd, asgn_id):
    st.subheader("Review Grades")
    st.caption("Review calculated AI grades before submitting them to Moodle / Paatshala:")
    
    import pandas as pd
    pending_items = []
    effective_max = max_grd if (max_grd and 1 <= max_grd <= 1000) else 15.0
    
    for row in submissions:
        sname = row.get('Name', 'Unknown')
        uid = row.get('User_ID')
        eval_doc = load_evaluation(course['id'], mod_id, sname, grp_id)
        if eval_doc and eval_doc.get('total_score') is not None:
            m_score, s_max = parse_moodle_grade(row.get('Final Grade', ''))
            t_max = s_max or effective_max
            ai_score = eval_doc.get('total_score', 0)
            scaled = round((ai_score / 100) * t_max)
            
            if m_score is None or abs(m_score - scaled) >= 0.5:
                pending_items.append({
                    "Student": clean_name(sname),
                    "User ID": uid or "Missing",
                    "AI Score": f"{ai_score}%",
                    "New Grade": f"{scaled}/{int(t_max)}",
                    "Current Grade": str(row.get('Final Grade', '-')) or "-",
                })
    
    if not pending_items:
        st.info("✅ All AI-scored evaluations are already submitted to Moodle!")
        if st.button("Close"):
            st.rerun()
        return
        
    st.dataframe(pd.DataFrame(pending_items), hide_index=True, use_container_width=True)
    st.markdown(f"**Total to submit:** `{len(pending_items)}` students")
    st.warning("⚠️ Submitting will immediately update the official grades and post feedback comments on Paatshala.")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        if st.button("🚀 Confirm & Submit to Moodle", type="primary", use_container_width=True):
            pbar = st.progress(0, text="Submitting to Moodle...")
            st_text = st.empty()
            
            def p_cb(info):
                curr = info.get("current", 0)
                tot = info.get("total", 1)
                pbar.progress(curr / tot if tot > 0 else 0, text=info.get("message", ""))
                if info.get("type") in ["success", "warning", "error"]:
                    st_text.caption(info.get("message", ""))
            
            try:
                sub_res = run_batch_moodle_submit(
                    course_id=course['id'],
                    module_id=mod_id,
                    group_id=grp_id,
                    submissions_data=submissions,
                    session_id=st.session_state.session_id,
                    assignment_id=asgn_id,
                    max_grade=effective_max,
                    progress_callback=p_cb
                )
                st.toast(f"Submitted {sub_res['submitted']} grades to Moodle!", icon="✅")
                st.success(f"✓ Submission complete! {sub_res['submitted']} grades submitted, {sub_res['failed']} failed.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to submit: {e}")
    with col2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


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
        # Restrictions / Batch Filtering
        restr_map = {}
        try:
            session = setup_session(st.session_state.session_id)
            restr_map = get_course_activity_restrictions(session, course['id'])
        except Exception as e:
            logger.debug(f"Could not load restrictions: {e}")

        show_all_tasks = False
        selected_group_id = None
        if st.session_state.selected_group:
            selected_group_id = st.session_state.selected_group['id']
            f_col1, f_col2 = st.columns([3, 2])
            with f_col1:
                st.info(f"📌 Active Batch: **{st.session_state.selected_group['name']}**")
            with f_col2:
                show_all_tasks = st.checkbox(
                    "Show all assignments (include other batches)",
                    value=False,
                    key=f"subm_show_all_{course['id']}",
                    help="By default, activities restricted to other batches or hidden are excluded. Check this to see all."
                )
        else:
            st.caption("💡 Select a group in the sidebar to filter assignments by batch")

        if st.session_state.selected_group and not show_all_tasks:
            filtered_tasks = [
                t for t in st.session_state.tasks_data
                if is_task_permitted_for_group(t, st.session_state.selected_group, restr_map)
            ]
            if not filtered_tasks:
                filtered_tasks = st.session_state.tasks_data
            else:
                st.caption(f"🎯 Filtered to **{len(filtered_tasks)}** assignments permitted for **{st.session_state.selected_group['name']}** (out of {len(st.session_state.tasks_data)} total)")
        else:
            filtered_tasks = st.session_state.tasks_data

        # Task selector
        task_options = {
            f"{t['Task Name']} (ID: {t['Module ID']})": t
            for t in filtered_tasks
        }
        
        # Try to pre-select from last session
        pre_select_index = 0
        last = load_last_session()
        if last.get('last_module_id'):
            for i, (name, t) in enumerate(task_options.items()):
                if str(t.get('Module ID')) == str(last['last_module_id']):
                    pre_select_index = i
                    break

        selected_task_name = st.selectbox(
            "Select Assignment",
            options=list(task_options.keys()),
            index=pre_select_index if pre_select_index < len(task_options) else 0
        )
        
        selected_task = task_options.get(selected_task_name)
        
        # Show task description if available
        if selected_task and selected_task.get('description'):
            with st.expander("📋 Task Description", expanded=False):
                st.markdown(selected_task['description'])
                
                # Refresh button to fetch latest task description
                if st.button("🔄 Refresh Description", key=f"refresh_desc_{selected_task['Module ID']}"):
                    with st.spinner("Fetching latest description..."):
                        from core.api import fetch_task_description
                        session = setup_session(st.session_state.session_id)
                        new_description = fetch_task_description(session, selected_task['Module ID'])
                        if new_description:
                            # Update the task in tasks_data
                            for task in st.session_state.tasks_data:
                                if str(task.get('Module ID')) == str(selected_task['Module ID']):
                                    task['description'] = new_description
                                    break
                            # Save updated tasks to disk
                            save_csv_to_disk(course['id'], f"tasks_{course['id']}.csv", st.session_state.tasks_data)
                            st.success("✓ Description refreshed!")
                            st.rerun()
                        else:
                            st.warning("Could not fetch description. The task page may not be accessible.")
        
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
                                format="DD/MM/YYYY",
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
                                format="DD/MM/YYYY",
                                key=f"cutoff_date_picker_{module_id}"
                            )
                            new_cutoff_time = st.time_input(
                                "Time",
                                value=current_cutoff.time(),
                                key=f"cutoff_time_picker_{module_id}"
                            )
                    
                    # Grade reminder toggle - secondary option, placed below main dates
                    grading_enabled = st.checkbox(
                        "⏰ Enable 'Remind me to grade by' date",
                        value=dates_info.get('grading_due_date_enabled', False),
                        key=f"grading_due_enabled_{module_id}",
                        help="⚠️ Must be on or after due date. Disable this if you get validation errors when moving due dates."
                    )
                    
                    # Quick actions row
                    st.divider()
                    st.markdown("**Quick Actions**")
                    qcol1, qcol2, qcol3 = st.columns(3)
                    with qcol1:
                        if st.button("➕ Extend 1 Day", key=f"extend_1d_{module_id}", width="stretch"):
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
                        if st.button("➕ Extend 1 Week", key=f"extend_1w_{module_id}", width="stretch"):
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
                        if st.button("🚫 Disable Cut-off", key=f"disable_cutoff_{module_id}", width="stretch"):
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
                            cutoff_date_enabled=cutoff_enabled,
                            grading_due_date_enabled=grading_enabled
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
                    width="stretch"
                )
            
            if fetch_btn:
                with st.spinner("Fetching submissions..."):
                    result = fetch_submissions(
                        st.session_state.session_id,
                        selected_task['Module ID'],
                        selected_group_id
                    )
                    
                    # Unpack tuple result (submissions_list, assignment_id, max_grade)
                    rows, assignment_id, max_grade = result
                    
                    if rows:
                        # Add task info to rows
                        for row in rows:
                            row['Task Name'] = selected_task['Task Name']
                            row['Module ID'] = selected_task['Module ID']
                        
                        st.session_state.submissions_data = rows
                        st.session_state.submissions_loaded_from_disk = False
                        st.session_state.submissions_module_id = module_id
                        st.session_state.submissions_group_id = selected_group_id
                        
                        # Store assignment_id for grade submission API
                        if assignment_id:
                            st.session_state[f"assignment_id_{module_id}"] = assignment_id
                        
                        # Store max_grade for evaluation tab (extracted from grading table)
                        if max_grade:
                            # Sanity check: Moodle max grades are typically 1-1000
                            if isinstance(max_grade, (int, float)) and 1 <= max_grade <= 1000:
                                st.session_state[f"max_grade_{module_id}"] = max_grade
                                logger.info(f"Stored max_grade={max_grade} for module {module_id}")
                            else:
                                logger.warning(f"Rejected suspicious max_grade={max_grade} for module {module_id} (out of range 1-1000)")
                        
                        # Calculate timeliness for each submission
                        try:
                            from core.api import check_submission_timeliness
                            session = setup_session(st.session_state.session_id)
                            dates_info = get_assignment_dates(session, module_id)
                            
                            if dates_info and dates_info.get('due_date_enabled') and dates_info.get('due_date'):
                                due_date = dates_info['due_date']
                                now = datetime.now()
                                
                                for row in rows:
                                    last_modified = row.get('Last Modified', '')
                                    if last_modified:
                                        timeliness = check_submission_timeliness(last_modified, due_date)
                                        row['Is_On_Time'] = timeliness.get('status', 'Unknown')
                                    else:
                                        # No submission - check if due date has passed
                                        if now > due_date:
                                            row['Is_On_Time'] = 'Late'
                                        else:
                                            row['Is_On_Time'] = 'Pending'
                        except Exception as e:
                            logger.debug(f"Could not calculate timeliness: {e}")
                        
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
                
                # Also fetch assignment_id if not already set (needed for grade submission)
                if f"assignment_id_{module_id}" not in st.session_state:
                    # Get assignment_id by fetching grader page for first student
                    first_user_id = None
                    for row in existing_data:
                        if row.get('User_ID'):
                            first_user_id = row['User_ID']
                            break
                    
                    if first_user_id:
                        from core.auth import BASE
                        from core.parser import extract_assignment_id
                        
                        try:
                            session = setup_session(st.session_state.session_id)
                            grader_url = f"{BASE}/mod/assign/view.php?id={module_id}&action=grader&userid={first_user_id}"
                            grader_resp = session.get(grader_url, timeout=15)
                            if grader_resp.ok:
                                assignment_id = extract_assignment_id(grader_resp.text)
                                if assignment_id:
                                    st.session_state[f"assignment_id_{module_id}"] = assignment_id
                        except:
                            pass  # Failed to get assignment_id, will show error on submit
            
            if display_data:
                import pandas as pd
                # Create a display-friendly dataframe
                df = pd.DataFrame(display_data)
                
                # Clean names - remove batch suffix from Name column
                if 'Name' in df.columns:
                    df['Name'] = df['Name'].apply(clean_name)
                
                # Convert dates to Indian format (DD/MM/YYYY)
                def to_indian_date(date_str):
                    """Convert Moodle date string to Indian format DD/MM/YYYY, H:MM AM/PM"""
                    if not date_str or not isinstance(date_str, str):
                        return date_str
                    try:
                        dt = datetime.strptime(date_str.strip(), "%A, %d %B %Y, %I:%M %p")
                        return dt.strftime("%d/%m/%Y, %I:%M %p")
                    except ValueError:
                        return date_str
                
                if 'Last Modified' in df.columns:
                    df['Last Modified'] = df['Last Modified'].apply(to_indian_date)
                
                # Add AI Score column from saved evaluations (same data shown in Evaluation tab)
                ai_scores = []
                for row in display_data:
                    student_name = row.get('Name', 'Unknown')
                    existing_eval = load_evaluation(course['id'], module_id, student_name, selected_group_id)
                    if existing_eval and existing_eval.get('total_score') is not None:
                        ai_scores.append(f"{existing_eval['total_score']}%")
                    else:
                        ai_scores.append("-")
                
                # Insert AI Score after Final Grade column (or at end)
                if 'Final Grade' in df.columns:
                    grade_idx = df.columns.get_loc('Final Grade') + 1
                    df.insert(grade_idx, 'AI Score', ai_scores)
                else:
                    df['AI Score'] = ai_scores
                
                # Drop internal columns not useful for display (and Submission_Files
                # contains Python lists which cause ArrowTypeError in st.dataframe)
                internal_cols = [c for c in ['Submission_Files', 'Submission_Type', 'Assignment_Type', 'User_ID'] if c in df.columns]
                if internal_cols:
                    df = df.drop(columns=internal_cols)
                
                # =====================================================================
                # BATCH EVALUATION & MOODLE SUBMISSION CARD
                # =====================================================================
                grading_status = get_task_grading_status(
                    course_id=course['id'],
                    module_id=module_id,
                    group_id=selected_group_id,
                    submissions_data=display_data,
                    max_grade=st.session_state.get(f"max_grade_{module_id}")
                )

                # Check if evaluation was triggered after rubric approval
                trigger_eval_key = f"start_evaluation_after_rubric_{module_id}"
                auto_trigger_eval = st.session_state.get(trigger_eval_key, False)
                if auto_trigger_eval:
                    st.session_state[trigger_eval_key] = False

                with st.container(border=True):
                    ev_c1, ev_c2, ev_c3, ev_c4 = st.columns([4, 2, 2, 2])
                    with ev_c1:
                        rubric_status_text = "✅ Rubric Configured" if grading_status['has_rubric'] else "⚠️ No Rubric Found"
                        st.markdown(
                            f"**⚡ AI Evaluation:** "
                            f"**{grading_status['ai_evaluated_count']}/{grading_status['submitted_count']}** scored "
                            f"({grading_status['ai_pending_count']} pending)"
                            f"<br><span style='font-size:12px; color:#888;'>Rubric: {rubric_status_text}</span>",
                            unsafe_allow_html=True
                        )
                    with ev_c2:
                        eval_btn = st.button(
                            "⚡ Evaluate Pending",
                            key=f"eval_pending_btn_{module_id}_{selected_group_id}",
                            disabled=(grading_status['ai_pending_count'] == 0),
                            type="primary",
                            use_container_width=True,
                            help="Evaluate all pending submissions with AI"
                        )
                    with ev_c3:
                        ready_cnt = grading_status['ready_for_moodle_count']
                        review_moodle_btn = st.button(
                            f"📤 Submit to Moodle ({ready_cnt})",
                            key=f"moodle_review_btn_{module_id}_{selected_group_id}",
                            disabled=(ready_cnt == 0),
                            use_container_width=True,
                            help="Review grades before submitting to Moodle"
                        )
                    with ev_c4:
                        failed_cnt = grading_status['failed_queue_count']
                        resume_btn = st.button(
                            f"🔁 Resume ({failed_cnt})",
                            key=f"resume_failed_btn_{module_id}_{selected_group_id}",
                            disabled=(failed_cnt == 0),
                            use_container_width=True,
                            help="Retry previously failed submissions"
                        )

                # Execute evaluation if button pressed or auto-triggered
                if eval_btn or auto_trigger_eval:
                    if not grading_status['has_rubric']:
                        show_rubric_approval_dialog(
                            course=course,
                            module_id=module_id,
                            task_name=selected_task['Task Name'],
                            task_description=selected_task.get('description', '') or selected_task['Task Name'],
                            group_id=selected_group_id
                        )
                    else:
                        progress_bar = st.progress(0, text="Evaluating submissions with AI...")
                        status_text = st.empty()
                        
                        def p_callback(info):
                            curr = info.get("current", 0)
                            tot = info.get("total", 1)
                            progress_bar.progress(curr / tot if tot > 0 else 0, text=info.get("message", ""))
                            if info.get("type") in ["success", "warning", "error", "skipped"]:
                                status_text.caption(info.get("message", ""))
                        
                        task_desc = selected_task.get('description', '') or selected_task['Task Name']
                        res = run_batch_scoring(
                            course_id=course['id'],
                            module_id=module_id,
                            group_id=selected_group_id,
                            submissions_data=display_data,
                            rubric=grading_status['rubric'],
                            task_description=task_desc,
                            session_id=st.session_state.session_id,
                            progress_callback=p_callback,
                            auto_fetch=True
                        )
                        st.toast(f"Scored {res['scored']} submissions!", icon="🎯")
                        st.rerun()

                if resume_btn:
                    from streamlit_modules.pages.evaluation import _perform_resume_failed
                    _perform_resume_failed(course, display_data, grading_status['rubric'], module_id, selected_group_id)

                if review_moodle_btn:
                    asgn_id = st.session_state.get(f"assignment_id_{module_id}")
                    max_grd = st.session_state.get(f"max_grade_{module_id}", 15.0)
                    show_moodle_review_dialog(course, module_id, selected_group_id, display_data, max_grd, asgn_id)

                # Add selection capability to dataframe
                selection = st.dataframe(
                    df,
                    width="stretch",
                    hide_index=True,
                    selection_mode="single-row",
                    on_select="rerun",
                    key=f"submissions_table_{module_id}_{selected_group_id}"
                )
                
                # Check if a row is selected and show dialog
                if selection and selection.selection and selection.selection.rows:
                    selected_idx = selection.selection.rows[0]
                    selected_row = display_data[selected_idx]
                    
                    @st.dialog("Submission Details", width="large")
                    def show_feedback_dialog(row, mod_id):
                        st.markdown(f"**Student:** {row.get('Name', 'N/A')}")
                        st.markdown(f"**Email:** {row.get('Email', 'N/A')}")
                        st.markdown(f"**Status:** {row.get('Status', 'N/A')}")
                        st.markdown(f"**Final Grade:** {row.get('Final Grade', 'N/A')}")
                        # Show AI Score if available
                        student_name = row.get('Name', 'Unknown')
                        ai_eval = load_evaluation(course['id'], mod_id, student_name, selected_group_id)
                        if ai_eval and ai_eval.get('total_score') is not None:
                            st.markdown(f"**AI Score:** {ai_eval['total_score']}%")
                        st.divider()
                        st.markdown("**Feedback Comments:**")
                        
                        # Fetch full feedback from grader page (table data is truncated)
                        user_id = row.get('User_ID')
                        if user_id and st.session_state.get('session_id'):
                            with st.spinner("Loading full feedback..."):
                                result = fetch_full_feedback(
                                    st.session_state.session_id, 
                                    mod_id, 
                                    user_id
                                )
                            
                            if result['success'] and result['feedback_html']:
                                # Render HTML feedback with styling for better presentation
                                html_content = f"""
                                <div style="
                                    max-height: 400px; 
                                    overflow-y: auto; 
                                    padding: 15px; 
                                    background-color: rgba(255,255,255,0.05); 
                                    border: 1px solid rgba(255,255,255,0.1); 
                                    border-radius: 8px;
                                    font-size: 14px;
                                    line-height: 1.6;
                                ">
                                    {result['feedback_html']}
                                </div>
                                <style>
                                    /* Style tables in feedback */
                                    div[data-testid="stMarkdown"] table {{
                                        border-collapse: collapse;
                                        width: 100%;
                                        margin: 10px 0;
                                    }}
                                    div[data-testid="stMarkdown"] th,
                                    div[data-testid="stMarkdown"] td {{
                                        border: 1px solid rgba(255,255,255,0.2);
                                        padding: 8px 12px;
                                        text-align: left;
                                    }}
                                    div[data-testid="stMarkdown"] th {{
                                        background-color: rgba(255,255,255,0.1);
                                        font-weight: bold;
                                    }}
                                    div[data-testid="stMarkdown"] tr:nth-child(even) {{
                                        background-color: rgba(255,255,255,0.02);
                                    }}
                                </style>
                                """
                                st.markdown(html_content, unsafe_allow_html=True)
                            elif result['success'] and result['feedback']:
                                # Plain text fallback
                                st.text_area("Feedback", value=result['feedback'], height=300, disabled=True, label_visibility="collapsed")
                            elif result['error']:
                                st.error(f"Failed to load feedback: {result['error']}")
                                # Fallback: show truncated feedback from table
                                fallback = row.get('Feedback Comments', '')
                                if fallback:
                                    st.caption("Showing cached (truncated) feedback:")
                                    st.text_area("Feedback", value=fallback, height=150, disabled=True, label_visibility="collapsed")
                            else:
                                st.info("No feedback comments available.")
                        else:
                            # Fallback: show truncated feedback from table if no User_ID
                            feedback = row.get('Feedback Comments', '')
                            if feedback:
                                st.caption("⚠️ Showing cached feedback (may be truncated):")
                                st.text_area("Feedback", value=feedback, height=300, disabled=True, label_visibility="collapsed")
                            else:
                                st.info("No feedback comments available.")
                    
                    show_feedback_dialog(selected_row, module_id)
                
                # Download All Tasks as XLSX (each task = separate sheet)
                import io
                from pathlib import Path
                
                output_dir = Path(f"output/course_{course['id']}")
                all_csv_files = sorted(output_dir.glob("submissions_*.csv")) if output_dir.exists() else []
                # Filter files based on selected group
                import re as _re_filter
                if selected_group_id:
                    # Only include files for the selected group
                    grp_suffix = f"_grp{selected_group_id}"
                    submission_files = [f for f in all_csv_files if grp_suffix in f.stem]
                else:
                    # No group selected: exclude group-specific files
                    submission_files = [f for f in all_csv_files if not _re_filter.search(r'_grp\d+', f.stem)]
                
                if submission_files:
                    # Build task name lookup from tasks_data
                    task_name_map = {}
                    if st.session_state.tasks_data:
                        for t in st.session_state.tasks_data:
                            task_name_map[str(t['Module ID'])] = t['Task Name']
                    
                    buffer = io.BytesIO()
                    sheet_count = 0
                    used_sheet_names = set()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        for csv_path in submission_files:
                            csv_rows = load_csv_from_disk(course['id'], csv_path.name)
                            if not csv_rows:
                                continue
                            
                            sheet_df = pd.DataFrame(csv_rows)
                            
                            # Clean names
                            if 'Name' in sheet_df.columns:
                                sheet_df['Name'] = sheet_df['Name'].apply(clean_name)
                            
                            # Extract module_id from filename pattern: submissions_{cid}_mod{mid}[_grp{gid}].csv
                            import re as _re
                            mid_match = _re.search(r'_mod(\d+)', csv_path.name)
                            gid_match = _re.search(r'_grp(\d+)', csv_path.name)
                            file_mod_id = mid_match.group(1) if mid_match else None
                            file_grp_id = gid_match.group(1) if gid_match else None
                            
                            # Add AI scores
                            if file_mod_id:
                                ai_scores = []
                                for r in csv_rows:
                                    sname = r.get('Name', 'Unknown')
                                    ev = load_evaluation(course['id'], file_mod_id, sname, file_grp_id)
                                    if ev and ev.get('total_score') is not None:
                                        ai_scores.append(f"{ev['total_score']}%")
                                    else:
                                        ai_scores.append("-")
                                if 'Final Grade' in sheet_df.columns:
                                    gi = sheet_df.columns.get_loc('Final Grade') + 1
                                    sheet_df.insert(gi, 'AI Score', ai_scores)
                                else:
                                    sheet_df['AI Score'] = ai_scores
                            
                            # Drop internal columns not useful in export
                            drop_cols = [c for c in ['Submission_Files', 'Submission_Type', 'Assignment_Type'] if c in sheet_df.columns]
                            if drop_cols:
                                sheet_df = sheet_df.drop(columns=drop_cols)
                            
                            # Build sheet name from task name (Excel max 31 chars)
                            task_name = task_name_map.get(file_mod_id, f"Module {file_mod_id or 'Unknown'}")
                            # Sanitize: Excel forbids \ / * ? : [ ] in sheet names
                            safe_name = _re.sub(r'[\\/\*\?\:\[\]]', '', task_name)[:31]
                            # Ensure unique sheet names
                            if safe_name in used_sheet_names:
                                safe_name = safe_name[:27] + f"_{file_mod_id}"[:4]
                            used_sheet_names.add(safe_name)
                            
                            sheet_df.to_excel(writer, sheet_name=safe_name, index=False)
                            sheet_count += 1
                    
                    buffer.seek(0)
                    group_label = f"_grp{selected_group_id}" if selected_group_id else ""
                    st.download_button(
                        label=f"📥 Download All Tasks ({sheet_count} sheets)",
                        data=buffer,
                        file_name=f"submissions_{course['id']}{group_label}_all.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"download_all_xlsx_{course['id']}_{selected_group_id}"
                    )
                else:
                    st.caption("No saved submission data found for export.")

