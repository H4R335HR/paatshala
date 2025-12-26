"""
Content viewers for the Evaluation tab.
Provides interactive viewing for GitHub repos and PDF files.
"""

import base64
import logging
from pathlib import Path
from typing import Dict, Optional, List, Set, Callable, Any

import streamlit as st

from core.persistence import get_config

logger = logging.getLogger(__name__)

# File extension to language mapping for syntax highlighting
LANGUAGE_MAP = {
    '.py': 'python',
    '.js': 'javascript',
    '.ts': 'typescript',
    '.jsx': 'jsx',
    '.tsx': 'tsx',
    '.html': 'html',
    '.css': 'css',
    '.json': 'json',
    '.xml': 'xml',
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.md': 'markdown',
    '.sql': 'sql',
    '.sh': 'bash',
    '.bash': 'bash',
    '.java': 'java',
    '.c': 'c',
    '.cpp': 'cpp',
    '.h': 'c',
    '.cs': 'csharp',
    '.go': 'go',
    '.rs': 'rust',
    '.rb': 'ruby',
    '.php': 'php',
}

# Maximum file size to display inline - now configurable via settings
# Default: 512KB (512 * 1024 = 524288 bytes)
def get_max_inline_size():
    """Get max inline file size from config (in bytes)."""
    try:
        size_kb = int(get_config("max_inline_size_kb") or 512)
        return size_kb * 1024
    except (ValueError, TypeError):
        return 512 * 1024  # 512KB default


def render_pdf_viewer(pdf_path: str, unique_key: str = ""):
    """
    PDF content viewer that extracts and displays text content.
    
    Shows extracted text in a scrollable container with download button
    for the original PDF file.
    
    Args:
        pdf_path: Path to the PDF file to display.
        unique_key: Optional unique key suffix to prevent duplicate key errors
                    when the same PDF is displayed in multiple places.
    """
    try:
        path = Path(pdf_path)
        if not path.exists():
            st.warning(f"⚠️ PDF file not found: {path.name}")
            return
        
        file_size = path.stat().st_size
        file_name = path.name
        
        # Generate a unique key combining path hash and optional suffix
        key_base = f"pdf_dl_{hash(str(path))}"
        if unique_key:
            key_base = f"{key_base}_{unique_key}"
        
        # Show file info header with action buttons
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.markdown(f"📄 **{file_name}** ({file_size / 1024:.1f} KB)")
        with col2:
            # View in new tab button - opens PDF in browser's native viewer
            with open(path, "rb") as f:
                pdf_data = f.read()
            b64_pdf = base64.b64encode(pdf_data).decode('utf-8')
            
            # Use JavaScript to create blob URL and open in new tab (bypasses Chrome data URL blocking)
            view_html = f'''
                <button onclick="openPdf()" style="width: 100%; padding: 0.4rem 0.75rem; 
                       background-color: #262730; color: white; text-align: center;
                       border-radius: 0.5rem; font-size: 0.875rem; cursor: pointer;
                       border: 1px solid #444;">
                    👁️ View
                </button>
                <script>
                    function openPdf() {{
                        const b64 = "{b64_pdf}";
                        const binary = atob(b64);
                        const len = binary.length;
                        const bytes = new Uint8Array(len);
                        for (let i = 0; i < len; i++) {{
                            bytes[i] = binary.charCodeAt(i);
                        }}
                        const blob = new Blob([bytes], {{ type: 'application/pdf' }});
                        const url = URL.createObjectURL(blob);
                        window.open(url, '_blank');
                    }}
                </script>
            '''
            st.components.v1.html(view_html, height=40)
        with col3:
            with open(path, "rb") as f:
                st.download_button(
                    label="📥 Download",
                    data=f,
                    file_name=file_name,
                    mime="application/pdf",
                    key=key_base,
                    use_container_width=True
                )
        
        # Extract and display text content
        from core.ai import extract_pdf_text
        
        with st.spinner("Extracting PDF content..."):
            text_content = extract_pdf_text(str(path))
        
        if text_content.startswith("(") and text_content.endswith(")"):
            # Error or special message from extraction
            st.warning(text_content)
        else:
            # Display extracted text in a scrollable container
            st.text_area(
                "📝 Extracted Content",
                value=text_content,
                height=400,
                key=f"pdf_text_{key_base}",
                disabled=True
            )
            
    except Exception as e:
        logger.error(f"Error rendering PDF viewer: {e}")
        st.error(f"Could not display PDF: {e}")


