"""
Custom CSS styles for the Shiny application
"""

def get_custom_css():
    """Returns the custom CSS for the Shiny application"""
    return """
:root {
    --primary-color: #4f46e5;
    --primary-hover: #4338ca;
    --bg-color: #f3f4f6;
    --card-bg: #ffffff;
    --text-main: #1f2937;
    --selected-bg: #e0e7ff;
}

body {
    background-color: var(--bg-color);
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    color: var(--text-main);
}

.app-card {
    background: var(--card-bg);
    border-radius: 12px;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    overflow: hidden;
    height: 80vh;
    display: flex;
    flex-direction: column;
}

.toolbar {
    background: #ffffff;
    border-bottom: 1px solid #e5e7eb;
    padding: 8px 20px;
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
    flex-shrink: 0;
    height: 56px;
    box-sizing: border-box;
}

/* Icon-Only Toolbar Buttons - Full Height */
.toolbar-icon-btn {
    width: 40px;
    height: 40px;
    border: none;
    background: transparent;
    color: #6b7280;
    border-radius: 6px;
    padding: 0;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s;
    flex-shrink: 0;
}
.toolbar-icon-btn:hover:not(:disabled) {
    background: #f3f4f6;
    color: #374151;
}
.toolbar-icon-btn:disabled {
    opacity: 0.35;
    cursor: not-allowed;
}
.toolbar-icon-btn-primary {
    background: var(--primary-color);
    color: white;
}
.toolbar-icon-btn-primary:hover:not(:disabled) {
    background: var(--primary-hover);
}
.toolbar-icon-btn-danger {
    color: #dc2626;
}
.toolbar-icon-btn-danger:hover:not(:disabled) {
    background: #fef2f2;
    color: #991b1b;
}

/* Toolbar Inputs - Full Height */
#toolbar_actions input[type="number"],
#toolbar_actions input[type="text"],
#toolbar_actions select {
    height: 40px !important;
    border: 1px solid #d1d5db !important;
    border-radius: 6px !important;
    padding: 0 10px !important;
    font-size: 0.875rem !important;
    background: white !important;
    transition: all 0.15s !important;
    box-sizing: border-box !important;
}
#toolbar_actions input[type="number"]:focus,
#toolbar_actions input[type="text"]:focus,
#toolbar_actions select:focus {
    outline: none !important;
    border-color: var(--primary-color) !important;
    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1) !important;
}
#toolbar_actions input[type="number"] {
    width: 55px !important;
    text-align: center !important;
}

/* Toolbar Divider - Full Height */
.toolbar-divider {
    width: 1px;
    height: 40px;
    background: #e5e7eb;
    flex-shrink: 0;
}

/* Legacy toolbar button styles (for backwards compatibility) */
.toolbar-btn {
    border: 1px solid #d1d5db;
    background: white;
    color: #374151;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
}
.toolbar-btn:hover:not(:disabled) { background: #f9fafb; border-color: #9ca3af; }
.toolbar-btn-primary { background: var(--primary-color); color: white; border-color: var(--primary-color); }
.toolbar-btn-primary:hover:not(:disabled) { background: var(--primary-hover); }
.toolbar-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* Custom Table */
.topics-table-container {
    flex-grow: 1;
    overflow-y: auto;
    position: relative;
    padding: 0;
}
.topics-table {
    width: 100%;
    border-collapse: collapse;
}
.topics-table th {
    position: sticky;
    top: 0;
    background: #f9fafb;
    padding: 12px 16px;
    text-align: left;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    color: #6b7280;
    border-bottom: 1px solid #e5e7eb;
    z-index: 10;
}
.topics-table td {
    padding: 12px 16px;
    border-bottom: 1px solid #f3f4f6;
    font-size: 0.875rem;
    vertical-align: middle;
}
.topics-table tr {
    background: white;
    transition: background 0.1s;
    cursor: pointer;
}
.topics-table tr:hover { background: #f9fafb; }
.topics-table tr.selected-row { background: var(--selected-bg); }
.topics-table tr.sortable-ghost { opacity: 0.4; background: #c7d2fe; }

.drag-handle {
    cursor: grab;
    color: #9ca3af;
    margin-right: 8px;
}
.btn-icon-action {
    cursor: pointer;
    padding: 4px;
    border-radius: 4px;
    transition: all 0.2s;
    margin-left: 8px;
    font-size: 1rem;
    border: none;
    background: transparent;
}
.btn-icon-action:hover { background: #e5e7eb; }
.text-success { color: #059669; }
.text-muted-light { color: #9ca3af; }
.text-danger { color: #dc2626; }

/* Inline Edit */
.editable-topic-name {
    cursor: pointer;
    border-bottom: 1px dashed transparent;
    transition: all 0.2s;
    padding-bottom: 1px;
}
.editable-topic-name:hover {
    border-bottom-color: #9ca3af;
    color: var(--primary-color);
}
.rename-input {
    width: 100%;
    padding: 4px 8px;
    border: 1px solid var(--primary-color);
    border-radius: 4px;
    font-size: 0.875rem;
    outline: none;
}

/* Activity Context Menu */
.activity-context-menu {
    position: fixed;
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
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
    color: #6b7280;
    text-transform: uppercase;
    border-bottom: 1px solid #e5e7eb;
}
.activity-context-menu .menu-item {
    padding: 8px 12px;
    cursor: pointer;
    font-size: 0.875rem;
    display: flex;
    align-items: center;
    gap: 8px;
}
.activity-context-menu .menu-item:hover {
    background: #f3f4f6;
}
.activity-context-menu .menu-item.current-section {
    background: #e0f2fe;
    color: #0369a1;
    font-weight: 500;
}

/* Activity Drag Handle */
.drag-handle {
    cursor: grab;
    color: #9ca3af;
    padding: 4px 8px;
    font-size: 1rem;
}
.drag-handle:hover {
    color: #6b7280;
}

/* Sortable states */
.sortable-ghost {
    opacity: 0.4;
    background: #e0f2fe !important;
}
.sortable-chosen {
    background: #f0f9ff !important;
}

/* Rename Button */
.btn-rename-activity {
    background: none;
    border: none;
    color: #6b7280;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
    transition: all 0.15s;
}
.btn-rename-activity:hover {
    background: #fef3c7;
    color: #d97706;
}

/* Duplicate Button */
.btn-duplicate-activity {
    background: none;
    border: none;
    color: #6b7280;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
    transition: all 0.15s;
}
.btn-duplicate-activity:hover {
    background: #f3f4f6;
    color: #3b82f6;
}

/* Delete Button */
.btn-delete-activity {
    background: none;
    border: none;
    color: #9ca3af;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
    transition: all 0.15s;
}
.btn-delete-activity:hover {
    background: #fef2f2;
    color: #ef4444;
}

/* Visibility Toggle Button */
.btn-toggle-visibility-activity {
    background: none;
    border: none;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
    transition: all 0.15s;
    font-size: 1.1rem;
}
.btn-toggle-visibility-activity:hover {
    background: #e0f2fe;
}
"""
