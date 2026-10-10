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
import logging

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
    "AI Settings": {
        # gemini_api_keys is handled separately with custom UI
        # ai_provider is handled separately with radio buttons
        # gemini_model and openrouter_model are handled by live API-fetched dropdowns
        "github_pat": {
            "label": "GitHub PAT (Optional)",
            "help": "Personal Access Token for GitHub API. Optional - increases rate limit from 60/hr to 5000/hr. Create at github.com/settings/tokens (no scopes needed for public repos)",
            "default": "",
            "type": "password"
        },
        "max_images_for_scoring": {
            "label": "Max Images for AI Scoring",
            "help": "Maximum number of images to extract from documents (DOCX, PDF, ZIP) for AI scoring. Higher = more accurate but uses more tokens. Default: 10",
            "default": "10",
            "type": "text"
        },
        "github_recursive_depth": {
            "label": "GitHub Recursive Depth",
            "help": "How many levels deep to fetch subdirectory contents from GitHub repos. Default: 5",
            "default": "5",
            "type": "text"
        },
        "max_image_dimension": {
            "label": "Max Image Dimension",
            "help": "Resize images larger than this (in pixels) before sending to AI. Smaller = fewer tokens. 0 = no resizing. Default: 800",
            "default": "800",
            "type": "text"
        },
        "timely_submission_weight": {
            "label": "Timely Submission Weight (%)",
            "help": "Default weight percentage for 'Timely Submission' criterion in generated rubrics. Set to 0 to disable. Default: 25",
            "default": "25",
            "type": "text"
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
    },
    "Display": {
        "max_inline_size_kb": {
            "label": "Max Inline File Size (KB)",
            "help": "Maximum file size in KB to display inline (images, code files from GitHub). Default: 512",
            "default": "512",
            "type": "text"
        }
    },
    "Application": {
        "default_volunteer_bonus": {
            "label": "Default Volunteer Bonus",
            "help": "Default bonus points for volunteers in presentation sessions (0-5). Default: 5",
            "default": "5",
            "type": "text"
        },
        "debug_logging": {
            "label": "Enable Debug Logging",
            "help": "Show detailed debug logs in the console. Useful for troubleshooting ZIP/PDF extraction, API calls, etc.",
            "default": "false",
            "type": "boolean"
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
    
    # === AI Provider Selection ===
    with st.expander("**🤖 AI Provider**", expanded=True):
        st.caption("Choose your AI backend. Gemini uses Google's API keys. OpenRouter gives access to 200+ models (GPT-4o, Claude, Llama, etc.) with a single key.")
        
        current_provider = current_config.get("ai_provider", "gemini") or "gemini"
        provider_options = ["gemini", "openrouter"]
        provider_labels = {"gemini": "🔷 Google Gemini", "openrouter": "🌐 OpenRouter"}
        
        selected_provider = st.radio(
            "AI Provider",
            options=provider_options,
            format_func=lambda x: provider_labels.get(x, x),
            index=provider_options.index(current_provider) if current_provider in provider_options else 0,
            horizontal=True,
            key="config_ai_provider",
            label_visibility="collapsed"
        )
        
        if selected_provider != current_provider:
            changes["ai_provider"] = selected_provider
        
        # Show Gemini model selector when Gemini is selected
        if selected_provider == "gemini":
            st.markdown("---")
            current_gemini_model = current_config.get("gemini_model", "") or "gemini-3.8-flash"
            
            from core.ai import fetch_gemini_models
            
            with st.spinner("Loading Gemini models..."):
                gemini_models = fetch_gemini_models()
            
            if gemini_models:
                # Build display with free/paid indicators
                model_ids = [m["id"] for m in gemini_models]
                model_display = {}
                for m in gemini_models:
                    tag = "🆓" if m["free"] else "💰"
                    model_display[m["id"]] = f"{tag}  {m['id']}"
                
                # Ensure current model is in the list
                if current_gemini_model not in model_ids:
                    model_ids.insert(0, current_gemini_model)
                    model_display[current_gemini_model] = current_gemini_model
                
                free_count = sum(1 for m in gemini_models if m["free"])
                selected_gemini = st.selectbox(
                    "Gemini Model",
                    options=model_ids,
                    index=model_ids.index(current_gemini_model) if current_gemini_model in model_ids else 0,
                    format_func=lambda x: model_display.get(x, x),
                    help=f"{len(gemini_models)} models available ({free_count} free). 🆓 = Free, 💰 = Paid.",
                    key="config_gemini_model_select"
                )
                
                if selected_gemini != current_gemini_model:
                    changes["gemini_model"] = selected_gemini
            else:
                # Fallback: text input if no API key or fetch failed
                manual_gemini = st.text_input(
                    "Gemini Model",
                    value=current_gemini_model,
                    help="Add API keys below to see available models as a dropdown",
                    key="config_gemini_model_manual"
                )
                if manual_gemini != current_gemini_model:
                    changes["gemini_model"] = manual_gemini
            
            # Optional: fall back to OpenRouter when all Gemini models fail
            current_or_fallback = str(current_config.get("openrouter_fallback", "false")).lower() == "true"
            or_fallback = st.checkbox(
                "🌐 Fall back to OpenRouter if all Gemini models fail",
                value=current_or_fallback,
                help="Used only when Gemini is overloaded (503) or all Gemini keys hit their quota. "
                     "Uses the OpenRouter key and model configured below.",
                key="config_openrouter_fallback"
            )
            if or_fallback != current_or_fallback:
                changes["openrouter_fallback"] = "true" if or_fallback else "false"
        else:
            or_fallback = False
        
        # Show OpenRouter settings when OpenRouter is the provider OR used as fallback
        if selected_provider == "openrouter" or or_fallback:
            st.markdown("---")
            if selected_provider != "openrouter":
                st.caption("**OpenRouter fallback settings**")
            current_or_key = current_config.get("openrouter_api_key", "")
            if current_or_key:
                st.caption("🔒 OpenRouter API Key is set")
            
            new_or_key = st.text_input(
                "OpenRouter API Key",
                value="",
                type="password",
                help="Get your key at https://openrouter.ai/keys",
                placeholder="sk-or-... (enter to change)" if current_or_key else "sk-or-...",
                key="config_openrouter_api_key"
            )
            if new_or_key:
                changes["openrouter_api_key"] = new_or_key
            
            # Model selector - fetch live from OpenRouter API
            st.markdown("")
            current_or_model = current_config.get("openrouter_model", "") or "openai/gpt-4o-mini"
            
            from core.ai import fetch_openrouter_models
            
            with st.spinner("Loading available models..."):
                or_models = fetch_openrouter_models(api_key=current_or_key or None)
            
            if or_models:
                # Build display with free/paid indicators
                model_ids = [m["id"] for m in or_models]
                model_display = {}
                for m in or_models:
                    tag = "🆓" if m["free"] else "💰"
                    model_display[m["id"]] = f"{tag}  {m['id']}  —  {m['name']}"
                
                # Ensure current model is in the list
                if current_or_model not in model_ids:
                    model_ids.insert(0, current_or_model)
                    model_display[current_or_model] = current_or_model
                
                free_count = sum(1 for m in or_models if m["free"])
                selected_or_model = st.selectbox(
                    "Model",
                    options=model_ids,
                    index=model_ids.index(current_or_model) if current_or_model in model_ids else 0,
                    format_func=lambda x: model_display.get(x, x),
                    help=f"{len(or_models)} models available ({free_count} free). 🆓 = Free, 💰 = Paid. Free models shown first.",
                    key="config_openrouter_model_select"
                )
                
                if selected_or_model != current_or_model:
                    changes["openrouter_model"] = selected_or_model
            else:
                # Fallback: manual text input if API fails
                st.warning("⚠️ Could not fetch models. Enter API key and save first, or type a model ID manually.")
                manual_model = st.text_input(
                    "Model ID",
                    value=current_or_model,
                    help="e.g., openai/gpt-4o, anthropic/claude-sonnet-4",
                    key="config_openrouter_model_manual"
                )
                if manual_model != current_or_model:
                    changes["openrouter_model"] = manual_model
    
    # === Custom Gemini API Keys Section (only show when Gemini selected) ===
    if selected_provider == "gemini":
      with st.expander("**🔑 Gemini API Keys**", expanded=True):
        st.caption("Keys are tried in order (top = first). Falls back to next on quota/rate-limit errors.")
        
        # Load existing keys from config
        import json
        api_keys_json = current_config.get("gemini_api_keys", "[]")
        try:
            api_keys = json.loads(api_keys_json) if api_keys_json else []
        except:
            api_keys = []
        
        # Migrate from old single key format
        if not api_keys and current_config.get("gemini_api_key"):
            api_keys = [{"name": "Default", "key": current_config.get("gemini_api_key")}]
        
        # Initialize session state for keys
        if "temp_api_keys" not in st.session_state:
            st.session_state.temp_api_keys = api_keys.copy()
        
        # Version counter to force widget refresh on reorder
        if "api_keys_version" not in st.session_state:
            st.session_state.api_keys_version = 0
        v = st.session_state.api_keys_version
        
        # Display existing keys with reorder controls
        keys_to_remove = []
        for i, key_info in enumerate(st.session_state.temp_api_keys):
            col_pos, col_name, col_key, col_up, col_down, col_del = st.columns([0.5, 2, 4, 0.5, 0.5, 0.5])
            
            with col_pos:
                st.markdown(f"**{i+1}.**")
            
            with col_name:
                new_name = st.text_input(
                    "Name", 
                    value=key_info.get("name", f"Key {i+1}"),
                    key=f"api_key_name_{v}_{i}",
                    label_visibility="collapsed",
                    placeholder="Key name"
                )
                st.session_state.temp_api_keys[i]["name"] = new_name
            
            with col_key:
                # Show masked key with option to update
                current_key = key_info.get("key", "")
                masked = f"{current_key[:10]}...{current_key[-4:]}" if len(current_key) > 14 else "****"
                new_key = st.text_input(
                    "Key",
                    value="",
                    type="password",
                    key=f"api_key_value_{v}_{i}",
                    label_visibility="collapsed",
                    placeholder=f"🔒 {masked} (enter to change)"
                )
                if new_key:
                    st.session_state.temp_api_keys[i]["key"] = new_key
            
            with col_up:
                # Up button (disabled if first)
                if st.button("↑", key=f"api_key_up_{i}", disabled=(i == 0)):
                    # Swap with previous
                    st.session_state.temp_api_keys[i], st.session_state.temp_api_keys[i - 1] = \
                        st.session_state.temp_api_keys[i - 1], st.session_state.temp_api_keys[i]
                    # Increment version to force fresh widgets
                    st.session_state.api_keys_version += 1
                    st.rerun()
            
            with col_down:
                # Down button (disabled if last)
                if st.button("↓", key=f"api_key_down_{i}", disabled=(i == len(st.session_state.temp_api_keys) - 1)):
                    # Swap with next
                    st.session_state.temp_api_keys[i], st.session_state.temp_api_keys[i + 1] = \
                        st.session_state.temp_api_keys[i + 1], st.session_state.temp_api_keys[i]
                    # Increment version to force fresh widgets
                    st.session_state.api_keys_version += 1
                    st.rerun()
            
            with col_del:
                if st.button("🗑️", key=f"remove_key_{i}"):
                    keys_to_remove.append(i)
        
        # Remove marked keys
        for i in reversed(keys_to_remove):
            st.session_state.temp_api_keys.pop(i)
            st.rerun()
        
        # Add new key button
        if st.button("➕ Add API Key"):
            st.session_state.temp_api_keys.append({"name": f"Key {len(st.session_state.temp_api_keys) + 1}", "key": ""})
            st.rerun()
        
        # Track API key changes for unified save
        valid_keys = [k for k in st.session_state.temp_api_keys if k.get("key")]
        current_keys_json = json.dumps(valid_keys)
        saved_keys_json = current_config.get("gemini_api_keys", "[]")
        if current_keys_json != saved_keys_json:
            changes["gemini_api_keys"] = current_keys_json
    
    # Render each category
    for category, settings in CONFIG_SCHEMA.items():
        with st.expander(f"**{category}**", expanded=True):
            cols = st.columns(2)
            col_idx = 0
            
            for key, meta in settings.items():
                # Skip provider-specific fields that don't match the active provider
                field_provider = meta.get("provider")
                if field_provider and field_provider != selected_provider:
                    continue
                
                with cols[col_idx % 2]:
                    current_value = current_config.get(key, "") or current_config.get(key.lower(), "")
                    
                    # Boolean type - render as checkbox
                    if meta["type"] == "boolean":
                        # Parse current value as boolean
                        if isinstance(current_value, bool):
                            is_checked = current_value
                        else:
                            is_checked = str(current_value).lower() in ['true', '1', 'yes', 'on']
                        
                        new_value = st.checkbox(
                            meta["label"],
                            value=is_checked,
                            help=meta["help"],
                            key=f"config_{key}"
                        )
                        
                        # Apply debug logging change immediately
                        if key == "debug_logging":
                            root_logger = logging.getLogger()
                            if new_value:
                                root_logger.setLevel(logging.DEBUG)
                            else:
                                root_logger.setLevel(logging.INFO)
                        
                        # Track as change if different from saved value
                        new_value_str = "true" if new_value else "false"
                        saved_value_str = str(current_value).lower() if current_value else meta["default"]
                        if new_value_str != saved_value_str:
                            changes[key] = new_value_str
                    
                    # For sensitive fields, show placeholder
                    elif meta["type"] == "password":
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
            if st.button("💾 Save Tab Order", type="primary", disabled=not order_changed, width="stretch"):
                if set_enabled_tabs(st.session_state.temp_tab_order):
                    # Clear the temp state so it reloads from config
                    del st.session_state.temp_tab_order
                    st.toast("✅ Tab order saved!", icon="✅")
                    st.rerun()
                else:
                    st.error("❌ Failed to save tab order")
        
        with col2:
            # Reset button
            if st.button("🔄 Reset Order", disabled=not order_changed, width="stretch"):
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
