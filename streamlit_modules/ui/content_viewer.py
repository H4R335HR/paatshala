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
MAX_INLINE_SIZE = 512 * 1024  # Legacy constant for backwards compatibility

def get_max_inline_size():
    """Get max inline file size from config (in bytes)."""
    try:
        size_kb = int(get_config("max_inline_size_kb") or 512)
        return size_kb * 1024
    except (ValueError, TypeError):
        return 512 * 1024  # 512KB default


# ============================================================================
# SHARED FILE TYPE CONSTANTS
# ============================================================================

# Image file extensions
IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg']

# Text/log file extensions (beyond code files in LANGUAGE_MAP)
TEXT_EXTENSIONS = ['.txt', '.log', '.csv', '.md']

# Archive file extensions
ARCHIVE_EXTENSIONS = ['.zip', '.7z', '.rar', '.tar', '.gz']


# ============================================================================
# SHARED CONTENT RENDERING HELPERS
# ============================================================================

def is_image_file(filename: str) -> bool:
    """Check if filename is an image based on extension."""
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def is_code_file(filename: str) -> bool:
    """Check if filename is a code file with syntax highlighting support."""
    return Path(filename).suffix.lower() in LANGUAGE_MAP


def is_text_file(filename: str) -> bool:
    """Check if filename is a plain text file."""
    return Path(filename).suffix.lower() in TEXT_EXTENSIONS


def is_archive_file(filename: str) -> bool:
    """Check if filename is an archive."""
    return Path(filename).suffix.lower() in ARCHIVE_EXTENSIONS


def get_language_for_file(filename: str) -> Optional[str]:
    """Get syntax highlighting language for a file based on extension."""
    ext = Path(filename).suffix.lower()
    return LANGUAGE_MAP.get(ext)


def render_code_content(content: str, filename: str = "", max_chars: int = 50000):
    """
    Render code/text content with appropriate syntax highlighting.
    
    Args:
        content: The text content to display
        filename: Optional filename to determine syntax highlighting
        max_chars: Maximum characters to display (default 50KB)
    """
    # Truncate if needed
    if len(content) > max_chars:
        display_content = content[:max_chars] + f"\n\n[Truncated at {max_chars} characters]"
    else:
        display_content = content
    
    # Get language from filename
    language = get_language_for_file(filename) if filename else None
    
    # Render with syntax highlighting
    st.code(display_content, language=language)


def render_image_content(image_source, caption: str = ""):
    """
    Render an image from various sources.
    
    Args:
        image_source: Can be a file path (str/Path), bytes, or URL
        caption: Optional caption for the image
    """
    st.image(image_source, caption=caption, width="stretch")


def render_text_content(content: str, label: str = "", max_chars: int = 50000, height: int = 400):
    """
    Render plain text content in a disabled text area.
    
    Args:
        content: Text content to display
        label: Optional label for the text area
        max_chars: Maximum characters to display
        height: Height of text area in pixels
    """
    if len(content) > max_chars:
        display_content = content[:max_chars] + f"\n\n[Truncated at {max_chars} characters]"
    else:
        display_content = content
    
    st.text_area(
        label or "Content",
        value=display_content,
        height=height,
        disabled=True,
        label_visibility="collapsed" if not label else "visible"
    )


