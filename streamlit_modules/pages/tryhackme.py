"""
TryHackMe tab page for Streamlit app.
Fetches TryHackMe leaderboard and scoreboard data from a hosted PHP page.
"""

import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import json

from core.persistence import get_output_dir, get_config


# Get API URL from config (with default fallback)
def get_thm_url():
    """Get TryHackMe tracker URL from config."""
    return get_config('thm_base_url', 'https://ictak.online/tryhackme.php')


def get_thm_cache_dir(course_id):
    """Get the TryHackMe cache directory for a course."""
    output_dir = get_output_dir(course_id)
    thm_dir = output_dir / "tryhackme"
    thm_dir.mkdir(parents=True, exist_ok=True)
    return thm_dir


def save_thm_data(course_id, batch_name, data_type, data):
    """Save TryHackMe data to disk for persistence."""
    cache_dir = get_thm_cache_dir(course_id)
    filename = f"{batch_name}_{data_type}.json"
    cache_file = cache_dir / filename
    
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, default=str)
    
    return cache_file


def load_thm_data(course_id, batch_name, data_type):
    """Load TryHackMe data from disk if available."""
    cache_dir = get_thm_cache_dir(course_id)
    filename = f"{batch_name}_{data_type}.json"
    cache_file = cache_dir / filename
    
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    return None


def find_thm_feedback(feedbacks):
    """
    Find a feedback form that likely contains TryHackMe usernames.
    
    Searches for (in priority order):
    1. 'account' + 'creation' or 'feedback' in name
    2. 'tryhackme' in name
    3. 'task' in name (e.g., TasksFeedback)
    
    Returns: (feedback_name, module_id) or (None, None)
    """
    if not feedbacks:
        return None, None
    
    # Priority 1: Account Creation Feedback
    for f in feedbacks:
        name = f[0].lower()
        if 'account' in name and ('creation' in name or 'feedback' in name):
            return f[0], f[1]
    
    # Priority 2: TryHackMe in name
    for f in feedbacks:
        if 'tryhackme' in f[0].lower():
            return f[0], f[1]
    
    # Priority 3: Task in name (covers TasksFeedback, Task 2, etc.)
    for f in feedbacks:
        if 'task' in f[0].lower():
            return f[0], f[1]
    
    return None, None


def find_thm_columns(columns):
    """
    Find TryHackMe username and Name columns from feedback column headers.
    
    Handles various formats:
    - "Enter your tryhackme username here"
    - "TryHackMe Username"
    - "THM Username"
    
    Returns: (thm_column, name_column) - either may be None if not found
    """
    thm_column = None
    name_column = None
    
    for col in columns:
        col_lower = col.lower()
        
        # Check for TryHackMe username column
        if thm_column is None:
            if 'tryhackme' in col_lower and ('username' in col_lower or 'enter' in col_lower):
                thm_column = col
            elif 'thm' in col_lower and 'username' in col_lower:
                thm_column = col
            elif 'tryhackme username' in col_lower:
                thm_column = col
        
        # Check for Name column
        if name_column is None:
            if 'first name' in col_lower or 'firstname' in col_lower:
                name_column = col
    
    # Fallback for name column - any column with 'name'
    if name_column is None:
        for col in columns:
            if 'name' in col.lower() and 'username' not in col.lower():
                name_column = col
                break
    
    return thm_column, name_column


# Month abbreviations for pattern matching
MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']


def extract_batch_name(group_name):
    """
    Extract batch name from group name.
    
    Examples:
        'CL-IRP-CSA-14-NOV-2025' -> 'csanov25'
        'CERTIFICATION-CSA-11-JAN-2024-BATCH-01-GROUP' -> 'csajan24'
    
    Pattern: CSA + 3-letter month + 2-digit year
    """
    if not group_name:
        return ""
    
    text = group_name.upper()
    
    # Check if CSA is present
    if 'CSA' not in text:
        # Fallback to simple lowercase if CSA not found
        return group_name.lower().replace(" ", "").replace("-", "")
    
    # Find month (3-letter abbreviation)
    month_found = None
    for month in MONTHS:
        if month.upper() in text:
            month_found = month
            break
    
    if not month_found:
        return group_name.lower().replace(" ", "").replace("-", "")
    
    # Find year - look for 4-digit year (2024, 2025) or 2-digit year
    # First try 4-digit year
    year_match = re.search(r'20(\d{2})', text)
    if year_match:
        year_found = year_match.group(1)  # Extract just the 2-digit part
    else:
        # Try 2-digit year (look for -24, -25, etc. not preceded by other digits)
        year_match = re.search(r'(?<!\d)(\d{2})(?!\d)', text)
        if year_match:
            year_found = year_match.group(1)
        else:
            return group_name.lower().replace(" ", "").replace("-", "")
    
    # Construct batch name: csa + month + year
    return f"csa{month_found}{year_found}"


