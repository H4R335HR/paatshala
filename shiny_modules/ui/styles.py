"""
Custom CSS styles for the Shiny application
Minimalistic design with dark/light theme support
"""

def get_custom_css():
    """Returns the custom CSS for the Shiny application"""
    return """
/* ============================================================================
   THEME SYSTEM - Light (default) and Dark modes
   ============================================================================ */
:root {
    /* Light Theme Colors */
    --bg-primary: #f8fafc;
    --bg-secondary: #ffffff;
    --bg-tertiary: #f1f5f9;
    --text-primary: #0f172a;
    --text-secondary: #475569;
    --text-muted: #94a3b8;
    --border-color: #e2e8f0;
    --accent: #6366f1;
    --accent-hover: #4f46e5;
    --accent-soft: #e0e7ff;
    --success: #10b981;
    --danger: #ef4444;
    --danger-soft: #fef2f2;
    --warning: #f59e0b;
    --shadow: 0 1px 3px rgba(0,0,0,0.1);
    --shadow-lg: 0 4px 6px -1px rgba(0,0,0,0.1);
}

[data-theme="dark"] {
    --bg-primary: #0f172a;
    --bg-secondary: #1e293b;
    --bg-tertiary: #334155;
    --text-primary: #f1f5f9;
    --text-secondary: #cbd5e1;
    --text-muted: #64748b;
    --border-color: #334155;
    --accent: #818cf8;
    --accent-hover: #a5b4fc;
    --accent-soft: rgba(99,102,241,0.2);
    --success: #34d399;
    --danger: #f87171;
    --danger-soft: rgba(239,68,68,0.15);
    --warning: #fbbf24;
    --shadow: 0 1px 3px rgba(0,0,0,0.3);
    --shadow-lg: 0 4px 6px -1px rgba(0,0,0,0.4);
}

/* ============================================================================
   BASE STYLES
   ============================================================================ */
* { transition: background-color 0.2s, border-color 0.2s, color 0.2s; }

body {
    background: var(--bg-primary);
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    color: var(--text-primary);
}

/* ============================================================================
   NAVBAR (Bootstrap override)
   ============================================================================ */
.navbar, .navbar-nav, .nav-link {
    background: var(--bg-secondary) !important;
    color: var(--text-primary) !important;
}
.navbar {
    border-bottom: 1px solid var(--border-color);
}
.navbar .form-select, .navbar select {
    background: var(--bg-secondary) !important;
    color: var(--text-primary) !important;
    border-color: var(--border-color) !important;
}
.navbar .btn-light {
    background: var(--bg-tertiary) !important;
    color: var(--text-primary) !important;
    border: none;
}
.navbar .btn-light:hover {
    background: var(--border-color) !important;
}

/* ============================================================================
   APP CARD & LAYOUT
   ============================================================================ */
.app-card {
    background: var(--bg-secondary);
    border-radius: 12px;
    box-shadow: var(--shadow-lg);
    overflow: hidden;
    height: 80vh;
    display: flex;
    flex-direction: column;
}

/* ============================================================================
   TOOLBAR
   ============================================================================ */
.toolbar {
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
    padding: 8px 20px;
    display: flex;
    gap: 4px;
    align-items: center;
    flex-wrap: nowrap;
    min-height: 56px;
    box-sizing: border-box;
    overflow: hidden;
}

.toolbar-divider {
    width: 1px;
    height: 28px;
    background: var(--border-color);
    flex-shrink: 0;
}

/* Icon Buttons */
.toolbar-icon-btn {
    width: 36px;
    height: 36px;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    border-radius: 8px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s;
    font-size: 1.25rem;
    font-weight: 600;
}
.toolbar-icon-btn:hover:not(:disabled) {
    background: var(--bg-tertiary);
    color: var(--text-primary);
}
.toolbar-icon-btn:disabled {
    opacity: 0.35;
    cursor: not-allowed;
}
.toolbar-icon-btn-primary {
    background: var(--accent);
    color: white;
}
.toolbar-icon-btn-primary:hover:not(:disabled) {
    background: var(--accent-hover);
}
.toolbar-icon-btn-danger {
    color: var(--danger);
}
.toolbar-icon-btn-danger:hover:not(:disabled) {
    background: var(--danger-soft);
}

/* Fix vertical alignment for Shiny inputs in toolbar */
#toolbar_actions .shiny-input-container,
#toolbar_actions .form-group {
    margin-bottom: 0 !important;
}

/* Toolbar Inputs */
#toolbar_actions input[type="number"],
#toolbar_actions input[type="text"],
#toolbar_actions select {
    height: 40px !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 8px !important;
    padding: 0 12px !important;
    font-size: 0.875rem !important;
    background: var(--bg-secondary) !important;
    color: var(--text-primary) !important;
    box-sizing: border-box !important;
}
#toolbar_actions input:focus,
#toolbar_actions select:focus {
    outline: none !important;
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-soft) !important;
}
#toolbar_actions input[type="number"] {
    width: 55px !important;
    text-align: center !important;
}

/* ============================================================================
   TABLE
   ============================================================================ */
.topics-table-container {
    flex: 1;
    overflow-y: auto;
}

.topics-table {
    width: 100%;
    border-collapse: collapse;
}

.topics-table th {
    position: sticky;
    top: 0;
    background: var(--bg-tertiary);
    padding: 12px 16px;
    text-align: left;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    color: var(--text-muted);
    border-bottom: 1px solid var(--border-color);
    z-index: 10;
}

.topics-table td {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border-color);
    font-size: 0.875rem;
    color: var(--text-primary);
}

.topics-table tr {
    background: var(--bg-secondary);
    cursor: pointer;
    transition: background 0.1s;
}
.topics-table tr:hover { background: var(--bg-tertiary); }
.topics-table tr.selected-row { background: var(--accent-soft); }
.topics-table tr.sortable-ghost { opacity: 0.4; background: var(--accent-soft); }

/* ============================================================================
   ICON ACTIONS & BUTTONS
   ============================================================================ */
.btn-icon-action {
    cursor: pointer;
    padding: 6px;
    border-radius: 6px;
    border: none;
    background: transparent;
    color: var(--text-muted);
    transition: all 0.15s;
    margin-left: 4px;
}
.btn-icon-action:hover { background: var(--bg-tertiary); color: var(--text-primary); }
.btn-icon-action.text-success { color: var(--success); }
.btn-icon-action.text-danger { color: var(--danger); }
.btn-icon-action.text-danger:hover { background: var(--danger-soft); }
.btn-icon-action.text-warning { color: var(--warning); }
.btn-icon-action.text-muted-light { color: var(--text-muted); }

.drag-handle {
    cursor: grab;
    color: var(--text-muted);
    padding: 4px 8px;
}
.drag-handle:hover { color: var(--text-secondary); }

/* ============================================================================
   INLINE EDITING
   ============================================================================ */
.editable-topic-name {
    cursor: pointer;
    border-bottom: 1px dashed transparent;
    padding-bottom: 1px;
}
.editable-topic-name:hover {
    border-bottom-color: var(--text-muted);
    color: var(--accent);
}
.rename-input {
    width: 100%;
    padding: 4px 8px;
    border: 1px solid var(--accent);
    border-radius: 6px;
    font-size: 0.875rem;
    background: var(--bg-secondary);
    color: var(--text-primary);
    outline: none;
}

/* ============================================================================
   ACTIVITY ACTIONS (in modal)
   ============================================================================ */
.btn-rename-activity,
.btn-duplicate-activity,
.btn-delete-activity,
.btn-toggle-visibility-activity {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 6px;
    transition: all 0.15s;
}
.btn-rename-activity:hover { background: var(--accent-soft); color: var(--accent); }
.btn-duplicate-activity:hover { background: var(--accent-soft); color: var(--accent); }
.btn-delete-activity:hover { background: var(--danger-soft); color: var(--danger); }
.btn-toggle-visibility-activity:hover { background: var(--accent-soft); }

/* Activity Checkboxes */
.activity-checkbox {
    width: 16px;
    height: 16px;
    cursor: pointer;
    accent-color: var(--accent);
}
#activity-select-all {
    width: 16px;
    height: 16px;
    cursor: pointer;
    accent-color: var(--accent);
}

/* Selected activity row */
tr:has(.activity-checkbox:checked) {
    background: var(--accent-soft) !important;
}

/* Batch delete button */
#btn-batch-delete {
    font-size: 0.875rem;
}
#btn-batch-delete:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

/* ============================================================================
   CONTEXT MENU
   ============================================================================ */
.activity-context-menu {
    position: fixed;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    box-shadow: var(--shadow-lg);
    z-index: 10000;
    min-width: 200px;
    max-height: 400px;
    overflow-y: auto;
    padding: 4px 0;
}
.activity-context-menu .menu-header {
    padding: 8px 12px;
    font-weight: 600;
    font-size: 0.75rem;
    color: var(--text-muted);
    text-transform: uppercase;
    border-bottom: 1px solid var(--border-color);
}
.activity-context-menu .menu-item {
    padding: 8px 12px;
    cursor: pointer;
    font-size: 0.875rem;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 8px;
}
.activity-context-menu .menu-item:hover { background: var(--bg-tertiary); }
.activity-context-menu .menu-item.current-section {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 500;
}

/* Sortable states */
.sortable-ghost { opacity: 0.4; background: var(--accent-soft) !important; }
.sortable-chosen { background: var(--bg-tertiary) !important; }

/* ============================================================================
   THEME TOGGLE BUTTON
   ============================================================================ */
.theme-toggle {
    width: 40px;
    height: 40px;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    border-radius: 8px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s;
}
.theme-toggle:hover {
    background: var(--bg-tertiary);
    color: var(--text-primary);
}
.theme-toggle svg {
    width: 20px;
    height: 20px;
}

/* ============================================================================
   UTILITY LINK BUTTON
   ============================================================================ */
.btn-link-subtle {
    background: none;
    border: none;
    color: var(--text-secondary);
    cursor: pointer;
    padding: 2px 6px;
    font-size: 0.9em;
    text-decoration: none;
}
.btn-link-subtle:hover {
    color: var(--text-primary);
    text-decoration: underline;
}

/* ============================================================================
   BOOTSTRAP OVERRIDES (modals, cards, forms)
   ============================================================================ */
.modal-content {
    background: var(--bg-secondary) !important;
    color: var(--text-primary) !important;
    border-color: var(--border-color) !important;
}
.modal-header, .modal-footer {
    border-color: var(--border-color) !important;
}
.modal-header .btn-close {
    filter: var(--text-primary);
}
[data-theme="dark"] .modal-header .btn-close {
    filter: invert(1);
}
.card {
    background: var(--bg-secondary) !important;
    color: var(--text-primary) !important;
    border-color: var(--border-color) !important;
}
.form-control, .form-select {
    background: var(--bg-secondary) !important;
    color: var(--text-primary) !important;
    border-color: var(--border-color) !important;
}
.form-control:focus, .form-select:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-soft) !important;
}
.form-label {
    color: var(--text-secondary) !important;
}
.btn-primary {
    background: var(--accent) !important;
    border-color: var(--accent) !important;
}
.btn-primary:hover {
    background: var(--accent-hover) !important;
    border-color: var(--accent-hover) !important;
}
.text-muted {
    color: var(--text-muted) !important;
}

/* ============================================================================
   NAVBAR CUSTOM COURSE INPUT
   ============================================================================ */
/* Fix alignment of Shiny input wrappers in navbar */
#nav_course_selector .shiny-input-container,
#nav_course_selector .form-group {
    margin-bottom: 0 !important;
}
#nav_course_selector > .d-flex {
    align-items: center !important;
}

.custom-course-input {
    display: flex;
    align-items: center;
    gap: 6px;
}
.custom-course-input input {
    height: 38px;
    width: 100px;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 0 10px;
    background: var(--bg-secondary);
    color: var(--text-primary);
    font-size: 0.875rem;
}
.custom-course-input input:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
}
.custom-course-input button {
    height: 38px;
    padding: 0 16px;
}
"""