def render_file_info_panel(filename: str, file_type: str = "", size_bytes: int = 0, 
                           extra_info: Dict[str, str] = None, download_url: str = ""):
    """
    Render a consistent file info panel used across viewers.
    
    Args:
        filename: Name of the file
        file_type: File type string (e.g., "PDF", "DOCX")
        size_bytes: File size in bytes
        extra_info: Additional key-value pairs to display
        download_url: Optional download URL
    """
    size_str = f"{size_bytes / 1024:.1f} KB" if size_bytes > 0 else "—"
    if not file_type:
        file_type = Path(filename).suffix.upper().replace(".", "") or "File"
    
    # Build info items
    info_items = [
        f'<div style="display: flex; align-items: center; gap: 6px;">'
        f'<span style="color: #888;">📄 File:</span>'
        f'<span style="color: #fff; font-weight: 500;">{filename}</span>'
        f'</div>',
        f'<div style="display: flex; align-items: center; gap: 6px;">'
        f'<span style="color: #888;">📁 Type:</span>'
        f'<span style="color: #fff; font-weight: 500;">{file_type}</span>'
        f'</div>',
        f'<div style="display: flex; align-items: center; gap: 6px;">'
        f'<span style="color: #888;">📊 Size:</span>'
        f'<span style="color: #fff; font-weight: 500;">{size_str}</span>'
        f'</div>',
    ]
    
    # Add extra info
    if extra_info:
        for key, value in extra_info.items():
            info_items.append(
                f'<div style="display: flex; align-items: center; gap: 6px;">'
                f'<span style="color: #888;">{key}:</span>'
                f'<span style="color: #fff; font-weight: 500;">{value}</span>'
                f'</div>'
            )
    
    # Add download link
    if download_url:
        info_items.append(
            f'<a href="{download_url}" target="_blank" style="color: #4da6ff; text-decoration: none;">📥 Download</a>'
        )
    
    info_html = f'''
    <div style="background: #2d2d2d; border-radius: 6px; padding: 10px 15px; margin-bottom: 10px; 
                display: flex; flex-wrap: wrap; gap: 20px; align-items: center; font-size: 13px; color: #ccc;">
        {''.join(info_items)}
    </div>
    '''
    st.components.v1.html(info_html, height=50)


