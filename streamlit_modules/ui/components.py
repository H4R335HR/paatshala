import streamlit as st
from datetime import datetime

def format_timestamp(iso_string):
    """Format ISO timestamp for display"""
    try:
        dt = datetime.fromisoformat(iso_string)
        now = datetime.now()
        diff = now - dt
        
        if diff.days == 0:
            if diff.seconds < 60:
                return "just now"
            elif diff.seconds < 3600:
                mins = diff.seconds // 60
                return f"{mins} min{'s' if mins > 1 else ''} ago"
            else:
                hours = diff.seconds // 3600
                return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif diff.days == 1:
            return f"yesterday at {dt.strftime('%I:%M %p')}"
        elif diff.days < 7:
            return f"{diff.days} days ago"
        else:
            return dt.strftime('%b %d, %Y at %I:%M %p')
    except:
        return iso_string

def show_data_status(meta, data_key, data_name):
    """Show status badge for data (loaded from disk or fresh)"""
    if data_key in meta:
        info = meta[data_key]
        timestamp = format_timestamp(info.get('updated', ''))
        rows = info.get('rows', 0)
        st.markdown(
            f'<span class="stale-badge">📂 Loaded from disk • {rows} rows • Updated {timestamp}</span>',
            unsafe_allow_html=True
        )
        return True
    return False

def show_fresh_status(rows_count):
    """Show fresh data status"""
    st.markdown(
        f'<span class="fresh-badge">✓ Fresh data • {rows_count} rows • Just now</span>',
        unsafe_allow_html=True
    )
