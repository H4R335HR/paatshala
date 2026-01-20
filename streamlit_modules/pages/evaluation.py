"""
Evaluation tab for Streamlit app.
Handles submission evaluation and detailed analysis.
"""

import logging
import time
from pathlib import Path
import pandas as pd
import streamlit as st
import ast

from core.api import evaluate_submission, download_file, get_assignment_dates, submit_grade, get_fresh_sesskey
from core.auth import setup_session
from core.persistence import save_csv_to_disk, get_config
from core.ai import generate_rubric, save_rubric, load_rubric, refine_rubric, fetch_submission_content, score_submission, save_evaluation, load_evaluation, refine_evaluation
from streamlit_modules.ui.components import format_timestamp
from streamlit_modules.ui.content_viewer import (
    render_docx_viewer, render_pdf_viewer, render_pdf_content, render_html_viewer,
    IMAGE_EXTENSIONS, LANGUAGE_MAP, HTML_EXTENSIONS, render_code_content, render_image_content,
    detect_file_type
)

logger = logging.getLogger(__name__)


@st.cache_data
def get_display_dataframe(data):
    """Create a display-friendly dataframe for the Evaluation tab"""
    display_data = []
    for r in data:
        display_data.append({
            "Name": r.get('Name'),
            "Status": r.get('Status'),
            "Submitted": format_timestamp(r.get('Last Modified', '')),
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
        if st.button("🚀 Evaluate Pending", width="stretch", disabled=(evaluated == total)):
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
    
    # Get module_id and group_id for loading AI scores
    module_id = data[0].get('Module ID') if data else None
    selected_group_id = st.session_state.selected_group['id'] if st.session_state.selected_group else None
    
    with table_placeholder:
        display_df = pd.DataFrame(get_display_dataframe(data))
        
        # Add AI Score column by loading saved evaluations
        if module_id:
            ai_scores = []
            for row in data:
                student_name = row.get('Name', 'Unknown')
                existing_eval = load_evaluation(course['id'], module_id, student_name, selected_group_id)
                if existing_eval and existing_eval.get('total_score') is not None:
                    ai_scores.append(f"{existing_eval['total_score']}%")
                else:
                    ai_scores.append("-")
            display_df.insert(2, "AI Score", ai_scores)  # Insert after Status column
        
        if assignment_type == 'file':
            # Remove columns from display DF
            cols_to_drop = [c for c in ["Link", "Valid?", "Repo Status", "Fork?"] if c in display_df.columns]
            display_df = display_df.drop(columns=cols_to_drop)
        
        # Add column config for AI Score
        cols_config["AI Score"] = st.column_config.TextColumn("AI Score", width="small")
        
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
    
    # Fetch deadline if not already loaded
    deadline_str = ""
    on_time_str = ""
    dates_info = None
    is_on_time = None  # Track for AI scoring
    
    # Get module_id from the row data (available from submission CSV)
    module_id = row.get('Module ID') if row else None
    
    if module_id:
        dates_key = f"dates_info_{module_id}"
        
        # Check if already cached in session state
        if dates_key in st.session_state and st.session_state[dates_key]:
            dates_info = st.session_state[dates_key]
        else:
            # Lazy load once
            try:
                session = setup_session(st.session_state.session_id)
                dates_info = get_assignment_dates(session, module_id)
                if dates_info:
                    st.session_state[dates_key] = dates_info
            except Exception as e:
                logger.debug(f"Could not fetch deadline: {e}")
        
        if dates_info and dates_info.get('due_date_enabled') and dates_info.get('due_date'):
            due_date = dates_info['due_date']
            deadline_str = f" | **Deadline:** {due_date.strftime('%A, %d %B %Y, %I:%M %p')}"
            
            # Check if submitted on time using shared utility
            last_modified = row.get('Last Modified', '')
            if last_modified:
                from core.api import check_submission_timeliness
                timeliness = check_submission_timeliness(last_modified, due_date)
                is_on_time = timeliness.get('is_on_time')
                if is_on_time is True:
                    on_time_str = " | ✅ **On Time**"
                elif is_on_time is False:
                    on_time_str = " | ❌ **Late**"
        elif dates_info:
            deadline_str = " | **Deadline:** Not set"
        
    col1, col2 = st.columns([3, 1])
    with col1:
        submitted_time = format_timestamp(row.get('Last Modified', ''))
        st.markdown(f"**Name:** {row.get('Name')} | **Email:** {row.get('Email')} | **Submitted:** {submitted_time}{deadline_str}{on_time_str}")
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
        # Preview is now integrated into _render_file_submission (file explorer pattern)
    else:
        _render_link_submission(row, sub_type)
    
    # =========================================================================
    # AI SCORING SECTION
    # =========================================================================
    _render_ai_scoring_section(course, row, idx, data)


def _render_file_submission(course, row, idx):
    """Render file submission with file explorer + preview pattern"""
    import hashlib
    import base64
    from datetime import datetime
    
    submission_files = _parse_submission_files(row.get('Submission_Files'))
    
    if not submission_files:
        st.warning("⚠️ No file submitted")
        return
    
    # Build file list data
    safe_student = "".join([c for c in row.get('Name', 'Unknown') if c.isalnum() or c in (' ', '-', '_')]).strip()
    
    file_list = []
    file_paths = {}  # Map index to path for preview
    
    for i, (fname, furl) in enumerate(submission_files):
        safe_filename = "".join([c for c in fname if c.isalnum() or c in (' ', '-', '_', '.')]).strip()
        local_path = Path(f"output/course_{course['id']}/downloads/{safe_student}/{safe_filename}")
        
        file_info = {
            "📄 Name": fname,
            "Type": Path(fname).suffix.upper().replace(".", "") or "Unknown",
            "Size": "—",
            "Modified": "—",
            "MD5": "—",
            "Status": "❌ Not fetched"
        }
        
        if local_path.exists():
            stat = local_path.stat()
            file_info["Size"] = f"{stat.st_size / 1024:.1f} KB"
            file_info["Modified"] = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            
            # Compute MD5 (cached approach for performance)
            md5_key = f"md5_{hash(str(local_path))}"
            if md5_key not in st.session_state:
                with open(local_path, "rb") as f:
                    st.session_state[md5_key] = hashlib.md5(f.read()).hexdigest()[:12]
            file_info["MD5"] = st.session_state[md5_key]
            file_info["Status"] = "✅ Ready"
            file_paths[i] = str(local_path)
        else:
            file_paths[i] = None
        
        file_list.append(file_info)
    
    # === SECTION 1: File List Table ===
    st.markdown("#### 📂 Submitted Files")
    
    import pandas as pd
    df = pd.DataFrame(file_list)
    
    # Display with selection
    event = st.dataframe(
        df,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"file_explorer_{idx}",
        width="stretch"
    )
    
    # Track selected file in session state for navigation
    selected_key = f"file_sel_{idx}"
    nav_flag_key = f"file_nav_pending_{idx}"
    
    # Get selected file index from dataframe or session state
    selected_file_idx = None
    
    # Check if a navigation just happened (skip table selection in that case)
    if st.session_state.get(nav_flag_key):
        del st.session_state[nav_flag_key]
        selected_file_idx = st.session_state.get(selected_key)
    elif event and event.selection and len(event.selection.rows) > 0:
        # User clicked on table - update session state
        selected_file_idx = event.selection.rows[0]
        st.session_state[selected_key] = selected_file_idx
    elif selected_key in st.session_state:
        # Use existing session state
        selected_file_idx = st.session_state[selected_key]
    
    # Ensure index is valid
    num_files = len(submission_files)
    if selected_file_idx is not None and selected_file_idx >= num_files:
        selected_file_idx = num_files - 1
        st.session_state[selected_key] = selected_file_idx
    
    # === Navigation buttons ===
    if num_files > 1 and selected_file_idx is not None:
        nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])
        
        with nav_col1:
            prev_disabled = selected_file_idx == 0
            if st.button("◀ Previous", key=f"prev_file_{idx}", disabled=prev_disabled, use_container_width=True):
                new_idx = selected_file_idx - 1
                st.session_state[selected_key] = new_idx
                st.session_state[nav_flag_key] = True
                
                # Check if file needs fetching
                prev_fname, prev_furl = submission_files[new_idx]
                prev_path = file_paths.get(new_idx)
                if not prev_path or not Path(prev_path).exists():
                    # Auto-fetch the file
                    with st.spinner(f"Fetching {prev_fname}..."):
                        session = setup_session(st.session_state.session_id)
                        saved_path = download_file(session, prev_furl, course['id'], row.get('Name', 'Unknown'), prev_fname)
                        if saved_path:
                            file_paths[new_idx] = saved_path
                
                st.rerun()
        
        with nav_col2:
            st.markdown(f"<p style='text-align:center; margin:0.5rem 0;'>📄 <b>Preview ({selected_file_idx + 1}/{num_files})</b></p>", unsafe_allow_html=True)
        
        with nav_col3:
            next_disabled = selected_file_idx == num_files - 1
            if st.button("Next ▶", key=f"next_file_{idx}", disabled=next_disabled, use_container_width=True):
                new_idx = selected_file_idx + 1
                st.session_state[selected_key] = new_idx
                st.session_state[nav_flag_key] = True
                
                # Check if file needs fetching
                next_fname, next_furl = submission_files[new_idx]
                next_path = file_paths.get(new_idx)
                if not next_path or not Path(next_path).exists():
                    # Auto-fetch the file
                    with st.spinner(f"Fetching {next_fname}..."):
                        session = setup_session(st.session_state.session_id)
                        saved_path = download_file(session, next_furl, course['id'], row.get('Name', 'Unknown'), next_fname)
                        if saved_path:
                            file_paths[new_idx] = saved_path
                
                st.rerun()
    
    # === SECTION 2: Actions & Preview ===
    if selected_file_idx is not None:
        fname = submission_files[selected_file_idx][0]
        furl = submission_files[selected_file_idx][1]
        local_path = file_paths.get(selected_file_idx)
        
        st.divider()
        
        # Action buttons
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.markdown(f"**Selected:** {fname}")
        
        if local_path and Path(local_path).exists():
            path = Path(local_path)
            
            with col2:
                # View in browser button for PDFs
                if fname.lower().endswith('.pdf'):
                    with open(path, "rb") as f:
                        pdf_data = f.read()
                    b64_pdf = base64.b64encode(pdf_data).decode('utf-8')
                    view_html = f'''
                        <button onclick="openPdf()" style="width: 100%; padding: 0.4rem; 
                               background-color: #262730; color: white;
                               border-radius: 0.5rem; cursor: pointer;
                               border: 1px solid #444;">👁️ Open in Browser</button>
                        <script>
                            function openPdf() {{
                                const binary = atob("{b64_pdf}");
                                const bytes = new Uint8Array(binary.length);
                                for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
                                window.open(URL.createObjectURL(new Blob([bytes], {{type:'application/pdf'}})), '_blank');
                            }}
                        </script>
                    '''
                    st.components.v1.html(view_html, height=40)
            
            with col3:
                with open(path, "rb") as f:
                    st.download_button(
                        label="📥 Download",
                        data=f,
                        file_name=fname,
                        mime="application/octet-stream",
                        key=f"dl_preview_{idx}_{selected_file_idx}",
                        width="stretch"
                    )
            
            # === Preview Pane ===
            st.markdown("#### 👁️ Preview")
            ext = path.suffix.lower()
            
            if ext == '.pdf':
                # Use the unified PDF content viewer with all view modes
                render_pdf_content(path, fname, unique_key=f"eval_{idx}_{selected_file_idx}")
            
            elif ext in IMAGE_EXTENSIONS:
                render_image_content(str(path), caption=fname)
            
            elif ext in ['.docx', '.doc']:
                # Use shared DOCX viewer from content_viewer
                with open(path, "rb") as f:
                    docx_bytes = f.read()
                render_docx_viewer(docx_bytes, fname, unique_key=f"eval_{idx}")
            
            elif ext in HTML_EXTENSIONS:
                # HTML file - render with HTML viewer
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        html_content = f.read()
                    render_html_viewer(html_content, fname, unique_key=f"eval_{idx}_{selected_file_idx}")
                except:
                    st.warning("Could not read HTML file content")
            
            elif ext in LANGUAGE_MAP or ext in ['.txt', '.log', '.csv']:
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    render_code_content(content, fname)
                except:
                    st.warning("Could not read file content")
            
            elif ext in ['.zip', '.7z', '.rar', '.tar', '.gz', '.tar.gz']:
                # ZIP file contents listing
                import zipfile
                
                st.markdown("#### 📦 Archive Contents")
                
                if ext == '.zip':
                    try:
                        with zipfile.ZipFile(path, 'r') as zf:
                            # Check if password protected
                            is_encrypted = any(info.flag_bits & 0x1 for info in zf.infolist())
                            
                            if is_encrypted:
                                st.info("🔐 Password-protected archive")
                                # Try known password
                                known_password = "ictkerala.org"
                                try:
                                    zf.setpassword(known_password.encode())
                                    # Test if password works by reading first file
                                    test_info = zf.infolist()[0] if zf.infolist() else None
                                    if test_info and test_info.file_size > 0:
                                        zf.read(test_info.filename, pwd=known_password.encode())
                                    st.success(f"✅ Unlocked with known password")
                                except Exception:
                                    st.warning("⚠️ Could not unlock - password may be different")
                            
                            # List contents
                            file_list = []
                            total_size = 0
                            for info in zf.infolist():
                                if not info.is_dir():
                                    size = info.file_size
                                    total_size += size
                                    file_list.append({
                                        "📄 Name": info.filename,
                                        "Size": f"{size / 1024:.1f} KB" if size > 0 else "—",
                                        "Compressed": f"{info.compress_size / 1024:.1f} KB" if info.compress_size > 0 else "—"
                                    })
                            
                            if file_list:
                                import pandas as pd
                                df = pd.DataFrame(file_list)
                                st.dataframe(df, hide_index=True, width="stretch")
                                st.caption(f"📊 {len(file_list)} file(s) • Total: {total_size / 1024:.1f} KB")
                            else:
                                st.info("📭 Empty archive")
                    except zipfile.BadZipFile:
                        st.error("❌ Invalid or corrupted ZIP file")
                    except Exception as e:
                        st.error(f"❌ Error reading archive: {e}")
                else:
                    st.info(f"📦 {ext.upper()} archive - extraction not supported, use Download button")
            
            else:
                # Unknown extension - try magic byte detection
                with open(path, 'rb') as f:
                    file_bytes = f.read()
                
                detected_type = detect_file_type(file_bytes)
                
                if detected_type == '.pdf':
                    render_pdf_content(file_bytes, fname, unique_key=f"eval_magic_{idx}_{selected_file_idx}")
                elif detected_type in IMAGE_EXTENSIONS:
                    render_image_content(file_bytes, caption=fname)
                elif detected_type in ['.docx', '.doc']:
                    render_docx_viewer(file_bytes, fname, unique_key=f"eval_magic_{idx}_{selected_file_idx}")
                elif detected_type == '.txt':
                    # Detected as text
                    text_content = file_bytes.decode('utf-8', errors='ignore')
                    render_code_content(text_content, fname)
                else:
                    st.info(f"📦 Binary file ({ext}) - use Download button to view")
        
        else:
            # File not fetched yet
            with col2:
                if st.button("⬇️ Fetch File", key=f"fetch_preview_{idx}_{selected_file_idx}", width="stretch"):
                    with st.spinner("Fetching from server..."):
                        session = setup_session(st.session_state.session_id)
                        saved_path = download_file(session, furl, course['id'], row.get('Name', 'Unknown'), fname)
                        if saved_path:
                            st.success("Fetched!")
                            st.rerun()
                        else:
                            st.error("Failed to fetch")
            
            st.info("👆 Click 'Fetch File' to download and preview this file")
    else:
        st.caption("👆 Click a row above to select a file for preview")


