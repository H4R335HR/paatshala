#!/usr/bin/env python3
"""
Paatshala Tool - Refactored GUI Version (Streamlit)
"""

import time
import streamlit as st
import pandas as pd
from pathlib import Path

from core.auth import (
    login_and_get_cookie, validate_session, setup_session, attempt_auto_login
)
from core.api import (
    get_courses, fetch_tasks_list, fetch_quiz_scores_all, get_quizzes,
    fetch_submissions, evaluate_submission, download_file, get_available_groups
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
        # Group selector for Quizzes
        selected_quiz_group_id = None
        
        # We need at least one quiz ID to check for groups
        # We can quickly fetch the list of quizzes without scores
        if st.session_state.authenticated:
            session = setup_session(st.session_state.session_id)
            # This is fast as it just parses the course page
            quizzes_list = get_quizzes(session, course['id'])
            
            if quizzes_list:
                # Use the first quiz to check for groups
                first_quiz_id = quizzes_list[0][1]
                quiz_groups = get_available_groups(session, first_quiz_id, activity_type='quiz')
                
                if quiz_groups:
                    q_group_options = {"All Groups": (None, None)}
                    q_group_options.update({
                        f"{g[1]} (ID: {g[0]})": (g[0], g[1])
                        for g in quiz_groups
                    })
                    
                    col_q1, col_q2 = st.columns([3, 1])
                    with col_q1:
                        selected_q_group_label = st.selectbox(
                            "Filter by Batch (Group)",
                            options=list(q_group_options.keys()),
                            key="quiz_group_selector"
                        )
                        selected_quiz_group_id, _ = q_group_options.get(selected_q_group_label, (None, None))
        
        # Construct filename based on group
        quiz_filename = f"quiz_scores_{course['id']}"
        if selected_quiz_group_id:
            quiz_filename += f"_grp{selected_quiz_group_id}"
        quiz_filename += ".csv"
        
        quiz_meta_key = 'quiz'
        if selected_quiz_group_id:
            quiz_meta_key += f"_grp{selected_quiz_group_id}"

        # Try to load from disk if not loaded (or if group changed)
        # We need a way to track which group is currently loaded in session_state
        # For simplicity, if the user changes group, they might need to hit fetch/refresh if we don't auto-reload
        # But let's try to auto-load if available
        
        # Check if current loaded data matches selected group
        # We can store the loaded group_id in session_state
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
                st.session_state.quiz_data = rows
                st.session_state.quiz_loaded_from_disk = False
                st.session_state.quiz_loaded_group_id = selected_quiz_group_id
                
                # Save to disk
                save_csv_to_disk(course['id'], quiz_filename, rows)
                save_meta(course['id'], quiz_meta_key, len(rows))
                
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
                file_name=quiz_filename,
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
            # Determine assignment type from first row
            assignment_type = "link"
            if data and len(data) > 0:
                assignment_type = data[0].get("Assignment_Type", "link")
            
            # Configure columns based on assignment type
            cols_config = {
                "Link": st.column_config.LinkColumn("Link"),
                "Valid?": st.column_config.TextColumn("Valid?"),
                "Fork?": st.column_config.TextColumn("Fork?"),
            }
            
            hidden_cols = []
            if assignment_type == 'file':
                hidden_cols = ["Link", "Valid?", "Repo Status", "Fork?", "Eval_Link", "Eval_Link_Valid", "Eval_Repo_Status", "Eval_Is_Fork", "Eval_Parent"]
                # Ensure these columns are hidden
                for col in ["Link", "Valid?", "Fork?"]: # Only these are directly in column_config
                    cols_config[col] = None
            
            with table_placeholder:
                # Filter out hidden columns from display dataframe if needed, 
                # but st.dataframe handles extra columns fine if we don't configure them explicitly.
                # However, to be safe, let's just rely on column_config to hide them if possible, 
                # or just don't include them in the view?
                # Actually, get_display_dataframe constructs specific columns. We should modify it or filter the result.
                
                display_df = pd.DataFrame(get_display_dataframe(data))
                if assignment_type == 'file':
                    # Remove columns from display DF
                    cols_to_drop = [c for c in ["Link", "Valid?", "Repo Status", "Fork?"] if c in display_df.columns]
                    display_df = display_df.drop(columns=cols_to_drop)
                
                event = st.dataframe(
                    display_df,
                    use_container_width=True,
                    column_config=cols_config,
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

            st.divider()

            # Determine submission type (fallback if missing)
            sub_type = row.get('Submission_Type')
            if not sub_type:
                submission_files = row.get('Submission_Files')
                if isinstance(submission_files, str) and submission_files.startswith('['):
                    try:
                        submission_files = eval(submission_files)
                    except:
                        submission_files = []
                
                if submission_files:
                    sub_type = 'file'
                elif "http" in row.get('Submission', ''):
                    sub_type = 'link'
                elif row.get('Submission'):
                    sub_type = 'text'
                else:
                    sub_type = 'empty'

            # Render based on ASSIGNMENT type (overrides individual submission type for UI structure)
            if assignment_type == 'file':
                # File Assignment View
                submission_files = row.get('Submission_Files')
                if isinstance(submission_files, str):
                    try:
                        submission_files = eval(submission_files)
                    except:
                        submission_files = []
                
                if submission_files:
                    st.markdown("#### 📂 Submitted Files")
                    for fname, furl in submission_files:
                        # Construct local path to check existence
                        safe_student = "".join([c for c in row.get('Name', 'Unknown') if c.isalnum() or c in (' ', '-', '_')]).strip()
                        safe_filename = "".join([c for c in fname if c.isalnum() or c in (' ', '-', '_', '.')]).strip()
                        local_path = Path(f"output/course_{course['id']}/downloads/{safe_student}/{safe_filename}")
                        
                        col_d1, col_d2 = st.columns([3, 1])
                        with col_d1:
                            st.text(fname)
                        with col_d2:
                            if local_path.exists():
                                with open(local_path, "rb") as f:
                                    st.download_button(
                                        label="📂 Download",
                                        data=f,
                                        file_name=fname,
                                        mime="application/octet-stream",
                                        key=f"dl_{idx}_{fname}",
                                        use_container_width=True
                                    )
                            else:
                                if st.button("⬇️ Fetch", key=f"fetch_{idx}_{fname}", use_container_width=True):
                                    with st.spinner("Fetching from server..."):
                                        session = setup_session(st.session_state.session_id)
                                        saved_path = download_file(session, furl, course['id'], row.get('Name', 'Unknown'), fname)
                                        if saved_path:
                                            st.success("Fetched!")
                                            st.rerun()
                                        else:
                                            st.error("Failed to fetch")
                else:
                    st.warning("⚠️ No file submitted")

            else:
                # Link/Text Assignment View
                if sub_type == 'link' or (sub_type == 'empty' and row.get('Eval_Last_Checked')):
                    # Show analysis if it's a link OR if we have checked it (even if empty, though unlikely)
                    if row.get('Eval_Last_Checked'):
                        st.markdown(f"**Submission Link:** [{row.get('Eval_Link')}]({row.get('Eval_Link')})")
                        
                        c1, c2 = st.columns(2)
                        with c1:
                            valid = row.get('Eval_Link_Valid') or 'N/A'
                            if '✅' in str(valid):
                                st.success(f"Link Valid: {valid}")
                            else:
                                st.error(f"Link Valid: {valid}")
                        with c2:
                            repo_status = row.get('Eval_Repo_Status') or 'N/A'
                            st.info(f"Repo Status: {repo_status}")
                            if row.get('Eval_Is_Fork') == 'Yes':
                                st.caption(f"Fork of: {row.get('Eval_Parent')}")
                    else:
                        st.warning("Analysis not run yet. Click 'Refresh Analysis'.")
                
                elif sub_type == 'text':
                    st.info("ℹ️ Text-only submission (No link detected)")
                
                elif sub_type == 'empty':
                    st.warning("⚠️ No submission found")
            
            with st.expander("Submission Content", expanded=True):
                st.text(row.get('Submission', ''))

if __name__ == "__main__":
    main()