def render_github_viewer(repo_url: str, pat: Optional[str] = None):
    """
    Interactive GitHub repository browser with file table and content preview.
    Follows file explorer + preview pattern (table on top, preview below).
    """
    import re
    import pandas as pd
    
    # Parse repo URL
    match = re.search(r'github\.com/([^/]+)/([^/\s]+)', repo_url)
    if not match:
        st.error("Could not parse GitHub URL")
        st.markdown(f"**Link:** [{repo_url}]({repo_url})")
        return
    
    owner = match.group(1)
    repo = match.group(2).removesuffix('.git').rstrip('/')
    repo_id = f"{owner}_{repo}"
    
    # Session state keys for this repo
    tree_key = f"gh_tree_{repo_id}"
    selected_key = f"gh_selected_{repo_id}"
    content_cache_key = f"gh_content_{repo_id}"
    current_path_key = f"gh_path_{repo_id}"
    
    # Initialize state
    if selected_key not in st.session_state:
        st.session_state[selected_key] = None
    if content_cache_key not in st.session_state:
        st.session_state[content_cache_key] = {}
    if current_path_key not in st.session_state:
        st.session_state[current_path_key] = ""  # Root directory
    
    # Header
    st.markdown(f"### 📂 Repository: [{owner}/{repo}]({repo_url})")
    
    # Current path for the file list
    current_path = st.session_state[current_path_key]
    cache_key = f"{tree_key}_{current_path}"
    
    # Fetch contents for current path
    if cache_key not in st.session_state:
        with st.spinner("Loading repository contents..."):
            from core.ai import fetch_github_content
            if current_path:
                # Fetch subdirectory
                files = _fetch_directory_contents(owner, repo, current_path, pat, repo_id)
                readme = ""
            else:
                # Fetch root
                result = fetch_github_content(repo_url, pat)
                if result.get("error"):
                    st.error(f"Could not load repository: {result['error']}")
                    return
                files = result.get("files", [])
                readme = result.get("readme", "")
            st.session_state[cache_key] = {"files": files, "readme": readme}
    
    data = st.session_state[cache_key]
    files = data.get("files", [])
    readme = data.get("readme", "")
    
    # === SECTION 1: Breadcrumb Navigation ===
    if current_path:
        parts = current_path.split("/")
        breadcrumb = "📁 "
        if st.button("🏠 Root", key=f"gh_root_{repo_id}"):
            st.session_state[current_path_key] = ""
            st.session_state[selected_key] = None
            st.rerun()
        for i, part in enumerate(parts):
            path_so_far = "/".join(parts[:i+1])
            col1, col2 = st.columns([0.1, 1])
            with col2:
                st.caption(f"→ {part}")
    
    # === SECTION 2: File List Table ===
    st.markdown("#### 📂 Files")
    
    # Build file list for dataframe
    file_list = []
    file_map = {}  # Map index to file info
    
    for i, f in enumerate(files):
        name = f.get("name", "")
        file_type = "📁 Directory" if f.get("type") == "dir" else Path(name).suffix.upper().replace(".", "") or "File"
        size = f.get("size", 0)
        size_str = f"{size / 1024:.1f} KB" if size > 0 else "—"
        
        icon = "📁" if f.get("type") == "dir" else _get_file_icon(name)
        
        file_list.append({
            "": icon,
            "Name": name,
            "Type": file_type if f.get("type") != "dir" else "Directory",
            "Size": size_str,
        })
        file_map[i] = f
    
    if file_list:
        df = pd.DataFrame(file_list)
        
        event = st.dataframe(
            df,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"gh_table_{repo_id}_{current_path}",
            width="stretch"
        )
        
        # Handle selection
        if event and event.selection and len(event.selection.rows) > 0:
            selected_idx = event.selection.rows[0]
            selected_file = file_map.get(selected_idx)
            
            if selected_file:
                if selected_file.get("type") == "dir":
                    # Navigate into directory
                    new_path = selected_file.get("path", selected_file.get("name"))
                    st.session_state[current_path_key] = new_path
                    st.session_state[selected_key] = None
                    st.rerun()
                else:
                    # Select file for preview
                    file_path = selected_file.get("path", selected_file.get("name"))
                    st.session_state[selected_key] = file_path
    else:
        st.info("📭 No files in this directory")
    
    st.caption("👆 Click a row to preview file or navigate into directory")
    
    # === SECTION 3: Preview Pane ===
    st.divider()
    
    selected = st.session_state.get(selected_key)
    if selected:
        st.markdown("#### 👁️ Preview")
        _render_file_preview(
            selected_path=selected,
            owner=owner,
            repo=repo,
            pat=pat,
            repo_id=repo_id
        )
    elif readme and not current_path:
        st.markdown("#### 📖 README.md")
        st.markdown(readme[:5000] if len(readme) > 5000 else readme)
    else:
        st.info("👆 Select a file above to preview")


