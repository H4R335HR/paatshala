"""
Video Importer tab for Streamlit app.
Import videos from Google Drive into Moodle course sections.
"""

import re
import json
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime

from core.api import (
    get_topics,
    get_fresh_sesskey,
    add_page_with_embed,
    enable_edit_mode,
    setup_session
)
from core.gdrive_parser import (
    parse_video_filename,
    generate_embed_html,
    group_videos_by_session
)
from core.persistence import get_config

# Constants
DEFAULT_EMBED_WIDTH = 800
DEFAULT_EMBED_HEIGHT = 600
DEFAULT_GDRIVE_URL = ''  # No default - user must provide URL or load from cache


def auto_select_topic(session_num: int, topics: list) -> int:
    """
    Auto-select topic based on session number.
    Looks for patterns: "Session 01", "Session 1", "Day 01", "Day 1"
    
    Args:
        session_num: The session number to match
        topics: List of topic dictionaries
    
    Returns:
        Topic index (1-based for selectbox) or 0 for "(Skip)"
    """
    patterns = [
        rf'\bSession\s+0*{session_num}\b',
        rf'\bDay\s+0*{session_num}\b',
    ]
    
    for i, topic in enumerate(topics):
        topic_name = topic.get('Topic Name', '')
        for pattern in patterns:
            if re.search(pattern, topic_name, re.IGNORECASE):
                return i + 1  # 1-based index for selectbox
    
    return 0  # Default to "(Skip)"


def import_videos_to_moodle(session, course_id, section_id, sesskey, videos, topic_name, dry_run=True):
    """
    Import a list of videos to a Moodle section.
    
    Args:
        session: Requests session
        course_id: Moodle course ID
        section_id: Target section ID
        sesskey: Session key
        videos: List of video dicts with 'clean_title', 'file_id'
        topic_name: Name of the target topic (for display)
        dry_run: If True, just simulate import
    
    Returns:
        Tuple of (success_count, fail_count)
    """
    st.markdown(f"**Target:** {topic_name}")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    success_count = 0
    fail_count = 0
    
    for i, video in enumerate(videos):
        page_name = video['clean_title']
        embed_html = generate_embed_html(video['file_id'], width=DEFAULT_EMBED_WIDTH, height=DEFAULT_EMBED_HEIGHT)
        
        status_text.markdown(f"**[{i+1}/{len(videos)}]** {page_name}")
        
        if dry_run:
            st.success(f"✅ Would import: {page_name}")
            success_count += 1
        else:
            try:
                success = add_page_with_embed(
                    session=session,
                    course_id=course_id,
                    section_id=section_id,
                    sesskey=sesskey,
                    page_name=page_name,
                    embed_html=embed_html,
                    visible=True
                )
                
                if success:
                    st.success(f"✅ Imported: {page_name}")
                    success_count += 1
                else:
                    st.error(f"❌ Failed: {page_name}")
                    fail_count += 1
            except Exception as e:
                st.error(f"❌ Error importing {page_name}: {e}")
                fail_count += 1
        
        progress_bar.progress((i + 1) / len(videos))
    
    return success_count, fail_count


