import streamlit as st

def apply_custom_css():
    st.markdown("""
    <style>
        .main-header {
            font-size: 2.5rem;
            font-weight: 700;
            color: #1f77b4;
            margin-bottom: 0.5rem;
        }
        .sub-header {
            font-size: 1rem;
            color: #666;
            margin-bottom: 2rem;
        }
        .stale-badge {
            padding: 0.25rem 0.75rem;
            border-radius: 1rem;
            background-color: #f0f2f6;
            color: #666;
            font-size: 0.85rem;
            display: inline-block;
            margin-bottom: 1rem;
        }
        .fresh-badge {
            padding: 0.25rem 0.75rem;
            border-radius: 1rem;
            background-color: #d4edda;
            color: #155724;
            font-size: 0.85rem;
            display: inline-block;
            margin-bottom: 1rem;
        }
    </style>
    """, unsafe_allow_html=True)
