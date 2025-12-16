"""
Quizizz tab for Streamlit app.
Displays and manages quiz data from Quizizz/Wayground platform.
Features:
- Upload Excel exports from Quizizz
- Fuzzy name matching with Moodle students
- Manual name mapping for unmatched students
- Persistent storage of uploaded files
"""

import os
import re
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime
from rapidfuzz import fuzz, process

from core.persistence import get_output_dir, write_wayground_config
from core.wayground import (
    wayground_login, validate_wayground_session, attempt_wayground_auto_login,
    get_available_reports, download_report
)


def get_quizizz_dir(course_id):
    """Get the Quizizz storage directory for a course."""
    output_dir = get_output_dir(course_id)
    quizizz_dir = output_dir / "quizizz"
    quizizz_dir.mkdir(parents=True, exist_ok=True)
    return quizizz_dir


def init_wayground_session_state():
    """Initialize wayground-related session state variables."""
    if 'wayground_session' not in st.session_state:
        st.session_state.wayground_session = None
    if 'wayground_user' not in st.session_state:
        st.session_state.wayground_user = None
    if 'wayground_auto_login_attempted' not in st.session_state:
        st.session_state.wayground_auto_login_attempted = False


def get_name_mappings_file(course_id):
    """Get path to the name mappings JSON file."""
    return get_quizizz_dir(course_id) / "name_mappings.json"