def _render_link_submission(row, sub_type):
    """Render link/text submission view"""
    if sub_type == 'link' or (sub_type == 'empty' and row.get('Eval_Last_Checked')):
        # Show analysis if it's a link OR if we have checked it
        link = row.get('Eval_Link', '')
        
        if row.get('Eval_Last_Checked'):
            # Show validation status
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
            
            # For GitHub URLs, show interactive browser
            if link and 'github.com' in link:
                from streamlit_modules.ui.content_viewer import render_github_viewer
                render_github_viewer(link, get_config('github_pat'))
            else:
                st.markdown(f"**Submission Link:** [{link}]({link})")
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
                width="stretch"
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
                if st.button("💾 Save Rubric", width="stretch"):
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
                refine_btn = st.button("✏️ Refine with AI", width="stretch")
            
            with col_s3:
                if st.button("🗑️ Clear", width="stretch"):
                    st.session_state[rubric_key] = None
                    st.rerun()
            
            # Refine dialog
            if refine_btn:
                _show_refine_dialog(rubric_key, edited_df.to_dict('records'), task_description, module_id)
            
            # Batch Score button
            st.divider()
            col_batch1, col_batch2, col_batch3 = st.columns(3)
            with col_batch1:
                do_batch_score = st.button("🎯 Batch Score with AI", width="stretch", help="Score all pending submissions with AI using this rubric")
            with col_batch2:
                do_batch_submit = st.button("📤 Batch Submit to Moodle", width="stretch", help="Submit all AI-scored evaluations to Moodle")
            with col_batch3:
                do_clear_scores = st.button("🗑️ Clear AI Scores", width="stretch", help="Delete all saved AI scores for this assignment")
            
            # Execute batch operations OUTSIDE column blocks for full-width progress bars
            if do_batch_score:
                _perform_batch_scoring(course, data, edited_df.to_dict('records'), module_id, selected_group_id)
            if do_batch_submit:
                _perform_batch_submit_to_moodle(course, data, module_id, selected_group_id)
            if do_clear_scores:
                _clear_ai_scores(course, data, module_id, selected_group_id)
        
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
        if st.button("🔄 Apply Changes", type="primary", width="stretch", disabled=not instructions):
            with st.spinner("AI is refining the rubric..."):
                result = refine_rubric(current_rubric, instructions, task_description)
                if result:
                    st.session_state[rubric_key] = result
                    st.success("✓ Rubric refined!")
                    st.rerun()
                else:
                    st.error("Failed to refine rubric. Please try again.")
    
    with col2:
        if st.button("Cancel", width="stretch"):
            st.rerun()


