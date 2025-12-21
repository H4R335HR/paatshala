"""
Configuration page for Streamlit app.
Centralizes all configuration values (credentials, API keys, URLs).
"""

import streamlit as st
from core.persistence import (
    get_config, set_config, get_all_config, 
    SENSITIVE_KEYS, CONFIG_FILE
)
import os

# Define all configurable settings with their metadata
CONFIG_SCHEMA = {
    "Moodle": {
        "moodle_url": {
            "label": "Moodle URL",
            "help": "Base URL of your Moodle/Paatshala instance",
            "default": "https://paatshala.ictkerala.org",
            "type": "url"
        },
        "username": {
            "label": "Username",
            "help": "Moodle login username",
            "default": "",
            "type": "text"
        },
        "password": {
            "label": "Password",
            "help": "Moodle login password",
            "default": "",
            "type": "password"
        },
        "cookie": {
            "label": "Session Cookie",
            "help": "MoodleSession cookie (alternative to username/password)",
            "default": "",
            "type": "password"
        }
    },
    "TryHackMe": {
        "thm_base_url": {
            "label": "Tracker URL",
            "help": "TryHackMe tracker PHP page URL",
            "default": "https://ictak.online/tryhackme.php",
            "type": "url"
        },
        "thm_auth_param": {
            "label": "Auth Param Name",
            "help": "Admin authentication parameter name",
            "default": "auth0r1ty",
            "type": "text"
        },
        "thm_auth_value": {
            "label": "Auth Param Value",
            "help": "Admin authentication parameter value",
            "default": "",
            "type": "password"
        },
        "thm_cron_secret": {
            "label": "Cron Secret",
            "help": "Secret key for triggering snapshots",
            "default": "",
            "type": "password"
        }
    },
    "Wayground": {
        "wayground_url": {
            "label": "Wayground URL",
            "help": "Base URL for Wayground/Quizizz",
            "default": "https://wayground.com",
            "type": "url"
        },
        "quizizz_tracker_url": {
            "label": "Leaderboard Tracker URL",
            "help": "Full URL to quizizz.php tracker (e.g., https://ictak.online/quizizz.php)",
            "default": "",
            "type": "url"
        },
        "wayground_email": {
            "label": "Email",
            "help": "Wayground login email",
            "default": "",
            "type": "text"
        },
        "wayground_password": {
            "label": "Password",
            "help": "Wayground login password",
            "default": "",
            "type": "password"
        }
    },
    "AI / Gemini": {
        "gemini_api_key": {
            "label": "API Key",
            "help": "Gemini API key from Google AI Studio (https://aistudio.google.com/app/apikey)",
            "default": "",
            "type": "password"
        },
        "gemini_model": {
            "label": "Model",
            "help": "Gemini model to use (e.g., gemini-2.5-flash, gemini-2.0-flash, gemini-1.5-pro)",
            "default": "gemini-2.5-flash",
            "type": "text"
        },
        "github_pat": {
            "label": "GitHub PAT (Optional)",
            "help": "Personal Access Token for GitHub API. Optional - increases rate limit from 60/hr to 5000/hr. Create at github.com/settings/tokens (no scopes needed for public repos)",
            "default": "",
            "type": "password"
        }
    },
    "Google Drive": {
        "google_drive_folder_url": {
            "label": "Default Folder URL",
            "help": "Default Google Drive folder URL for Video Importer",
            "default": "",
            "type": "url"
        },
        "google_drive_credentials": {
            "label": "Credentials File Path",
            "help": "Path to Google Drive service account JSON file (for Video Importer)",
            "default": "",
            "type": "text"
        }
    }
}