def render_pdf_viewer(pdf_bytes: bytes, filename: str = "document.pdf", unique_key: str = ""):
    """
    Rich PDF viewer using pdf.js with zoom, fullscreen, and multi-page support.
    
    Args:
        pdf_bytes: The raw bytes of the PDF file
        filename: Display name for the document  
        unique_key: Optional unique key suffix to prevent duplicate key errors
    """
    try:
        if not pdf_bytes or len(pdf_bytes) < 10:
            st.warning("⚠️ Empty or invalid PDF data")
            return
        
        # Large PDFs (>1MB) can cause JavaScript loading issues with inline base64
        if len(pdf_bytes) > 1024 * 1024:  # 1MB limit
            st.warning(f"⚠️ PDF is large ({len(pdf_bytes) / 1024 / 1024:.1f} MB). Download for best viewing experience.")
            st.download_button(
                label=f"📥 Download {filename}",
                data=pdf_bytes,
                file_name=filename,
                mime="application/pdf",
                key=f"dl_large_pdf_{unique_key or abs(hash(pdf_bytes[:100]))}"
            )
            return
        
        b64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
        idx = unique_key or abs(hash(pdf_bytes[:100]))
        
        # PDF.js viewer with zoom, fullscreen, multi-page scrolling
        pdfjs_html = f'''
        <style>
            #pdfContainer_{idx} {{ 
                width: 100%; 
                background: #525659; 
                border-radius: 8px; 
                padding: 10px;
                text-align: center;
            }}
            #pdfContainer_{idx}:fullscreen {{
                background: #525659;
                padding: 20px;
            }}
            #pdfScroller_{idx} {{
                max-height: 550px;
                overflow-y: auto;
                background: #3a3a3a;
                border-radius: 4px;
                padding: 10px;
            }}
            #pdfContainer_{idx}:fullscreen #pdfScroller_{idx} {{
                max-height: calc(100vh - 80px);
            }}
            .pdf-page-canvas_{idx} {{
                max-width: 100%; 
                box-shadow: 0 2px 10px rgba(0,0,0,0.3);
                margin-bottom: 15px;
                display: block;
                margin-left: auto;
                margin-right: auto;
            }}
            .pdf-controls_{idx} {{
                display: flex;
                justify-content: center;
                align-items: center;
                gap: 12px;
                margin-bottom: 10px;
                color: white;
                font-family: sans-serif;
                flex-wrap: wrap;
            }}
            .pdf-btn_{idx} {{
                background: #333;
                color: white;
                border: 1px solid #555;
                padding: 6px 12px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 13px;
            }}
            .pdf-btn_{idx}:hover {{ background: #444; }}
        </style>
        
        <div id="pdfContainer_{idx}">
            <div class="pdf-controls_{idx}">
                <span id="pageInfo_{idx}">Loading...</span>
                <span>|</span>
                <span>Zoom:</span>
                <button class="pdf-btn_{idx}" onclick="zoomOut_{idx}()">−</button>
                <span id="zoomLevel_{idx}">100%</span>
                <button class="pdf-btn_{idx}" onclick="zoomIn_{idx}()">+</button>
                <span>|</span>
                <button class="pdf-btn_{idx}" onclick="toggleFullscreen_{idx}()" id="fsBtn_{idx}">⛶ Fullscreen</button>
            </div>
            <div id="pdfScroller_{idx}">
                <div id="pdfPages_{idx}"></div>
            </div>
        </div>
        
        <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
        <script>
            (async function() {{
                const pdfjsLib = window['pdfjs-dist/build/pdf'];
                pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
                
                const b64 = "{b64_pdf}";
                const binary = atob(b64);
                const bytes = new Uint8Array(binary.length);
                for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
                
                let pdfDoc = null;
                let scale = 1.5;
                const container = document.getElementById('pdfPages_{idx}');
                
                async function renderAllPages() {{
                    container.innerHTML = '';
                    for (let num = 1; num <= pdfDoc.numPages; num++) {{
                        const page = await pdfDoc.getPage(num);
                        const viewport = page.getViewport({{ scale: scale }});
                        
                        const canvas = document.createElement('canvas');
                        canvas.className = 'pdf-page-canvas_{idx}';
                        canvas.height = viewport.height;
                        canvas.width = viewport.width;
                        container.appendChild(canvas);
                        
                        const ctx = canvas.getContext('2d');
                        await page.render({{ canvasContext: ctx, viewport: viewport }}).promise;
                    }}
                    document.getElementById('pageInfo_{idx}').textContent = pdfDoc.numPages + ' page(s)';
                    document.getElementById('zoomLevel_{idx}').textContent = Math.round(scale*100/1.5) + '%';
                }}
                
                window.zoomIn_{idx} = function() {{ scale += 0.25; renderAllPages(); }};
                window.zoomOut_{idx} = function() {{ if (scale > 0.5) {{ scale -= 0.25; renderAllPages(); }} }};
                
                window.toggleFullscreen_{idx} = function() {{
                    const cont = document.getElementById('pdfContainer_{idx}');
                    const btn = document.getElementById('fsBtn_{idx}');
                    
                    if (document.fullscreenElement) {{
                        document.exitFullscreen();
                        btn.textContent = '⛶ Fullscreen';
                    }} else {{
                        cont.requestFullscreen().then(() => {{
                            btn.textContent = '✕ Exit';
                        }}).catch(err => {{
                            alert('Fullscreen not available: ' + err.message);
                        }});
                    }}
                }};
                
                document.addEventListener('fullscreenchange', () => {{
                    const btn = document.getElementById('fsBtn_{idx}');
                    if (btn && !document.fullscreenElement) {{
                        btn.textContent = '⛶ Fullscreen';
                    }}
                }});
                
                try {{
                    pdfDoc = await pdfjsLib.getDocument({{ data: bytes }}).promise;
                    await renderAllPages();
                }} catch (err) {{
                    document.getElementById('pageInfo_{idx}').textContent = 'Error: ' + err.message;
                }}
            }})();
        </script>
        '''
        st.components.v1.html(pdfjs_html, height=650)
        st.caption("💡 Scroll through pages • Zoom in/out • Fullscreen mode")
        
    except Exception as e:
        logger.error(f"Error rendering PDF viewer: {e}")
        st.error(f"Could not display PDF: {e}")