def _get_file_icon(filename: str) -> str:
    """Get appropriate icon for file type."""
    ext = Path(filename).suffix.lower()
    icons = {
        '.py': '🐍', '.js': '📜', '.ts': '📘', '.html': '🌐', '.css': '🎨',
        '.json': '📋', '.md': '📝', '.txt': '📄', '.pdf': '📕', '.doc': '📄',
        '.docx': '📄', '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', '.gif': '🖼️',
        '.svg': '🖼️', '.zip': '📦', '.tar': '📦', '.gz': '📦',
    }
    return icons.get(ext, '📄')


def _render_file_tree(files: List[Dict], repo_url: str, current_path: str,
                      owner: str, repo: str, pat: Optional[str], repo_id: str):
    """
    Render a clickable file tree using st.button styled as tree items.
    """
    expanded_key = f"gh_expanded_{repo_id}"
    selected_key = f"gh_selected_{repo_id}"
    
    # Sort: directories first, then files
    sorted_files = sorted(files, key=lambda f: (0 if f.get("type") == "dir" else 1, f.get("name", "").lower()))
    
    for file_info in sorted_files:
        name = file_info.get("name", "Unknown")
        file_type = file_info.get("type", "file")
        size = file_info.get("size", 0)
        full_path = f"{current_path}/{name}" if current_path else name
        
        if file_type == "dir":
            # Directory - show expand/collapse
            is_expanded = full_path in st.session_state.get(expanded_key, set())
            icon = "📂" if is_expanded else "📁"
            
            if st.button(f"{icon} {name}", key=f"dir_{repo_id}_{full_path}", use_container_width=True):
                # Toggle expansion
                if is_expanded:
                    st.session_state[expanded_key].discard(full_path)
                else:
                    st.session_state[expanded_key].add(full_path)
                    # Fetch subdirectory contents
                    _fetch_directory_contents(owner, repo, full_path, pat, repo_id)
                st.rerun()
            
            # Show children if expanded
            if is_expanded:
                subdir_key = f"gh_subdir_{repo_id}_{full_path}"
                if subdir_key in st.session_state:
                    with st.container():
                        # Indent children
                        st.markdown("<div style='margin-left: 20px;'>", unsafe_allow_html=True)
                        _render_file_tree(
                            files=st.session_state[subdir_key],
                            repo_url=repo_url,
                            current_path=full_path,
                            owner=owner,
                            repo=repo,
                            pat=pat,
                            repo_id=repo_id
                        )
                        st.markdown("</div>", unsafe_allow_html=True)
        else:
            # File - show select button
            ext = Path(name).suffix.lower()
            
            # Choose icon based on file type
            if ext in ['.py', '.js', '.ts', '.java', '.c', '.cpp']:
                icon = "🐍" if ext == '.py' else "📜"
            elif ext in ['.md', '.txt', '.rst']:
                icon = "📝"
            elif ext in ['.json', '.yaml', '.yml', '.xml']:
                icon = "⚙️"
            elif ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg']:
                icon = "🖼️"
            elif ext == '.pdf':
                icon = "📄"
            else:
                icon = "📄"
            
            is_selected = st.session_state.get(selected_key) == full_path
            size_str = f" ({size / 1024:.1f}KB)" if size > 1024 else ""
            
            btn_label = f"{icon} {name}{size_str}"
            if st.button(btn_label, key=f"file_{repo_id}_{full_path}", 
                        use_container_width=True, type="primary" if is_selected else "secondary"):
                st.session_state[selected_key] = full_path
                st.rerun()