def _render_ai_scoring_section(course, row, idx, data):
    """Render the AI scoring section for an individual submission."""
    st.divider()
    st.markdown("### 🤖 AI Scoring")
    
    # Get module info
    module_id = row.get('Module ID')
    if not module_id:
        st.warning("Cannot score: Module ID not available")
        return
    
    # Check for rubric
    selected_group_id = None
    if st.session_state.selected_group:
        selected_group_id = st.session_state.selected_group['id']
    
    rubric_key = f"rubric_{module_id}"
    if selected_group_id:
        rubric_key += f"_grp{selected_group_id}"
    
    # Load rubric if not in session
    if rubric_key not in st.session_state or st.session_state[rubric_key] is None:
        existing = load_rubric(course['id'], module_id, selected_group_id)
        if existing and 'criteria' in existing:
            st.session_state[rubric_key] = existing['criteria']
        else:
            st.session_state[rubric_key] = None
    
    rubric = st.session_state.get(rubric_key)
    
    if not rubric:
        st.info("⚠️ No rubric found for this task. Generate one in the 'Scoring Rubric' section above first.")
        return
    
    # Check for existing evaluation
    student_name = row.get('Name', 'Unknown')
    existing_eval = load_evaluation(course['id'], module_id, student_name, selected_group_id)
    
    # Get max grade for this task (needed for display and restore)
    max_grade = None
    max_grade_source = None
    
    # HIGHEST PRIORITY: Check session state (populated when submissions are fetched from grading page)
    # This is the most reliable source as it comes directly from the grading table header/input
    session_state_key = f"max_grade_{module_id}"
    if session_state_key in st.session_state and st.session_state[session_state_key]:
        max_grade = st.session_state[session_state_key]
        max_grade_source = 'grading_page'
    
    # Second: try to get from tasks_data (from assignment view page)
    if max_grade is None and st.session_state.tasks_data:
        for task in st.session_state.tasks_data:
            if str(task.get('Module ID')) == str(module_id):
                max_grade_str = task.get('Max Grade', '')
                if max_grade_str:
                    try:
                        max_grade = float(max_grade_str.replace('/100.00', '').strip())
                        max_grade_source = 'tasks_data'
                    except:
                        pass
                break
    
    # Fallback: Try to extract max from ANY student's Final Grade (format: "12.5 / 15.00")
    if max_grade is None:
        for student_row in data:
            grade_str = student_row.get('Final Grade', '')
            if grade_str:
                _, student_max = _parse_moodle_grade(grade_str)
                if student_max:
                    max_grade = student_max
                    max_grade_source = 'submission_data'
                    break
    
    # Final fallback with warning
    if max_grade is None:
        max_grade = 15
        max_grade_source = 'default'
        logger.warning(f"Using default max_grade=15 for module {module_id}. Fetch submissions first to auto-detect max grade.")
    
    # Get Moodle grade and feedback from row data
    moodle_grade = row.get('Final Grade', '')
    moodle_feedback = row.get('Feedback Comments', '')
    
    # Check for pending rescore result
    pending_key = f"pending_rescore_{module_id}_{student_name}"
    pending_rescore = st.session_state.get(pending_key)
    
    # Display existing evaluation if present
    if existing_eval and existing_eval.get('total_score') is not None:
        # If there's a pending rescore, show comparison
        if pending_rescore:
            old_score = existing_eval.get('total_score', 0)
            new_score = pending_rescore.get('total_score', 0)
            
            st.warning(f"### 🔄 New Score: **{new_score}/100** (was {old_score}/100)")
            
            # Show new breakdown
            with st.expander("📊 New Score Breakdown", expanded=True):
                new_criteria = pending_rescore.get('criteria_scores', [])
                if new_criteria:
                    breakdown_data = []
                    for cs in new_criteria:
                        breakdown_data.append({
                            "Criterion": cs.get('criterion', ''),
                            "Score": f"{cs.get('score', 0)}/{cs.get('max_score', 0)}",
                            "Feedback": cs.get('comment', '')
                        })
                    st.dataframe(breakdown_data, width="stretch", hide_index=True)
                
                new_comments = pending_rescore.get('comments', '')
                if new_comments:
                    st.markdown("**Overall Feedback:**")
                    st.info(new_comments)
            
            # Accept/Reject buttons
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Accept New Score", key=f"accept_rescore_{idx}", type="primary"):
                    save_evaluation(course['id'], module_id, student_name, pending_rescore, selected_group_id)
                    del st.session_state[pending_key]
                    st.success("✓ New score saved!")
                    st.rerun()
            with col2:
                if st.button("❌ Reject", key=f"reject_rescore_{idx}"):
                    del st.session_state[pending_key]
                    st.info("Score unchanged")
                    st.rerun()
            return  # Don't show rest of UI while pending
        
        _display_evaluation_results(existing_eval, rubric, moodle_grade, max_grade)
        
        # Show conversation history if exists
        conversation = existing_eval.get('conversation', [])
        if conversation:
            with st.expander("💬 Previous Discussion", expanded=False):
                for msg in conversation:
                    if msg['role'] == 'teacher':
                        st.markdown(f"**You:** {msg['content']}")
                    else:
                        st.markdown(f"**AI:** {msg['content']}")
        
        # Action buttons: Restore, Clear, Discuss, Re-Score, and Submit to Moodle
        col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1])
        moodle_score, moodle_max = _parse_moodle_grade(moodle_grade)
        
        with col1:
            restore_btn = st.button(
                "📥 Restore from Moodle", 
                key=f"restore_{idx}",
                disabled=(moodle_score is None),
                help="Load the existing grade and feedback from Moodle"
            )
        with col2:
            clear_btn = st.button("🗑️ Clear Score", key=f"clear_score_{idx}", help="Delete the AI score for this student")
        with col3:
            discuss = st.button("💬 Discuss", key=f"discuss_{idx}")
        with col4:
            rescore = st.button("🔄 Re-Score", key=f"rescore_{idx}")
        with col5:
            submit_btn = st.button("📤 Submit to Moodle", key=f"submit_moodle_{idx}", type="primary")
        
        if rescore:
            _perform_scoring(course, row, rubric, module_id, selected_group_id, data, is_rescore=True)
        
        if clear_btn:
            from core.ai import delete_evaluation
            if delete_evaluation(course['id'], module_id, student_name, selected_group_id):
                st.success(f"✓ Cleared AI score for {student_name}")
                st.rerun()
            else:
                st.warning("No AI score to clear")
        
        if restore_btn and moodle_score is not None:
            # Convert Moodle grade to percentage
            effective_max = moodle_max if moodle_max else max_grade
            percentage_score = (moodle_score / effective_max) * 100
            
            # Create evaluation dict from Moodle data
            from datetime import datetime
            restored_eval = {
                'total_score': round(percentage_score, 1),
                'criteria_scores': [],  # No per-criterion breakdown from Moodle
                'comments': moodle_feedback if moodle_feedback else "Restored from Moodle - no detailed feedback available.",
                'evaluated_at': datetime.now().isoformat(),
                'source': 'moodle_restore'
            }
            
            # Save to local cache
            save_evaluation(course['id'], module_id, student_name, restored_eval, selected_group_id)
            st.success(f"✓ Restored from Moodle: {moodle_score}/{effective_max:.0f} → {percentage_score:.1f}/100")
            st.rerun()
        
        if discuss:
            _show_discuss_dialog(course, row, existing_eval, rubric, module_id, selected_group_id, idx)
        
        if submit_btn:
            with st.spinner("Submitting to Moodle..."):
                _submit_to_moodle(course, row, existing_eval, max_grade, max_grade_source)
    else:
        # No AI evaluation yet - show Moodle status if available
        moodle_score, moodle_max = _parse_moodle_grade(moodle_grade)
        
        if moodle_score is not None:
            moodle_display = f"{moodle_score:.2f}"
            if moodle_max:
                moodle_display += f" / {moodle_max:.0f}"
            st.info(f"📋 **Moodle Grade:** {moodle_display} (No AI score yet)")
        else:
            st.caption("No AI score or Moodle grade yet")
        
        # Get task description
        task_description = _get_task_description(module_id)
        
        if not task_description:
            st.warning("⚠️ Task description not available. Fetch tasks in Submissions tab first.")
        
        # Score buttons
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            if st.button("🎯 Score with AI", key=f"score_{idx}", type="primary"):
                _perform_scoring(course, row, rubric, module_id, selected_group_id, data)
        
        with col2:
            if moodle_score is not None:
                restore_btn = st.button(
                    "📥 Restore from Moodle", 
                    key=f"restore_new_{idx}",
                    help="Load the existing grade and feedback from Moodle"
                )
                if restore_btn:
                    # Convert Moodle grade to percentage
                    effective_max = moodle_max if moodle_max else max_grade
                    percentage_score = (moodle_score / effective_max) * 100
                    
                    # Create evaluation dict from Moodle data
                    from datetime import datetime
                    restored_eval = {
                        'total_score': round(percentage_score, 1),
                        'criteria_scores': [],
                        'comments': moodle_feedback if moodle_feedback else "Restored from Moodle - no detailed feedback available.",
                        'evaluated_at': datetime.now().isoformat(),
                        'source': 'moodle_restore'
                    }
                    
                    save_evaluation(course['id'], module_id, student_name, restored_eval, selected_group_id)
                    st.success(f"✓ Restored from Moodle: {moodle_score}/{effective_max:.0f} → {percentage_score:.1f}/100")
                    st.rerun()
            else:
                st.caption(f"Using {len(rubric)} criteria")