def render_config_page():
    """Render the configuration page."""
    st.title("⚙️ Configuration")
    st.caption("Manage application settings, credentials, and API keys.")
    
    # Show config file status
    if os.path.exists(CONFIG_FILE):
        mtime = os.path.getmtime(CONFIG_FILE)
        from datetime import datetime
        last_modified = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        st.info(f"📄 Config file: `{CONFIG_FILE}` | Last modified: {last_modified}")
    else:
        st.warning(f"📄 No config file found. Settings will be saved to `{CONFIG_FILE}`")
    
    # Load current config values (unmasked for form defaults)
    current_config = get_all_config(mask_sensitive=False)
    
    # Track changes
    changes = {}
    
    # Render each category
    for category, settings in CONFIG_SCHEMA.items():
        with st.expander(f"**{category}**", expanded=True):
            cols = st.columns(2)
            col_idx = 0
            
            for key, meta in settings.items():
                with cols[col_idx % 2]:
                    current_value = current_config.get(key, "") or current_config.get(key.lower(), "")
                    
                    # For sensitive fields, show placeholder
                    if meta["type"] == "password":
                        # If there's an existing value, show a helper message
                        if current_value:
                            st.caption(f"🔒 {meta['label']} is set")
                        
                        new_value = st.text_input(
                            meta["label"],
                            value="",  # Always empty for password fields
                            type="password",
                            help=meta["help"],
                            placeholder="Enter new value to update" if current_value else "Enter value",
                            key=f"config_{key}"
                        )
                        # Only track if user entered something
                        if new_value:
                            changes[key] = new_value
                    else:
                        # For non-password fields, show current value or default
                        display_value = current_value if current_value else meta["default"]
                        new_value = st.text_input(
                            meta["label"],
                            value=display_value,
                            help=meta["help"],
                            key=f"config_{key}"
                        )
                        # Only track as change if:
                        # 1. User changed from existing saved value, OR
                        # 2. User changed from default AND there's no saved value
                        if current_value and new_value != current_value:
                            # Changed from saved value
                            changes[key] = new_value
                        elif not current_value and new_value != meta["default"]:
                            # Changed from default (and nothing was saved before)
                            changes[key] = new_value
                
                col_idx += 1
    
    # Tab Order Section
    with st.expander("**📑 Tab Order**", expanded=False):
        st.caption("Use ↑↓ arrows to reorder tabs")
        
        from streamlit_modules.tab_registry import TAB_REGISTRY, get_all_tab_ids
        from core.persistence import get_enabled_tabs, set_enabled_tabs
        
        all_tab_ids = get_all_tab_ids()
        current_enabled = get_enabled_tabs()
        
        # Initialize session state for tab order if not exists
        if 'temp_tab_order' not in st.session_state:
            st.session_state.temp_tab_order = current_enabled.copy()
        
        # Show current order with up/down buttons
        for idx, tab_id in enumerate(st.session_state.temp_tab_order):
            tab_info = TAB_REGISTRY.get(tab_id)
            if not tab_info:
                continue
            
            col1, col2, col3 = st.columns([4, 1, 1])
            
            with col1:
                st.text(f"{idx + 1}. {tab_info['name']}")
            
            with col2:
                # Up button (disabled if first)
                if st.button("↑", key=f"up_{tab_id}", disabled=(idx == 0)):
                    # Swap with previous
                    st.session_state.temp_tab_order[idx], st.session_state.temp_tab_order[idx - 1] = \
                        st.session_state.temp_tab_order[idx - 1], st.session_state.temp_tab_order[idx]
                    st.rerun()
            
            with col3:
                # Down button (disabled if last)
                if st.button("↓", key=f"down_{tab_id}", disabled=(idx == len(st.session_state.temp_tab_order) - 1)):
                    # Swap with next
                    st.session_state.temp_tab_order[idx], st.session_state.temp_tab_order[idx + 1] = \
                        st.session_state.temp_tab_order[idx + 1], st.session_state.temp_tab_order[idx]
                    st.rerun()
        
        st.divider()
        
        # Save and Reset buttons
        col1, col2 = st.columns(2)
        
        with col1:
            # Save button (only enabled if order changed)
            order_changed = st.session_state.temp_tab_order != current_enabled
            if st.button("💾 Save Tab Order", type="primary", disabled=not order_changed, use_container_width=True):
                if set_enabled_tabs(st.session_state.temp_tab_order):
                    # Clear the temp state so it reloads from config
                    del st.session_state.temp_tab_order
                    st.toast("✅ Tab order saved!", icon="✅")
                    st.rerun()
                else:
                    st.error("❌ Failed to save tab order")
        
        with col2:
            # Reset button
            if st.button("🔄 Reset Order", disabled=not order_changed, use_container_width=True):
                st.session_state.temp_tab_order = current_enabled.copy()
                st.rerun()
    
    st.divider()
    
    # Save button
    col1, col2, col3 = st.columns([1, 1, 3])
    
    with col1:
        if st.button("💾 Save Changes", type="primary", disabled=len(changes) == 0):
            success_count = 0
            for key, value in changes.items():
                if set_config(key, value):
                    success_count += 1
            
            if success_count == len(changes):
                st.success(f"✅ Saved {success_count} setting(s)")
                # Clear password field widget states to prevent "pending change" bug
                for key in changes.keys():
                    widget_key = f"config_{key}"
                    if widget_key in st.session_state:
                        del st.session_state[widget_key]
                st.rerun()
            else:
                st.error("❌ Some settings failed to save")
    
    with col2:
        if changes:
            st.caption(f"📝 {len(changes)} pending change(s)")
    
    # Show current config summary
    with st.expander("📋 Current Config File Contents", expanded=False):
        masked_config = get_all_config(mask_sensitive=True)
        if masked_config:
            for key, value in masked_config.items():
                st.text(f"{key}={value}")
        else:
            st.text("No configuration saved yet.")
    
    # Help section
    with st.expander("ℹ️ Help", expanded=False):
        st.markdown("""
        ### About Configuration
        
        - **Passwords** are write-only. You can set new values, but existing passwords are not displayed.
        - All settings are saved to the `.config` file in the project root.
        - Changes take effect immediately for most settings.
        - Some URL changes may require app restart.
        
        ### Config File Format
        
        The `.config` file uses simple `key=value` format:
        ```
        username=myuser
        password=mypassword
        moodle_url=https://example.com
        ```
        
        ### Tab Management
        
        - **Enable/Disable Tabs**: Use the "📑 Manage Tabs" dropdown in the sidebar
        - **Reorder Tabs**: Use the "📑 Tab Order" section above to set tab positions
        - Changes are saved when you click "💾 Save Changes"
        """)
