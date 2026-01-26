"""
AI Debug page for Streamlit app.
Displays AI request/response logs for debugging and optimization.
"""

import streamlit as st
from datetime import datetime


def render_ai_debug_tab(course=None, meta=None):
    """Render the AI Debug tab with request/response logs."""
    st.header("🔬 AI Debug Logs")
    st.caption("View AI request/response history for debugging and optimization.")
    
    # Import here to avoid circular imports
    from core.ai import get_ai_logs, clear_ai_logs, get_key_stats, get_api_keys, reset_daily_key_stats, reset_single_key_daily_stats
    
    # ========== API KEYS STATISTICS SECTION ==========
    st.subheader("🔑 API Keys Statistics")
    
    key_stats = get_key_stats()
    configured_keys = get_api_keys()
    active_key = key_stats.get("active_key")
    
    if not configured_keys:
        st.info("No API keys configured. Add keys in the Config tab.")
    else:
        # Controls row for key stats
        col1, col2 = st.columns([3, 1])
        with col1:
            st.caption(f"Last reset: {key_stats.get('last_reset_date', 'Never')}")
        with col2:
            if st.button("🔄 Reset All Stats", key="reset_key_stats"):
                if reset_daily_key_stats():
                    st.toast("All daily stats reset!", icon="✅")
                    st.rerun()
        
        # Build table data with per-key reset functionality
        import pandas as pd
        table_data = []
        for key_info in configured_keys:
            key_name = key_info.get("name", "Unknown")
            stats = key_stats.get("keys", {}).get(key_name, {})
            
            # Determine status
            if stats.get("quota_exhausted"):
                status = "🔴 Quota Exhausted"
            elif key_name == active_key:
                status = "🟢 Active"
            elif stats.get("last_used"):
                status = "⚪ Idle"
            else:
                status = "⚫ Never Used"
            
            # Format last used time
            last_used = stats.get("last_used")
            if last_used:
                try:
                    ts = datetime.fromisoformat(last_used)
                    last_used_str = ts.strftime("%H:%M:%S")
                except:
                    last_used_str = "Unknown"
            else:
                last_used_str = "—"
            
            table_data.append({
                "Key Name": key_name,
                "Status": status,
                "Calls Today": stats.get("call_count_today", 0),
                "Errors Today": stats.get("error_count_today", 0),
                "Last Used": last_used_str,
                "Total Calls": stats.get("total_calls", 0)
            })
        
        # Display as dataframe for overview
        df = pd.DataFrame(table_data)
        st.dataframe(df, width="stretch", hide_index=True)
        
        # Per-key reset section - scalable dropdown approach
        with st.expander("🔧 Individual Key Actions", expanded=False):
            # Build options with stats for context
            key_options = []
            for key_info in configured_keys:
                key_name = key_info.get("name", "Unknown")
                stats = key_stats.get("keys", {}).get(key_name, {})
                calls = stats.get("call_count_today", 0)
                errors = stats.get("error_count_today", 0)
                exhausted = "🔴" if stats.get("quota_exhausted") else ""
                key_options.append(f"{key_name} ({calls} calls, {errors} errors) {exhausted}".strip())
            
            col1, col2 = st.columns([3, 1])
            with col1:
                selected = st.selectbox(
                    "Select API key to reset",
                    options=key_options,
                    key="single_key_reset_select",
                    label_visibility="collapsed"
                )
            with col2:
                if st.button("🔄 Reset Key", key="reset_single_key_btn", width='stretch'):
                    # Extract key name from selection (before the first " (")
                    selected_key_name = selected.split(" (")[0] if selected else None
                    if selected_key_name and reset_single_key_daily_stats(selected_key_name):
                        st.toast(f"Reset stats for '{selected_key_name}'", icon="✅")
                        st.rerun()
                    else:
                        st.toast("Failed to reset key", icon="❌")
        
        # Google Cloud Console link
        st.markdown(
            "📊 [View quotas in Google Cloud Console]"
            "(https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com/quotas) "
            "— Select your project to see official usage data."
        )
    
    st.divider()
    
    # ========== DEBUG LOGS SECTION ==========
    st.subheader("📋 Request Logs")
    
    # Controls row
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        limit = st.selectbox(
            "Show entries",
            options=[10, 25, 50, 100],
            index=1,
            key="ai_debug_limit"
        )
    
    with col2:
        function_filter = st.selectbox(
            "Filter by function",
            options=["All", "generate_rubric", "refine_rubric", "score_submission", "refine_evaluation"],
            key="ai_debug_filter"
        )
    
    with col3:
        if st.button("🗑️ Clear Logs", type="secondary"):
            if clear_ai_logs():
                st.toast("✅ Logs cleared!", icon="✅")
                st.rerun()
            else:
                st.error("Failed to clear logs")
    
    # Get logs
    logs = get_ai_logs(limit=limit)
    
    # Apply filter
    if function_filter != "All":
        logs = [log for log in logs if log.get("function") == function_filter]
    
    if not logs:
        st.info("No AI logs yet. Perform an AI operation (generate rubric, score submission, etc.) to see logs here.")
        return

    
    # Stats row
    success_count = sum(1 for log in logs if log.get("success"))
    error_count = len(logs) - success_count
    avg_duration = sum(log.get("duration_ms", 0) for log in logs) / len(logs) if logs else 0
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Shown", len(logs))
    with col2:
        st.metric("Successful", success_count)
    with col3:
        st.metric("Errors", error_count)
    with col4:
        st.metric("Avg Duration", f"{avg_duration:.0f}ms")
    
    st.divider()
    
    # Display logs
    for log in logs:
        # Status indicator
        status_icon = "✅" if log.get("success") else "❌"
        
        # Format timestamp
        try:
            ts = datetime.fromisoformat(log.get("timestamp", ""))
            time_str = ts.strftime("%H:%M:%S")
            date_str = ts.strftime("%Y-%m-%d")
        except:
            time_str = "Unknown"
            date_str = ""
        
        # Build header
        func_name = log.get("function", "unknown")
        model = log.get("model", "unknown")
        duration = log.get("duration_ms", 0)
        num_images = log.get("num_images", 0)
        
        # Header with key info
        header = f"{status_icon} **{func_name}** | `{model}` | {duration}ms"
        if num_images > 0:
            header += f" | 🖼️ {num_images} images"
        header += f" | {time_str}"
        if date_str:
            header += f" ({date_str})"
        
        with st.expander(header, expanded=False):
            # Error message if failed
            if not log.get("success") and log.get("error"):
                st.error(f"**Error:** {log.get('error')}")
            
            # Tabs for prompt and response
            tab1, tab2 = st.tabs(["📤 Prompt", "📥 Response"])
            
            with tab1:
                # Show preview first, then expandable full
                st.text_area(
                    "Prompt Preview",
                    value=log.get("prompt_preview", ""),
                    height=150,
                    disabled=True,
                    key=f"prompt_preview_{log.get('id')}"
                )
                
                if len(log.get("prompt_full", "")) > len(log.get("prompt_preview", "")):
                    with st.expander("Show Full Prompt"):
                        st.code(log.get("prompt_full", ""), language=None)
            
            with tab2:
                st.text_area(
                    "Response Preview",
                    value=log.get("response_preview", ""),
                    height=150,
                    disabled=True,
                    key=f"response_preview_{log.get('id')}"
                )
                
                if len(log.get("response_full", "")) > len(log.get("response_preview", "")):
                    with st.expander("Show Full Response"):
                        st.code(log.get("response_full", ""), language="json")
            
            # Metadata row
            st.caption(f"ID: {log.get('id')} | Logged at: {log.get('timestamp')}")