def render_tryhackme_tab(course, meta):
    """Render the TryHackMe tab content"""
    
    st.markdown("### 🎯 TryHackMe Progress Tracker")
    st.caption("Track participant progress on TryHackMe platform")
    
    # =========================================================================
    # URL and Batch Configuration
    # =========================================================================
    
    # Initialize session state for TryHackMe settings
    if 'thm_base_url' not in st.session_state:
        st.session_state.thm_base_url = get_thm_url()
    if 'thm_batch_name' not in st.session_state:
        st.session_state.thm_batch_name = ""
    if 'thm_leaderboard_data' not in st.session_state:
        st.session_state.thm_leaderboard_data = None
    if 'thm_scoreboard_data' not in st.session_state:
        st.session_state.thm_scoreboard_data = None
    if 'thm_batch_info' not in st.session_state:
        st.session_state.thm_batch_info = None
    if 'thm_current_batch' not in st.session_state:
        st.session_state.thm_current_batch = None  # Track which batch the data belongs to
    
    # Auto-detect batch name from selected group using smart extraction
    selected_group = st.session_state.get('selected_group')
    auto_batch = ""
    if selected_group and selected_group.get('name'):
        auto_batch = extract_batch_name(selected_group['name'])
    
    # Determine effective batch name
    effective_batch = st.session_state.thm_batch_name or auto_batch
    
    # Get course ID for persistence
    course_id = course.get('id')
    
    # Check if batch has changed - if so, clear and reload data
    if effective_batch != st.session_state.thm_current_batch:
        # Batch changed - clear session data
        st.session_state.thm_leaderboard_data = None
        st.session_state.thm_scoreboard_data = None
        st.session_state.thm_batch_info = None
        st.session_state.thm_current_batch = effective_batch
        
        # Try to load cached data for the new batch
        if effective_batch:
            cached_leaderboard = load_thm_data(course_id, effective_batch, 'leaderboard')
            cached_scoreboard = load_thm_data(course_id, effective_batch, 'scoreboard')
            cached_batch_info = load_thm_data(course_id, effective_batch, 'batch_info')
            
            if cached_leaderboard:
                st.session_state.thm_leaderboard_data = cached_leaderboard
            if cached_scoreboard:
                st.session_state.thm_scoreboard_data = cached_scoreboard
            if cached_batch_info:
                st.session_state.thm_batch_info = cached_batch_info
    
    # =========================================================================
    # Action Buttons (at top)
    # =========================================================================
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        fetch_btn = st.button("📥 Fetch Data", key="fetch_thm_btn", type="primary", 
                              disabled=not effective_batch)
    with col2:
        if st.session_state.thm_leaderboard_data:
            refresh_btn = st.button("🔄 Refresh", key="refresh_thm_btn")
        else:
            refresh_btn = False
    with col3:
        if effective_batch:
            st.caption(f"Batch: **{effective_batch}**")
    
    # =========================================================================
    # Fetch Data
    # =========================================================================
    if fetch_btn or refresh_btn:
        base_url = st.session_state.thm_base_url
        
        # Headers to mimic browser request (avoid 406 errors)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        }
        
        # Fetch leaderboard (JSON API with refresh action)
        leaderboard_url = f"{base_url}?action=refresh&b={effective_batch}"
        
        with st.spinner("Fetching leaderboard data..."):
            try:
                response = requests.get(leaderboard_url, headers=headers, timeout=30)
                response.raise_for_status()
                
                leaderboard_json = response.json()
                
                if leaderboard_json.get('error'):
                    st.error(f"❌ Error: {leaderboard_json['error']}")
                    return
                
                if leaderboard_json.get('success'):
                    st.session_state.thm_leaderboard_data = leaderboard_json.get('data', [])
                    st.session_state.thm_cached_at = leaderboard_json.get('cached_at', '')
                else:
                    st.error("❌ Failed to fetch leaderboard data")
                    return
                    
            except requests.exceptions.RequestException as e:
                st.error(f"❌ Network error fetching leaderboard: {e}")
                return
            except ValueError as e:
                st.error(f"❌ Error parsing leaderboard response: {e}")
                return
        
        # Fetch scoreboard (HTML page)
        with st.spinner("Fetching scoreboard data..."):
            try:
                scoreboard_url = f"{base_url}?b={effective_batch}"
                response = requests.get(scoreboard_url, headers=headers, timeout=30)
                response.raise_for_status()
                
                # Parse the HTML to extract scoreboard data
                scoreboard_data, batch_info = parse_scoreboard_html(response.text)
                st.session_state.thm_scoreboard_data = scoreboard_data
                st.session_state.thm_batch_info = batch_info
                
            except requests.exceptions.RequestException as e:
                st.error(f"❌ Network error fetching scoreboard: {e}")
            except Exception as e:
                st.error(f"❌ Error parsing scoreboard: {e}")
        
        # Save fetched data to disk for persistence
        if st.session_state.thm_leaderboard_data:
            save_thm_data(course_id, effective_batch, 'leaderboard', st.session_state.thm_leaderboard_data)
        if st.session_state.thm_scoreboard_data:
            save_thm_data(course_id, effective_batch, 'scoreboard', st.session_state.thm_scoreboard_data)
        if st.session_state.thm_batch_info:
            save_thm_data(course_id, effective_batch, 'batch_info', st.session_state.thm_batch_info)
        
        st.success(f"✓ Data fetched for batch: **{effective_batch.upper()}**")
    
    # =========================================================================
    # Display Data with Tabs (MAIN CONTENT - shown first)
    # =========================================================================
    if st.session_state.thm_leaderboard_data or st.session_state.thm_scoreboard_data:
        st.divider()
        
        # Show batch info if available
        if st.session_state.thm_batch_info:
            info = st.session_state.thm_batch_info
            st.markdown(f"**📊 {info.get('name', effective_batch.upper())}**")
            if info.get('start_date') and info.get('end_week'):
                st.caption(f"Started: {info['start_date']} | Ends: Week {info['end_week']}")
        
        # Create sub-tabs for Leaderboard and Scoreboard
        tab1, tab2 = st.tabs(["🏆 Leaderboard", "📈 Scoreboard"])
        
        with tab1:
            render_leaderboard_section()
        
        with tab2:
            render_scoreboard_section()
        
        st.divider()
    
    # =========================================================================
    # Configuration (at bottom, collapsed when data is loaded)
    # =========================================================================
    with st.expander("⚙️ Configuration", expanded=not st.session_state.thm_leaderboard_data):
        col1, col2 = st.columns([2, 1])
        
        with col1:
            base_url = st.text_input(
                "Base URL",
                value=st.session_state.thm_base_url,
                help="The base URL for the TryHackMe tracker (e.g., https://ictak.online/tryhackme.php)",
                key="thm_url_input"
            )
            if base_url != st.session_state.thm_base_url:
                st.session_state.thm_base_url = base_url
        
        with col2:
            # Show auto-detected batch if available
            placeholder = f"Auto: {auto_batch}" if auto_batch else "Enter batch name"
            batch_name = st.text_input(
                "Batch Name",
                value=st.session_state.thm_batch_name or auto_batch,
                placeholder=placeholder,
                help="Batch identifier (auto-detected from group name, or enter manually)",
                key="thm_batch_input"
            )
            # Update session state
            st.session_state.thm_batch_name = batch_name
        
        if auto_batch:
            st.caption(f"📍 Auto-detected: **{auto_batch}** (from group: {selected_group['name']})")
    
    # =========================================================================
    # Admin Panel (expandable, below configuration)
    # =========================================================================
    render_admin_panel(effective_batch)
    
    # =========================================================================
    # Legacy Fetcher (direct TryHackMe API, below Admin Panel)
    # =========================================================================
    render_legacy_fetcher(course)
    
    # Show help text if no data yet
    if not st.session_state.thm_leaderboard_data and not st.session_state.thm_scoreboard_data:
        if not effective_batch:
            st.warning("⚠️ Please select a group or enter a batch name in Configuration below.")
        else:
            st.info("👆 Click 'Fetch Data' to load TryHackMe progress data.")
            st.markdown("""
            **How it works:**
            1. Data is fetched from the configured TryHackMe tracker URL
            2. **Leaderboard** shows current room completion rankings
            3. **Scoreboard** shows weekly points (5 pts for weekly progress)
            """)