def render_docx_viewer(docx_bytes: bytes, filename: str = "document.docx", unique_key: str = ""):
    """
    DOCX content viewer using mammoth.js with document metadata display.
    
    Provides rich viewing experience with:
    - Document metadata (author, words, edit time, revisions, template)
    - Fullscreen support
    - Page estimation from rendered height
    
    Args:
        docx_bytes: The raw bytes of the DOCX file
        filename: Display name for the document
        unique_key: Optional unique key suffix to prevent duplicate key errors
    """
    try:
        import io
        
        # Check if DOCX is valid (should start with "PK" - ZIP magic bytes)
        if len(docx_bytes) < 4 or docx_bytes[:2] != b'PK':
            st.warning("🔐 This document appears to be password-protected and cannot be previewed.")
            st.info("💡 The student may have applied password protection to the DOCX file itself.")
            return
        
        # Extract metadata from DOCX
        doc_meta = {
            'author': '—',
            'words': '—',
            'meta_pages': '—',
            'edit_time': '—',
            'revision': '—',
            'template': '—',
            'warning': ''
        }
        
        try:
            import zipfile
            import xml.etree.ElementTree as ET
            
            with zipfile.ZipFile(io.BytesIO(docx_bytes), 'r') as zf:
                # Extract from app.xml (words, pages, edit time, template)
                if 'docProps/app.xml' in zf.namelist():
                    app_xml = zf.read('docProps/app.xml')
                    root = ET.fromstring(app_xml)
                    for elem in root.iter():
                        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                        if tag == 'Words' and elem.text:
                            doc_meta['words'] = elem.text
                        elif tag == 'TotalTime' and elem.text:
                            try:
                                mins = int(elem.text)
                                if mins < 60:
                                    doc_meta['edit_time'] = f"{mins} min"
                                else:
                                    doc_meta['edit_time'] = f"{mins // 60}h {mins % 60}m"
                            except:
                                doc_meta['edit_time'] = f"{elem.text} min"
                        elif tag == 'Pages' and elem.text:
                            doc_meta['meta_pages'] = elem.text
                        elif tag == 'Template' and elem.text:
                            doc_meta['template'] = elem.text
                
                # Extract from core.xml (author, revision)
                if 'docProps/core.xml' in zf.namelist():
                    core_xml = zf.read('docProps/core.xml')
                    root = ET.fromstring(core_xml)
                    for elem in root.iter():
                        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                        if tag == 'creator' and elem.text:
                            doc_meta['author'] = elem.text.strip()
                        elif tag == 'revision' and elem.text:
                            doc_meta['revision'] = elem.text
                
                # Check for suspicious patterns (high words/min)
                try:
                    words = int(doc_meta['words']) if doc_meta['words'] != '—' else 0
                    edit_time_str = doc_meta['edit_time']
                    if edit_time_str != '—':
                        if 'h' in edit_time_str:
                            parts = edit_time_str.replace('h', ' ').replace('m', '').split()
                            edit_mins = int(parts[0]) * 60 + int(parts[1]) if len(parts) > 1 else int(parts[0]) * 60
                        else:
                            edit_mins = int(edit_time_str.replace(' min', ''))
                        if edit_mins > 0 and words > 0:
                            wpm = words / edit_mins
                            if wpm > 100:  # More than 100 words/min is suspicious
                                doc_meta['warning'] = f'⚠️ High words/min ratio ({wpm:.0f}) - possible copy-paste'
                except:
                    pass
        except Exception:
            pass  # Metadata extraction failed, continue with defaults
        
        b64_docx = base64.b64encode(docx_bytes).decode('utf-8')
        idx = unique_key or hash(docx_bytes[:100])
        
        mammoth_html = f'''
        <style>
            #docxContainer_{idx} {{
                width: 100%;
                background: #ffffff;
                border-radius: 8px;
                padding: 10px;
            }}
            #docxContainer_{idx}:fullscreen {{
                background: #ffffff;
                padding: 20px;
            }}
            #docxScroller_{idx} {{
                max-height: 500px;
                overflow-y: auto;
                background: #ffffff;
                border-radius: 4px;
                padding: 20px 30px;
                color: #333;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
            }}
            #docxContainer_{idx}:fullscreen #docxScroller_{idx} {{
                max-height: calc(100vh - 80px);
            }}
            #docxContent_{idx} h1 {{ font-size: 1.8em; margin: 0.8em 0; color: #222; }}
            #docxContent_{idx} h2 {{ font-size: 1.5em; margin: 0.7em 0; color: #333; }}
            #docxContent_{idx} h3 {{ font-size: 1.2em; margin: 0.6em 0; color: #444; }}
            #docxContent_{idx} p {{ margin: 0.5em 0; }}
            #docxContent_{idx} table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
            #docxContent_{idx} td, #docxContent_{idx} th {{ border: 1px solid #ddd; padding: 8px; }}
            #docxContent_{idx} ul, #docxContent_{idx} ol {{ padding-left: 2em; }}
            .docx-controls_{idx} {{
                display: flex;
                justify-content: flex-end;
                gap: 10px;
                margin-bottom: 10px;
            }}
            .docx-btn_{idx} {{
                background: #333;
                color: white;
                border: 1px solid #555;
                padding: 6px 12px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 13px;
            }}
            .docx-btn_{idx}:hover {{ background: #444; }}
            #docxStatus_{idx} {{ color: #666; font-size: 13px; }}
            .docx-info-panel_{idx} {{
                background: #2d2d2d;
                border-radius: 6px;
                padding: 10px 15px;
                margin-bottom: 10px;
                display: flex;
                flex-wrap: wrap;
                gap: 20px;
                align-items: center;
                font-size: 13px;
                color: #ccc;
            }}
            .docx-info-item_{idx} {{
                display: flex;
                align-items: center;
                gap: 6px;
            }}
            .docx-info-label_{idx} {{ color: #888; }}
            .docx-info-value_{idx} {{ color: #fff; font-weight: 500; }}
        </style>
        
        <div id="docxContainer_{idx}">
            <div class="docx-info-panel_{idx}">
                <div class="docx-info-item_{idx}">
                    <span class="docx-info-label_{idx}">👤 Author:</span>
                    <span class="docx-info-value_{idx}">{doc_meta['author']}</span>
                </div>
                <div class="docx-info-item_{idx}">
                    <span class="docx-info-label_{idx}">📝 Words:</span>
                    <span class="docx-info-value_{idx}">{doc_meta['words']}</span>
                </div>
                <div class="docx-info-item_{idx}">
                    <span class="docx-info-label_{idx}">📄 Meta pages:</span>
                    <span class="docx-info-value_{idx}">{doc_meta['meta_pages']}</span>
                </div>
                <div class="docx-info-item_{idx}">
                    <span class="docx-info-label_{idx}">⏱️ Edit time:</span>
                    <span class="docx-info-value_{idx}">{doc_meta['edit_time']}</span>
                </div>
                <div class="docx-info-item_{idx}">
                    <span class="docx-info-label_{idx}">🔄 Revisions:</span>
                    <span class="docx-info-value_{idx}">{doc_meta['revision']}</span>
                </div>
                <div class="docx-info-item_{idx}">
                    <span class="docx-info-label_{idx}">📋 Template:</span>
                    <span class="docx-info-value_{idx}">{doc_meta['template']}</span>
                </div>
                {f'<div style="background: #553300; color: #ffaa00; padding: 4px 10px; border-radius: 4px; font-size: 12px;">{doc_meta["warning"]}</div>' if doc_meta['warning'] else ''}
            </div>
            <div class="docx-controls_{idx}">
                <span id="docxStatus_{idx}">Loading document...</span>
                <button class="docx-btn_{idx}" onclick="toggleDocxFullscreen_{idx}()" id="docxFsBtn_{idx}">⛶ Fullscreen</button>
            </div>
            <div id="docxScroller_{idx}">
                <div id="docxContent_{idx}"></div>
            </div>
        </div>
        
        <script src="https://cdnjs.cloudflare.com/ajax/libs/mammoth/1.6.0/mammoth.browser.min.js"></script>
        <script>
            (async function() {{
                const b64 = "{b64_docx}";
                const binary = atob(b64);
                const bytes = new Uint8Array(binary.length);
                for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
                
                try {{
                    const result = await mammoth.convertToHtml({{ arrayBuffer: bytes.buffer }});
                    const contentDiv = document.getElementById('docxContent_{idx}');
                    contentDiv.innerHTML = result.value;
                    
                    // Estimate page count based on rendered height
                    setTimeout(() => {{
                        const contentHeight = contentDiv.scrollHeight;
                        const pageHeightPx = 1050;
                        const estimatedPages = Math.max(1, Math.ceil(contentHeight / pageHeightPx));
                        document.getElementById('docxStatus_{idx}').textContent = 
                            '📄 ~' + estimatedPages + ' page(s) (estimated)';
                    }}, 100);
                }} catch (err) {{
                    document.getElementById('docxContent_{idx}').innerHTML = 
                        '<p style="color:red;">Error loading document: ' + err.message + '</p>';
                    document.getElementById('docxStatus_{idx}').textContent = '❌ Error';
                }}
                
                window.toggleDocxFullscreen_{idx} = function() {{
                    const cont = document.getElementById('docxContainer_{idx}');
                    const btn = document.getElementById('docxFsBtn_{idx}');
                    
                    if (document.fullscreenElement) {{
                        document.exitFullscreen();
                        btn.textContent = '⛶ Fullscreen';
                    }} else {{
                        cont.requestFullscreen().then(() => {{
                            btn.textContent = '✕ Exit';
                        }}).catch(err => {{
                            alert('Fullscreen not available: ' + err.message);
                        }});
                    }}
                }};
                
                document.addEventListener('fullscreenchange', () => {{
                    const btn = document.getElementById('docxFsBtn_{idx}');
                    if (btn && !document.fullscreenElement) {{
                        btn.textContent = '⛶ Fullscreen';
                    }}
                }});
            }})();
        </script>
        '''
        st.components.v1.html(mammoth_html, height=650)
        st.caption("💡 Scroll through document • Fullscreen mode available")
        
    except Exception as e:
        logger.error(f"Error rendering DOCX viewer: {e}")
        st.error(f"Could not display DOCX: {e}")


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
        
        # Handle selection from table (but skip if navigation happened this cycle)
        nav_flag_key = f"gh_nav_pending_{repo_id}"
        if st.session_state.get(nav_flag_key):
            # Clear the flag and skip table processing
            del st.session_state[nav_flag_key]
        elif event and event.selection and len(event.selection.rows) > 0:
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
        # Build list of previewable files (excluding directories) for navigation
        file_paths = [f.get("path", f.get("name")) for f in files if f.get("type") != "dir"]
        current_idx = file_paths.index(selected) if selected in file_paths else -1
        total_files = len(file_paths)
        
        # Navigation row: Previous | Title | Next
        nav_col1, nav_col2, nav_col3 = st.columns([1, 4, 1])
        nav_flag_key = f"gh_nav_pending_{repo_id}"
        
        with nav_col1:
            if current_idx > 0:
                if st.button("⬅️ Previous", key=f"gh_prev_{repo_id}"):
                    st.session_state[nav_flag_key] = True
                    st.session_state[selected_key] = file_paths[current_idx - 1]
                    st.rerun()
            else:
                st.button("⬅️ Previous", key=f"gh_prev_{repo_id}", disabled=True)
        
        with nav_col2:
            if current_idx >= 0:
                st.markdown(f"#### 👁️ Preview ({current_idx + 1}/{total_files})")
            else:
                st.markdown("#### 👁️ Preview")
        
        with nav_col3:
            if current_idx < total_files - 1 and current_idx >= 0:
                if st.button("Next ➡️", key=f"gh_next_{repo_id}"):
                    st.session_state[nav_flag_key] = True
                    st.session_state[selected_key] = file_paths[current_idx + 1]
                    st.rerun()
            else:
                st.button("Next ➡️", key=f"gh_next_{repo_id}", disabled=True)
        
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
            
            if st.button(f"{icon} {name}", key=f"dir_{repo_id}_{full_path}", width="stretch"):
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
                        width="stretch", type="primary" if is_selected else "secondary"):
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
    elif ext in IMAGE_EXTENSIONS:
        # Display image from raw GitHub URL
        if download_url:
            render_image_content(download_url, caption=filename)
        else:
            st.warning("🖼️ Could not load image - no download URL available")
    elif ext == '.pdf':
        # PDF file - fetch and use PDF viewer
        if download_url:
            import requests
            
            with st.spinner("Fetching PDF..."):
                try:
                    resp = requests.get(download_url, timeout=30)
                    if resp.status_code == 200:
                        # Use the shared PDF viewer with bytes directly
                        render_pdf_viewer(resp.content, filename, unique_key=f"gh_{hash(download_url)}")
                    else:
                        st.warning(f"Could not fetch PDF (HTTP {resp.status_code})")
                        st.markdown(f"[📥 Download {filename}]({download_url})")
                except Exception as e:
                    st.error(f"Error fetching PDF: {e}")
                    st.markdown(f"[📥 Download {filename}]({download_url})")
        else:
            st.info("📕 PDF file - no download URL available")
    elif ext in ['.docx', '.doc']:
        # DOCX file - fetch and reuse existing DOCX viewer
        if download_url:
            import requests
            
            with st.spinner("Fetching document..."):
                try:
                    resp = requests.get(download_url, timeout=30)
                    if resp.status_code == 200:
                        # Use the shared DOCX viewer
                        render_docx_viewer(resp.content, filename, unique_key=f"gh_{hash(download_url)}")
                    else:
                        st.warning(f"Could not fetch DOCX (HTTP {resp.status_code})")
                        st.markdown(f"[📥 Download {filename}]({download_url})")
                except Exception as e:
                    st.error(f"Error fetching DOCX: {e}")
                    st.markdown(f"[📥 Download {filename}]({download_url})")
        else:
            st.info("📄 DOCX file - no download URL available")
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
                        # Check if ZIP archive is password protected
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
                                    elif file_ext in IMAGE_EXTENSIONS:
                                        render_image_content(file_content, caption=file_name)
                                    elif file_ext == '.json':
                                        text_content = file_content.decode('utf-8', errors='ignore')
                                        st.code(text_content, language='json')
                                    elif file_ext == '.pdf':
                                        # Use the reusable PDF viewer for PDFs inside ZIP
                                        if len(file_content) < 100:
                                            st.warning(f"⚠️ PDF appears empty or corrupted ({len(file_content)} bytes)")
                                        else:
                                            # Show size info and render
                                            st.caption(f"📄 Loading PDF ({len(file_content) / 1024:.1f} KB)...")
                                            render_pdf_viewer(file_content, file_name, unique_key=f"zip_{abs(hash(selected_zip_file))}")
                                    elif file_ext in ['.docx', '.doc']:
                                        # Use the reusable DOCX viewer
                                        render_docx_viewer(file_content, file_name, unique_key=f"zip_{abs(hash(selected_zip_file))}")
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
                elif ext in IMAGE_EXTENSIONS:
                    render_image_content(str(local_path), caption=fname)
                elif ext in LANGUAGE_MAP or ext in ['.txt', '.log', '.csv']:
                    file_size = local_path.stat().st_size
                    if file_size > get_max_inline_size():
                        st.warning(f"⚠️ {fname} is too large ({file_size / 1024:.1f}KB)")
                        with open(local_path, "rb") as file:
                            st.download_button(f"📥 Download {fname}", file, fname)
                    else:
                        with open(local_path, 'r', encoding='utf-8', errors='ignore') as file:
                            content = file.read()
                        st.markdown(f"**{fname}**")
                        render_code_content(content, fname)
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