def load_name_mappings(course_id):
    """Load saved name mappings from disk."""
    import json
    mappings_file = get_name_mappings_file(course_id)
    if mappings_file.exists():
        with open(mappings_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_name_mappings(course_id, mappings):
    """Save name mappings to disk."""
    import json
    mappings_file = get_name_mappings_file(course_id)
    with open(mappings_file, 'w', encoding='utf-8') as f:
        json.dump(mappings, f, indent=2)


def parse_quizizz_excel(file_bytes, filename):
    """
    Parse a Quizizz Excel export file.
    
    Returns:
        tuple: (quiz_name, participants_df) or (None, None) if parsing fails
    """
    try:
        # Extract quiz name from filename pattern: QuizName-YYYY-MM-DD...
        quiz_name = extract_quiz_name(filename)
        
        # Read Excel file
        df_dict = pd.read_excel(file_bytes, sheet_name=None)
        sheets = list(df_dict.keys())
        
        if len(sheets) < 2:
            return None, None
        
        # Participants sheet is typically the second one
        participants_df = df_dict[sheets[1]]
        
        # Add quiz name column
        participants_df['Quiz Name'] = quiz_name
        participants_df['Source File'] = filename
        
        return quiz_name, participants_df
    except Exception as e:
        st.error(f"Error parsing {filename}: {e}")
        return None, None


def extract_quiz_name(filename):
    """
    Extract quiz name from Quizizz filename.
    Pattern: QuizName-YYYY-MM-DDTHH_MM_SS_...-xxxxx.xlsx
    """
    # Remove extension
    name = filename.rsplit('.', 1)[0]
    
    # Try to extract everything before the date pattern
    match = re.match(r'(.+?)-\d{4}-\d{2}-\d{2}T', name)
    if match:
        return match.group(1).replace('-', ' ').strip()
    
    # Fallback: just return the filename without extension
    return name


def get_moodle_students(session_id, course_id, group_id=None):
    """
    Get list of Moodle students for name matching.
    Returns list of dicts with 'id', 'name', 'clean_name'.
    """
    from core.api import setup_session, get_course_groups, clean_name
    
    # Try to get enrolled users from API
    try:
        session = setup_session(session_id)
        
        # Use the enrollment API
        url = f"https://paatshala.ictkerala.org/webservice/rest/server.php"
        params = {
            'wstoken': session.cookies.get('MoodleSession', ''),
            'wsfunction': 'core_enrol_get_enrolled_users',
            'moodlewsrestformat': 'json',
            'courseid': course_id,
        }
        if group_id:
            params['options[0][name]'] = 'groupid'
            params['options[0][value]'] = group_id
        
        # This might not work without proper webservice token
        # Fallback to scraping if needed
    except:
        pass
    
    # For now, return empty - we'll populate from quiz scores if available
    return []


def fuzzy_match_name(quizizz_name, moodle_names, threshold=70):
    """
    Find the best fuzzy match for a Quizizz name among Moodle names.
    
    Args:
        quizizz_name: Name from Quizizz (First + Last)
        moodle_names: List of Moodle student names (cleaned)
        threshold: Minimum score to consider a match (0-100)
    
    Returns:
        tuple: (best_match, score) or (None, 0) if no good match
    """
    if not moodle_names or not quizizz_name:
        return None, 0
    
    # Normalize the quizizz name
    quizizz_clean = quizizz_name.strip().lower()
    
    # Use rapidfuzz to find best match
    result = process.extractOne(
        quizizz_clean, 
        [n.lower() for n in moodle_names],
        scorer=fuzz.token_sort_ratio
    )
    
    if result and result[1] >= threshold:
        # Get the original case name
        idx = result[2]
        return moodle_names[idx], result[1]
    
    return None, 0


def load_uploaded_files(course_id):
    """Load all previously uploaded Quizizz files for a course."""
    quizizz_dir = get_quizizz_dir(course_id)
    files = list(quizizz_dir.glob("*.xlsx"))
    return files


def combine_quizizz_data(course_id):
    """
    Combine all uploaded Quizizz files into a single DataFrame.
    """
    files = load_uploaded_files(course_id)
    all_data = []
    
    for file_path in files:
        with open(file_path, 'rb') as f:
            quiz_name, df = parse_quizizz_excel(f, file_path.name)
            if df is not None:
                all_data.append(df)
    
    if all_data:
        combined = pd.concat(all_data, ignore_index=True)
        return combined
    return None


def render_quizizz_tab(course, meta):
    """Render the Quizizz tab content."""
    course_id = course.get('id')
    
    # Initialize session state
    init_wayground_session_state()
    
    if 'quizizz_name_mappings' not in st.session_state:
        st.session_state.quizizz_name_mappings = {}
    
    saved_mappings = load_name_mappings(course_id)
    if saved_mappings:
        st.session_state.quizizz_name_mappings.update(saved_mappings)
    
    if 'quizizz_data' not in st.session_state:
        st.session_state.quizizz_data = None
    
    if 'wayground_reports' not in st.session_state:
        st.session_state.wayground_reports = None
    
    # Auto-login attempt on first load (silent)
    if not st.session_state.wayground_session and not st.session_state.wayground_auto_login_attempted:
        st.session_state.wayground_auto_login_attempted = True
        session, user_info = attempt_wayground_auto_login()
        if session:
            st.session_state.wayground_session = session
            st.session_state.wayground_user = user_info
            st.rerun()
    
    # =========================================================================
    # Header with inconspicuous login status
    # =========================================================================
    col_title, col_status = st.columns([4, 2])
    with col_title:
        st.markdown("### 📝 Quizizz / Wayground")
    with col_status:
        if st.session_state.wayground_session:
            user = st.session_state.wayground_user or {}
            user_name = user.get('firstName', 'User')
            col_name, col_logout = st.columns([3, 1])
            with col_name:
                st.caption(f"✓ {user_name}")
            with col_logout:
                if st.button("↪", key="wayground_logout", help="Logout from Wayground"):
                    st.session_state.wayground_session = None
                    st.session_state.wayground_user = None
                    st.session_state.wayground_reports = None
                    st.rerun()
        else:
            st.caption("Not logged in")
    
    # Load combined data on first load
    existing_files = load_uploaded_files(course_id)
    if existing_files and st.session_state.quizizz_data is None:
        st.session_state.quizizz_data = combine_quizizz_data(course_id)
    
    # =========================================================================
    # 1. Quiz Results Table (MAIN FEATURE - comes first)
    # =========================================================================
    if st.session_state.quizizz_data is not None and not st.session_state.quizizz_data.empty:
        df = st.session_state.quizizz_data.copy()
        
        st.subheader("📊 Quiz Results")
        
        # Create full name column
        if 'First Name' in df.columns:
            df['Full Name'] = df['First Name'].fillna('') + ' ' + df['Last Name'].fillna('')
            df['Full Name'] = df['Full Name'].str.strip()
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Attempts", len(df))
        with col2:
            unique_quizzes = df['Quiz Name'].nunique() if 'Quiz Name' in df.columns else 0
            st.metric("Quizzes", unique_quizzes)
        with col3:
            unique_students = df['Full Name'].nunique() if 'Full Name' in df.columns else 0
            st.metric("Students", unique_students)
        with col4:
            try:
                if 'Accuracy' in df.columns:
                    accuracy_series = df['Accuracy'].astype(str).str.replace('%', '', regex=False)
                    accuracy_numeric = pd.to_numeric(accuracy_series, errors='coerce')
                    avg_accuracy = accuracy_numeric.mean()
                else:
                    avg_accuracy = 0
            except Exception:
                avg_accuracy = 0
            st.metric("Avg Accuracy", f"{avg_accuracy:.1f}%")
        
        # Filter by quiz
        quiz_names = ['All'] + sorted(df['Quiz Name'].unique().tolist()) if 'Quiz Name' in df.columns else ['All']
        selected_quiz = st.selectbox("Filter by Quiz", quiz_names, key="quizizz_filter")
        
        if selected_quiz == 'All' and 'Full Name' in df.columns:
            # ===== CONSOLIDATED VIEW =====
            st.caption("📊 **Consolidated Summary** - Aggregated results per student across all quizzes")
            
            df_numeric = df.copy()
            
            if 'Accuracy' in df_numeric.columns:
                df_numeric['Accuracy_Num'] = pd.to_numeric(
                    df_numeric['Accuracy'].astype(str).str.replace('%', '', regex=False),
                    errors='coerce'
                )
            
            if 'Score' in df_numeric.columns:
                df_numeric['Score_Num'] = pd.to_numeric(df_numeric['Score'], errors='coerce')
            
            for col in ['Correct', 'Incorrect']:
                if col in df_numeric.columns:
                    df_numeric[f'{col}_Num'] = pd.to_numeric(df_numeric[col], errors='coerce')
            
            agg_dict = {'Quiz Name': 'count'}
            if 'Score_Num' in df_numeric.columns:
                agg_dict['Score_Num'] = 'sum'
            if 'Accuracy_Num' in df_numeric.columns:
                agg_dict['Accuracy_Num'] = 'mean'
            if 'Correct_Num' in df_numeric.columns:
                agg_dict['Correct_Num'] = 'sum'
            if 'Incorrect_Num' in df_numeric.columns:
                agg_dict['Incorrect_Num'] = 'sum'
            
            consolidated = df_numeric.groupby('Full Name').agg(agg_dict).reset_index()
            
            rename_map = {
                'Quiz Name': 'Quizzes Taken',
                'Score_Num': 'Total Score',
                'Accuracy_Num': 'Avg Accuracy',
                'Correct_Num': 'Total Correct',
                'Incorrect_Num': 'Total Incorrect'
            }
            consolidated = consolidated.rename(columns=rename_map)
            
            if 'Avg Accuracy' in consolidated.columns:
                consolidated['Avg Accuracy'] = consolidated['Avg Accuracy'].apply(
                    lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A"
                )
            
            if 'Total Score' in consolidated.columns:
                consolidated = consolidated.sort_values('Total Score', ascending=False)
            
            consolidated.insert(0, 'Rank', range(1, len(consolidated) + 1))
            
            st.dataframe(consolidated, width="stretch", hide_index=True)
            
            # Action buttons row
            csv = consolidated.to_csv(index=False)
            col1, col2, col3 = st.columns([1, 1, 4])
            with col1:
                st.download_button(
                    label="📥 Download CSV",
                    data=csv,
                    file_name=f"quizizz_consolidated_{course_id}.csv",
                    mime="text/csv",
                    key="download_quizizz_csv"
                )
            with col2:
                if st.button("🔗 Name Matching", key="name_match_btn_consolidated"):
                    st.session_state.show_name_matching = True
        else:
            # ===== INDIVIDUAL QUIZ VIEW =====
            display_df = df.copy()
            if selected_quiz != 'All':
                display_df = df[df['Quiz Name'] == selected_quiz]
            
            display_cols = ['Quiz Name', 'Full Name', 'Score', 'Accuracy', 'Correct', 'Incorrect', 
                           'Total Time Taken', 'Started At']
            display_cols = [c for c in display_cols if c in display_df.columns]
            
            st.dataframe(display_df[display_cols], width="stretch", hide_index=True)
            
            # Action buttons row
            csv = display_df.to_csv(index=False)
            col1, col2, col3 = st.columns([1, 1, 4])
            with col1:
                st.download_button(
                    label="📥 Download CSV",
                    data=csv,
                    file_name=f"quizizz_results_{course_id}.csv",
                    mime="text/csv",
                    key="download_quizizz_csv"
                )
            with col2:
                if st.button("🔗 Name Matching", key="name_match_btn_individual"):
                    st.session_state.show_name_matching = True
        
        st.divider()
    else:
        st.info("📤 Upload or fetch Quizizz reports to view quiz results")
    
    # =========================================================================
    # 2. Uploaded Files List
    # =========================================================================
    if existing_files:
        with st.expander(f"📁 Uploaded Files ({len(existing_files)})", expanded=False):
            for file_path in existing_files:
                col1, col2 = st.columns([5, 1])
                with col1:
                    st.text(file_path.name)
                with col2:
                    if st.button("🗑️", key=f"del_{file_path.name}", help="Delete file"):
                        file_path.unlink()
                        st.session_state.quizizz_data = None
                        st.rerun()
            
            if st.button("🔄 Refresh Data"):
                st.session_state.quizizz_data = combine_quizizz_data(course_id)
                st.rerun()
    
    # =========================================================================
    # 3. Wayground Fetch Reports Section
    # =========================================================================
    with st.expander("🌐 Wayground Reports", expanded=False):
        if st.session_state.wayground_session:
            col1, col2 = st.columns([1, 4])
            with col1:
                if st.button("🔄 Fetch", key="fetch_wg_reports"):
                    with st.spinner("Fetching reports..."):
                        reports = get_available_reports(st.session_state.wayground_session)
                        st.session_state.wayground_reports = reports
                        if not reports:
                            st.warning("No reports found")
                        st.rerun()
            
            if st.session_state.wayground_reports:
                st.caption(f"Found {len(st.session_state.wayground_reports)} reports")
                
                quizizz_dir = get_quizizz_dir(course_id)
                
                for i, report in enumerate(st.session_state.wayground_reports):
                    report_name = report.get('name', f'report_{i}')
                    report_date = report.get('date', '')
                    safe_name = "".join(c if c.isalnum() or c in '-_' else '_' for c in report_name)
                    
                    if report_date:
                        local_path = quizizz_dir / f"{safe_name}_{report_date}.xlsx"
                    else:
                        local_path = quizizz_dir / f"{safe_name}.xlsx"
                    
                    col1, col2, col3 = st.columns([3, 1, 1])
                    with col1:
                        st.text(f"{report_name}" + (f" ({report_date})" if report_date else ""))
                    with col2:
                        if local_path.exists():
                            st.caption("✓")
                    with col3:
                        if st.button("📥", key=f"dl_report_{i}", help="Download"):
                            with st.spinner("Downloading..."):
                                content, dl_filename = download_report(
                                    st.session_state.wayground_session,
                                    report['id'],
                                    local_path
                                )
                                if content:
                                    st.session_state.quizizz_data = None
                                    st.rerun()
                                else:
                                    st.error("Download failed")
        else:
            # Login form (compact)
            st.caption("Login to fetch reports from Wayground")
            col1, col2 = st.columns(2)
            with col1:
                wg_email = st.text_input("Email", key="wg_email", placeholder="email@example.com")
            with col2:
                wg_password = st.text_input("Password", type="password", key="wg_password")
            
            col1, col2 = st.columns([1, 2])
            with col1:
                wg_remember = st.checkbox("Remember", value=True, key="wg_remember")
            with col2:
                if st.button("Login", key="wg_login_btn"):
                    if wg_email and wg_password:
                        with st.spinner("Logging in..."):
                            session, user_info = wayground_login(wg_email, wg_password)
                            if session:
                                st.session_state.wayground_session = session
                                st.session_state.wayground_user = user_info
                                if wg_remember:
                                    write_wayground_config(email=wg_email, password=wg_password)
                                st.rerun()
                            else:
                                st.error("Login failed")
                    else:
                        st.warning("Enter credentials")
    
    # =========================================================================
    # 4. Manual Upload Section (last)
    # =========================================================================
    with st.expander("📤 Upload Quiz Reports", expanded=False):
        uploaded_files = st.file_uploader(
            "Upload Quizizz Excel exports",
            type=['xlsx'],
            accept_multiple_files=True,
            key="quizizz_uploader",
            help="Select one or more .xlsx files exported from Quizizz/Wayground"
        )
        
        if uploaded_files:
            quizizz_dir = get_quizizz_dir(course_id)
            
            for uploaded_file in uploaded_files:
                target_path = quizizz_dir / uploaded_file.name
                
                if not target_path.exists():
                    with open(target_path, 'wb') as f:
                        f.write(uploaded_file.getbuffer())
                    st.success(f"✓ Saved: {uploaded_file.name}")
                    st.session_state.quizizz_data = None  # Trigger refresh
                else:
                    st.info(f"Already exists: {uploaded_file.name}")
    
    # =========================================================================
    # Name Matching Dialog (triggered by button)
    # =========================================================================
    if 'show_name_matching' not in st.session_state:
        st.session_state.show_name_matching = False
    
    if st.session_state.show_name_matching and st.session_state.quizizz_data is not None:
        df = st.session_state.quizizz_data.copy()
        if 'First Name' in df.columns:
            df['Full Name'] = df['First Name'].fillna('') + ' ' + df['Last Name'].fillna('')
            df['Full Name'] = df['Full Name'].str.strip()
        
        @st.dialog("🔗 Name Matching")
        def show_name_matching_dialog():
            st.caption("Match Quizizz names to Moodle students")
            
            quizizz_names = df['Full Name'].unique().tolist() if 'Full Name' in df.columns else []
            
            moodle_names = []
            if 'quiz_data' in st.session_state and st.session_state.quiz_data:
                quiz_df = pd.DataFrame(st.session_state.quiz_data)
                if 'Student' in quiz_df.columns:
                    from core.api import clean_name
                    moodle_names = [clean_name(n) for n in quiz_df['Student'].unique().tolist()]
            
            if moodle_names:
                st.info(f"Found {len(moodle_names)} Moodle students")
                
                match_results = []
                for qname in quizizz_names:
                    if qname in st.session_state.quizizz_name_mappings:
                        match_results.append({
                            'Quizizz Name': qname,
                            'Moodle Name': st.session_state.quizizz_name_mappings[qname],
                            'Confidence': 100,
                            'Status': '✅ Manual'
                        })
                    else:
                        best_match, score = fuzzy_match_name(qname, moodle_names)
                        match_results.append({
                            'Quizizz Name': qname,
                            'Moodle Name': best_match or '❓ No match',
                            'Confidence': score,
                            'Status': '✅ Auto' if score >= 80 else ('⚠️ Low' if score >= 50 else '❌ None')
                        })
                
                match_df = pd.DataFrame(match_results)
                st.dataframe(
                    match_df,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        'Confidence': st.column_config.ProgressColumn(
                            "Confidence", min_value=0, max_value=100, format="%d%%"
                        )
                    }
                )
                
                low_confidence = match_df[match_df['Confidence'] < 80]
                if not low_confidence.empty:
                    st.caption("Manual mapping for low-confidence matches:")
                    for _, row in low_confidence.iterrows():
                        qname = row['Quizizz Name']
                        col1, col2 = st.columns([2, 3])
                        with col1:
                            st.text(qname)
                        with col2:
                            selected = st.selectbox(
                                "Map to:",
                                ['-- Select --'] + moodle_names,
                                key=f"map_{qname}",
                                label_visibility="collapsed"
                            )
                            if selected != '-- Select --':
                                st.session_state.quizizz_name_mappings[qname] = selected
                    
                    if st.button("💾 Save Mappings"):
                        save_name_mappings(course_id, st.session_state.quizizz_name_mappings)
                        st.success("✓ Saved!")
            else:
                st.warning("Fetch Quiz Scores first to enable name matching")
            
            if st.button("Close"):
                st.session_state.show_name_matching = False
                st.rerun()
        
        show_name_matching_dialog()
