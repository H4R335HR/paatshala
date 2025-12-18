"""
Evaluation tab for Streamlit app.
Handles submission evaluation and detailed analysis.
"""

import logging
from pathlib import Path
import pandas as pd
import streamlit as st
import ast

from core.auth import setup_session
from core.api import evaluate_submission, download_file
from core.persistence import save_csv_to_disk, get_config
from core.ai import generate_rubric, save_rubric, load_rubric, refine_rubric
from streamlit_modules.ui.components import format_timestamp

logger = logging.getLogger(__name__)


@st.cache_data
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


def _parse_submission_files(submission_files):
    """Safely parse submission files string to list"""
    if isinstance(submission_files, str) and submission_files.startswith('['):
        try:
            return ast.literal_eval(submission_files)
        except:
            return []
    return submission_files if isinstance(submission_files, list) else []


def render_evaluation_tab(course, meta):
    """Render the Evaluation tab content"""
    st.subheader("Submission Evaluation")
    
    if not st.session_state.submissions_data:
        st.info("⚠️ Please fetch submissions first (in Submissions tab) to evaluate them.")
        return
    
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
                    width="stretch",
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
    
    if assignment_type == 'file':
        # Ensure these columns are hidden
        for col in ["Link", "Valid?", "Fork?"]:
            cols_config[col] = None
    
    with table_placeholder:
        display_df = pd.DataFrame(get_display_dataframe(data))
        if assignment_type == 'file':
            # Remove columns from display DF
            cols_to_drop = [c for c in ["Link", "Valid?", "Repo Status", "Fork?"] if c in display_df.columns]
            display_df = display_df.drop(columns=cols_to_drop)
        
        event = st.dataframe(
            display_df,
            width="stretch",
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
    
    # --- Rubric Section ---
    _render_rubric_section(course, data)
    
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
        submission_files = _parse_submission_files(row.get('Submission_Files'))
        
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
        _render_file_submission(course, row, idx)
    else:
        _render_link_submission(row, sub_type)
    
    with st.expander("Submission Content", expanded=True):
        st.text(row.get('Submission', ''))


def _render_file_submission(course, row, idx):
    """Render file submission view"""
    submission_files = _parse_submission_files(row.get('Submission_Files'))
    
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


def _render_link_submission(row, sub_type):
    """Render link/text submission view"""
    if sub_type == 'link' or (sub_type == 'empty' and row.get('Eval_Last_Checked')):
        # Show analysis if it's a link OR if we have checked it
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


def _render_rubric_section(course, data):
    """Render the scoring rubric section"""
    st.markdown("### 📊 Scoring Rubric")
    
    # Get task description from session state (from Submissions tab)
    task_description = ""
    if st.session_state.tasks_data and data:
        module_id = data[0].get('Module ID')
        for task in st.session_state.tasks_data:
            if str(task.get('Module ID')) == str(module_id):
                task_description = task.get('description', '')
                break
    
    if not task_description:
        st.info("ℹ️ No task description available. Fetch tasks in Submissions tab first.")
        return
    
    module_id = data[0].get('Module ID') if data else None
    if not module_id:
        return
    
    # Check for batch-specific customization
    selected_group_id = None
    if st.session_state.selected_group:
        selected_group_id = st.session_state.selected_group['id']
    
    # Session state keys for rubric
    rubric_key = f"rubric_{module_id}"
    if selected_group_id:
        rubric_key += f"_grp{selected_group_id}"
    
    customize_batch_key = f"customize_batch_{module_id}"
    
    with st.expander("📋 View/Edit Rubric", expanded=False):
        # Check if API key is configured
        api_key = get_config("gemini_api_key")
        if not api_key:
            st.warning("⚠️ Gemini API key not configured. Go to Config page to add it.")
            return
        
        # Load existing rubric if not in session
        if rubric_key not in st.session_state:
            existing = load_rubric(
                course['id'], 
                module_id, 
                selected_group_id if st.session_state.get(customize_batch_key) else None
            )
            if existing and 'criteria' in existing:
                st.session_state[rubric_key] = existing['criteria']
            else:
                st.session_state[rubric_key] = None
        
        rubric_data = st.session_state[rubric_key]
        
        # Batch customization toggle
        if selected_group_id:
            customize = st.checkbox(
                f"🎯 Customize rubric for {st.session_state.selected_group['name']}", 
                key=customize_batch_key,
                help="Create a separate rubric for this batch/group"
            )
        else:
            customize = False
        
        # Generate button
        col1, col2 = st.columns([1, 3])
        with col1:
            generate_btn = st.button(
                "✨ Generate Rubric" if not rubric_data else "🔄 Regenerate",
                use_container_width=True
            )
        
        if generate_btn:
            with st.spinner("Generating rubric with AI..."):
                result = generate_rubric(task_description)
                if result:
                    st.session_state[rubric_key] = result
                    st.success("✓ Rubric generated!")
                    st.rerun()
                else:
                    st.error("Failed to generate rubric. Check API key and try again.")
        
        # Display and edit rubric
        if rubric_data:
            # Create editable dataframe
            df = pd.DataFrame(rubric_data)
            
            edited_df = st.data_editor(
                df,
                column_config={
                    "criterion": st.column_config.TextColumn(
                        "Criterion",
                        help="Short name for this scoring aspect",
                        width="medium"
                    ),
                    "description": st.column_config.TextColumn(
                        "Description", 
                        help="What to evaluate",
                        width="large"
                    ),
                    "weight_percent": st.column_config.NumberColumn(
                        "Weight %",
                        help="Percentage weight (should sum to 100)",
                        min_value=0,
                        max_value=100,
                        step=5,
                        width="small"
                    )
                },
                num_rows="dynamic",
                width="stretch",
                key=f"rubric_editor_{module_id}"
            )
            
            # Show total weight
            total_weight = edited_df['weight_percent'].sum() if not edited_df.empty else 0
            if total_weight == 100:
                st.success(f"✓ Total: {total_weight}%")
            else:
                st.warning(f"⚠️ Total: {total_weight}% (should be 100%)")
            
            # Save, Refine, and Clear buttons
            col_s1, col_s2, col_s3 = st.columns([1, 1, 1])
            with col_s1:
                if st.button("💾 Save Rubric", use_container_width=True):
                    # Convert back to list of dicts
                    new_rubric = edited_df.to_dict('records')
                    st.session_state[rubric_key] = new_rubric
                    
                    # Save to disk
                    success = save_rubric(
                        course['id'],
                        module_id,
                        new_rubric,
                        selected_group_id if customize else None
                    )
                    if success:
                        st.success("✓ Rubric saved!")
                    else:
                        st.error("Failed to save rubric")
            
            with col_s2:
                refine_btn = st.button("✏️ Refine with AI", use_container_width=True)
            
            with col_s3:
                if st.button("🗑️ Clear", use_container_width=True):
                    st.session_state[rubric_key] = None
                    st.rerun()
            
            # Refine dialog
            if refine_btn:
                _show_refine_dialog(rubric_key, edited_df.to_dict('records'), task_description, module_id)
        
        # Show task description for reference
        with st.expander("📝 Task Description (Reference)", expanded=False):
            st.markdown(task_description)


@st.dialog("✏️ Refine Rubric with AI")
def _show_refine_dialog(rubric_key, current_rubric, task_description, module_id):
    """Show dialog for refining rubric with AI instructions"""
    
    st.markdown("**Current Rubric:**")
    # Show current rubric as a compact table
    if current_rubric:
        summary = "\n".join([
            f"• **{item['criterion']}** ({item['weight_percent']}%): {item['description'][:50]}..."
            if len(item['description']) > 50 else f"• **{item['criterion']}** ({item['weight_percent']}%): {item['description']}"
            for item in current_rubric
        ])
        st.markdown(summary)
    
    st.divider()
    
    st.markdown("**Your Instructions:**")
    instructions = st.text_area(
        "Tell the AI how to modify the rubric",
        placeholder="Examples:\n• Add a criterion for code documentation\n• Increase weight for functionality to 50%\n• Split 'Code Quality' into 'Readability' and 'Best Practices'\n• Remove the repository criterion",
        height=150,
        key=f"refine_instructions_{module_id}"
    )
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Apply Changes", type="primary", use_container_width=True, disabled=not instructions):
            with st.spinner("AI is refining the rubric..."):
                result = refine_rubric(current_rubric, instructions, task_description)
                if result:
                    st.session_state[rubric_key] = result
                    st.success("✓ Rubric refined!")
                    st.rerun()
                else:
                    st.error("Failed to refine rubric. Please try again.")
    
    with col2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()