def _perform_batch_scoring(course, data, rubric, module_id, group_id):
    """Perform AI scoring on all pending submissions sequentially.
    
    Args:
        course: Course dict with 'id'
        data: List of submission rows
        rubric: List of rubric criteria dicts
        module_id: Module ID for the assignment
        group_id: Optional group ID for batch-specific rubrics
    """
    # Get task description for scoring context
    task_description = _get_task_description(module_id)
    
    if not task_description:
        st.warning("⚠️ Task description not available. Fetch tasks in Submissions tab first.")
        return
    
    # Filter to students without AI evaluation AND who have actually submitted something
    pending = []
    skipped_no_submission = 0
    for i, row in enumerate(data):
        student_name = row.get('Name', 'Unknown')
        
        # Skip students who haven't submitted anything
        submission_type = row.get('Submission_Type', '')
        submission_content = row.get('Submission', '')
        submission_files = row.get('Submission_Files', [])
        
        # Check if there's no actual submission
        has_no_submission = (
            submission_type == 'empty' or 
            (not submission_content.strip() and not submission_files)
        )
        
        if has_no_submission:
            skipped_no_submission += 1
            continue
        
        existing_eval = load_evaluation(course['id'], module_id, student_name, group_id)
        if not existing_eval or existing_eval.get('total_score') is None:
            pending.append((i, row))
    
    if not pending:
        if skipped_no_submission > 0:
            st.info(f"✅ All submissions already have AI scores. ({skipped_no_submission} students with no submission were skipped)")
        else:
            st.info("✅ All submissions already have AI scores.")
        return
    
    # Show info about skipped entries at the start
    if skipped_no_submission > 0:
        st.caption(f"ℹ️ Skipping {skipped_no_submission} students with no submission")
    
    # Progress tracking (full-width since function is called outside column blocks)
    progress_bar = st.progress(0, text=f"Scoring 0/{len(pending)} submissions...")
    status_text = st.empty()
    results = {'scored': 0, 'failed': 0, 'skipped': 0}
    
    for idx, (i, row) in enumerate(pending):
        student_name = row.get('Name', 'Unknown')
        
        # Update progress
        progress_bar.progress((idx) / len(pending), 
                             text=f"Scoring {idx + 1}/{len(pending)}: {student_name}...")
        
        try:
            # Fetch submission content (same as individual scoring)
            submission_content = fetch_submission_content(row, course['id'])
            
            if submission_content.get('error'):
                status_text.caption(f"⚠️ {student_name}: {submission_content['error']}")
            
            # Add deadline info if available
            dates_key = f"dates_info_{module_id}"
            if dates_key in st.session_state and st.session_state[dates_key]:
                dates_info = st.session_state[dates_key]
                if dates_info.get('due_date_enabled') and dates_info.get('due_date'):
                    due_date = dates_info['due_date']
                    submission_content['deadline'] = due_date.strftime('%A, %d %B %Y, %I:%M %p')
                    
                    # Check if on time
                    last_modified = row.get('Last Modified', '')
                    if last_modified:
                        from datetime import datetime
                        try:
                            sub_time = datetime.strptime(last_modified, "%A, %d %B %Y, %I:%M %p")
                            submission_content['on_time'] = sub_time <= due_date
                        except ValueError:
                            pass
            
            # Score with AI - with retry logic for transient errors
            max_retries = 3
            retry_delay = 3  # Start with 3 seconds
            result = None
            
            for attempt in range(max_retries):
                result = score_submission(
                    submission_content,
                    rubric,
                    task_description,
                    student_name
                )
                
                # Check for transient errors that should be retried
                if result and result.get('error'):
                    error_msg = str(result.get('error', '')).lower()
                    is_transient = any(x in error_msg for x in ['503', 'overloaded', 'unavailable', '429', 'rate'])
                    
                    if is_transient and attempt < max_retries - 1:
                        status_text.caption(f"⏳ {student_name}: API busy, retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                
                break  # Success or non-transient error, exit retry loop
            
            if result and result.get('error'):
                status_text.caption(f"❌ {student_name}: {result['error']}")
                results['failed'] += 1
            elif result:
                # Save evaluation
                save_evaluation(course['id'], module_id, student_name, result, group_id)
                status_text.caption(f"✓ {student_name}: {result['total_score']}/100")
                results['scored'] += 1
            else:
                results['failed'] += 1
        
        except Exception as e:
            logger.error(f"Error scoring {student_name}: {e}")
            status_text.caption(f"❌ {student_name}: Error - {str(e)[:50]}")
            results['failed'] += 1
        
        # Small delay between API calls to avoid rate limiting
        if idx < len(pending) - 1:  # Don't delay after last item
            time.sleep(1.5)
    
    # Complete progress bar
    progress_bar.progress(1.0, text="Batch scoring complete!")
    
    # Show completion notification (toast)
    toast_msg = f"🎯 Batch scoring complete: {results['scored']} scored, {results['failed']} failed"
    if skipped_no_submission > 0:
        toast_msg += f", {skipped_no_submission} skipped (no submission)"
    st.toast(toast_msg, icon="✅")
    
    # Show summary
    skip_note = f" ({skipped_no_submission} students with no submission were skipped)" if skipped_no_submission > 0 else ""
    if results['failed'] == 0:
        st.success(f"✅ Batch scoring complete! Scored {results['scored']} submissions.{skip_note}")
    else:
        st.warning(f"⚠️ Batch scoring complete: {results['scored']} scored, {results['failed']} failed.{skip_note}")
    
    # Trigger rerun to refresh the UI with new scores
    st.rerun()


def _perform_batch_submit_to_moodle(course, data, module_id, group_id):
    """Submit all AI-scored evaluations to Moodle in batch.
    
    Args:
        course: Course dict with 'id'
        data: List of submission rows
        module_id: Module ID for the assignment
        group_id: Optional group ID for batch-specific evaluations
    """
    from core.api import submit_grade, get_fresh_sesskey, setup_session
    
    # Get max grade for this task
    max_grade = 15  # Default
    if st.session_state.tasks_data:
        for task in st.session_state.tasks_data:
            if str(task.get('Module ID')) == str(module_id):
                max_grade_str = task.get('Max Grade', '')
                if max_grade_str:
                    try:
                        max_grade = float(max_grade_str.replace('/100.00', '').strip())
                    except:
                        pass
                break
    
    # Get assignment ID
    assignment_id = st.session_state.get(f"assignment_id_{module_id}")
    if not assignment_id:
        st.error(f"❌ Assignment ID not available for module {module_id}. Please re-fetch submissions.")
        return
    
    # Get session and sesskey
    session = setup_session(st.session_state.session_id)
    sesskey = get_fresh_sesskey(session, course['id'])
    if not sesskey:
        st.error("❌ Could not get session key. Please try again.")
        return
    
    # Filter to students with AI evaluation that haven't been submitted yet
    pending = []
    for i, row in enumerate(data):
        student_name = row.get('Name', 'Unknown')
        existing_eval = load_evaluation(course['id'], module_id, student_name, group_id)
        
        if existing_eval and existing_eval.get('total_score') is not None:
            # Has AI score - check if already submitted to Moodle
            moodle_grade = row.get('Final Grade', '')
            ai_score = existing_eval.get('total_score', 0)
            scaled_ai = round((ai_score / 100) * max_grade)
            
            # Parse Moodle grade to compare
            moodle_score, _ = _parse_moodle_grade(moodle_grade)
            
            # Submit if Moodle grade is missing or different from AI score
            if moodle_score is None or abs(moodle_score - scaled_ai) >= 0.5:
                pending.append((i, row, existing_eval))
    
    if not pending:
        st.info("✅ All AI-scored evaluations are already submitted to Moodle.")
        return
    
    # Progress tracking
    progress_bar = st.progress(0, text=f"Submitting 0/{len(pending)} to Moodle...")
    status_text = st.empty()
    results = {'submitted': 0, 'failed': 0}
    
    for idx, (i, row, evaluation) in enumerate(pending):
        student_name = row.get('Name', 'Unknown')
        user_id = row.get('User_ID')
        
        # Update progress
        progress_bar.progress((idx) / len(pending), 
                             text=f"Submitting {idx + 1}/{len(pending)}: {student_name}...")
        
        if not user_id:
            status_text.caption(f"⚠️ {student_name}: No user ID")
            results['failed'] += 1
            continue
        
        try:
            # Calculate scaled grade
            total_score = evaluation.get('total_score', 0)
            scaled_grade = round((total_score / 100) * max_grade)
            
            # Format feedback as HTML
            feedback_html = _format_feedback_html(evaluation)
            
            # Submit grade
            result = submit_grade(
                session,
                assignment_id,
                user_id,
                module_id,
                scaled_grade,
                feedback_html,
                sesskey
            )
            
            if result['success']:
                status_text.caption(f"✓ {student_name}: {scaled_grade}/{int(max_grade)}")
                results['submitted'] += 1
            else:
                status_text.caption(f"❌ {student_name}: {result.get('error', 'Unknown error')[:50]}")
                results['failed'] += 1
        
        except Exception as e:
            logger.error(f"Error submitting {student_name}: {e}")
            status_text.caption(f"❌ {student_name}: Error - {str(e)[:50]}")
            results['failed'] += 1
        
        # Small delay between submissions
        if idx < len(pending) - 1:
            time.sleep(0.5)
    
    # Complete progress bar
    progress_bar.progress(1.0, text="Batch submission complete!")
    
    # Show completion notification (toast)
    st.toast(f"📤 Batch submission complete: {results['submitted']} submitted, {results['failed']} failed", icon="✅")
    
    # Show summary
    if results['failed'] == 0:
        st.success(f"✅ Batch submission complete! Submitted {results['submitted']} evaluations to Moodle.")
    else:
        st.warning(f"⚠️ Batch submission complete: {results['submitted']} submitted, {results['failed']} failed.")
    
    # Trigger rerun to refresh the UI
    st.rerun()


def _clear_ai_scores(course, data, module_id, group_id):
    """Clear all saved AI evaluations for the current module.
    
    Args:
        course: Course dict with 'id'
        data: List of submission rows
        module_id: Module ID for the assignment
        group_id: Optional group ID for batch-specific evaluations
    """
    from core.ai import delete_evaluation
    
    cleared_count = 0
    
    for row in data:
        student_name = row.get('Name', 'Unknown')
        # Check if evaluation exists before trying to delete
        existing_eval = load_evaluation(course['id'], module_id, student_name, group_id)
        if existing_eval and existing_eval.get('total_score') is not None:
            if delete_evaluation(course['id'], module_id, student_name, group_id):
                cleared_count += 1
    
    if cleared_count > 0:
        st.success(f"✅ Cleared {cleared_count} AI score(s).")
        st.toast(f"🗑️ Cleared {cleared_count} AI scores", icon="✅")
    else:
        st.info("ℹ️ No AI scores to clear.")
    
    st.rerun()

def _get_task_description(module_id):
    """Get task description from session state tasks data."""
    if not st.session_state.tasks_data:
        return ""
    
    for task in st.session_state.tasks_data:
        if str(task.get('Module ID')) == str(module_id):
            return task.get('description', '')
    
    return ""


def _perform_scoring(course, row, rubric, module_id, group_id, data, is_rescore=False):
    """Perform AI scoring on a submission.
    
    Args:
        is_rescore: If True, stores result as pending for Accept/Reject. If False, saves immediately.
    """
    with st.spinner("Fetching submission content..."):
        submission_content = fetch_submission_content(row, course['id'])
    
    if submission_content.get('error'):
        st.warning(f"⚠️ {submission_content['error']}")
    
    # Add deadline info to submission content for AI context
    dates_key = f"dates_info_{module_id}"
    if dates_key in st.session_state and st.session_state[dates_key]:
        dates_info = st.session_state[dates_key]
        if dates_info.get('due_date_enabled') and dates_info.get('due_date'):
            due_date = dates_info['due_date']
            submission_content['deadline'] = due_date.strftime('%A, %d %B %Y, %I:%M %p')
            
            # Check if on time
            last_modified = row.get('Last Modified', '')
            if last_modified:
                from datetime import datetime
                try:
                    sub_time = datetime.strptime(last_modified, "%A, %d %B %Y, %I:%M %p")
                    submission_content['on_time'] = sub_time <= due_date
                except ValueError:
                    pass
    
    with st.spinner("Scoring with AI..."):
        task_description = _get_task_description(module_id)
        result = score_submission(
            submission_content,
            rubric,
            task_description,
            row.get('Name', '')
        )
    
    if result and result.get('error'):
        st.error(f"❌ Scoring failed: {result['error']}")
        return
    
    if result:
        student_name = row.get('Name', 'Unknown')
        
        if is_rescore:
            # Store as pending - don't save yet, let user Accept/Reject
            pending_key = f"pending_rescore_{module_id}_{student_name}"
            st.session_state[pending_key] = result
            st.rerun()
        else:
            # First-time scoring - save immediately
            save_evaluation(course['id'], module_id, student_name, result, group_id)
            st.success(f"✓ Scored: **{result['total_score']}/100**")
            st.rerun()


def _parse_moodle_grade(grade_str):
    """Parse Moodle grade string like '12.75 / 15.00' into (score, max) tuple."""
    if not grade_str or grade_str == '-':
        return None, None
    
    import re
    match = re.search(r'(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)', str(grade_str))
    if match:
        return float(match.group(1)), float(match.group(2))
    
    # Try simple number
    try:
        return float(grade_str), None
    except:
        return None, None


def _display_evaluation_results(evaluation, rubric, moodle_grade=None, max_grade=15):
    """Display evaluation results with score breakdown and comments.
    
    Args:
        evaluation: AI evaluation dict with total_score, criteria_scores, comments
        rubric: The rubric used for evaluation
        moodle_grade: Moodle grade string from row.get('Final Grade'), e.g. '12.75 / 15.00'
        max_grade: Maximum grade for this assignment (for scaling comparison)
    """
    
    # Total score with visual indicator
    total_score = evaluation.get('total_score', 0)
    
    # Color based on score
    if total_score >= 80:
        score_emoji = "🎉"
    elif total_score >= 60:
        score_emoji = "👍"
    elif total_score >= 40:
        score_emoji = "⚠️"
    else:
        score_emoji = "❌"
    
    # Parse Moodle grade for comparison
    moodle_score, moodle_max = _parse_moodle_grade(moodle_grade)
    
    # Build header with Moodle comparison
    if moodle_score is not None:
        # Convert AI score to same scale as Moodle for comparison
        ai_scaled = (total_score / 100) * max_grade
        
        # Determine sync status
        if abs(ai_scaled - moodle_score) < 0.5:
            sync_indicator = "✅ Synced"
        else:
            sync_indicator = "⚠️ Different"
        
        moodle_display = f"{moodle_score:.2f}" if moodle_max else str(moodle_score)
        if moodle_max:
            moodle_display += f" / {moodle_max:.0f}"
        
        st.markdown(f"## {score_emoji} AI Score: **{total_score}/100** &nbsp;|&nbsp; Moodle: **{moodle_display}** {sync_indicator}")
    else:
        st.markdown(f"## {score_emoji} AI Score: **{total_score}/100** &nbsp;|&nbsp; ❌ Not in Moodle")
    
    # Criteria breakdown
    criteria_scores = evaluation.get('criteria_scores', [])
    if criteria_scores:
        st.markdown("#### Per-Criterion Breakdown")
        
        # Create a dataframe for display
        breakdown_data = []
        for cs in criteria_scores:
            breakdown_data.append({
                "Criterion": cs.get('criterion', ''),
                "Score": f"{cs.get('score', 0)}/{cs.get('max_score', 0)}",
                "Feedback": cs.get('comment', '')
            })
        
        st.dataframe(
            breakdown_data,
            width="stretch",
            hide_index=True,
            column_config={
                "Criterion": st.column_config.TextColumn("Criterion", width="medium"),
                "Score": st.column_config.TextColumn("Score", width="small"),
                "Feedback": st.column_config.TextColumn("Feedback", width="large"),
            }
        )
    
    # Overall comments
    comments = evaluation.get('comments', '')
    if comments:
        st.markdown("#### 💬 Overall Feedback")
        st.info(comments)
        
        # Copy button
        if st.button("📋 Copy Feedback", key="copy_feedback"):
            st.code(comments, language=None)
            st.caption("Select and copy the text above")
    
    # Metadata
    scored_at = evaluation.get('evaluated_at', '')
    if scored_at:
        st.caption(f"Scored: {format_timestamp(scored_at)}")


def _format_feedback_html(evaluation):
    """Format evaluation as HTML for Moodle feedback comments."""
    html_parts = []
    
    # Per-criterion breakdown as HTML table
    criteria_scores = evaluation.get('criteria_scores', [])
    if criteria_scores:
        html_parts.append("<p><strong>Per-Criterion Breakdown:</strong></p>")
        html_parts.append("<table border='1' cellpadding='5' cellspacing='0' style='border-collapse: collapse;'>")
        html_parts.append("<tr><th>Criterion</th><th>Score</th><th>Feedback</th></tr>")
        for cs in criteria_scores:
            criterion = cs.get('criterion', '')
            score = cs.get('score', 0)
            max_score = cs.get('max_score', 0)
            comment = cs.get('comment', '')
            html_parts.append(f"<tr><td>{criterion}</td><td>{score}/{max_score}</td><td>{comment}</td></tr>")
        html_parts.append("</table>")
        html_parts.append("<br>")
    
    # Overall comments
    comments = evaluation.get('comments', '')
    if comments:
        html_parts.append("<p><strong>Overall Feedback:</strong></p>")
        html_parts.append(f"<p>{comments}</p>")
    
    return "".join(html_parts)


def _submit_to_moodle(course, row, evaluation, max_grade, max_grade_source='unknown'):
    """Submit grade and feedback to Moodle."""
    import html
    
    # Warn user if using default max grade
    if max_grade_source == 'default':
        st.warning(f"⚠️ Using default max grade of {max_grade}. For accuracy, fetch tasks in Submissions tab first.")
    
    # Check required data
    module_id = row.get('Module ID')
    user_id = row.get('User_ID')
    assignment_id = st.session_state.get(f"assignment_id_{module_id}")
    
    # Debug: Log what we're looking for
    if not assignment_id:
        # Find all assignment_id keys in session state
        assign_keys = [k for k in st.session_state.keys() if 'assignment_id' in str(k)]
        logger.warning(f"Looking for assignment_id_{module_id}, found keys: {assign_keys}")
    
    if not user_id:
        st.error("❌ User ID not available. Please re-fetch submissions.")
        return False
    
    if not assignment_id:
        st.error(f"❌ Assignment ID not available for module {module_id}. Please re-fetch submissions.")
        return False
    
    # Calculate scaled grade
    total_score = evaluation.get('total_score', 0)
    scaled_grade = (total_score / 100) * max_grade
    scaled_grade = round(scaled_grade)  # Round to nearest whole number
    
    # Format feedback as HTML
    feedback_html = _format_feedback_html(evaluation)
    
    # Get fresh sesskey
    session = setup_session(st.session_state.session_id)
    sesskey = get_fresh_sesskey(session, course['id'])
    
    if not sesskey:
        st.error("❌ Could not get session key. Please try again.")
        return False
    
    # Submit grade
    result = submit_grade(
        session,
        assignment_id,
        user_id,
        module_id,
        scaled_grade,
        feedback_html,
        sesskey
    )
    
    if result['success']:
        st.success(f"✅ Submitted to Moodle: **{scaled_grade}/{max_grade}**")
        return True
    else:
        st.error(f"❌ Failed: {result.get('error', 'Unknown error')}")
        return False


@st.dialog("💬 Discuss Evaluation with AI", width="large")
def _show_discuss_dialog(course, row, current_eval, rubric, module_id, group_id, idx):
    """Show dialog for discussing/refining the evaluation with AI."""
    
    student_name = row.get('Name', 'Unknown')
    
    # Session state key for this dialog's pending result
    result_key = f"discuss_result_{module_id}_{student_name}"
    pending_result = st.session_state.get(result_key)
    
    # Show current score summary
    st.markdown(f"**Student:** {student_name}")
    
    # Show score - use pending result if available
    if pending_result and pending_result.get('total_score') is not None:
        old_score = current_eval.get('total_score', 0)
        new_score = pending_result.get('total_score', 0)
        st.markdown(f"**Current Score:** {old_score}/100 → **{new_score}/100**")
    else:
        st.markdown(f"**Current Score:** {current_eval.get('total_score', 0)}/100")
    
    # Show criteria summary - from pending result if available
    display_eval = pending_result if pending_result else current_eval
    with st.expander("📊 Current Breakdown", expanded=False):
        for cs in display_eval.get('criteria_scores', []):
            st.text(f"• {cs.get('criterion')}: {cs.get('score')}/{cs.get('max_score')}")
    
    # If we have a pending result, show AI response and Save button
    if pending_result:
        st.divider()
        st.markdown("### 🤖 AI Response")
        st.info(pending_result.get('response_to_teacher', 'Score updated successfully.'))
        
        # Show score change
        old_score = current_eval.get('total_score', 0)
        new_score = pending_result.get('total_score', 0)
        if old_score != new_score:
            st.markdown(f"**Score Updated:** {old_score} → **{new_score}**")
            
            with st.expander("📊 Updated Breakdown"):
                for cs in pending_result.get('criteria_scores', []):
                    st.text(f"• {cs.get('criterion')}: {cs.get('score')}/{cs.get('max_score')}")
        
        # Save and Cancel buttons
        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 Save & Close", type="primary", width="stretch"):
                save_evaluation(course['id'], module_id, student_name, pending_result, group_id)
                # Clear the pending result
                del st.session_state[result_key]
                st.success("✓ Saved!")
                st.rerun()
        
        with col2:
            if st.button("Cancel", width="stretch"):
                # Clear pending result and close
                del st.session_state[result_key]
                st.rerun()
        
        # Option to continue refining
        st.divider()
        st.markdown("**Continue the conversation:**")
    else:
        st.divider()
        st.markdown("**Ask a question or request changes:**")
    
    # Input for user's message
    user_message = st.text_area(
        "Your message",
        placeholder="Examples:\n• Why did you give a low score for code quality?\n• The student actually did include error handling, please reconsider\n• Can you be more lenient on documentation for beginners?\n• Increase the score for functionality by 10 points",
        height=120,
        key=f"discuss_input_{idx}",
        label_visibility="collapsed"
    )
    
    col1, col2 = st.columns(2)
    
    with col1:
        send_btn = st.button("📤 Send", type="primary", width="stretch", disabled=not user_message)
    
    if not pending_result:
        with col2:
            if st.button("Cancel", width="stretch"):
                st.rerun()
    
    if send_btn and user_message:
        with st.spinner("Fetching submission content..."):
            submission_content = fetch_submission_content(row, course['id'])
        
        with st.spinner("AI is thinking..."):
            task_description = _get_task_description(module_id)
            # Use pending result as base if we're continuing a conversation
            base_eval = pending_result if pending_result else current_eval
            result = refine_evaluation(
                base_eval,
                user_message,
                submission_content,
                rubric,
                task_description
            )
        
        if result and result.get('error'):
            st.error(f"❌ Error: {result['error']}")
        elif result:
            # Store result in session state so it persists
            st.session_state[result_key] = result
            st.rerun()