def parse_scoreboard_html(html_content):
    """Parse the scoreboard HTML to extract weekly data"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    scoreboard_data = []
    batch_info = {}
    
    # Extract batch info from header
    card_title = soup.find('h2', class_='card-title')
    if card_title:
        batch_info['name'] = card_title.get_text(strip=True).replace('📊', '').strip()
    
    cached_info = soup.find('span', class_='cached-info')
    if cached_info:
        info_text = cached_info.get_text(strip=True)
        # Parse "Started: YYYY-MM-DD | Ends: Week N"
        start_match = re.search(r'Started:\s*(\S+)', info_text)
        end_match = re.search(r'Ends:\s*Week\s*(\d+)', info_text)
        if start_match:
            batch_info['start_date'] = start_match.group(1)
        if end_match:
            batch_info['end_week'] = int(end_match.group(1))
    
    # Find the scoreboard tab content
    scoreboard_tab = soup.find('div', id='scoreboard-tab')
    if not scoreboard_tab:
        return scoreboard_data, batch_info
    
    table = scoreboard_tab.find('table')
    if not table:
        return scoreboard_data, batch_info
    
    # Parse header to get week numbers
    thead = table.find('thead')
    if thead:
        headers = []
        for th in thead.find_all('th'):
            text = th.get_text(strip=True)
            headers.append(text)
    
    # Count week columns (between Name and Total)
    week_count = len(headers) - 2  # Subtract Name and Total columns
    
    # Parse body rows
    tbody = table.find('tbody')
    if tbody:
        for tr in tbody.find_all('tr'):
            cells = tr.find_all('td')
            if len(cells) < 2:
                continue
            
            row_data = {
                'Name': cells[0].get_text(strip=True)
            }
            
            # Extract weekly points
            for i in range(1, len(cells) - 1):  # Skip first (name) and last (total)
                week_num = i
                cell_text = cells[i].get_text(strip=True)
                # Parse points or dash
                if cell_text == '-':
                    row_data[f'Week {week_num}'] = '-'
                else:
                    try:
                        row_data[f'Week {week_num}'] = int(cell_text)
                    except ValueError:
                        row_data[f'Week {week_num}'] = cell_text
            
            # Total points
            if len(cells) > 1:
                total_text = cells[-1].get_text(strip=True)
                try:
                    row_data['Total'] = int(total_text)
                except ValueError:
                    row_data['Total'] = 0
            
            scoreboard_data.append(row_data)
    
    return scoreboard_data, batch_info


def render_leaderboard_section():
    """Render the leaderboard tab content"""
    data = st.session_state.thm_leaderboard_data
    
    if not data:
        st.info("No leaderboard data available. Click 'Fetch Data' to load.")
        return
    
    # Show cached time if available
    if st.session_state.get('thm_cached_at'):
        st.caption(f"Last updated: {st.session_state.thm_cached_at}")
    
    # Summary metrics
    total_participants = len(data)
    total_rooms = sum(x.get('rooms_completed', 0) for x in data)
    avg_rooms = total_rooms / total_participants if total_participants > 0 else 0
    top_performer = data[0] if data else None
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Participants", total_participants)
    with col2:
        st.metric("Total Rooms", total_rooms)
    with col3:
        st.metric("Avg Rooms", f"{avg_rooms:.1f}")
    with col4:
        if top_performer:
            st.metric("Top Performer", f"{top_performer.get('rooms_completed', 0)} rooms")
    
    st.divider()
    
    # Prepare data for display
    display_data = []
    for i, item in enumerate(data, 1):
        display_data.append({
            'Rank': i,
            'Name': item.get('name', 'Unknown'),
            'Username': item.get('username', ''),
            'Rooms Completed': item.get('rooms_completed', 0),
            'Profile URL': f"https://tryhackme.com/p/{item.get('username', '')}" if item.get('username') else ''
        })
    
    df = pd.DataFrame(display_data)
    
    # Display dataframe
    column_config = {
        "Rank": st.column_config.NumberColumn("🏅 Rank", width="small"),
        "Name": st.column_config.TextColumn("👤 Name", width="medium"),
        "Username": st.column_config.TextColumn("🔗 Username", width="medium"),
        "Rooms Completed": st.column_config.NumberColumn("✅ Rooms", width="small"),
        "Profile URL": st.column_config.LinkColumn(
            "🌐 Profile",
            display_text="View Profile",
            width="small"
        )
    }
    
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config=column_config
    )
    
    # Download button (below table)
    csv = df.to_csv(index=False)
    st.download_button(
        label="📥 Download CSV",
        data=csv,
        file_name=f"tryhackme_leaderboard_{st.session_state.thm_batch_name}.csv",
        mime="text/csv",
        key="download_thm_leaderboard_csv"
    )


def render_scoreboard_section():
    """Render the scoreboard tab content"""
    data = st.session_state.thm_scoreboard_data
    
    if not data:
        st.info("No scoreboard data available. Click 'Fetch Data' to load.")
        return
    
    # Convert to DataFrame
    df = pd.DataFrame(data)
    
    if df.empty:
        st.info("No scoreboard data to display.")
        return
    
    # Summary
    if 'Total' in df.columns:
        total_points = df['Total'].sum()
        avg_points = df['Total'].mean()
        max_points = df['Total'].max()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Points", total_points)
        with col2:
            st.metric("Avg Points", f"{avg_points:.1f}")
        with col3:
            st.metric("Max Points", max_points)
        
        st.divider()
    
    # Download button
    col1, col2 = st.columns([1, 4])
    with col1:
        csv = df.to_csv(index=False)
        st.download_button(
            label="📥 Download CSV",
            data=csv,
            file_name=f"tryhackme_scoreboard_{st.session_state.thm_batch_name}.csv",
            mime="text/csv",
            key="download_thm_scoreboard_csv"
        )
    
    # Prepare column config
    column_config = {
        "Name": st.column_config.TextColumn("👤 Name", width="medium"),
        "Total": st.column_config.NumberColumn("🏆 Total", width="small")
    }
    
    # Add week columns
    for col in df.columns:
        if col.startswith('Week'):
            column_config[col] = st.column_config.TextColumn(f"📅 {col}", width="small")
    
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config=column_config
    )
    
    # How it works info
    with st.expander("ℹ️ How Scoring Works"):
        st.markdown("""
        Every Monday at midnight, a snapshot is taken of everyone's completed rooms on TryHackMe.
        
        - **Week 1:** Complete at least 1 room → **+5 points**
        - **Week 2+:** Complete more rooms than previous week → **+5 points**
        - No progress = **0 points**
        
        *Consistency is key! 🎯*
        """)


def render_admin_panel(effective_batch):
    """Render the admin panel section for TryHackMe management"""
    
    # Admin auth constants from config (with defaults matching PHP backend)
    AUTH_PARAM = get_config('thm_auth_param', 'auth0r1ty')
    AUTH_VALUE = get_config('thm_auth_value', 'l3tm3in')
    CRON_SECRET = get_config('thm_cron_secret', 'm0nd4ySn4p!')
    
    with st.expander("🔧 Admin Panel", expanded=False):
        st.caption("Manage TryHackMe leaderboard batches and snapshots")
        
        base_url = st.session_state.get('thm_base_url', get_thm_url())
        # Remove filename from URL if present to get base site URL
        site_url = base_url.rsplit('/', 1)[0] if '/tryhackme.php' in base_url else base_url
        
        # Headers for requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        
        # Tabs for different admin actions
        admin_tab1, admin_tab2, admin_tab3, admin_tab4 = st.tabs([
            "📤 Upload Batch", "🗑️ Delete Batch", "🧹 Delete Snapshots", "⏰ Trigger Snapshot"
        ])
        
        # =====================================================================
        # Upload New Batch
        # =====================================================================
        with admin_tab1:
            st.markdown("##### Upload New Batch")
            
            col1, col2 = st.columns(2)
            with col1:
                subject = st.selectbox("Subject", ["CSA"], key="admin_subject")
                month = st.selectbox("Month", [
                    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
                ], key="admin_month")
            
            with col2:
                year = st.selectbox("Year", ["24", "25", "26", "27"], index=1, key="admin_year")
                end_week = st.selectbox("End Week", [4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52], 
                                        index=3, key="admin_end_week")
            
            # Start week - default to this Monday
            from datetime import datetime, timedelta
            today = datetime.now()
            monday = today - timedelta(days=today.weekday())
            start_week = st.date_input("Start Week", value=monday, key="admin_start_week")
            
            # CSV file upload
            csv_file = st.file_uploader("CSV File (Name, Username columns)", type=['csv'], key="admin_csv")
            
            if st.button("📤 Upload Batch", key="admin_upload_btn", type="primary"):
                if not csv_file:
                    st.error("Please select a CSV file")
                else:
                    with st.spinner("Uploading batch..."):
                        try:
                            files = {'csv_file': (csv_file.name, csv_file.getvalue(), 'text/csv')}
                            data = {
                                AUTH_PARAM: AUTH_VALUE,
                                'action_type': 'upload',
                                'subject': subject,
                                'month': month,
                                'year': year,
                                'start_week': start_week.strftime('%Y-%m-%d'),
                                'end_week': str(end_week)
                            }
                            
                            response = requests.post(
                                f"{site_url}/tryhackme.php?page=upload",
                                data=data,
                                files=files,
                                headers=headers,
                                timeout=30
                            )
                            
                            if 'successfully' in response.text.lower() or 'batch created' in response.text.lower():
                                st.success(f"✅ Batch uploaded successfully! ({subject.lower()}{month.lower()}{year})")
                            elif 'already exists' in response.text.lower():
                                st.error("❌ Batch already exists!")
                            else:
                                st.info("Upload completed. Check the site to verify.")
                        except Exception as e:
                            st.error(f"❌ Error: {e}")
            
            st.divider()
            st.markdown("##### Or Auto-Generate from Moodle")
            st.caption("Fetch usernames from 'Account Creation Feedback' and upload directly")
            
            if st.button("🔄 Generate & Upload from Moodle", key="admin_auto_upload_btn"):
                with st.spinner("Fetching feedback data from Moodle..."):
                    try:
                        from core.api import (
                            setup_session, get_feedbacks, fetch_feedback_responses,
                            extract_thm_username, clean_name
                        )
                        import io
                        
                        course_id = st.session_state.get('selected_course', {}).get('id')
                        selected_group = st.session_state.get('selected_group')
                        selected_group_id = selected_group.get('id') if selected_group else None
                        
                        session = setup_session(st.session_state.session_id)
                        feedbacks = get_feedbacks(session, course_id)
                        
                        if not feedbacks:
                            st.error("No feedback forms found in this course.")
                        else:
                            # Find feedback form with TryHackMe data
                            feedback_name, module_id = find_thm_feedback(feedbacks)
                            
                            if not feedback_name:
                                st.error("Could not find a feedback form with TryHackMe data.")
                                st.info(f"Available: {[f[0] for f in feedbacks]}")
                            else:
                                st.info(f"Using: **{feedback_name}**")
                                
                                columns, responses = fetch_feedback_responses(
                                    st.session_state.session_id,
                                    module_id,
                                    selected_group_id
                                )
                                
                                if not responses:
                                    st.error("No responses found.")
                                else:
                                    # Find THM and Name columns using helper
                                    thm_column, name_column = find_thm_columns(columns)
                                    
                                    if not thm_column:
                                        st.error(f"No TryHackMe column found. Available: {columns}")
                                    else:
                                        # Generate CSV data
                                        csv_rows = []
                                        for response in responses:
                                            raw_name = response.get(name_column, 'Unknown')
                                            cleaned_name = clean_name(raw_name)
                                            
                                            raw_thm = response.get(thm_column, '')
                                            username = extract_thm_username(raw_thm)
                                            
                                            if username:
                                                csv_rows.append({'Name': cleaned_name, 'Username': username})
                                        
                                        if not csv_rows:
                                            st.error("No valid TryHackMe usernames found in responses.")
                                        else:
                                            st.success(f"Found {len(csv_rows)} users with TryHackMe usernames")
                                            
                                            # Create CSV in memory
                                            df_csv = pd.DataFrame(csv_rows)
                                            csv_buffer = io.StringIO()
                                            df_csv.to_csv(csv_buffer, index=False)
                                            csv_bytes = csv_buffer.getvalue().encode('utf-8')
                                            
                                            # Upload to PHP tracker
                                            with st.spinner("Uploading to TryHackMe tracker..."):
                                                batch_name = f"{subject.lower()}{month.lower()}{year}"
                                                files = {'csv_file': (f'{batch_name}.csv', csv_bytes, 'text/csv')}
                                                data = {
                                                    AUTH_PARAM: AUTH_VALUE,
                                                    'action_type': 'upload',
                                                    'subject': subject,
                                                    'month': month,
                                                    'year': year,
                                                    'start_week': start_week.strftime('%Y-%m-%d'),
                                                    'end_week': str(end_week)
                                                }
                                                
                                                response = requests.post(
                                                    f"{site_url}/tryhackme.php?page=upload",
                                                    data=data,
                                                    files=files,
                                                    headers=headers,
                                                    timeout=30
                                                )
                                                
                                                if 'successfully' in response.text.lower() or 'batch created' in response.text.lower():
                                                    st.success(f"✅ Batch '{batch_name}' created with {len(csv_rows)} users!")
                                                elif 'already exists' in response.text.lower():
                                                    st.error("❌ Batch already exists!")
                                                else:
                                                    st.info("Upload completed. Check the site to verify.")
                    except Exception as e:
                        st.error(f"❌ Error: {e}")
        
        # =====================================================================
        # Delete Batch
        # =====================================================================
        with admin_tab2:
            st.markdown("##### Delete Batch")
            st.caption("⚠️ This will permanently delete the batch and all associated data")
            
            delete_batch_name = st.text_input(
                "Batch Name", 
                value=effective_batch or "",
                placeholder="e.g., csanov25",
                key="admin_delete_batch"
            )
            
            if st.button("🗑️ Delete Batch", key="admin_delete_btn", type="secondary"):
                if not delete_batch_name:
                    st.error("Please enter a batch name")
                else:
                    with st.spinner("Deleting batch..."):
                        try:
                            data = {
                                AUTH_PARAM: AUTH_VALUE,
                                'action_type': 'delete',
                                'delete_batch': delete_batch_name.lower()
                            }
                            
                            response = requests.post(
                                f"{site_url}/tryhackme.php?page=upload",
                                data=data,
                                headers=headers,
                                timeout=30
                            )
                            
                            if 'deleted successfully' in response.text.lower():
                                st.success(f"✅ Batch '{delete_batch_name}' deleted successfully!")
                            else:
                                st.info("Delete completed. Check the site to verify.")
                        except Exception as e:
                            st.error(f"❌ Error: {e}")
        
        # =====================================================================
        # Delete Snapshots
        # =====================================================================
        with admin_tab3:
            st.markdown("##### Delete Snapshots")
            st.caption("Delete weekly snapshot data for a batch")
            
            col1, col2 = st.columns(2)
            with col1:
                snapshot_batch_name = st.text_input(
                    "Batch Name",
                    value=effective_batch or "",
                    placeholder="e.g., csanov25",
                    key="admin_snapshot_batch"
                )
            with col2:
                delete_mode = st.selectbox(
                    "Delete Mode",
                    ["latest", "all"],
                    format_func=lambda x: "Latest Week Only" if x == "latest" else "All Snapshots",
                    key="admin_delete_mode"
                )
            
            if st.button("🧹 Delete Snapshots", key="admin_delete_snapshots_btn", type="secondary"):
                if not snapshot_batch_name:
                    st.error("Please enter a batch name")
                else:
                    with st.spinner("Deleting snapshots..."):
                        try:
                            data = {
                                AUTH_PARAM: AUTH_VALUE,
                                'action_type': 'delete_snapshots',
                                'snapshot_batch': snapshot_batch_name.lower(),
                                'delete_mode': delete_mode
                            }
                            
                            response = requests.post(
                                f"{site_url}/tryhackme.php?page=upload",
                                data=data,
                                headers=headers,
                                timeout=30
                            )
                            
                            if 'deleted' in response.text.lower():
                                mode_text = "Latest week" if delete_mode == "latest" else "All"
                                st.success(f"✅ {mode_text} snapshots deleted for '{snapshot_batch_name}'!")
                            else:
                                st.info("Delete completed. Check the site to verify.")
                        except Exception as e:
                            st.error(f"❌ Error: {e}")
        
        # =====================================================================
        # Trigger Weekly Snapshot
        # =====================================================================
        with admin_tab4:
            st.markdown("##### Trigger Weekly Snapshot")
            st.caption("Manually trigger the Monday snapshot (for testing or catching up)")
            
            st.warning("⚠️ This will take a snapshot of all active batches. Use sparingly.")
            
            if st.button("⏰ Run Snapshot Now", key="admin_cron_btn", type="primary"):
                with st.spinner("Running snapshot..."):
                    try:
                        response = requests.get(
                            f"{site_url}/tryhackme.php?cron=snapshot&key={CRON_SECRET}",
                            headers=headers,
                            timeout=60
                        )
                        
                        result = response.json()
                        if result.get('success'):
                            st.success("✅ Weekly snapshot completed successfully!")
                        else:
                            st.error("❌ Error running snapshot")
                    except ValueError:
                        st.error("❌ Invalid response from server")
                    except Exception as e:
                        st.error(f"❌ Error: {e}")


def render_legacy_fetcher(course):
    """Render the legacy TryHackMe fetcher section that uses direct API calls."""
    
    # Initialize session state
    if 'thm_legacy_data' not in st.session_state:
        st.session_state.thm_legacy_data = None
    
    with st.expander("📡 Direct TryHackMe Fetch (Legacy)", expanded=False):
        st.caption("Fetch data directly from TryHackMe API using Moodle feedback responses")
        
        course_id = course.get('id')
        selected_group = st.session_state.get('selected_group')
        selected_group_id = selected_group.get('id') if selected_group else None
        
        col1, col2 = st.columns([1, 3])
        with col1:
            fetch_legacy_btn = st.button("📥 Fetch from TryHackMe", key="fetch_thm_legacy_btn")
        
        if fetch_legacy_btn:
            with st.spinner("Loading feedback data to find TryHackMe usernames..."):
                from core.api import (
                    setup_session, get_feedbacks, fetch_feedback_responses,
                    extract_thm_username, fetch_thm_user_data, clean_name
                )
                
                session = setup_session(st.session_state.session_id)
                feedbacks = get_feedbacks(session, course_id)
                
                if not feedbacks:
                    st.warning("No feedback forms found in this course.")
                    return
                
                # Find feedback form with TryHackMe data
                feedback_name, module_id = find_thm_feedback(feedbacks)
                
                if not feedback_name:
                    st.warning("Could not find a feedback form with TryHackMe data.")
                    st.info(f"Available feedbacks: {[f[0] for f in feedbacks]}")
                    return
                
                st.info(f"Using feedback: **{feedback_name}**")
            
            with st.spinner("Fetching feedback responses..."):
                columns, responses = fetch_feedback_responses(
                    st.session_state.session_id,
                    module_id,
                    selected_group_id
                )
                
                if not responses:
                    st.warning("No responses found in the feedback form.")
                    return
                
                # Find TryHackMe and Name columns
                thm_column, name_column = find_thm_columns(columns)
                
                if not thm_column:
                    st.warning("Could not find TryHackMe username column in feedback responses.")
                    st.info(f"Available columns: {columns}")
                    return
                
                st.success(f"Found {len(responses)} responses. Fetching TryHackMe data...")
            
            # Process each response and fetch TryHackMe data
            progress_bar = st.progress(0, text="Fetching TryHackMe data...")
            thm_data = []
            errors = []
            
            for i, response in enumerate(responses):
                raw_name = response.get(name_column, 'Unknown')
                cleaned_name = clean_name(raw_name)
                
                raw_thm = response.get(thm_column, '')
                username = extract_thm_username(raw_thm)
                
                if username:
                    user_data = fetch_thm_user_data(username)
                    thm_data.append({
                        'Name': cleaned_name,
                        'Username': username,
                        'Completed Rooms': user_data.get('completed_rooms', 0),
                        'Avatar': user_data.get('avatar', ''),
                        'Profile URL': f"https://tryhackme.com/p/{username}",
                        'Error': user_data.get('error', '')
                    })
                    if user_data.get('error'):
                        errors.append(f"{cleaned_name}: {user_data.get('error')}")
                else:
                    thm_data.append({
                        'Name': cleaned_name,
                        'Username': raw_thm[:30] + '...' if len(raw_thm) > 30 else raw_thm,
                        'Completed Rooms': 0,
                        'Avatar': '',
                        'Profile URL': '',
                        'Error': 'Could not parse username'
                    })
                
                progress_bar.progress((i + 1) / len(responses), 
                                      text=f"Fetching TryHackMe data... ({i+1}/{len(responses)})")
            
            progress_bar.empty()
            
            # Store in session state
            st.session_state.thm_legacy_data = thm_data
            
            if errors:
                with st.expander(f"⚠️ {len(errors)} errors encountered"):
                    for error in errors[:10]:
                        st.text(error)
                    if len(errors) > 10:
                        st.text(f"... and {len(errors) - 10} more")
            
            st.success(f"✓ Fetched data for {len(thm_data)} participants")
        
        # Display legacy data if available
        if st.session_state.thm_legacy_data:
            thm_data = st.session_state.thm_legacy_data
            
            # Sort by completed rooms (descending)
            sorted_data = sorted(thm_data, key=lambda x: x.get('Completed Rooms', 0), reverse=True)
            
            # Add rank
            for i, item in enumerate(sorted_data, 1):
                item['Rank'] = i
            
            st.markdown("##### 🏆 Direct API Leaderboard")
            
            # Summary metrics
            total_participants = len(sorted_data)
            total_rooms = sum(x.get('Completed Rooms', 0) for x in sorted_data)
            avg_rooms = total_rooms / total_participants if total_participants > 0 else 0
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Participants", total_participants)
            with col2:
                st.metric("Total Rooms", total_rooms)
            with col3:
                st.metric("Avg Rooms", f"{avg_rooms:.1f}")
            
            # Create DataFrame for display
            df = pd.DataFrame(sorted_data)
            
            # Reorder columns
            display_columns = ['Rank', 'Name', 'Username', 'Completed Rooms', 'Profile URL']
            df_display = df[[c for c in display_columns if c in df.columns]].copy()
            
            # Download button
            csv = df_display.to_csv(index=False)
            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name=f"tryhackme_direct_{course_id}.csv",
                mime="text/csv",
                key="download_thm_legacy_csv"
            )
            
            # Display as dataframe
            column_config = {
                "Rank": st.column_config.NumberColumn("🏅 Rank", width="small"),
                "Name": st.column_config.TextColumn("👤 Name", width="medium"),
                "Username": st.column_config.TextColumn("🔗 Username", width="medium"),
                "Completed Rooms": st.column_config.NumberColumn("✅ Rooms", width="small"),
                "Profile URL": st.column_config.LinkColumn(
                    "🌐 Profile",
                    display_text="View Profile",
                    width="small"
                )
            }
            
            st.dataframe(
                df_display,
                width="stretch",
                hide_index=True,
                column_config=column_config
            )
