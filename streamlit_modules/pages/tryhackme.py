"""
TryHackMe tab page for Streamlit app.
Displays TryHackMe progress leaderboard for participants.
"""

import streamlit as st
import pandas as pd
from core.api import (
    get_feedbacks,
    fetch_feedback_responses,
    extract_thm_username,
    fetch_thm_user_data,
    clean_name,
    BASE
)


def render_tryhackme_tab(course, meta):
    """Render the TryHackMe tab content"""
    course_id = course.get('id')
    
    # Get selected group from sidebar
    selected_group = st.session_state.get('selected_group')
    selected_group_id = selected_group.get('id') if selected_group else None
    
    st.markdown("### 🎯 TryHackMe Progress Tracker")
    st.caption("Track participant progress on TryHackMe platform")
    
    # =========================================================================
    # Action Button
    # =========================================================================
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        fetch_btn = st.button("📥 Fetch Data", key="fetch_thm_btn", type="primary")
    with col2:
        refresh_btn = st.button("🔄 Refresh", key="refresh_thm_btn")
    
    # =========================================================================
    # Fetch TryHackMe Data
    # =========================================================================
    if fetch_btn or refresh_btn:
        with st.spinner("Loading feedback data to find TryHackMe usernames..."):
            # First, we need to find the "Account Creation Feedback" form
            from core.api import setup_session
            session = setup_session(st.session_state.session_id)
            feedbacks = get_feedbacks(session, course_id)
            
            if not feedbacks:
                st.warning("No feedback forms found in this course.")
                return
            
            # Find "Account Creation Feedback" or similar
            account_feedback = None
            for f in feedbacks:
                name = f[0].lower()
                if 'account' in name and ('creation' in name or 'feedback' in name):
                    account_feedback = f
                    break
            
            # Fallback: just use the first feedback if no match
            if not account_feedback:
                # Look for any feedback with "tryhackme" in name
                for f in feedbacks:
                    if 'tryhackme' in f[0].lower():
                        account_feedback = f
                        break
            
            if not account_feedback:
                st.warning("Could not find 'Account Creation Feedback' form. Please ensure it exists in this course.")
                st.info(f"Available feedbacks: {[f[0] for f in feedbacks]}")
                return
            
            module_id = account_feedback[1]
            st.info(f"Using feedback: **{account_feedback[0]}**")
        
        with st.spinner("Fetching feedback responses..."):
            # Fetch responses from this feedback
            columns, responses = fetch_feedback_responses(
                st.session_state.session_id,
                module_id,
                selected_group_id
            )
            
            if not responses:
                st.warning("No responses found in the feedback form.")
                return
            
            # Find the column that contains TryHackMe usernames
            thm_column = None
            name_column = None
            
            for col in columns:
                col_lower = col.lower()
                if 'tryhackme' in col_lower or 'thm' in col_lower:
                    thm_column = col
                elif 'first name' in col_lower or 'firstname' in col_lower:
                    name_column = col
            
            if not thm_column:
                st.warning("Could not find TryHackMe username column in feedback responses.")
                st.info(f"Available columns: {columns}")
                return
            
            if not name_column:
                # Try to find any name column
                for col in columns:
                    if 'name' in col.lower():
                        name_column = col
                        break
            
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
        st.session_state.tryhackme_data = thm_data
        
        if errors:
            with st.expander(f"⚠️ {len(errors)} errors encountered"):
                for error in errors[:10]:  # Show first 10 errors
                    st.text(error)
                if len(errors) > 10:
                    st.text(f"... and {len(errors) - 10} more")
        
        st.success(f"✓ Fetched data for {len(thm_data)} participants")
    
    # =========================================================================
    # Display Leaderboard
    # =========================================================================
    if st.session_state.tryhackme_data:
        thm_data = st.session_state.tryhackme_data
        
        # Sort by completed rooms (descending)
        sorted_data = sorted(thm_data, key=lambda x: x.get('Completed Rooms', 0), reverse=True)
        
        # Add rank
        for i, item in enumerate(sorted_data, 1):
            item['Rank'] = i
        
        st.divider()
        st.subheader("🏆 TryHackMe Leaderboard")
        
        # Summary metrics
        total_participants = len(sorted_data)
        total_rooms = sum(x.get('Completed Rooms', 0) for x in sorted_data)
        avg_rooms = total_rooms / total_participants if total_participants > 0 else 0
        top_performer = sorted_data[0] if sorted_data else None
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Participants", total_participants)
        with col2:
            st.metric("Total Rooms", total_rooms)
        with col3:
            st.metric("Avg Rooms", f"{avg_rooms:.1f}")
        with col4:
            if top_performer:
                st.metric("Top Performer", f"{top_performer.get('Completed Rooms', 0)} rooms")
        
        st.divider()
        
        # Create DataFrame for display
        df = pd.DataFrame(sorted_data)
        
        # Reorder columns
        display_columns = ['Rank', 'Name', 'Username', 'Completed Rooms', 'Profile URL']
        df_display = df[[c for c in display_columns if c in df.columns]].copy()
        
        # Download button
        col1, col2 = st.columns([1, 4])
        with col1:
            csv = df_display.to_csv(index=False)
            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name=f"tryhackme_leaderboard_{course_id}.csv",
                mime="text/csv",
                key="download_thm_csv"
            )
        
        # Display as dataframe with clickable links
        # Create a column config for the Profile URL to make it clickable
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
        
    else:
        st.info("👆 Click 'Fetch Data' to load TryHackMe progress data.")
        st.markdown("""
        **How it works:**
        1. Fetches responses from the "Account Creation Feedback" form
        2. Extracts TryHackMe usernames from responses
        3. Queries TryHackMe API for each user's completed rooms
        4. Displays a ranked leaderboard
        
        **Note:** Group filtering from the sidebar will be applied.
        """)
