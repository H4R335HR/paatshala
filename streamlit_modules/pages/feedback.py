"""
Feedback tab page for Streamlit app.
Displays feedback activities, responses, and non-respondents.
"""

import streamlit as st
import pandas as pd
from core.api import (
    get_feedbacks,
    fetch_feedback_overview,
    fetch_feedback_responses,
    fetch_feedback_non_respondents,
    clean_name,
    BASE
)


def render_feedback_tab(course, meta):
    """Render the Feedback tab content"""
    course_id = course.get('id')
    
    # Get selected group from sidebar
    selected_group = st.session_state.get('selected_group')
    selected_group_id = selected_group.get('id') if selected_group else None
    
    # =========================================================================
    # Load Feedbacks List
    # =========================================================================
    if not st.session_state.feedbacks_data:
        with st.spinner("Loading feedback activities..."):
            from core.api import setup_session
            session = setup_session(st.session_state.session_id)
            feedbacks = get_feedbacks(session, course_id)
            
            if feedbacks:
                st.session_state.feedbacks_data = feedbacks
            else:
                st.info("No feedback activities found in this course.")
                return
    
    feedbacks = st.session_state.feedbacks_data
    
    if not feedbacks:
        st.info("No feedback activities found in this course.")
        return
    
    # =========================================================================
    # Feedback Selector
    # =========================================================================
    feedback_names = [f[0] for f in feedbacks]
    
    # Build mapping for lookup
    feedback_map = {f[0]: {'module_id': f[1], 'url': f[2]} for f in feedbacks}
    
    # Find current selection index
    current_idx = 0
    if st.session_state.selected_feedback:
        try:
            current_idx = feedback_names.index(st.session_state.selected_feedback)
        except ValueError:
            current_idx = 0
    
    selected_feedback_name = st.selectbox(
        "Select Feedback Form",
        feedback_names,
        index=current_idx,
        key="feedback_selector"
    )
    
    # Update selected feedback in session state
    if selected_feedback_name != st.session_state.selected_feedback:
        st.session_state.selected_feedback = selected_feedback_name
        # Clear previous data when switching feedbacks
        st.session_state.feedback_responses_data = None
        st.session_state.feedback_non_respondents_data = None
        st.session_state.feedback_overview_data = None
    
    selected_feedback = feedback_map.get(selected_feedback_name, {})
    module_id = selected_feedback.get('module_id')
    feedback_url = selected_feedback.get('url')
    
    if not module_id:
        st.warning("Could not find module ID for the selected feedback.")
        return
    
    # =========================================================================
    # Action Buttons
    # =========================================================================
    fetch_btn = st.button("📥 Fetch Data", key="fetch_feedback_btn")
    
    # =========================================================================
    # Fetch Data
    # =========================================================================
    if fetch_btn:
        with st.spinner("Fetching feedback data..."):
            # Fetch overview (with group filter)
            overview = fetch_feedback_overview(
                st.session_state.session_id,
                module_id,
                selected_group_id
            )
            st.session_state.feedback_overview_data = overview
            
            # Fetch responses
            columns, responses = fetch_feedback_responses(
                st.session_state.session_id,
                module_id,
                selected_group_id
            )
            st.session_state.feedback_responses_data = {
                'columns': columns,
                'rows': responses
            }
            
            # Fetch non-respondents
            non_respondents = fetch_feedback_non_respondents(
                st.session_state.session_id,
                module_id,
                selected_group_id
            )
            st.session_state.feedback_non_respondents_data = non_respondents
            
            st.success("Data fetched successfully!")
    
    # =========================================================================
    # Display Overview
    # =========================================================================
    if st.session_state.feedback_overview_data:
        overview = st.session_state.feedback_overview_data
        
        st.subheader("📊 Overview")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Responses", overview.get('submitted_answers', 0))
        
        with col2:
            st.metric("Questions", overview.get('questions', 0))
        
        with col3:
            allow_from = overview.get('allow_from', 'Not set')
            st.metric("Opens", allow_from[:20] + "..." if len(allow_from) > 20 else allow_from)
        
        with col4:
            allow_until = overview.get('allow_until', '')
            if allow_until:
                st.metric("Closes", allow_until[:20] + "..." if len(allow_until) > 20 else allow_until)
            else:
                st.metric("Closes", "Not set")
        
        st.divider()
    
    # =========================================================================
    # Display Responses and Non-Respondents in Sub-tabs
    # =========================================================================
    if st.session_state.feedback_responses_data or st.session_state.feedback_non_respondents_data:
        response_tab, non_respondent_tab = st.tabs(["📝 Responses", "👥 Non-Respondents"])
        
        # =====================================================================
        # Responses Tab
        # =====================================================================
        with response_tab:
            responses_data = st.session_state.feedback_responses_data
            
            if responses_data and responses_data.get('rows'):
                rows = responses_data['rows']
                columns = responses_data['columns']
                
                # Create DataFrame
                df = pd.DataFrame(rows)
                
                # Clean names - remove batch suffix from name columns
                for col in df.columns:
                    col_lower = col.lower()
                    if 'first name' in col_lower or 'firstname' in col_lower or col_lower == 'name':
                        df[col] = df[col].apply(clean_name)
                
                # Reorder columns if we have column info
                if columns:
                    # Only keep columns that exist in the DataFrame
                    ordered_cols = [c for c in columns if c in df.columns]
                    df = df[ordered_cols]
                
                st.write(f"**Total Responses: {len(df)}**")
                
                # Action buttons row - Download CSV and Open in Paatshala
                btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 3])
                with btn_col1:
                    csv = df.to_csv(index=False)
                    st.download_button(
                        label="📥 Download CSV",
                        data=csv,
                        file_name=f"feedback_{module_id}_responses.csv",
                        mime="text/csv",
                        key="download_responses_csv"
                    )
                with btn_col2:
                    if feedback_url:
                        st.link_button("🔗 Open in Paatshala", feedback_url)
                
                # Display table
                st.dataframe(df, width="stretch", hide_index=True)
            else:
                st.info("No responses found. Click 'Fetch Data' to load responses.")
        
        # =====================================================================
        # Non-Respondents Tab
        # =====================================================================
        with non_respondent_tab:
            non_respondents = st.session_state.feedback_non_respondents_data
            
            if non_respondents:
                df = pd.DataFrame(non_respondents)
                
                st.write(f"**Non-Respondents: {len(df)}**")
                
                # Action buttons row - Download CSV and Open in Paatshala
                btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 3])
                with btn_col1:
                    csv = df.to_csv(index=False)
                    st.download_button(
                        label="📥 Download CSV",
                        data=csv,
                        file_name=f"feedback_{module_id}_non_respondents.csv",
                        mime="text/csv",
                        key="download_non_respondents_csv"
                    )
                with btn_col2:
                    if feedback_url:
                        st.link_button("🔗 Open in Paatshala", feedback_url)
                
                # Display table
                st.dataframe(df, width="stretch", hide_index=True)
            else:
                st.info("No non-respondents found or all users have responded.")
    else:
        st.info("Click 'Fetch Data' to load feedback responses and non-respondents.")

