"""
Skill Matrix tab for Streamlit app.
Displays a matrix of students × skills with color-coded numeric scores.
"""

import streamlit as st
import pandas as pd
import logging

from core.skill_matrix import (
    load_skills, save_skills, get_flat_skill_list,
    load_quiz_mappings, save_quiz_mappings,
    load_quizizz_mappings, save_quizizz_mappings,
    load_task_mappings, save_task_mappings,
    load_name_aliases, save_name_aliases,
    calculate_skill_scores, get_available_quizzes, get_available_quizizz_names,
    load_all_task_submissions, get_available_tasks
)
from core.persistence import load_csv_from_disk, get_output_dir

logger = logging.getLogger(__name__)


def render_skill_matrix_tab(course, meta):
    """Render the Skill Matrix tab content."""
    course_id = course.get('id')
    
    st.subheader("📊 Skill Matrix")
    st.caption("Map quiz and task scores to skills and view competency levels across all students")
    
    # Load skills and mappings
    skills = load_skills(course_id)
    flat_skills = get_flat_skill_list(skills)
    quiz_mappings = load_quiz_mappings(course_id)
    quizizz_mappings = load_quizizz_mappings(course_id)
    task_mappings = load_task_mappings(course_id)
    name_aliases = load_name_aliases(course_id)
    
    # Get quiz data from session state (loaded by Quiz tab)
    quiz_data = st.session_state.get('quiz_data')
    quizizz_data = st.session_state.get('quizizz_data')
    tasks_data = st.session_state.get('tasks_data')
    
    # Check for available quizzes (handle both list and DataFrame)
    available_quizzes = get_available_quizzes(quiz_data) if quiz_data else []
    
    # Handle quizizz_data which may be a DataFrame
    has_quizizz_data = quizizz_data is not None and (
        isinstance(quizizz_data, pd.DataFrame) and not quizizz_data.empty or
        isinstance(quizizz_data, list) and len(quizizz_data) > 0
    )
    available_quizizz = get_available_quizizz_names(quizizz_data) if has_quizizz_data else []
    
    # Load task submissions from disk
    task_submissions, available_task_info = load_all_task_submissions(course_id, tasks_data)
    available_tasks = [t['task_key'] for t in available_task_info]
    
    # ==========================================================================
    # Mapping Configuration Section
    # ==========================================================================
    has_any_mappings = bool(quiz_mappings or quizizz_mappings or task_mappings)
    with st.expander("🔗 Source → Skill Mappings", expanded=not has_any_mappings):
        tab1, tab2, tab3 = st.tabs(["Practice Quizzes", "Quizizz", "Tasks"])
        
        with tab1:
            if not available_quizzes:
                st.info("📊 No Practice Quiz data loaded. Fetch data in the Quiz Scores tab first.")
            else:
                st.caption(f"Found {len(available_quizzes)} quizzes. Assign skills to each quiz.")
                
                # Build mapping UI
                updated_quiz_mappings = {}
                for quiz_name in available_quizzes:
                    current_skills = quiz_mappings.get(quiz_name, [])
                    
                    col1, col2 = st.columns([2, 3])
                    with col1:
                        st.text(quiz_name[:50] + "..." if len(quiz_name) > 50 else quiz_name)
                    with col2:
                        selected = st.multiselect(
                            "Skills",
                            options=[s['id'] for s in flat_skills],
                            default=current_skills,
                            format_func=lambda x: next((s['name'] for s in flat_skills if s['id'] == x), x),
                            key=f"quiz_skill_{quiz_name}",
                            label_visibility="collapsed"
                        )
                        if selected:
                            updated_quiz_mappings[quiz_name] = selected
                
                if st.button("💾 Save Quiz Mappings", key="save_quiz_mappings"):
                    save_quiz_mappings(course_id, updated_quiz_mappings)
                    st.success("✓ Quiz mappings saved")
                    st.rerun()
        
        with tab2:
            if not available_quizizz:
                st.info("📝 No Quizizz data loaded. Upload data in the Quizizz tab first.")
            else:
                st.caption(f"Found {len(available_quizizz)} quizzes. Assign skills to each quiz.")
                
                # Build mapping UI
                updated_quizizz_mappings = {}
                for quiz_name in available_quizizz:
                    current_skills = quizizz_mappings.get(quiz_name, [])
                    
                    col1, col2 = st.columns([2, 3])
                    with col1:
                        st.text(quiz_name[:50] + "..." if len(quiz_name) > 50 else quiz_name)
                    with col2:
                        selected = st.multiselect(
                            "Skills",
                            options=[s['id'] for s in flat_skills],
                            default=current_skills,
                            format_func=lambda x: next((s['name'] for s in flat_skills if s['id'] == x), x),
                            key=f"quizizz_skill_{quiz_name}",
                            label_visibility="collapsed"
                        )
                        if selected:
                            updated_quizizz_mappings[quiz_name] = selected
                
                if st.button("💾 Save Quizizz Mappings", key="save_quizizz_mappings"):
                    save_quizizz_mappings(course_id, updated_quizizz_mappings)
                    st.success("✓ Quizizz mappings saved")
                    st.rerun()
        
        with tab3:
            if not available_tasks:
                st.info("📋 No Task submissions found. Fetch submissions in the Submissions tab first.")
            else:
                st.caption(f"Found {len(available_tasks)} tasks with saved submissions. Assign skills to each task.")
                
                # Build mapping UI
                updated_task_mappings = {}
                for task_name in available_tasks:
                    current_skills = task_mappings.get(task_name, [])
                    
                    col1, col2 = st.columns([2, 3])
                    with col1:
                        st.text(task_name[:50] + "..." if len(task_name) > 50 else task_name)
                    with col2:
                        selected = st.multiselect(
                            "Skills",
                            options=[s['id'] for s in flat_skills],
                            default=current_skills,
                            format_func=lambda x: next((s['name'] for s in flat_skills if s['id'] == x), x),
                            key=f"task_skill_{task_name}",
                            label_visibility="collapsed"
                        )
                        if selected:
                            updated_task_mappings[task_name] = selected
                
                if st.button("💾 Save Task Mappings", key="save_task_mappings"):
                    save_task_mappings(course_id, updated_task_mappings)
                    st.success("✓ Task mappings saved")
                    st.rerun()
    
    # ==========================================================================
    # Calculate and Display Skill Matrix
    # ==========================================================================
    has_mappings = bool(quiz_mappings or quizizz_mappings or task_mappings)
    has_quiz_data = quiz_data is not None and len(quiz_data) > 0
    has_task_data = bool(task_submissions)
    has_data = has_quiz_data or has_quizizz_data or has_task_data
    
    if not has_data:
        st.warning("📊 No data available. Load data from the Quiz Scores, Quizizz, and/or Submissions tabs first.")
        return
    
    if not has_mappings:
        st.info("🔗 No skill mappings configured. Set up mappings above to generate the skill matrix.")
        return
    
    # Calculate scores
    results, skill_columns = calculate_skill_scores(
        quiz_data, quizizz_data, task_submissions,
        quiz_mappings, quizizz_mappings, task_mappings, skills,
        name_aliases=name_aliases
    )
    
    if not results:
        st.warning("No students with mapped skill scores found.")
        return
    
    # Display stats
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Students", len(results))
    with col2:
        mapped_skills = sum(1 for r in results for col in skill_columns if r.get(col) is not None) // max(len(results), 1)
        st.metric("Avg Skills/Student", mapped_skills)
    with col3:
        total_mappings = len(quiz_mappings) + len(quizizz_mappings) + len(task_mappings)
        st.metric("Total Mappings", total_mappings)
    
    # Build DataFrame
    df = pd.DataFrame(results)
    
    # Reorder columns: Student Name first, then skills in order
    cols = ['Student Name'] + [c for c in skill_columns if c in df.columns]
    df = df[cols]
    
    # Style the DataFrame with color gradient
    def color_score(val):
        """Apply color based on score value (0-10 scale)."""
        if pd.isna(val) or val is None:
            return 'background-color: #f0f0f0; color: #999'
        
        # Convert to float for comparison
        try:
            v = float(val)
        except (ValueError, TypeError):
            return ''
        
        # Color gradient: red (0) -> yellow (5) -> green (10)
        if v < 4:
            return 'background-color: #ffcccc; color: #990000'  # Light red
        elif v < 6:
            return 'background-color: #fff3cd; color: #856404'  # Light yellow
        elif v < 8:
            return 'background-color: #d4edda; color: #155724'  # Light green
        else:
            return 'background-color: #28a745; color: white'    # Strong green
    
    # Apply styling to skill columns only
    styled_df = df.style.map(
        color_score,
        subset=[c for c in df.columns if c != 'Student Name']
    )
    
    st.dataframe(styled_df, width="stretch", hide_index=True)
    
    # ==========================================================================
    # Name Merge (manual alias management)
    # ==========================================================================
    with st.expander("🔀 Merge Duplicate Names", expanded=False):
        st.caption("If you see duplicate student entries due to name variations, merge them here.")
        
        # Get all unique student names from results
        all_names = sorted([r['Student Name'] for r in results])
        
        if len(all_names) < 2:
            st.info("Not enough students to merge.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                duplicate_name = st.selectbox(
                    "Select duplicate name to remove:",
                    options=all_names,
                    key="merge_duplicate"
                )
            with col2:
                # Filter out the selected duplicate from canonical options
                canonical_options = [n for n in all_names if n != duplicate_name]
                canonical_name = st.selectbox(
                    "Merge into (canonical name):",
                    options=canonical_options,
                    key="merge_canonical"
                )
            
            if st.button("🔗 Merge Names", key="merge_names_btn"):
                if duplicate_name and canonical_name and duplicate_name != canonical_name:
                    name_aliases[duplicate_name] = canonical_name
                    save_name_aliases(course_id, name_aliases)
                    st.success(f"✓ '{duplicate_name}' will now merge into '{canonical_name}'")
                    st.rerun()
            
            # Show existing aliases
            if name_aliases:
                st.markdown("**Current Aliases:**")
                for alias, canonical in name_aliases.items():
                    col_a, col_b = st.columns([4, 1])
                    with col_a:
                        st.text(f"{alias} → {canonical}")
                    with col_b:
                        if st.button("❌", key=f"del_alias_{alias}"):
                            del name_aliases[alias]
                            save_name_aliases(course_id, name_aliases)
                            st.rerun()
    
    # ==========================================================================
    # Export Options
    # ==========================================================================
    st.divider()
    
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        csv_data = df.to_csv(index=False)
        st.download_button(
            "📥 Download CSV",
            data=csv_data,
            file_name=f"skill_matrix_{course_id}.csv",
            mime="text/csv"
        )
    
    with col2:
        # Excel export with formatting
        import io
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Skill Matrix')
        
        st.download_button(
            "📥 Download Excel",
            data=buffer.getvalue(),
            file_name=f"skill_matrix_{course_id}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    # ==========================================================================
    # Skill Configuration (Advanced)
    # ==========================================================================
    with st.expander("⚙️ Skill Configuration", expanded=False):
        st.caption("View and manage the skill framework (24 skills across 10 milestones)")
        
        for milestone in skills.get('milestones', []):
            st.markdown(f"**{milestone['id']}: {milestone['name']}**")
            for skill in milestone.get('skills', []):
                st.text(f"  • {skill['id']}: {skill['name']}")
