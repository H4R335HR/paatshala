"""
Presentation tab for Streamlit app.
Manages presentation sessions with student voting and instructor scoring.
"""

import streamlit as st
import requests
import json
from datetime import datetime, timedelta

from core.persistence import get_config, get_output_dir

# Default HTTP headers
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json,text/html,*/*;q=0.8',
}


def get_presentation_url():
    """Get presentation portal URL from config."""
    return get_config('presentation_url', 'https://ictak.online/presentation.php')


def get_admin_auth():
    """Get admin auth params from config."""
    return {
        get_config('thm_auth_param', 'auth0r1ty'): get_config('thm_auth_value', 'l3tm3in')
    }


def api_call(action, batch, data=None, admin=False):
    """Make API call to presentation portal."""
    base_url = get_presentation_url()
    auth = get_admin_auth()
    
    if admin:
        url = f"{base_url}?admin={action}&b={batch}"
        params = {**auth, **(data or {})}
    else:
        url = f"{base_url}?action={action}&b={batch}"
        params = data or {}
    
    try:
        if data:
            response = requests.post(url, data={**auth, **params}, headers=DEFAULT_HEADERS, timeout=30)
        else:
            response = requests.get(url, params=auth, headers=DEFAULT_HEADERS, timeout=30)
        return response.json()
    except Exception as e:
        return {'error': str(e)}


def render_presentation_tab(course, meta):
    """Render the Presentation Sessions tab."""
    
    st.markdown("### 🎤 Presentation Sessions")
    st.caption("Manage student presentation sessions with live voting")
    
    # Get batch name from selected group
    from streamlit_modules.pages.tryhackme import extract_batch_name
    selected_group = st.session_state.get('selected_group')
    batch = extract_batch_name(selected_group.get('name', '')) if selected_group else ''
    
    if not batch:
        st.warning("⚠️ Please select a group in the sidebar to manage presentations.")
        return
    
    st.info(f"📍 Batch: **{batch.upper()}**")
    
    # Initialize session state
    if 'pres_session_data' not in st.session_state:
        st.session_state.pres_session_data = None
    if 'pres_slots' not in st.session_state:
        st.session_state.pres_slots = []
    if 'pres_presenters' not in st.session_state:
        st.session_state.pres_presenters = []
    
    # Fetch data button
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("🔄 Refresh", key="pres_refresh"):
            with st.spinner("Fetching data..."):
                result = api_call('session_info', batch)
                if result.get('success'):
                    st.session_state.pres_session_data = result.get('session')
                    st.session_state.pres_slots = result.get('slots', [])
                    st.session_state.pres_presenters = result.get('presenters', [])
                    st.rerun()
                elif result.get('error'):
                    st.error(f"Error: {result['error']}")
    
    # Create tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Session", "📅 Slots", "🎯 Live Dashboard", "📊 Results"])
    
    # =========================================================================
    # TAB 1: Session Management
    # =========================================================================
    with tab1:
        session = st.session_state.pres_session_data
        
        if not session:
            st.markdown("#### Create New Session")
            
            with st.form("create_session"):
                title = st.text_input("Session Title", value="Cyberattacks & Breaches Presentations")
                
                col1, col2 = st.columns(2)
                with col1:
                    instructor_weight = st.slider("Instructor Weight", 0.0, 1.0, 0.6, 0.1)
                with col2:
                    voting_duration = st.number_input("Voting Duration (min)", 5, 30, 15)
                
                if st.form_submit_button("✨ Create Session", type="primary"):
                    result = api_call('create_session', batch, {
                        'title': title,
                        'instructor_weight': instructor_weight,
                        'audience_weight': 1 - instructor_weight,
                        'voting_duration': voting_duration
                    }, admin=True)
                    
                    if result.get('success'):
                        st.success("✅ Session created!")
                        st.session_state.pres_session_data = result.get('session')
                        st.rerun()
                    else:
                        st.error(f"Error: {result.get('error', 'Unknown error')}")
        else:
            st.markdown(f"#### {session.get('title', 'Session')}")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Status", session.get('status', 'unknown').title())
            with col2:
                st.metric("Instructor Weight", f"{session.get('instructor_weight', 0.6):.0%}")
            with col3:
                st.metric("Voting Duration", f"{session.get('voting_duration', 15)} min")
            
            # Registrations summary
            presenters = st.session_state.pres_presenters
            st.markdown(f"**Registered:** {len(presenters)} students")
            
            if presenters:
                with st.expander("📋 Manage Registrations", expanded=False):
                    for p in presenters:
                        status_icon = {'registered': '⏳', 'scheduled': '📅', 'presenting': '🎯', 'completed': '✅'}.get(p.get('status'), '❓')
                        col_info, col_link, col_action = st.columns([3, 1, 1])
                        with col_info:
                            st.markdown(f"{status_icon} **{p.get('name')}** - {p.get('topic', 'No topic')}")
                        with col_link:
                            if p.get('link'):
                                st.markdown(f"[🔗 Open]({p.get('link')})")
                        with col_action:
                            if p.get('status') == 'registered':
                                if st.button("🗑️", key=f"dereg_{p.get('id')}", help="Deregister student"):
                                    result = api_call('deregister', batch, {'presenter_id': p.get('id')}, admin=True)
                                    if result.get('success'):
                                        st.success(f"Deregistered {p.get('name')}")
                                        # Refresh
                                        refresh = api_call('session_info', batch)
                                        if refresh.get('success'):
                                            st.session_state.pres_presenters = refresh.get('presenters', [])
                                        st.rerun()
                                    else:
                                        st.error(result.get('error', 'Failed'))
                        st.divider()
    
    # =========================================================================
    # TAB 2: Slot Management
    # =========================================================================
    with tab2:
        st.markdown("#### Presentation Slots")
        
        # Add new slot
        with st.expander("➕ Add New Slot", expanded=False):
            # Use session state to track slot creation counter for unique keys
            if 'slot_counter' not in st.session_state:
                st.session_state.slot_counter = 0
            
            col1, col2 = st.columns(2)
            with col1:
                slot_date = st.date_input(
                    "Date", 
                    value=datetime.now().date(),
                    key=f"slot_date_{batch}"
                )
            with col2:
                slot_time = st.time_input(
                    "Time", 
                    value=datetime.now().replace(second=0, microsecond=0).time(),
                    key=f"slot_time_{batch}"
                )
            
            if st.button("Add Slot", type="primary", key="add_slot_btn"):
                dt = datetime.combine(slot_date, slot_time)
                result = api_call('create_slot', batch, {'datetime': dt.isoformat()}, admin=True)
                if result.get('success'):
                    st.success(f"✅ Slot created for {dt.strftime('%b %d, %I:%M %p')}!")
                    st.session_state.slot_counter += 1
                    # Refresh
                    refresh_result = api_call('session_info', batch)
                    if refresh_result.get('success'):
                        st.session_state.pres_slots = refresh_result.get('slots', [])
                    st.rerun()
                else:
                    st.error(f"Error: {result.get('error')}")
        
        # Display slots
        slots = st.session_state.pres_slots
        if not slots:
            st.info("No slots created yet. Add slots above.")
        else:
            # Sort by datetime
            slots_sorted = sorted(slots, key=lambda x: x.get('datetime', ''))
            
            for slot in slots_sorted:
                dt_str = slot.get('datetime', '')
                try:
                    dt = datetime.fromisoformat(dt_str)
                    dt_display = dt.strftime('%b %d, %I:%M %p')
                except:
                    dt_display = dt_str
                
                status = slot.get('status', 'open')
                status_colors = {'open': '🟢', 'locked': '🟡', 'presenting': '🔴', 'completed': '⚪'}
                
                with st.container():
                    col1, col2, col3, col4 = st.columns([2, 2, 1, 0.5])
                    with col1:
                        st.markdown(f"{status_colors.get(status, '⚪')} **{dt_display}**")
                        if slot.get('presenter_name'):
                            st.caption(f"{slot.get('presenter_name')} - {slot.get('topic', '')}")
                    with col2:
                        st.caption(f"Status: {status.title()}")
                    with col3:
                        if status == 'open':
                            # Show assign button
                            presenters = st.session_state.pres_presenters
                            available = [p for p in presenters if p.get('status') == 'registered']
                            if available and st.button("Assign", key=f"assign_{slot['id']}"):
                                st.session_state[f"show_assign_{slot['id']}"] = True
                        elif status == 'locked':
                            if st.button("▶️ Start", key=f"start_{slot['id']}"):
                                result = api_call('start_slot', batch, {'slot_id': slot['id']}, admin=True)
                                if result.get('success'):
                                    st.success("Presentation started!")
                                    st.rerun()
                        elif status == 'presenting':
                            if st.button("⏹ End", key=f"end_{slot['id']}"):
                                result = api_call('end_slot', batch, {'slot_id': slot['id']}, admin=True)
                                if result.get('success'):
                                    st.success("Presentation ended!")
                                    st.rerun()
                    with col4:
                        # Delete button (for open, locked, and completed slots - not while presenting)
                        if status in ['open', 'locked', 'completed']:
                            if st.button("🗑️", key=f"del_{slot['id']}", help="Delete slot"):
                                result = api_call('delete_slot', batch, {'slot_id': slot['id']}, admin=True)
                                if result.get('success'):
                                    st.success("Slot deleted!")
                                    # Refresh
                                    refresh = api_call('session_info', batch)
                                    if refresh.get('success'):
                                        st.session_state.pres_slots = refresh.get('slots', [])
                                    st.rerun()
                                else:
                                    st.error(result.get('error', 'Failed'))
                    
                    # Assignment dialog
                    if st.session_state.get(f"show_assign_{slot['id']}"):
                        presenters = st.session_state.pres_presenters
                        available = [p for p in presenters if p.get('status') == 'registered']
                        options = {f"{p['name']} - {p['topic']}": p['id'] for p in available}
                        
                        selected = st.selectbox("Select presenter", list(options.keys()), key=f"sel_{slot['id']}")
                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button("Confirm", key=f"confirm_{slot['id']}"):
                                result = api_call('assign_slot', batch, {
                                    'slot_id': slot['id'],
                                    'presenter_id': options[selected]
                                }, admin=True)
                                if result.get('success'):
                                    st.success("Assigned!")
                                    st.session_state[f"show_assign_{slot['id']}"] = False
                                    st.rerun()
                        with col_b:
                            if st.button("Cancel", key=f"cancel_{slot['id']}"):
                                st.session_state[f"show_assign_{slot['id']}"] = False
                                st.rerun()
                    
                    st.divider()
    
    # =========================================================================
    # TAB 3: Live Dashboard
    # =========================================================================
    with tab3:
        st.markdown("#### 🎯 Live Dashboard")
        
        # Find active slot
        slots = st.session_state.pres_slots
        active_slot = next((s for s in slots if s.get('status') == 'presenting'), None)
        
        if not active_slot:
            st.info("No presentation currently active. Start a slot from the Slots tab.")
        else:
            st.markdown(f"### 🎤 Now Presenting: {active_slot.get('presenter_name', 'Unknown')}")
            st.markdown(f"**Topic:** {active_slot.get('topic', 'N/A')}")
            
            # Timer
            started_at = active_slot.get('started_at')
            timer_expired = False
            if started_at:
                session = st.session_state.pres_session_data or {}
                duration = session.get('voting_duration', 15) * 60
                try:
                    started = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                    elapsed = (datetime.now(started.tzinfo) - started).total_seconds()
                except:
                    started = datetime.fromisoformat(started_at[:19])
                    elapsed = (datetime.now() - started).total_seconds()
                remaining = max(0, duration - elapsed)
                timer_expired = remaining <= 0
                
                mins, secs = divmod(int(remaining), 60)
                if timer_expired:
                    st.warning("⏰ **Timer Expired!** Click 'End Presentation' below to finalize.")
                else:
                    st.metric("⏱️ Time Remaining", f"{mins:02d}:{secs:02d}")
            
            # Show End button prominently if timer expired
            if timer_expired:
                if st.button("⏹ End Presentation & Calculate Results", type="primary", key="end_expired"):
                    result = api_call('end_slot', batch, {'slot_id': active_slot['id']}, admin=True)
                    if result.get('success'):
                        st.success("✅ Presentation ended! Check Results tab.")
                        # Refresh
                        refresh = api_call('session_info', batch)
                        if refresh.get('success'):
                            st.session_state.pres_slots = refresh.get('slots', [])
                            st.session_state.pres_presenters = refresh.get('presenters', [])
                        st.rerun()
            
            st.divider()
            
            # Check if instructor already scored
            votes_result = api_call('get_votes', batch, {'slot_id': active_slot['id']}, admin=True)
            existing_instructor_score = None
            if votes_result.get('success'):
                for v in votes_result.get('votes', []):
                    if v.get('type') == 'instructor':
                        existing_instructor_score = v
                        break
            
            if existing_instructor_score:
                st.success(f"✅ You already scored this presentation (Total: {existing_instructor_score.get('total', 'N/A')})")
                st.caption("Submitting again will update your score.")
            
            # Instructor scoring
            st.markdown("#### 📝 Instructor Score")
            
            rubric = (st.session_state.pres_session_data or {}).get('rubric', [
                {'id': 1, 'name': 'Content Knowledge'},
                {'id': 2, 'name': 'Clarity & Delivery'},
                {'id': 3, 'name': 'Visual Quality'},
                {'id': 4, 'name': 'Engagement'},
                {'id': 5, 'name': 'Time Management'}
            ])
            
            scores = {}
            for criterion in rubric:
                cid = str(criterion['id'])
                st.markdown(f"**{criterion['name']}**")
                score = st.radio(
                    f"Score for {criterion['name']}",
                    options=[1, 2, 3],
                    format_func=lambda x: {1: '👍 OK', 2: '⭐ Good', 3: '🌟 Brilliant'}[x],
                    horizontal=True,
                    key=f"score_{cid}",
                    label_visibility="collapsed"
                )
                scores[cid] = score
            
            comment = st.text_area("Comments", key="instructor_comment")
            
            if st.button("💾 Submit Instructor Score", type="primary"):
                result = api_call('instructor_score', batch, {
                    'slot_id': active_slot['id'],
                    'scores': json.dumps(scores),
                    'comment': comment
                }, admin=True)
                
                if result.get('success'):
                    st.success(f"✅ Score submitted! Total: {result.get('total')}")
                else:
                    st.error(f"Error: {result.get('error')}")
    
    # =========================================================================
    # TAB 4: Results
    # =========================================================================
    with tab4:
        st.markdown("#### 📊 Results & Leaderboard")
        
        if st.button("🔄 Load Results"):
            result = api_call('leaderboard', batch)
            if result.get('success'):
                st.session_state.pres_leaderboard = result.get('leaderboard', [])
        
        leaderboard = st.session_state.get('pres_leaderboard', [])
        
        if not leaderboard:
            st.info("No completed presentations yet.")
        else:
            import pandas as pd
            df = pd.DataFrame(leaderboard)
            df.insert(0, 'Rank', range(1, len(df) + 1))
            
            # Add medal emojis
            df['Rank'] = df['Rank'].apply(lambda x: {1: '🥇', 2: '🥈', 3: '🥉'}.get(x, str(x)))
            
            st.dataframe(df, hide_index=True, width='stretch')
            
            # Export
            csv = df.to_csv(index=False)
            st.download_button(
                "📥 Download CSV",
                data=csv,
                file_name=f"presentation_results_{batch}.csv",
                mime="text/csv"
            )