def _fetch_directory_contents(owner: str, repo: str, path: str, pat: Optional[str], repo_id: str):
    """Fetch contents of a subdirectory and return as list."""
    import requests
    
    headers = {"Accept": "application/vnd.github.v3+json"}
    if pat:
        headers["Authorization"] = f"token {pat}"
    
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            files = resp.json()
            return [
                {
                    "name": f.get("name"), 
                    "type": f.get("type"), 
                    "size": f.get("size", 0),
                    "path": f.get("path", "")
                }
                for f in files if isinstance(f, dict)
            ]
        elif resp.status_code == 403:
            return [{"name": "(Rate limit reached)", "type": "file", "size": 0, "path": ""}]
        else:
            return [{"name": f"(Error: {resp.status_code})", "type": "file", "size": 0, "path": ""}]
    except Exception as e:
        return [{"name": f"(Error: {e})", "type": "file", "size": 0, "path": ""}]


def _render_file_preview(selected_path: str, owner: str, repo: str, 
                         pat: Optional[str], repo_id: str):
    """Render file content with appropriate formatting."""
    import requests
    import base64 as b64
    
    content_cache_key = f"gh_content_{repo_id}"
    
    # Check cache first
    if selected_path in st.session_state.get(content_cache_key, {}):
        content_data = st.session_state[content_cache_key][selected_path]
    else:
        # Fetch file content
        headers = {"Accept": "application/vnd.github.v3+json"}
        if pat:
            headers["Authorization"] = f"token {pat}"
        
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}/contents/{selected_path}"
            resp = requests.get(url, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                size = data.get("size", 0)
                
                if size > get_max_inline_size():
                    content_data = {
                        "error": None,
                        "content": None,
                        "too_large": True,
                        "size": size,
                        "download_url": data.get("download_url", "")
                    }
                else:
                    if data.get("encoding") == "base64":
                        content = b64.b64decode(data.get("content", "")).decode("utf-8", errors="ignore")
                    else:
                        content = data.get("content", "")
                    
                    content_data = {
                        "error": None,
                        "content": content,
                        "too_large": False,
                        "size": size,
                        "download_url": data.get("download_url", "")
                    }
            elif resp.status_code == 403:
                content_data = {"error": "GitHub API rate limit reached", "content": None}
            else:
                content_data = {"error": f"Could not fetch file (HTTP {resp.status_code})", "content": None}
                
        except Exception as e:
            content_data = {"error": str(e), "content": None}
        
        # Cache the result
        if content_cache_key not in st.session_state:
            st.session_state[content_cache_key] = {}
        st.session_state[content_cache_key][selected_path] = content_data
    
    # Display
    filename = Path(selected_path).name
    ext = Path(filename).suffix.lower()
    size = content_data.get("size", 0)
    download_url = content_data.get("download_url", "")
    
    # File info panel (like DOCX viewer)
    size_str = f"{size / 1024:.1f} KB" if size > 0 else "—"
    file_type = ext.upper().replace(".", "") if ext else "File"
    
    info_html = f'''
    <div style="background: #2d2d2d; border-radius: 6px; padding: 10px 15px; margin-bottom: 10px; 
                display: flex; flex-wrap: wrap; gap: 20px; align-items: center; font-size: 13px; color: #ccc;">
        <div style="display: flex; align-items: center; gap: 6px;">
            <span style="color: #888;">📄 File:</span>
            <span style="color: #fff; font-weight: 500;">{filename}</span>
        </div>
        <div style="display: flex; align-items: center; gap: 6px;">
            <span style="color: #888;">📁 Type:</span>
            <span style="color: #fff; font-weight: 500;">{file_type}</span>
        </div>
        <div style="display: flex; align-items: center; gap: 6px;">
            <span style="color: #888;">📊 Size:</span>
            <span style="color: #fff; font-weight: 500;">{size_str}</span>
        </div>
        {f'<a href="{download_url}" target="_blank" style="color: #4da6ff; text-decoration: none;">📥 Download</a>' if download_url else ''}
    </div>
    '''
    st.components.v1.html(info_html, height=50)
    
    if content_data.get("error"):
        st.error(content_data["error"])
        return
    
    if content_data.get("too_large"):
        size_kb = content_data.get("size", 0) / 1024
        st.warning(f"⚠️ File too large to display inline ({size_kb:.1f} KB)")
        if download_url:
            st.markdown(f"[📥 Download {filename}]({download_url})")
        return
    content = content_data.get("content", "")
    
    # Render based on file type
    if ext == '.md':
        st.markdown(content)
    elif ext in LANGUAGE_MAP:
        st.code(content, language=LANGUAGE_MAP[ext])
    elif ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp']:
        # Display image from raw GitHub URL
        if download_url:
            st.image(download_url, caption=filename, width="stretch")
        else:
            st.warning("🖼️ Could not load image - no download URL available")
    elif ext in ['.zip', '.7z', '.rar', '.tar', '.gz']:
        # Archive files - fetch and display contents with drill-down
        import requests
        import zipfile
        import io
        import pandas as pd
        
        if ext == '.zip' and download_url:
            # Session state keys for ZIP navigation
            zip_cache_key = f"gh_zip_{repo_id}_{selected_path}"
            zip_file_key = f"gh_zip_file_{repo_id}_{selected_path}"
            
            # Fetch ZIP from GitHub raw URL
            if zip_cache_key not in st.session_state:
                with st.spinner("Fetching archive..."):
                    try:
                        resp = requests.get(download_url, timeout=30)
                        if resp.status_code == 200:
                            st.session_state[zip_cache_key] = resp.content
                        else:
                            st.session_state[zip_cache_key] = None
                    except Exception:
                        st.session_state[zip_cache_key] = None
            
            zip_data = st.session_state.get(zip_cache_key)
            selected_zip_file = st.session_state.get(zip_file_key)
            
            if zip_data:
                try:
                    with zipfile.ZipFile(io.BytesIO(zip_data), 'r') as zf:
                        # Check if password protected
                        is_encrypted = any(info.flag_bits & 0x1 for info in zf.infolist())
                        known_password = "ictkerala.org" if is_encrypted else None
                        
                        if is_encrypted:
                            try:
                                zf.setpassword(known_password.encode())
                            except Exception:
                                pass
                        
                        if selected_zip_file:
                            # === DRILL-DOWN VIEW: Show selected file from ZIP ===
                            st.markdown("#### 📄 File from Archive")
                            
                            # Back button
                            if st.button("🔙 Back to Archive", key=f"zip_back_{repo_id}"):
                                del st.session_state[zip_file_key]
                                st.rerun()
                            
                            # Get file info
                            try:
                                file_info = zf.getinfo(selected_zip_file)
                                file_size = file_info.file_size
                                file_name = Path(selected_zip_file).name
                                file_ext = Path(file_name).suffix.lower()
                                
                                # Info panel for file inside ZIP
                                size_str = f"{file_size / 1024:.1f} KB" if file_size > 0 else "—"
                                file_type_str = file_ext.upper().replace(".", "") if file_ext else "File"
                                
                                info_html = f'''
                                <div style="background: #2d2d2d; border-radius: 6px; padding: 10px 15px; margin: 10px 0; 
                                            display: flex; flex-wrap: wrap; gap: 20px; align-items: center; font-size: 13px; color: #ccc;">
                                    <div style="display: flex; align-items: center; gap: 6px;">
                                        <span style="color: #888;">📄 File:</span>
                                        <span style="color: #fff; font-weight: 500;">{file_name}</span>
                                    </div>
                                    <div style="display: flex; align-items: center; gap: 6px;">
                                        <span style="color: #888;">📁 Type:</span>
                                        <span style="color: #fff; font-weight: 500;">{file_type_str}</span>
                                    </div>
                                    <div style="display: flex; align-items: center; gap: 6px;">
                                        <span style="color: #888;">📊 Size:</span>
                                        <span style="color: #fff; font-weight: 500;">{size_str}</span>
                                    </div>
                                    <div style="display: flex; align-items: center; gap: 6px;">
                                        <span style="color: #888;">📦 From:</span>
                                        <span style="color: #fff; font-weight: 500;">{filename}</span>
                                    </div>
                                </div>
                                '''
                                st.components.v1.html(info_html, height=50)
                                
                                # Read file content
                                try:
                                    file_content = zf.read(selected_zip_file, pwd=known_password.encode() if known_password else None)
                                    
                                    # Render based on file type
                                    if file_ext in ['.txt', '.md', '.csv', '.log']:
                                        text_content = file_content.decode('utf-8', errors='ignore')
                                        if file_ext == '.md':
                                            st.markdown(text_content)
                                        else:
                                            st.code(text_content[:50000], language=None)
                                    elif file_ext in LANGUAGE_MAP:
                                        text_content = file_content.decode('utf-8', errors='ignore')
                                        st.code(text_content[:50000], language=LANGUAGE_MAP[file_ext])
                                    elif file_ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp']:
                                        st.image(file_content, caption=file_name, width="stretch")
                                    elif file_ext == '.json':
                                        text_content = file_content.decode('utf-8', errors='ignore')
                                        st.code(text_content, language='json')
                                    else:
                                        # Try to display as text for files without extension or unknown types
                                        try:
                                            text_content = file_content.decode('utf-8')
                                            # Check if it looks like text (mostly printable)
                                            if text_content and sum(c.isprintable() or c in '\n\r\t' for c in text_content) / len(text_content) > 0.9:
                                                st.code(text_content[:50000], language=None)
                                            else:
                                                st.info(f"📦 Binary file ({file_type_str}) - cannot display inline")
                                        except UnicodeDecodeError:
                                            st.info(f"📦 Binary file ({file_type_str}) - cannot display inline")
                                except Exception as e:
                                    st.error(f"❌ Error reading file: {e}")
                            except KeyError:
                                st.error(f"❌ File not found in archive: {selected_zip_file}")
                                del st.session_state[zip_file_key]
                        else:
                            # === ARCHIVE LIST VIEW ===
                            st.markdown("#### 📦 Archive Contents")
                            
                            if is_encrypted:
                                st.info("🔐 Password-protected archive")
                                st.success("✅ Unlocked with known password")
                            
                            # Build file list
                            file_list = []
                            file_map = {}
                            total_size = 0
                            
                            for i, info in enumerate(zf.infolist()):
                                if not info.is_dir():
                                    size = info.file_size
                                    total_size += size
                                    fname = info.filename
                                    fext = Path(fname).suffix.lower()
                                    icon = _get_file_icon(fname)
                                    
                                    file_list.append({
                                        "": icon,
                                        "Name": Path(fname).name,
                                        "Path": fname if "/" in fname else "—",
                                        "Size": f"{size / 1024:.1f} KB" if size > 0 else "—",
                                    })
                                    file_map[len(file_list) - 1] = fname
                            
                            if file_list:
                                df = pd.DataFrame(file_list)
                                
                                event = st.dataframe(
                                    df,
                                    hide_index=True,
                                    on_select="rerun",
                                    selection_mode="single-row",
                                    key=f"zip_table_{repo_id}_{selected_path}",
                                    width="stretch"
                                )
                                
                                # Handle selection
                                if event and event.selection and len(event.selection.rows) > 0:
                                    selected_idx = event.selection.rows[0]
                                    selected_file_in_zip = file_map.get(selected_idx)
                                    if selected_file_in_zip:
                                        st.session_state[zip_file_key] = selected_file_in_zip
                                        st.rerun()
                                
                                st.caption(f"📊 {len(file_list)} file(s) • Total: {total_size / 1024:.1f} KB • 👆 Click to preview")
                            else:
                                st.info("📭 Empty archive")
                                
                except zipfile.BadZipFile:
                    st.error("❌ Invalid or corrupted ZIP file")
                except Exception as e:
                    st.error(f"❌ Error reading archive: {e}")
            else:
                st.warning("Could not fetch archive from GitHub")
                if download_url:
                    st.markdown(f"[📥 Download {filename}]({download_url})")
        else:
            st.info(f"🗜️ {ext.upper()} archives not supported for inline viewing")
            if download_url:
                st.markdown(f"[📥 Download {filename}]({download_url})")
    else:
        # For other binary files, don't show garbled content
        if content and not content.isprintable():
            st.info(f"📦 Binary file ({file_type}) - download to view")
            if download_url:
                st.markdown(f"[📥 Download {filename}]({download_url})")
        else:
            st.code(content, language=None)


def render_submission_content(row: Dict[str, Any], course_id: int):
    """
    Smart content viewer that detects submission type and renders appropriate viewer.
    """
    import ast
    
    submission_text = row.get("Submission", "")
    submission_type = row.get("Submission_Type", "")
    submission_files = row.get("Submission_Files", [])
    
    # Parse submission files if string
    if isinstance(submission_files, str) and submission_files.startswith('['):
        try:
            submission_files = ast.literal_eval(submission_files)
        except:
            submission_files = []
    
    # Determine type if not set
    if not submission_type:
        if submission_files:
            submission_type = "file"
        elif "http" in submission_text.lower():
            submission_type = "link"
        elif submission_text.strip():
            submission_type = "text"
        else:
            submission_type = "empty"
    
    if submission_type == "empty" or not submission_text.strip():
        st.warning("⚠️ No submission content found")
        return
    
    if submission_type == "file":
        # File submissions - show each file
        if not submission_files:
            st.text(submission_text)
            return
            
        for f in submission_files:
            fname = f[0] if isinstance(f, (list, tuple)) else str(f)
            
            # Check if downloaded locally
            safe_student = "".join([c for c in row.get('Name', 'Unknown') if c.isalnum() or c in (' ', '-', '_')]).strip()
            safe_filename = "".join([c for c in fname if c.isalnum() or c in (' ', '-', '_', '.')]).strip()
            local_path = Path(f"output/course_{course_id}/downloads/{safe_student}/{safe_filename}")
            
            if local_path.exists():
                ext = local_path.suffix.lower()
                
                if ext == '.pdf':
                    # Show only extracted text content (file info is already shown above)
                    from core.ai import extract_pdf_text
                    text_content = extract_pdf_text(str(local_path))
                    
                    if text_content.startswith("(") and text_content.endswith(")"):
                        st.warning(text_content)
                    else:
                        st.text_area(
                            "📝 Extracted Content",
                            value=text_content,
                            height=400,
                            key=f"pdf_content_{hash(str(local_path))}",
                            disabled=True
                        )
                elif ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
                    st.image(str(local_path), caption=fname, width="stretch")
                elif ext in LANGUAGE_MAP or ext in ['.txt', '.log', '.csv']:
                    file_size = local_path.stat().st_size
                    if file_size > MAX_INLINE_SIZE:
                        st.warning(f"⚠️ {fname} is too large ({file_size / 1024:.1f}KB)")
                        with open(local_path, "rb") as file:
                            st.download_button(f"📥 Download {fname}", file, fname)
                    else:
                        with open(local_path, 'r', encoding='utf-8', errors='ignore') as file:
                            content = file.read()
                        lang = LANGUAGE_MAP.get(ext, None)
                        st.markdown(f"**{fname}**")
                        st.code(content, language=lang)
                else:
                    st.markdown(f"**{fname}** (Binary file)")
                    with open(local_path, "rb") as file:
                        st.download_button(f"📥 Download {fname}", file, fname, key=f"dl_{fname}")
            else:
                st.info(f"📂 {fname} - not downloaded yet")
    
    elif submission_type == "link":
        # Link submission
        import re
        url_match = re.search(r'(https?://[^\s]+)', submission_text)
        if url_match:
            url = url_match.group(1)
            
            if "github.com" in url:
                pat = get_config("github_pat")
                render_github_viewer(url, pat)
            else:
                # Non-GitHub link - just show it
                st.markdown(f"**Submitted Link:** [{url}]({url})")
                st.caption("(Content preview not available for non-GitHub URLs)")
        else:
            st.text(submission_text)
    
    elif submission_type == "text":
        st.text(submission_text)
