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

# Maximum file size to display inline (100KB)
MAX_INLINE_SIZE = 100000


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
    Interactive GitHub repository browser with file tree and content preview.
    """
    import re
    
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
    expanded_key = f"gh_expanded_{repo_id}"
    selected_key = f"gh_selected_{repo_id}"
    content_cache_key = f"gh_content_{repo_id}"
    
    # Initialize state
    if expanded_key not in st.session_state:
        st.session_state[expanded_key] = set()
    if selected_key not in st.session_state:
        st.session_state[selected_key] = None
    if content_cache_key not in st.session_state:
        st.session_state[content_cache_key] = {}
    
    # Header
    st.markdown(f"### 📂 Repository: [{owner}/{repo}]({repo_url})")
    
    # Fetch root contents if not cached
    if tree_key not in st.session_state:
        with st.spinner("Loading repository contents..."):
            from core.ai import fetch_github_content
            result = fetch_github_content(repo_url, pat)
            if result.get("error"):
                st.error(f"Could not load repository: {result['error']}")
                return
            st.session_state[tree_key] = {
                "files": result.get("files", []),
                "readme": result.get("readme", "")
            }
    
    tree_data = st.session_state[tree_key]
    files = tree_data.get("files", [])
    readme = tree_data.get("readme", "")
    
    # Layout: file tree on left, preview on right
    col_tree, col_preview = st.columns([1, 2])
    
    with col_tree:
        st.markdown("**Files**")
        _render_file_tree(
            files=files,
            repo_url=repo_url,
            current_path="",
            owner=owner,
            repo=repo,
            pat=pat,
            repo_id=repo_id
        )
    
    with col_preview:
        selected = st.session_state.get(selected_key)
        if selected:
            _render_file_preview(
                selected_path=selected,
                owner=owner,
                repo=repo,
                pat=pat,
                repo_id=repo_id
            )
        elif readme:
            st.markdown("**README.md**")
            st.markdown(readme[:5000] if len(readme) > 5000 else readme)
        else:
            st.info("👈 Select a file to preview")


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
    """Fetch contents of a subdirectory."""
    import requests
    import base64
    
    subdir_key = f"gh_subdir_{repo_id}_{path}"
    if subdir_key in st.session_state:
        return  # Already cached
    
    headers = {"Accept": "application/vnd.github.v3+json"}
    if pat:
        headers["Authorization"] = f"token {pat}"
    
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            files = resp.json()
            st.session_state[subdir_key] = [
                {"name": f.get("name"), "type": f.get("type"), "size": f.get("size", 0)}
                for f in files if isinstance(f, dict)
            ]
        elif resp.status_code == 403:
            st.session_state[subdir_key] = [{"name": "(Rate limit reached)", "type": "file", "size": 0}]
        else:
            st.session_state[subdir_key] = [{"name": f"(Error: {resp.status_code})", "type": "file", "size": 0}]
    except Exception as e:
        st.session_state[subdir_key] = [{"name": f"(Error: {e})", "type": "file", "size": 0}]


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
                
                if size > MAX_INLINE_SIZE:
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
                        "size": size
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
    st.markdown(f"**{selected_path}**")
    
    if content_data.get("error"):
        st.error(content_data["error"])
        return
    
    if content_data.get("too_large"):
        size_kb = content_data.get("size", 0) / 1024
        st.warning(f"⚠️ File too large to display inline ({size_kb:.1f} KB)")
        download_url = content_data.get("download_url", "")
        if download_url:
            st.markdown(f"[📥 Download {filename}]({download_url})")
        return
    
    content = content_data.get("content", "")
    ext = Path(filename).suffix.lower()
    
    # Render based on file type
    if ext == '.md':
        st.markdown(content)
    elif ext in LANGUAGE_MAP:
        st.code(content, language=LANGUAGE_MAP[ext])
    elif ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg']:
        st.info("🖼️ Image files cannot be previewed from GitHub API directly.")
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
