#!/usr/bin/env python3
"""
Paatshala Tool - Refactored GUI Version (Streamlit)
"""

import time
import streamlit as st
import pandas as pd

from core.auth import (
    login_and_get_cookie, validate_session, setup_session, attempt_auto_login
)
from core.api import (
    get_courses, fetch_tasks_list, fetch_quiz_scores_all,
    fetch_submissions, evaluate_submission, get_available_groups
)
from core.persistence import (
    read_config, write_config, clear_config,
    load_last_session, save_last_session,
    load_meta, save_meta,
    load_csv_from_disk, save_csv_to_disk, dataframe_to_csv,
    OUTPUT_DIR, get_output_dir
)
from ui.styles import apply_custom_css
from ui.components import show_data_status, show_fresh_status, format_timestamp

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

# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

def init_session_state():
    """Initialize all session state variables"""
    defaults = {
        'authenticated': False,
        'session_id': None,
        'auth_source': None,  # 'config', 'manual', 'cookie'
        'courses': [],
        'selected_course': None,
        'tasks_data': None,
        'tasks_loaded_from_disk': False,
        'quiz_data': None,
        'quiz_loaded_from_disk': False,
        'submissions_data': None,
        'submissions_loaded_from_disk': False,
        'auto_login_attempted': False,
        'selected_task_for_submissions': None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# ============================================================================
# UI HELPERS (Local to app.py for specific logic)
# ============================================================================

def get_display_dataframe(data):
    """Create a display-friendly dataframe for the Evaluation tab"""
    display_data = []
    for r in data:
        display_data.append({
            "Name": r.get('Name'),
            "Status": r.get('Status'),
            "Link": r.get('Eval_Link'),
            "Valid?": r.get('Eval_Link_Valid'),
            "Repo Status": r.get('Eval_Repo_Status'),
            "Fork?": r.get('Eval_Is_Fork'),
            "Parent": r.get('Eval_Parent'),
            "Checked": format_timestamp(r.get('Eval_Last_Checked', ''))
        })
    return display_data

# ============================================================================
# MAIN APP
# ============================================================================

def main():
    # Attempt auto-login on first load
    if not st.session_state.authenticated and not st.session_state.auto_login_attempted:
        if attempt_auto_login():
            st.rerun()
    
    # Header
    st.markdown('<p class="main-header">🎓 Paatshala Tool</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Extract data from ICT Academy Kerala\'s Moodle LMS</p>', unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.header("🔐 Authentication")
        
        if not st.session_state.authenticated:
            auth_method = st.radio(
                "Login method",
                ["Credentials", "Session Cookie"],
                horizontal=True
            )
            
            if auth_method == "Credentials":
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                remember_me = st.checkbox("Remember me", value=True)
                
                if st.button("Login", type="primary", use_container_width=True):
                    if username and password:
                        with st.spinner("Logging in..."):
                            session_id = login_and_get_cookie(username, password)
                            if session_id:
                                st.session_state.session_id = session_id
                                st.session_state.authenticated = True
                                st.session_state.auth_source = 'manual'
                                
                                # Save to config
                                if remember_me:
                                    write_config(cookie=session_id, username=username, password=password)
                                else:
                                    write_config(cookie=session_id)
                                
                                st.success("✓ Logged in!")
                                st.rerun()
                            else:
                                st.error("✗ Login failed. Check credentials.")
                    else:
                        st.warning("Please enter username and password")
            
            else:  # Cookie method
                cookie = st.text_input("MoodleSession Cookie", type="password")
                remember_cookie = st.checkbox("Save cookie", value=True)
                
                if st.button("Validate & Login", type="primary", use_container_width=True):
                    if cookie:
                        with st.spinner("Validating session..."):
                            if validate_session(cookie):
                                st.session_state.session_id = cookie
                                st.session_state.authenticated = True
                                st.session_state.auth_source = 'cookie'
                                
                                if remember_cookie:
                                    write_config(cookie=cookie)
                                
                                st.success("✓ Session valid!")
                                st.rerun()
                            else:
                                st.error("✗ Invalid or expired cookie")
                    else:
                        st.warning("Please enter cookie")
        
        else:
            # Logged in state
            auth_source_text = {
                'config_cookie': 'saved cookie',
                'config_credentials': 'saved credentials',
                'manual': 'this session',
                'cookie': 'session cookie'
            }.get(st.session_state.auth_source, 'unknown')
            
            st.success(f"✓ Logged in ({auth_source_text})")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Logout", use_container_width=True):
                    st.session_state.authenticated = False
                    st.session_state.session_id = None
                    st.session_state.auth_source = None
                    st.session_state.courses = []
                    st.session_state.selected_course = None
                    st.session_state.tasks_data = None
                    st.session_state.quiz_data = None
                    st.session_state.submissions_data = None
                    st.rerun()
            
            with col2:
                if st.button("🗑️ Forget", use_container_width=True, help="Clear saved credentials"):
                    clear_config()
                    st.toast("Saved credentials cleared")
        
        st.divider()
        
        # Course Selection
        if st.session_state.authenticated:
            st.header("📚 Course")
            
            # Load courses if not loaded
            if not st.session_state.courses:
                # Try to load from last session first
                last = load_last_session()
                if last.get('courses'):
                    st.session_state.courses = last['courses']
                    # Auto-select last course if available
                    if last.get('course_id'):
                        for c in st.session_state.courses:
                            if c['id'] == last['course_id']:
                                st.session_state.selected_course = c
                                break
                    st.rerun()

                if st.button("Load Courses", type="primary", use_container_width=True):
                    with st.spinner("Fetching courses..."):
                        session = setup_session(st.session_state.session_id)
                        st.session_state.courses = get_courses(session)
                        if st.session_state.courses:
                            st.success(f"Found {len(st.session_state.courses)} courses")
                            
                            # Save to last session
                            save_last_session({'courses': st.session_state.courses})
                            
                            # Check for last session course selection
                            last = load_last_session()
                            if last.get('course_id'):
                                for c in st.session_state.courses:
                                    if c['id'] == last['course_id']:
                                        st.session_state.selected_course = c
                                        break
                            
                            st.rerun()
                        else:
                            st.warning("No courses found")
            else:
                if st.button("🔄 Refresh", use_container_width=True):
                    with st.spinner("Refreshing..."):
                        session = setup_session(st.session_state.session_id)
                        st.session_state.courses = get_courses(session)
                        if st.session_state.courses:
                            save_last_session({'courses': st.session_state.courses})
                        st.rerun()
                
                # Course dropdown
                course_options = {
                    f"{'⭐ ' if c['starred'] else ''}{c['name']}": c
                    for c in st.session_state.courses
                }
                
                # Find current index
                current_index = 0
                if st.session_state.selected_course:
                    for i, (name, course) in enumerate(course_options.items()):
                        if course['id'] == st.session_state.selected_course['id']:
                            current_index = i
                            break
                
                selected_name = st.selectbox(
                    "Select Course",
                    options=list(course_options.keys()),
                    index=current_index,
                    label_visibility="collapsed"
                )
                
                if selected_name:
                    new_course = course_options[selected_name]
                    if st.session_state.selected_course is None or new_course['id'] != st.session_state.selected_course['id']:
                        st.session_state.selected_course = new_course
                        # Clear data when course changes
                        st.session_state.tasks_data = None
                        st.session_state.tasks_loaded_from_disk = False
                        st.session_state.quiz_data = None
                        st.session_state.quiz_loaded_from_disk = False
                        st.session_state.submissions_data = None
                        st.session_state.submissions_loaded_from_disk = False
                        # Save to last session
                        save_last_session({
                            'course_id': new_course['id'],
                            'course_name': new_course['name']
                        })
                        st.rerun()
                
                # Show last session indicator
                last = load_last_session()
                if last.get('course_id') and st.session_state.selected_course:
                    if last['course_id'] == st.session_state.selected_course['id']:
                        st.caption("📌 From last session")
            
            st.divider()
            
            # Output folder info
            st.header("⚙️ Output")
            st.caption(f"📁 `{OUTPUT_DIR}/`")
            
            if st.session_state.selected_course:
                output_path = get_output_dir(st.session_state.selected_course['id'])
                st.caption(f"└─ `course_{st.session_state.selected_course['id']}/`")
    
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
    
    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Tasks", "📊 Quiz Scores", "📝 Submissions", "🔍 Evaluation"])
    
    # -------------------------------------------------------------------------
    # TAB 1: TASKS
    # -------------------------------------------------------------------------
    with tab1:
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
            
            rows = fetch_tasks_list(st.session_state.session_id, course['id'], update_progress)
            
            progress_bar.progress(1.0, text="Complete!")
            
            if rows:
                st.session_state.tasks_data = rows
                st.session_state.tasks_loaded_from_disk = False
                
                # Save to disk
                save_csv_to_disk(course['id'], f"tasks_{course['id']}.csv", rows)
                save_meta(course['id'], 'tasks', len(rows))
                
                st.success(f"✓ Fetched {len(rows)} tasks → Saved to `output/course_{course['id']}/`")
                time.sleep(0.5)
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
            
            csv_data = dataframe_to_csv(st.session_state.tasks_data)
            st.download_button(
                label="📥 Download CSV",
                data=csv_data,
                file_name=f"tasks_{course['id']}.csv",
                mime="text/csv"
            )
    
    # -------------------------------------------------------------------------
    # TAB 2: QUIZ SCORES
    # -------------------------------------------------------------------------
    with tab2:
        st.subheader("Practice Quiz Scores")
        
        # Try to load from disk if not loaded
        if st.session_state.quiz_data is None:
            disk_data = load_csv_from_disk(course['id'], f"quiz_scores_{course['id']}.csv")
            if disk_data:
                st.session_state.quiz_data = disk_data
                st.session_state.quiz_loaded_from_disk = True
        
        col1, col2 = st.columns([3, 1])
        with col1:
            if st.session_state.quiz_loaded_from_disk and 'quiz' in meta:
                show_data_status(meta, 'quiz', 'Quiz')
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
                st.session_state.session_id, course['id'], update_progress
            )
            
            progress_bar.progress(1.0, text="Complete!")
            
            if rows:
                st.session_state.quiz_data = rows
                st.session_state.quiz_loaded_from_disk = False
                
                # Save to disk
                save_csv_to_disk(course['id'], f"quiz_scores_{course['id']}.csv", rows)
                save_meta(course['id'], 'quiz', len(rows))
                
                st.success(f"✓ Fetched scores for {len(rows)} students → Saved to `output/course_{course['id']}/`")
                time.sleep(0.5)
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
                file_name=f"quiz_scores_{course['id']}.csv",
                mime="text/csv"
            )
    
    # -------------------------------------------------------------------------
    # TAB 3: SUBMISSIONS
    # -------------------------------------------------------------------------
    with tab3:
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
            
            selected_task_name = st.selectbox(
                "Select Assignment",
                options=list(task_options.keys())
            )
            
            selected_task = task_options.get(selected_task_name)
            
            # Group selector
            selected_group_id = None
            selected_group_name = None
            
            if selected_task:
                session = setup_session(st.session_state.session_id)
                groups = get_available_groups(session, selected_task['Module ID'])
                
                if groups:
                    group_options = {"All Groups": (None, None)}
                    group_options.update({
                        f"{g[1]} (ID: {g[0]})": (g[0], g[1])
                        for g in groups
                    })
                    
                    selected_group_label = st.selectbox(
                        "Filter by Group (optional)",
                        options=list(group_options.keys())
                    )
                    selected_group_id, selected_group_name = group_options.get(selected_group_label, (None, None))
                else:
                    st.caption("No groups available for this assignment")
                
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
                    st.session_state.submissions_data = existing_data
                
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
                            
                            st.success(f"✓ Fetched {len(rows)} submissions → Saved to `output/course_{course['id']}/`")
                            st.rerun()
                        else:
                            st.warning("No submission data found")
            
            if st.session_state.submissions_data:
                st.dataframe(
                    st.session_state.submissions_data,
                    use_container_width=True,
                    hide_index=True
                )
                
                csv_data = dataframe_to_csv(st.session_state.submissions_data)
                st.download_button(
                    label="📥 Download CSV",
                    data=csv_data,
                    file_name=f"submissions_{course['id']}.csv",
                    mime="text/csv"
                )

    # -------------------------------------------------------------------------
    # TAB 4: EVALUATION
    # -------------------------------------------------------------------------
    with tab4:
        st.subheader("Submission Evaluation")
        
        if not st.session_state.submissions_data:
            st.info("⚠️ Please fetch submissions first (in Submissions tab) to evaluate them.")
        else:
            # --- Batch Actions ---
            data = st.session_state.submissions_data
            total = len(data)
            evaluated = sum(1 for r in data if r.get('Eval_Last_Checked'))
            
            # Placeholder for the table (defined early for real-time updates)
            table_placeholder = st.empty()
            
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                st.metric("Evaluated Submissions", f"{evaluated} / {total}")
            
            with col2:
                if st.button("🚀 Evaluate Pending", use_container_width=True, disabled=(evaluated == total)):
                    progress_bar = st.progress(0, text="Evaluating pending submissions...")
                    pending_indices = [i for i, r in enumerate(data) if not r.get('Eval_Last_Checked')]
                    count = len(pending_indices)
                    
                    for idx, i in enumerate(pending_indices):
                        data[i] = evaluate_submission(data[i])
                        progress_bar.progress((idx + 1) / count)
                        
                        # Real-time update
                        table_placeholder.dataframe(
                            get_display_dataframe(data),
                            use_container_width=True,
                            column_config={
                                "Link": st.column_config.LinkColumn("Link"),
                                "Valid?": st.column_config.TextColumn("Valid?", width="small"),
                                "Fork?": st.column_config.TextColumn("Fork?", width="small"),
                            },
                            selection_mode="single-row"
                        )
                        
                        # Check for Rate Limit to abort early
                        if data[i].get('Eval_Repo_Status') == "Rate Limit":
                            st.warning("⚠️ GitHub API Rate Limit reached. Stopping early.")
                            break
                    
                    # Save progress
                    if data and 'Module ID' in data[0]:
                        mid = data[0]['Module ID']
                        fname = f"submissions_{course['id']}_mod{mid}.csv"
                        save_csv_to_disk(course['id'], fname, data)
            
            # --- Table View (Interactive) ---
            # --- Table View (Interactive) ---
            # Use the placeholder for the main display too
            with table_placeholder:
                event = st.dataframe(
                    pd.DataFrame(get_display_dataframe(data)),
                    use_container_width=True,
                    column_config={
                        "Link": st.column_config.LinkColumn("Link"),
                        "Valid?": st.column_config.TextColumn("Valid?", width="small"),
                        "Fork?": st.column_config.TextColumn("Fork?", width="small"),
                    },
                    on_select="rerun",
                    selection_mode="single-row",
                    key="submission_table"
                )
            
            # Handle Selection
            selected_idx = None
            if event and event.selection and len(event.selection.rows) > 0:
                selected_idx = event.selection.rows[0]
            
            st.divider()

            # --- Detail View ---
            st.markdown("### 🔍 Individual Detail")
            
            # Use indices for options to handle duplicate names correctly
            student_indices = list(range(len(data)))
            
            def format_student_option(i):
                row = data[i]
                return f"{row.get('Name', 'Unknown')} ({row.get('Status', 'Unknown')})"
            
            # Initialize session state for selection tracking
            if 'last_table_selection' not in st.session_state:
                st.session_state.last_table_selection = None
            if 'eval_selected_index' not in st.session_state:
                st.session_state.eval_selected_index = 0
            
            # Detect change in table selection
            if selected_idx != st.session_state.last_table_selection:
                st.session_state.last_table_selection = selected_idx
                if selected_idx is not None:
                    st.session_state.eval_selected_index = selected_idx
                    # Force update the widget state
                    st.session_state.eval_student_select = selected_idx
            
            # Ensure index is valid
            if st.session_state.eval_selected_index >= len(data):
                st.session_state.eval_selected_index = 0
                
            # Ensure widget state is initialized
            if 'eval_student_select' not in st.session_state:
                st.session_state.eval_student_select = st.session_state.eval_selected_index

            def on_change_selectbox():
                st.session_state.eval_selected_index = st.session_state.eval_student_select
            
            selected_index = st.selectbox(
                "Select Student for Details",
                options=student_indices,
                format_func=format_student_option,
                key="eval_student_select",
                on_change=on_change_selectbox
            )
            
            # Use the tracked index
            idx = st.session_state.eval_selected_index
            row = data[idx]
                
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**Name:** {row.get('Name')} | **Email:** {row.get('Email')}")
            with col2:
                if st.button("🔄 Refresh Analysis", key=f"refresh_{idx}"):
                    data[idx] = evaluate_submission(row)
                    if 'Module ID' in row:
                        save_csv_to_disk(course['id'], f"submissions_{course['id']}_mod{row['Module ID']}.csv", data)
                    st.rerun()

            # Show existing analysis
            if row.get('Eval_Last_Checked'):
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.info(f"Link: {row.get('Eval_Link') or 'None'}")
                with c2:
                    st.info(f"Valid: {row.get('Eval_Link_Valid') or 'N/A'}")
                with c3:
                    st.info(f"Repo: {row.get('Eval_Repo_Status') or 'N/A'}")
                    if row.get('Eval_Is_Fork') == 'Yes':
                        st.caption(f"Fork of: {row.get('Eval_Parent')}")
            
            with st.expander("Submission Content", expanded=True):
                st.text(row.get('Submission', ''))

if __name__ == "__main__":
    main()