def render_video_importer_tab(course, meta):
    """Render the Video Importer tab content"""
    course_id = course.get('id')
    
    # Clear all video import state when course changes
    if st.session_state.get('video_import_course_id') != course_id:
        st.session_state.video_import_course_id = course_id
        st.session_state.video_import_topics = None
        st.session_state.video_import_videos = None
        st.session_state.video_import_mapping = {}
    
    st.markdown("### 📹 Google Drive Video Importer")
    st.markdown("Import videos from Google Drive as embedded pages in course topics.")
    
    # =========================================================================
    # Instructions (collapsed by default)
    # =========================================================================
    with st.expander("ℹ️ How to Use", expanded=False):
        st.markdown("""
        **Option 1: Direct URL (Easiest)**
        1. Paste your Google Drive folder URL below
        2. Click "Fetch Videos" to extract the list
        3. Map sessions to topics (auto-mapped by default)
        4. Select videos and Import!
        
        **Option 2: Upload JSON File**
        If you already have a `gdrive_files.json` file, upload it below
        
        **Filename Format:**
        ```
        #1.1_-_what_is_cyber_security_v30 (720p).mp4
        → Session 1, "What Is Cyber Security"
        ```
        """)
    
    # =========================================================================
    # Input Method Selection
    # =========================================================================
    st.subheader("📁 Video Source")
    
    input_method = st.radio(
        "Choose input method:",
        ["🔗 Google Drive URL (Recommended)", "📤 Upload JSON File"],
        horizontal=True,
        label_visibility="collapsed"
    )
    
    if input_method.startswith("🔗"):
        # =====================================================================
        # Google Drive API Configuration
        # =====================================================================
        from core.persistence import get_config, set_config, save_cache, load_cache, clear_cache
        
        credentials_path = get_config('google_drive_credentials')
        
        # Check if credentials are configured
        if not credentials_path:
            st.warning("⚠️ Google Drive API credentials not configured")
            
            with st.expander("🔧 Setup Google Drive API", expanded=True):
                st.markdown("""
                **Steps to setup:**
                1. You should have a service account JSON file from Google Cloud Console
                2. Upload or specify the path to your credentials file below
                3. The path will be saved to `.config` for future use
                
                **Note:** The credentials file should have read access to your Google Drive folder.
                """)
                
                # Option 1: Upload credentials file
                uploaded_creds = st.file_uploader(
                    "Upload Google Drive credentials JSON",
                    type=['json'],
                    help="Service account credentials from Google Cloud Console"
                )
                
                if uploaded_creds:
                    creds_dir = Path("output") / ".credentials"
                    creds_dir.mkdir(parents=True, exist_ok=True)
                    creds_path = creds_dir / "google_drive_credentials.json"
                    
                    with open(creds_path, 'wb') as f:
                        f.write(uploaded_creds.getvalue())
                    
                    set_config('google_drive_credentials', str(creds_path))
                    st.success(f"✅ Credentials saved to: `{creds_path}`")
                    st.info("Please refresh the page to use the new credentials")
                    st.stop()
                
                # Option 2: Specify existing path
                st.markdown("**Or specify existing credentials file path:**")
                manual_path = st.text_input(
                    "Credentials file path",
                    placeholder="C:/path/to/credentials.json"
                )
                
                if st.button("Save Path", key="save_creds_path") and manual_path:
                    if Path(manual_path).exists():
                        set_config('google_drive_credentials', manual_path)
                        st.success("✅ Credentials path saved!")
                        st.info("Please refresh the page")
                        st.stop()
                    else:
                        st.error("❌ File not found")
            
            st.stop()
        
        # Credentials are configured
        st.success(f"✅ Credentials configured: `{Path(credentials_path).name}`")
        
        # =====================================================================
        # Google Drive URL Input
        # =====================================================================
        st.markdown("**Enter Google Drive Folder URL:**")
        
        cache_key = f"video_cache_{course_id}"
        cached_data = st.session_state.get(cache_key)
        
        # Get default URL from config, then from cache, then fallback to empty
        config_url = get_config('google_drive_folder_url', '')
        default_url = cached_data.get('folder_url', config_url) if cached_data else config_url
        
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col1:
            folder_url = st.text_input(
                "Google Drive URL",
                value=default_url,
                placeholder="https://drive.google.com/drive/folders/...",
                label_visibility="collapsed"
            )
        
        with col2:
            fetch_btn = st.button("🔍 Fetch Videos", type="primary", width="stretch", key="fetch_videos_btn")
        
        with col3:
            # Always show refresh/clear button if we have videos
            if st.session_state.get('video_import_videos'):
                if st.button("🗑️ Clear", width="stretch", key="clear_videos_btn"):
                    st.session_state.video_import_videos = None
                    st.session_state.video_import_topics = None
                    st.session_state.video_import_mapping = {}
                    if cache_key in st.session_state:
                        del st.session_state[cache_key]
                    # Also clear disk cache
                    clear_cache(cache_key)
                    st.rerun()
        
        # Load from cache if available (try disk cache first if session state is empty)
        if not fetch_btn and 'video_import_videos' not in st.session_state:
            # Try session state cache first
            if cached_data and cached_data.get('folder_url') == folder_url:
                st.session_state.video_import_videos = cached_data.get('videos')
                fetched_time = cached_data.get('fetched_at', 'Unknown')
                st.info(f"📦 Loaded {len(st.session_state.video_import_videos)} videos from session cache (fetched: {fetched_time})")
            else:
                # Try disk cache
                disk_cache = load_cache(cache_key)
                if disk_cache and disk_cache.get('folder_url') == folder_url:
                    st.session_state.video_import_videos = disk_cache.get('videos')
                    st.session_state[cache_key] = disk_cache  # Also store in session state
                    fetched_time = disk_cache.get('fetched_at', 'Unknown')
                    st.info(f"💾 Loaded {len(st.session_state.video_import_videos)} videos from disk cache (fetched: {fetched_time})")
        
        if fetch_btn and folder_url:
            folder_id_match = re.search(r'/folders/([a-zA-Z0-9_-]+)', folder_url)
            
            if not folder_id_match:
                st.error("❌ Invalid Google Drive folder URL")
            else:
                folder_id = folder_id_match.group(1)
                
                with st.spinner("Fetching videos from Google Drive API..."):
                    try:
                        from core.gdrive_api import get_videos_from_folder_api
                        
                        videos_list = get_videos_from_folder_api(folder_id, credentials_path)
                        
                        if videos_list:
                            st.session_state.video_import_videos = videos_list
                            st.session_state.video_import_topics = None  # Reset topics
                            
                            cache_data = {
                                'videos': videos_list,
                                'folder_url': folder_url,
                                'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            }
                            st.session_state[cache_key] = cache_data
                            # Also save to disk cache for persistence
                            save_cache(cache_key, cache_data)
                            
                            st.success(f"✅ Found {len(videos_list)} videos!")
                            st.rerun()
                        else:
                            st.error("❌ No videos found or API error occurred")
                            st.info("""
                            **Possible issues:**
                            - Folder is empty
                            - Credentials don't have access to this folder
                            - Folder ID is incorrect
                            
                            **Try:**
                            - Make sure the folder is shared with the service account email
                            - Use the 'Upload JSON File' method as fallback
                            """)
                    
                    except ImportError:
                        st.error("❌ Google API client not installed")
                        st.code("pip install google-api-python-client google-auth", language="bash")
                    except Exception as e:
                        st.error(f"❌ Error: {e}")
    
    else:
        # =====================================================================
        # File Upload Method
        # =====================================================================
        uploaded_file = st.file_uploader(
            "Upload gdrive_files.json",
            type=['json'],
            help="JSON file containing video information from Google Drive"
        )
        
        if uploaded_file is not None:
            try:
                videos = json.load(uploaded_file)
                st.session_state.video_import_videos = videos
                st.success(f"✅ Loaded {len(videos)} videos")
            except Exception as e:
                st.error(f"❌ Error loading JSON file: {e}")
                return
    
    # Check if we have videos loaded
    if not st.session_state.get('video_import_videos'):
        st.info("👆 Fetch videos or upload a JSON file to get started")
        return
    
    videos = st.session_state.video_import_videos
    
    # =========================================================================
    # Group Videos by Session
    # =========================================================================
    grouped_videos = group_videos_by_session(videos)
    
    # =========================================================================
    # Load Course Topics (cached)
    # =========================================================================
    topics_just_loaded = False
    if not st.session_state.get('video_import_topics'):
        with st.spinner("Loading course topics..."):
            session = setup_session(st.session_state.session_id)
            topics = get_topics(session, course_id)
            st.session_state.video_import_topics = topics
            topics_just_loaded = True
    
    topics = st.session_state.video_import_topics
    
    if not topics:
        st.error("❌ No topics found in course")
        return
    
    # Create topic options for dropdowns
    topic_options = ["(Skip - don't import)"] + [
        f"{i+1}. {t.get('Topic Name', 'Untitled')}"
        for i, t in enumerate(topics)
    ]
    
    # =========================================================================
    # Compact Summary Row
    # =========================================================================
    total_videos = sum(len(vids) for vids in grouped_videos.values())
    session_count = len([s for s in grouped_videos.keys() if s != 0])
    ungrouped = len(grouped_videos.get(0, []))
    
    col1, col2, col3, col4 = st.columns([2, 2, 2, 2])
    with col1:
        st.metric("📹 Total Videos", total_videos)
    with col2:
        st.metric("📂 Sessions", session_count)
    with col3:
        st.metric("⚠️ Ungrouped", ungrouped)
    with col4:
        dry_run = st.checkbox("🔍 Dry Run", value=False, help="Test without importing")
    
    st.divider()
    
    # =========================================================================
    # Initialize mapping and selection state
    # =========================================================================
    # Reset mapping if topics were just loaded (to re-run auto_select on fresh topics)
    if topics_just_loaded or 'video_import_mapping' not in st.session_state:
        st.session_state.video_import_mapping = {}
        for session_num in grouped_videos.keys():
            if session_num == 0:
                st.session_state.video_import_mapping[0] = 0  # Ungrouped defaults to Skip
            else:
                st.session_state.video_import_mapping[session_num] = auto_select_topic(session_num, topics)
    
    # =========================================================================
    # Unified Session Cards
    # =========================================================================
    st.subheader("📂 Sessions")
    
    for session_num in sorted(grouped_videos.keys()):
        if session_num == 0:
            continue  # Handle ungrouped separately
        
        session_videos = grouped_videos[session_num]
        video_count = len(session_videos)
        
        # Initialize selection state for this session
        selection_key = f"video_selection_{session_num}"
        if selection_key not in st.session_state:
            st.session_state[selection_key] = {i: True for i in range(video_count)}
        
        # Count selected videos
        selected_count = sum(1 for v in st.session_state[selection_key].values() if v)
        
        # Session card with border
        with st.container(border=True):
            # Header row: Session name + Topic dropdown + Import button
            header_cols = st.columns([2, 3, 2])
            
            with header_cols[0]:
                st.markdown(f"### 📂 Session {session_num}")
                st.caption(f"{video_count} videos")
            
            with header_cols[1]:
                # Get current mapping
                current_mapping = st.session_state.video_import_mapping.get(session_num, 0)
                
                selected_topic_idx = st.selectbox(
                    "Target Topic",
                    range(len(topic_options)),
                    index=current_mapping,
                    format_func=lambda x: topic_options[x],
                    key=f"topic_select_{session_num}",
                    label_visibility="collapsed"
                )
                
                # Update mapping
                st.session_state.video_import_mapping[session_num] = selected_topic_idx
            
            with header_cols[2]:
                # Import button
                is_mapped = selected_topic_idx > 0
                btn_label = f"🚀 Import ({selected_count})" if selected_count < video_count else "🚀 Import All"
                
                import_disabled = not is_mapped or selected_count == 0
                
                if st.button(
                    btn_label, 
                    key=f"import_btn_{session_num}", 
                    type="primary", 
                    width="stretch",
                    disabled=import_disabled
                ):
                    # Get selected videos with custom titles
                    titles_key = f"video_titles_{session_num}"
                    selected_videos = []
                    for i, video in enumerate(session_videos):
                        if st.session_state[selection_key].get(i, True):
                            video_copy = video.copy()
                            # Apply custom title if set
                            if titles_key in st.session_state:
                                video_copy['clean_title'] = st.session_state[titles_key].get(i, video['clean_title'])
                            selected_videos.append(video_copy)
                    
                    # Set pending import with complete data
                    st.session_state.pending_import = {
                        'session_num': session_num,
                        'topic_idx': selected_topic_idx - 1,  # Convert to 0-indexed
                        'topic_name': topics[selected_topic_idx - 1].get('Topic Name', 'Untitled'),
                        'section_id': topics[selected_topic_idx - 1].get('Section ID'),
                        'selected_videos': selected_videos,
                        'dry_run': dry_run
                    }
                    st.session_state.import_complete = False
                    st.rerun()
            
            # Select All toggle
            col_toggle, col_spacer = st.columns([1, 5])
            with col_toggle:
                all_selected = all(st.session_state[selection_key].values())
                toggle_all = st.checkbox(
                    "Deselect All" if all_selected else "Select All",
                    value=all_selected,
                    key=f"select_all_{session_num}"
                )
                # Update all checkboxes based on toggle state
                if toggle_all != all_selected:
                    for i in range(video_count):
                        st.session_state[selection_key][i] = toggle_all
                        # Also update the individual checkbox widget state
                        st.session_state[f"video_{session_num}_{i}"] = toggle_all
                    st.rerun()
            
            # Initialize custom titles state
            titles_key = f"video_titles_{session_num}"
            if titles_key not in st.session_state:
                st.session_state[titles_key] = {i: video['clean_title'] for i, video in enumerate(session_videos)}
            
            # Video checkboxes with rename popover
            for i, video in enumerate(session_videos):
                col_check, col_rename = st.columns([10, 1])
                
                current_title = st.session_state[titles_key].get(i, video['clean_title'])
                is_renamed = current_title != video['clean_title']
                
                # Initialize widget key if it doesn't exist (avoid passing value when key exists)
                widget_key = f"video_{session_num}_{i}"
                if widget_key not in st.session_state:
                    st.session_state[widget_key] = st.session_state[selection_key].get(i, True)
                
                with col_check:
                    display_title = f"*{current_title}*" if is_renamed else current_title
                    is_selected = st.checkbox(
                        display_title,
                        key=widget_key
                    )
                    st.session_state[selection_key][i] = is_selected
                
                with col_rename:
                    with st.popover("✏️", help="Rename video"):
                        new_title = st.text_input(
                            "Video title",
                            value=current_title,
                            key=f"rename_{session_num}_{i}",
                            label_visibility="collapsed"
                        )
                        if new_title != current_title:
                            st.session_state[titles_key][i] = new_title
                            st.rerun()
    
    # =========================================================================
    # Handle Ungrouped Videos (as importable session card)
    # =========================================================================
    if grouped_videos.get(0):
        st.divider()
        st.subheader("⚠️ Ungrouped Videos")
        st.caption("These videos don't have a session number in their filename (e.g., #1, #2)")
        
        session_num = 0
        session_videos = grouped_videos[0]
        video_count = len(session_videos)
        
        # Initialize selection state for ungrouped
        selection_key = f"video_selection_{session_num}"
        if selection_key not in st.session_state:
            st.session_state[selection_key] = {i: True for i in range(video_count)}
        
        # Count selected videos
        selected_count = sum(1 for v in st.session_state[selection_key].values() if v)
        
        with st.container(border=True):
            header_cols = st.columns([2, 3, 2])
            
            with header_cols[0]:
                st.markdown(f"### 📂 Ungrouped")
                st.caption(f"{video_count} videos")
            
            with header_cols[1]:
                current_mapping = st.session_state.video_import_mapping.get(0, 0)
                
                selected_topic_idx = st.selectbox(
                    "Target Topic",
                    range(len(topic_options)),
                    index=current_mapping,
                    format_func=lambda x: topic_options[x],
                    key=f"topic_select_ungrouped",
                    label_visibility="collapsed"
                )
                
                st.session_state.video_import_mapping[0] = selected_topic_idx
            
            with header_cols[2]:
                is_mapped = selected_topic_idx > 0
                btn_label = f"🚀 Import ({selected_count})" if selected_count < video_count else "🚀 Import All"
                
                import_disabled = not is_mapped or selected_count == 0
                
                if st.button(
                    btn_label, 
                    key=f"import_btn_ungrouped", 
                    type="primary", 
                    width="stretch",
                    disabled=import_disabled
                ):
                    # Get selected videos with custom titles
                    titles_key = f"video_titles_{session_num}"
                    selected_videos = []
                    for i, video in enumerate(session_videos):
                        if st.session_state[selection_key].get(i, True):
                            video_copy = video.copy()
                            if titles_key in st.session_state:
                                video_copy['clean_title'] = st.session_state[titles_key].get(i, video['clean_title'])
                            selected_videos.append(video_copy)
                    
                    st.session_state.pending_import = {
                        'session_num': 'Ungrouped',
                        'topic_idx': selected_topic_idx - 1,
                        'topic_name': topics[selected_topic_idx - 1].get('Topic Name', 'Untitled'),
                        'section_id': topics[selected_topic_idx - 1].get('Section ID'),
                        'selected_videos': selected_videos,
                        'dry_run': dry_run
                    }
                    st.session_state.import_complete = False
                    st.rerun()
            
            # Select All toggle
            col_toggle, col_spacer = st.columns([1, 5])
            with col_toggle:
                all_selected = all(st.session_state[selection_key].values())
                toggle_all = st.checkbox(
                    "Deselect All" if all_selected else "Select All",
                    value=all_selected,
                    key=f"select_all_ungrouped"
                )
                # Update all checkboxes based on toggle state
                if toggle_all != all_selected:
                    for i in range(video_count):
                        st.session_state[selection_key][i] = toggle_all
                        # Also update the individual checkbox widget state
                        st.session_state[f"video_{session_num}_{i}"] = toggle_all
                    st.rerun()
            
            # Initialize custom titles state for ungrouped
            titles_key = f"video_titles_{session_num}"
            if titles_key not in st.session_state:
                st.session_state[titles_key] = {i: video['clean_title'] for i, video in enumerate(session_videos)}
            
            # Video checkboxes with rename popover
            for i, video in enumerate(session_videos):
                col_check, col_rename = st.columns([10, 1])
                
                current_title = st.session_state[titles_key].get(i, video['clean_title'])
                is_renamed = current_title != video['clean_title']
                
                # Initialize widget key if it doesn't exist (avoid passing value when key exists)
                widget_key = f"video_ungrouped_{i}"
                if widget_key not in st.session_state:
                    st.session_state[widget_key] = st.session_state[selection_key].get(i, True)
                
                with col_check:
                    display_title = f"*{current_title}*" if is_renamed else current_title
                    is_selected = st.checkbox(
                        display_title,
                        key=widget_key
                    )
                    st.session_state[selection_key][i] = is_selected
                
                with col_rename:
                    with st.popover("✏️", help="Rename video"):
                        new_title = st.text_input(
                            "Video title",
                            value=current_title,
                            key=f"rename_ungrouped_{i}",
                            label_visibility="collapsed"
                        )
                        if new_title != current_title:
                            st.session_state[titles_key][i] = new_title
                            st.rerun()
    
    # =========================================================================
    # Import Dialog
    # =========================================================================
    if st.session_state.get('pending_import'):
        pending = st.session_state.pending_import
        
        # Generate unique import ID to track completion
        import_id = f"import_{pending['session_num']}_{len(pending['selected_videos'])}_{id(pending['selected_videos'])}"
        
        # Initialize completed imports tracking
        if 'completed_imports' not in st.session_state:
            st.session_state.completed_imports = {}
        
        @st.dialog(f"Importing Session {pending['session_num']}", width="large")
        def show_import_dialog():
            session_num = pending['session_num']
            topic_name = pending['topic_name']
            section_id = pending['section_id']
            selected_videos = pending['selected_videos']
            is_dry_run = pending['dry_run']
            
            # Check if this import was already completed
            if import_id in st.session_state.completed_imports:
                # Show cached results
                cached = st.session_state.completed_imports[import_id]
                st.markdown(f"### {'🔍 DRY RUN - ' if is_dry_run else ''}📤 Import Results")
                st.markdown(f"**Target:** {topic_name}")
                st.markdown("---")
                
                if is_dry_run:
                    st.info(f"🔍 **Dry Run Complete:** Would import {cached['success']} videos")
                else:
                    if cached['fail'] == 0:
                        st.success(f"✅ **Import Complete:** {cached['success']} videos imported successfully!")
                    else:
                        st.warning(f"⚠️ **Import Complete:** {cached['success']} succeeded, {cached['fail']} failed")
            else:
                # First time - actually run the import
                st.markdown(f"### {'🔍 DRY RUN - ' if is_dry_run else ''}📤 Importing {len(selected_videos)} Videos")
                
                # Setup Moodle session
                moodle_session = setup_session(st.session_state.session_id)
                
                # Get fresh sesskey
                sesskey = get_fresh_sesskey(moodle_session, course_id)
                if not sesskey:
                    st.warning("⚠️ Could not get fresh sesskey, using cached one")
                    sesskey = topics[0].get('Sesskey', '') if topics else ''
                
                # Enable edit mode
                with st.spinner("Enabling edit mode..."):
                    enable_edit_mode(moodle_session, course_id, sesskey)
                
                # Import videos
                success_count, fail_count = import_videos_to_moodle(
                    session=moodle_session,
                    course_id=course_id,
                    section_id=section_id,
                    sesskey=sesskey,
                    videos=selected_videos,
                    topic_name=topic_name,
                    dry_run=is_dry_run
                )
                
                # Cache the results to prevent re-import on rerun
                st.session_state.completed_imports[import_id] = {
                    'success': success_count,
                    'fail': fail_count
                }
                
                # Summary
                st.markdown("---")
                if is_dry_run:
                    st.info(f"🔍 **Dry Run Complete:** Would import {success_count} videos")
                else:
                    if fail_count == 0:
                        st.success(f"✅ **Import Complete:** {success_count} videos imported successfully!")
                    else:
                        st.warning(f"⚠️ **Import Complete:** {success_count} succeeded, {fail_count} failed")
            
            # Close button
            if st.button("✅ Done", type="primary", width="stretch", key="import_done_btn"):
                # Clear pending import and refresh
                st.session_state.pending_import = None
                st.session_state.video_import_topics = None  # Refresh topics
                st.rerun()
        
        show_import_dialog()
    
    # =========================================================================
    # Bulk Import Option
    # =========================================================================
    st.divider()
    
    # Count total mapped videos
    mapped_sessions = {
        s: st.session_state.video_import_mapping.get(s, 0) 
        for s in grouped_videos.keys() 
        if s != 0 and st.session_state.video_import_mapping.get(s, 0) > 0
    }
    
    if mapped_sessions:
        total_mapped_videos = sum(len(grouped_videos[s]) for s in mapped_sessions)
        
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"**⚡ Bulk Import:** {total_mapped_videos} videos from {len(mapped_sessions)} sessions")
        with col2:
            if st.button("⚡ Import All Mapped", type="secondary", width="stretch", key="bulk_import_btn"):
                st.session_state.pending_bulk_import = {
                    'sessions': mapped_sessions,
                    'dry_run': dry_run
                }
                st.session_state.bulk_import_complete = False
                st.rerun()
    
    # Handle bulk import dialog
    if st.session_state.get('pending_bulk_import'):
        bulk_pending = st.session_state.pending_bulk_import
        
        # Generate unique bulk import ID
        bulk_import_id = f"bulk_import_{hash(str(sorted(bulk_pending['sessions'].items())))}"
        
        @st.dialog("Bulk Import All Sessions", width="large")
        def show_bulk_import_dialog():
            is_dry_run = bulk_pending['dry_run']
            sessions_to_import = bulk_pending['sessions']
            
            # Check if this bulk import was already completed
            if bulk_import_id in st.session_state.completed_imports:
                # Show cached results
                cached = st.session_state.completed_imports[bulk_import_id]
                st.markdown(f"### {'🔍 DRY RUN - ' if is_dry_run else ''}📤 Bulk Import Results")
                st.markdown("---")
                
                if is_dry_run:
                    st.info(f"🔍 **Dry Run Complete:** Would import {cached['success']} videos total")
                else:
                    st.success(f"✅ **Bulk Import Complete:** {cached['success']} succeeded, {cached['fail']} failed")
            else:
                # First time - actually run the bulk import
                st.markdown(f"### {'🔍 DRY RUN - ' if is_dry_run else ''}📤 Bulk Import")
                
                moodle_session = setup_session(st.session_state.session_id)
                sesskey = get_fresh_sesskey(moodle_session, course_id)
                
                if not sesskey:
                    sesskey = topics[0].get('Sesskey', '') if topics else ''
                
                with st.spinner("Enabling edit mode..."):
                    enable_edit_mode(moodle_session, course_id, sesskey)
                
                total_success = 0
                total_fail = 0
                
                for session_num, topic_idx in sessions_to_import.items():
                    topic = topics[topic_idx - 1]
                    st.markdown(f"---\n### Session {session_num}")
                    
                    success, fail = import_videos_to_moodle(
                        session=moodle_session,
                        course_id=course_id,
                        section_id=topic.get('Section ID'),
                        sesskey=sesskey,
                        videos=grouped_videos[session_num],
                        topic_name=topic.get('Topic Name', 'Untitled'),
                        dry_run=is_dry_run
                    )
                    total_success += success
                    total_fail += fail
                
                # Cache results to prevent re-import
                st.session_state.completed_imports[bulk_import_id] = {
                    'success': total_success,
                    'fail': total_fail
                }
                
                st.markdown("---")
                if is_dry_run:
                    st.info(f"🔍 **Dry Run Complete:** Would import {total_success} videos total")
                else:
                    st.success(f"✅ **Bulk Import Complete:** {total_success} succeeded, {total_fail} failed")
            
            if st.button("✅ Done", type="primary", width="stretch", key="bulk_import_done_btn"):
                st.session_state.pending_bulk_import = None
                st.session_state.video_import_topics = None
                st.rerun()
        
        show_bulk_import_dialog()
