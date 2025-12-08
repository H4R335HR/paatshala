from shiny import App, render, ui, reactive
import pandas as pd
from core.auth import login_and_get_cookie, setup_session, validate_session
from core.api import get_courses, get_topics, rename_topic_inplace, move_topic, toggle_topic_visibility, delete_topic, enable_edit_mode, add_topic, get_course_groups, update_topic_restriction, add_or_update_group_restriction, get_topic_restriction, get_restriction_summary, get_course_grade_items, update_restrictions_batch, move_activity_to_section, duplicate_activity, reorder_activity_within_section, delete_activity, rename_activity, get_fresh_sesskey, toggle_activity_visibility
from core.persistence import read_config, write_config, save_cache, load_cache
import logging
from faicons import icon_svg
import threading
from queue import Queue

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# CUSTOM CSS & JS
# ============================================================================
custom_css = """
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
    padding: 12px 20px;
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
    flex-shrink: 0;
}

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



custom_js = """
// Initialize Sortable
let sortableInstance = null;
let lastSelectedIdx = null;

function initSortable() {
    const el = document.getElementById('topics_list_body');
    if (!el) return;
    
    if (sortableInstance) sortableInstance.destroy();
    
    sortableInstance = new Sortable(el, {
        animation: 150,
        handle: '.drag-handle',
        ghostClass: 'sortable-ghost',
        onEnd: function (evt) {
            // Notify Shiny of the move
            Shiny.setInputValue("drag_move", {
                from: evt.oldIndex, 
                to: evt.newIndex, 
                nonce: Math.random()
            }, {priority: "event"});
        }
    });
}

// Click handler
document.addEventListener('click', function(e) {
    // Check if clicked boolean checkbox
    if (e.target.matches('.row-checkbox')) {
        updateSelection();
        e.stopPropagation(); // prevent row click
        return;
    }

    // Check if clicked action button
    const actionVis = e.target.closest('.action-vis');
    const actionDel = e.target.closest('.action-del');
    
    if (actionVis) {
         e.stopPropagation();
         Shiny.setInputValue("row_action_vis", {
             index: parseInt(actionVis.dataset.index),
             nonce: Math.random()
         }, {priority: "event"});
         return;
    }
    
    if (actionDel) {
         e.stopPropagation();
         Shiny.setInputValue("row_action_del", {
             index: parseInt(actionDel.dataset.index),
             nonce: Math.random()
         }, {priority: "event"});
         return;
    }

    // Check if clicked lock button
    const actionLock = e.target.closest('.action-lock');
    if (actionLock) {
         e.stopPropagation();
         Shiny.setInputValue("row_action_lock", {
             index: parseInt(actionLock.dataset.index),
             nonce: Math.random()
         }, {priority: "event"});
         return;
    }
    
    // Check if clicked activities button
    const actionActivities = e.target.closest('.action-activities');
    if (actionActivities) {
         e.stopPropagation();
         Shiny.setInputValue("row_action_activities", {
             index: parseInt(actionActivities.dataset.index),
             nonce: Math.random()
         }, {priority: "event"});
         return;
    }
    
    // Check if clicked editable name
    const editableName = e.target.closest('.editable-topic-name');
    if (editableName) {
        e.stopPropagation();
        makeEditable(editableName);
        return;
    }

    const row = e.target.closest('tr.topic-row');
    if (!row) return; // Clicked outside row

    // Row Click -> Single Select
    document.querySelectorAll('.row-checkbox').forEach(cb => cb.checked = false);
    
    const cb = row.querySelector('.row-checkbox');
    if (cb) cb.checked = true;
    
    updateSelection();
});

// Select All Handler
document.addEventListener('change', function(e) {
    if (e.target.id === 'select-all-cb') {
        const isChecked = e.target.checked;
        document.querySelectorAll('.row-checkbox').forEach(cb => cb.checked = isChecked);
        updateSelection();
    }
});

function updateSelection() {
    const checkedBoxes = Array.from(document.querySelectorAll('.row-checkbox:checked'));
    const indices = checkedBoxes.map(cb => parseInt(cb.dataset.index));
    
    // Update Shiny
    Shiny.setInputValue("selected_row_indices", indices);
    
    // Update Styles
    document.querySelectorAll('tr.topic-row').forEach(r => {
        const cb = r.querySelector('.row-checkbox');
        if (cb && cb.checked) r.classList.add('selected-row');
        else r.classList.remove('selected-row');
    });
}

// Inline Editing Logic
function makeEditable(el) {
    const currentText = el.innerText;
    const idx = el.dataset.index;
    
    const input = document.createElement('input');
    input.type = 'text';
    input.value = currentText;
    input.className = 'rename-input';
    
    // Replace span with input
    el.replaceWith(input);
    input.focus();
    
    // Save on Blur or Enter
    let saved = false;
    
    function save() {
        if (saved) return;
        saved = true;
        
        const newText = input.value.trim();
        
        // Revert to span
        const newSpan = document.createElement('span');
        newSpan.className = 'editable-topic-name';
        newSpan.dataset.index = idx;
        newSpan.innerText = newText; // Optimistic update
        newSpan.title = "Click to rename";
        
        input.replaceWith(newSpan);
        
        if (newText && newText !== currentText) {
             Shiny.setInputValue("inline_rename_event", {
                 index: parseInt(idx),
                 name: newText,
                 nonce: Math.random()
             }, {priority: "event"});
        }
    }
    
    input.addEventListener('blur', save);
    input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            save();
        } else if (e.key === 'Escape') {
            saved = true; // Cancel without save
            el.innerText = currentText; // Restore original
            input.replaceWith(el);
        }
    });
}

// Re-init on new data
$(document).on('shiny:value', function(event) {
    if (event.name === 'topics_table_html') {
        setTimeout(initSortable, 100); // Wait for render
    }
});

// Activity Context Menu for Move
let activeContextMenu = null;

function hideActivityContextMenu() {
    if (activeContextMenu) {
        activeContextMenu.remove();
        activeContextMenu = null;
    }
}

document.addEventListener('click', function(e) {
    if (!e.target.closest('.activity-context-menu')) {
        hideActivityContextMenu();
    }
});

document.addEventListener('contextmenu', function(e) {
    const row = e.target.closest('tr[data-activity-id]');
    if (row) {
        e.preventDefault();
        showActivityContextMenu(e.clientX, e.clientY, row);
    }
});

function showActivityContextMenu(x, y, row) {
    hideActivityContextMenu();
    
    const activityId = row.dataset.activityId;
    const activityName = row.dataset.activityName;
    const currentSectionId = row.dataset.sectionId;
    
    // Get topics from global variable (set by Shiny)
    const topicsData = window.activityModalTopics || [];
    if (!topicsData.length) {
        console.log('No topics data available');
        return;
    }
    
    // Create menu
    const menu = document.createElement('div');
    menu.className = 'activity-context-menu';
    
    // Header
    menu.innerHTML = `<div class="menu-header">Move "${activityName}" to:</div>`;
    
    // Topic items
    topicsData.forEach(function(topic) {
        const item = document.createElement('div');
        item.className = 'menu-item' + (topic.sectionId == currentSectionId ? ' current-section' : '');
        item.innerHTML = topic.sectionId == currentSectionId 
            ? `📍 ${topic.name} (current)` 
            : `📁 ${topic.name}`;
        
        if (topic.sectionId != currentSectionId) {
            item.onclick = function() {
                hideActivityContextMenu();
                Shiny.setInputValue('activity_move_to_topic', {
                    activityId: activityId,
                    activityName: activityName,
                    targetSectionId: topic.sectionId,
                    targetSectionDbId: topic.dbId,
                    targetSectionName: topic.name,
                    nonce: Math.random()
                }, {priority: 'event'});
            };
        }
        menu.appendChild(item);
    });
    
    // Position menu
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
    
    document.body.appendChild(menu);
    activeContextMenu = menu;
    
    // Adjust if off screen
    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) {
        menu.style.left = (window.innerWidth - rect.width - 10) + 'px';
    }
    if (rect.bottom > window.innerHeight) {
        menu.style.top = (window.innerHeight - rect.height - 10) + 'px';
    }
}

// Sortable for Activities Table (drag-drop reordering)
let activitySortableInstance = null;

function initActivitySortable() {
    const el = document.getElementById('activities_table_body');
    if (!el) return;
    
    if (activitySortableInstance) activitySortableInstance.destroy();
    
    activitySortableInstance = new Sortable(el, {
        animation: 150,
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        handle: '.drag-handle',
        onEnd: function(evt) {
            const rows = el.querySelectorAll('tr[data-activity-id]');
            const activityIds = Array.from(rows).map(r => r.dataset.activityId);
            const movedId = evt.item.dataset.activityId;
            const newIndex = evt.newIndex;
            const beforeId = (newIndex < activityIds.length - 1) ? activityIds[newIndex + 1] : null;
            
            Shiny.setInputValue("activity_reorder", {
                activityId: movedId,
                newIndex: newIndex,
                beforeId: beforeId,
                nonce: Math.random()
            }, {priority: "event"});
        }
    });
}

// Duplicate button click handler
document.addEventListener('click', function(e) {
    const dupBtn = e.target.closest('.btn-duplicate-activity');
    if (dupBtn) {
        e.preventDefault();
        e.stopPropagation();
        const activityId = dupBtn.dataset.activityId;
        const activityName = dupBtn.dataset.activityName;
        
        Shiny.setInputValue("activity_duplicate", {
            activityId: activityId,
            activityName: activityName,
            nonce: Math.random()
        }, {priority: "event"});
    }
    
    // Rename button handler
    const renameBtn = e.target.closest('.btn-rename-activity');
    if (renameBtn) {
        e.preventDefault();
        e.stopPropagation();
        const activityId = renameBtn.dataset.activityId;
        const activityName = renameBtn.dataset.activityName;
        const activityType = renameBtn.dataset.activityType;
        
        const newName = prompt(`Rename activity:`, activityName);
        if (newName && newName.trim() && newName.trim() !== activityName) {
            Shiny.setInputValue("activity_rename", {
                activityId: activityId,
                oldName: activityName,
                newName: newName.trim(),
                activityType: activityType,
                nonce: Math.random()
            }, {priority: "event"});
        }
    }
    
    // Visibility toggle button handler
    const visBtn = e.target.closest('.btn-toggle-visibility-activity');
    if (visBtn) {
        e.preventDefault();
        e.stopPropagation();
        const activityId = visBtn.dataset.activityId;
        const isVisible = visBtn.dataset.visible === 'true';
        const row = visBtn.closest('tr');

        // Optimistic UI update
        if (row) {
            const newVisible = !isVisible;
            row.dataset.visible = newVisible.toString();
            visBtn.dataset.visible = newVisible.toString();
            visBtn.textContent = newVisible ? '👁️' : '🚫';
            visBtn.title = newVisible ? 'Hide' : 'Show';
        }

        Shiny.setInputValue("activity_toggle_visibility", {
            activityId: activityId,
            hide: isVisible,
            nonce: Math.random()
        }, {priority: "event"});
        return;
    }

    // Delete button handler - with optimistic UI update
    const delBtn = e.target.closest('.btn-delete-activity');
    if (delBtn) {
        e.preventDefault();
        e.stopPropagation();
        const activityId = delBtn.dataset.activityId;
        const activityName = delBtn.dataset.activityName;
        const row = delBtn.closest('tr');

        if (confirm(`Are you sure you want to delete "${activityName}"?`)) {
            // Optimistic UI: fade out and remove the row immediately
            if (row) {
                row.style.transition = 'opacity 0.3s';
                row.style.opacity = '0.3';
            }

            Shiny.setInputValue("activity_delete", {
                activityId: activityId,
                activityName: activityName,
                nonce: Math.random()
            }, {priority: "event"});
        }
    }
});

// Listen for successful delete to fully remove row
Shiny.addCustomMessageHandler('activity_deleted', function(data) {
    const row = document.querySelector(`tr[data-activity-id="${data.activityId}"]`);
    if (row) {
        row.style.transition = 'all 0.3s';
        row.style.opacity = '0';
        row.style.transform = 'translateX(-20px)';
        setTimeout(() => row.remove(), 300);
    }
});

// Listen for successful duplicate to add a new row
Shiny.addCustomMessageHandler('activity_duplicated', function(data) {
    const originalRow = document.querySelector(`tr[data-activity-id="${data.originalId}"]`);
    if (originalRow && data.newRowHtml) {
        // Insert the new row after the original
        originalRow.insertAdjacentHTML('afterend', data.newRowHtml);
        const newRow = originalRow.nextElementSibling;
        if (newRow) {
            newRow.style.opacity = '0';
            newRow.style.transition = 'opacity 0.3s';
            setTimeout(() => newRow.style.opacity = '1', 10);
        }
    }
});

// Initialize activity sortable when modal opens
$(document).on('shiny:value', function(event) {
    if (event.name === 'activities_modal_content') {
        setTimeout(initActivitySortable, 100);
    }
});
"""



# ============================================================================
# APP UI
# ============================================================================
app_ui = ui.page_fluid(
    ui.head_content(
        ui.tags.style(custom_css),
        ui.tags.script(src="https://cdnjs.cloudflare.com/ajax/libs/Sortable/1.15.0/Sortable.min.js"),
        ui.tags.script(custom_js)
    ),
    
    # TOP NAVBAR
    ui.navset_bar(
        ui.nav_control(
            ui.div(
                ui.tags.span("🎓 Paatshala", style="font-size: 1.25rem; font-weight: bold; margin-right: 20px;"),
                class_="d-flex align-items-center"
            )
        ),
        ui.nav_spacer(),
        ui.nav_control(ui.output_ui("nav_course_selector")),
        ui.nav_control(ui.output_ui("nav_user_profile")),
        title=None, bg="white"
    ),

    # MAIN CONTENT
    ui.div(
        ui.output_ui("main_view"),
        class_="main-container",
        style="padding: 20px; max-width: 1200px; margin: 0 auto;"
    )
)

def server(input, output, session):
    # Reactive State
    user_session_id = reactive.Value(None)
    user_authenticated = reactive.Value(False)
    current_username = reactive.Value("")
    topics_list = reactive.Value([])
    is_edit_mode_on = reactive.Value(False)

    # State for selection (List of indices)
    selected_indices = reactive.Value([])

    # Cache for course-level data (keyed by course_id)
    course_groups_cache = reactive.Value({})      # {course_id: [{id, name}, ...]}
    course_grade_items_cache = reactive.Value({}) # {course_id: {item_id: name, ...}}

    # Thread-safe queue for background refresh results
    refresh_queue = Queue()

    # -------------------------------------------------------------------------
    # AUTH & LOAD - Now done reactively, not during server init
    # -------------------------------------------------------------------------
    auth_initialized = reactive.Value(False)
    
    @reactive.Effect
    def auto_authenticate():
        """Attempt auto-login from config on first load (runs once)"""
        if auth_initialized():
            return  # Already initialized
        
        auth_initialized.set(True)  # Mark as done
        
        loaded_cookie, loaded_user, loaded_pwd = read_config()
        
        if loaded_cookie:
            # Check if we validated recently (within 1 hour) - skip network call
            from datetime import datetime, timedelta
            cached_validation = load_cache("session_validation")
            skip_validation = False
            
            if cached_validation:
                try:
                    last_validated = datetime.fromisoformat(cached_validation.get("timestamp", ""))
                    cached_cookie = cached_validation.get("cookie", "")
                    # Skip if same cookie and validated within 1 hour
                    if cached_cookie == loaded_cookie and datetime.now() - last_validated < timedelta(hours=1):
                        skip_validation = True
                        logger.info("Session validated recently, skipping network check")
                except:
                    pass
            
            if skip_validation:
                # Trust the cached validation
                user_session_id.set(loaded_cookie)
                user_authenticated.set(True)
                current_username.set(loaded_user if loaded_user else "User")
                ui.notification_show("Session restored!", type="message", duration=2)
                return
            
            # Need to validate via network
            ui.notification_show("Validating saved session...", duration=2)
            if validate_session(loaded_cookie):
                user_session_id.set(loaded_cookie)
                user_authenticated.set(True)
                current_username.set(loaded_user if loaded_user else "User")
                # Cache this validation
                save_cache("session_validation", {
                    "timestamp": datetime.now().isoformat(),
                    "cookie": loaded_cookie
                })
                ui.notification_show("Session restored!", type="message", duration=2)
                return
        
        if loaded_user and loaded_pwd:
            ui.notification_show("Logging in...", duration=2)
            sid = login_and_get_cookie(loaded_user, loaded_pwd)
            if sid:
                user_session_id.set(sid)
                user_authenticated.set(True)
                current_username.set(loaded_user)
                # Save the new cookie for faster startup next time
                write_config(cookie=sid)
                # Also cache this validation
                from datetime import datetime
                save_cache("session_validation", {
                    "timestamp": datetime.now().isoformat(),
                    "cookie": sid
                })
                ui.notification_show("Login successful!", type="message", duration=2)
                return
        
        # If we get here, no auto-auth worked - user will see login form
    
    @reactive.Effect
    @reactive.event(input.login_btn)
    def do_login():
        if input.username() and input.password():
            ui.notification_show("Authenticating...", duration=1)
            sid = login_and_get_cookie(input.username(), input.password())
            if sid:
                user_session_id.set(sid)
                user_authenticated.set(True)
                current_username.set(input.username())
            else:
                ui.notification_show("Invalid credentials", type="error")

    # Reactive value for courses (to allow background updates)
    courses_data = reactive.Value([])
    courses_loaded_from_cache = reactive.Value(False)
    
    @reactive.Effect
    @reactive.event(user_authenticated)
    def load_courses_from_cache():
        """Load courses from cache on auth (instant, non-blocking)"""
        if not user_authenticated():
            courses_data.set([])
            return
        
        cached = load_cache("courses")
        if cached:
            logger.info("Loaded courses from cache (instant)")
            courses_data.set(cached)
            courses_loaded_from_cache.set(True)
        else:
            # No cache - must fetch live
            logger.info("No cached courses, fetching live...")
            try:
                s = setup_session(user_session_id())
                live = get_courses(s)
                courses_data.set(live)
                save_cache("courses", live)
            except Exception as e:
                logger.error(f"Error fetching courses: {e}")
    
    @reactive.Effect
    @reactive.event(input.refresh_courses)
    def refresh_courses_live():
        """Refresh courses from live data (only on explicit refresh click)"""
        if not user_authenticated():
            return
        
        logger.info("Refreshing courses from live data...")
        try:
            s = setup_session(user_session_id())
            live = get_courses(s)
            courses_data.set(live)
            save_cache("courses", live)
            ui.notification_show("Courses refreshed", type="message", duration=2)
        except Exception as e:
            logger.error(f"Error refreshing courses: {e}")
            ui.notification_show("Failed to refresh courses", type="error")
    
    @reactive.Calc
    def available_courses():
        return courses_data()

    @output
    @render.ui
    def nav_course_selector():
        if not user_authenticated(): return None
        choices = {c['id']: c['name'] for c in available_courses()}
        return ui.div(ui.input_select("course_id", None, choices=choices, width="300px"), style="margin-top: 10px;")

    @output
    @render.ui
    def nav_user_profile():
        if not user_authenticated(): return None
        return ui.div(
            icon_svg("user"),
            ui.tags.span(current_username(), style="margin-left: 8px; font-weight: 500;"),
            ui.input_action_button("refresh_courses", "", icon=icon_svg("arrow-rotate-right"), class_="btn-sm btn-light ms-2"),
            class_="d-flex align-items-center text-muted", style="margin-top: 8px;"
        )

    # -------------------------------------------------------------------------
    # MAIN VIEW
    # -------------------------------------------------------------------------
    @output
    @render.ui
    def main_view():
        if not user_authenticated(): return render_login_view()
        return render_dashboard_view()

    def render_login_view():
        return ui.div(
            ui.card(
                ui.h3("Welcome Back", class_="text-center mb-4"),
                ui.input_text("username", "Username"),
                ui.input_password("password", "Password"),
                ui.input_action_button("login_btn", "Sign In", class_="btn-primary w-100 mt-3"),
                style="max-width: 400px; margin: 100px auto; padding: 20px;"
            )
        )

    def render_dashboard_view():
        return ui.div(
            # TOOLBAR
            ui.div(
                ui.div(ui.output_ui("toolbar_selection_info"), class_="d-flex align-items-center"),
                ui.div(ui.output_ui("toolbar_actions"), class_="ms-auto d-flex gap-2"),
                class_="toolbar"
            ),
            # CUSTOM TABLE
            ui.div(
                ui.output_ui("topics_table_html"),
                class_="topics-table-container"
            ),
            class_="app-card"
        )

    @reactive.Effect
    @reactive.event(input.course_id)
    def load_data():
        cid = input.course_id()
        if not cid: return
        is_edit_mode_on.set(False)
        selected_indices.set([]) # Reset selection
        
        # Cache keys for this course
        topics_key = f"course_{cid}_topics"
        groups_key = f"course_{cid}_groups"
        grade_items_key = f"course_{cid}_grade_items"
        
        # Load from cache first (instant display)
        cached_topics = load_cache(topics_key)
        cached_groups = load_cache(groups_key)
        cached_grade_items = load_cache(grade_items_key)
        
        has_cache = cached_topics is not None
        
        if cached_topics:
            logger.info(f"Loaded {len(cached_topics)} topics from cache for course {cid} (instant)")
            topics_list.set(cached_topics)
        
        if cached_groups:
            groups_cache = course_groups_cache()
            groups_cache[cid] = cached_groups
            course_groups_cache.set(groups_cache)
            logger.info(f"Loaded {len(cached_groups)} groups from cache")
        
        if cached_grade_items:
            grade_items_cache = course_grade_items_cache()
            grade_items_cache[cid] = cached_grade_items
            course_grade_items_cache.set(grade_items_cache)
            logger.info(f"Loaded grade items from cache")
        
        # Trigger background refresh (after showing cache)
        # This fetches fresh data silently and updates if different
        trigger_background_refresh(cid)
        
        # If no cache, fetch immediately (blocking)
        if not has_cache:
            logger.info(f"No cache for course {cid}, fetching live data...")
            do_background_refresh(cid)

    # Background refresh trigger
    background_refresh_trigger = reactive.Value(None)
    background_refresh_counter = reactive.Value(0)

    def trigger_background_refresh(cid):
        """Helper to trigger background refresh with counter to ensure it always fires"""
        counter = background_refresh_counter.get() + 1
        background_refresh_counter.set(counter)
        background_refresh_trigger.set((cid, counter))

    @reactive.Effect
    @reactive.event(background_refresh_trigger)
    def on_background_refresh():
        """Background refresh: fetch live data and update silently in a separate thread"""
        trigger_data = background_refresh_trigger.get()
        if not trigger_data: return

        # Extract cid from tuple (cid, counter) to ensure trigger always fires
        if isinstance(trigger_data, tuple):
            cid, _ = trigger_data
        else:
            cid = trigger_data

        logger.info(f"[MAIN THREAD] Scheduling background refresh for course {cid}...")

        # Launch background thread (non-blocking)
        thread = threading.Thread(
            target=do_background_refresh_threaded,
            args=(cid, user_session_id()),
            daemon=True
        )
        thread.start()
        logger.info(f"[MAIN THREAD] Background thread started, UI remains responsive")

    def do_background_refresh_threaded(cid, session_id):
        """Actually fetch live data and update (runs in background thread)"""
        try:
            logger.info(f"[BACKGROUND THREAD] Starting refresh for course {cid}...")

            s = setup_session(session_id)

            topics_key = f"course_{cid}_topics"
            groups_key = f"course_{cid}_groups"
            grade_items_key = f"course_{cid}_grade_items"

            # Fetch topics
            live_topics = get_topics(s, cid)

            # Fetch groups
            live_groups = get_course_groups(s, cid)

            # Fetch grade items (pass topics to avoid redundant fetch)
            live_grade_items = get_course_grade_items(s, cid, topics=live_topics)

            # Save to disk cache (safe from any thread)
            if live_topics:
                save_cache(topics_key, live_topics)
                logger.info(f"[BACKGROUND THREAD] Cached {len(live_topics)} topics")
            save_cache(groups_key, live_groups)
            save_cache(grade_items_key, live_grade_items)

            # Put data in thread-safe queue (no reactive updates here!)
            refresh_queue.put({
                'cid': cid,
                'topics': live_topics,
                'groups': live_groups,
                'grade_items': live_grade_items
            })

            logger.info(f"[BACKGROUND THREAD] Refresh complete for course {cid}")

        except Exception as e:
            logger.error(f"[BACKGROUND THREAD] Refresh error: {e}")

    # Polling mechanism to check queue and apply updates on main thread
    @reactive.Effect
    def poll_refresh_queue():
        """Poll the queue for background refresh results (runs on main thread)"""
        # Use reactive.invalidate_later to create a polling loop
        reactive.invalidate_later(0.5)  # Check every 500ms

        # Try to get data from queue without blocking
        try:
            while not refresh_queue.empty():
                data = refresh_queue.get_nowait()

                cid = data.get('cid')
                live_topics = data.get('topics')
                live_groups = data.get('groups')
                live_grade_items = data.get('grade_items')

                # Update reactive values (safe on main thread)
                if live_topics:
                    topics_list.set(live_topics)
                    logger.info(f"[MAIN THREAD] Applied {len(live_topics)} topics from background refresh")

                if live_groups:
                    groups_cache = course_groups_cache()
                    groups_cache[cid] = live_groups
                    course_groups_cache.set(groups_cache)

                if live_grade_items:
                    grade_items_cache = course_grade_items_cache()
                    grade_items_cache[cid] = live_grade_items
                    course_grade_items_cache.set(grade_items_cache)

        except:
            pass  # Queue was empty, that's fine

    def do_background_refresh(cid):
        """Synchronous version for manual refresh button (blocking)"""
        try:
            s = setup_session(user_session_id())

            topics_key = f"course_{cid}_topics"
            groups_key = f"course_{cid}_groups"
            grade_items_key = f"course_{cid}_grade_items"

            logger.info(f"Manual refresh: fetching live data for course {cid}...")

            # Fetch topics
            live_topics = get_topics(s, cid)
            if live_topics:
                topics_list.set(live_topics)
                save_cache(topics_key, live_topics)
                logger.info(f"Manual refresh: updated {len(live_topics)} topics")

            # Fetch groups
            live_groups = get_course_groups(s, cid)
            groups_cache = course_groups_cache()
            groups_cache[cid] = live_groups
            course_groups_cache.set(groups_cache)
            save_cache(groups_key, live_groups)

            # Fetch grade items (pass topics to avoid redundant fetch)
            live_grade_items = get_course_grade_items(s, cid, topics=live_topics)
            grade_items_cache = course_grade_items_cache()
            grade_items_cache[cid] = live_grade_items
            course_grade_items_cache.set(grade_items_cache)
            save_cache(grade_items_key, live_grade_items)

            logger.info(f"Manual refresh complete for course {cid}")

        except Exception as e:
            logger.error(f"Manual refresh error: {e}")


    # -------------------------------------------------------------------------
    # TABLE RENDERER
    # -------------------------------------------------------------------------
    @output
    @render.ui
    def topics_table_html():
        data = topics_list()
        if not data: return ui.HTML("<div class='p-4 text-center text-muted'>No topics found</div>")
        
        # Build HTML Table
        html_rows = []
        # Pre-render common icons to save time (strings)
        icon_trash = str(icon_svg("trash"))
        icon_eye = str(icon_svg("eye"))
        icon_eye_slash = str(icon_svg("eye-slash"))
        icon_grip = str(icon_svg("grip-vertical"))
        icon_lock = str(icon_svg("lock"))
        icon_unlock = str(icon_svg("unlock"))
        icon_list = str(icon_svg("list"))

        for i, row in enumerate(data):
            # Icons
            vis = row['Visible']
            vis_svg = icon_eye if vis else icon_eye_slash
            vis_class = "text-success" if vis else "text-muted-light"
            vis_title = "Hide" if vis else "Show"
            
            # Restriction info for tooltip
            restriction_summary = row.get('Restriction Summary', '').strip()
            has_restriction = bool(restriction_summary)
            lock_icon = icon_lock if has_restriction else icon_unlock
            lock_class = "text-warning" if has_restriction else "text-muted-light"
            
            # Escape for HTML title attribute
            restriction_tooltip = restriction_summary.replace('"', '&quot;').replace("'", "&#39;") if restriction_summary else "No restrictions"
            lock_title = f"Restrictions: {restriction_tooltip}" if has_restriction else "No restrictions - Click to add"
            
            # Activity count display
            activity_count = row.get('Activity Count', 0)
            activities_text = f"{activity_count} activities" if activity_count != 1 else "1 activity"
            
            # Use i as data-index
            tr = f"""
            <tr class="topic-row" data-index="{i}">
                <td style="width: 30px;" class="text-center">
                    <input type="checkbox" class="row-checkbox" data-index="{i}" style="cursor: pointer;">
                </td>
                <td style="width: 30px;"><span class="drag-handle">{icon_grip}</span></td>
                <td>
                    <span class="editable-topic-name" data-index="{i}" title="Click to rename">
                        {row['Topic Name']}
                    </span>
                </td>
                <td>
                    <button class="btn-link-subtle action-activities" data-index="{i}" title="View activities">
                        {activities_text}
                    </button>
                </td>
                <td class="text-end" style="white-space: nowrap;">
                    <button class="btn-icon-action action-vis {vis_class}" data-index="{i}" title="{vis_title}">
                        {vis_svg}
                    </button>
                    <button class="btn-icon-action action-lock {lock_class}" data-index="{i}" title="{lock_title}">
                        {lock_icon}
                    </button>
                    <button class="btn-icon-action action-del text-danger" data-index="{i}" title="Delete">
                        {icon_trash}
                    </button>
                </td>
            </tr>
            """
            html_rows.append(tr)
        
        html = f"""
        <style>
            .btn-link-subtle {{
                background: none;
                border: none;
                color: #6c757d;
                cursor: pointer;
                padding: 2px 6px;
                font-size: 0.9em;
                text-decoration: none;
            }}
            .btn-link-subtle:hover {{
                color: #495057;
                text-decoration: underline;
            }}
            .text-warning {{
                color: #ffc107 !important;
            }}
        </style>
        <table class="topics-table">
            <thead>
                <tr>
                    <th style="width: 30px;" class="text-center">
                        <input type="checkbox" id="select-all-cb" style="cursor: pointer;">
                    </th>
                    <th style="width: 30px;"></th>
                    <th>Topic Name</th>
                    <th>Content</th>
                    <th class="text-end">Actions</th>
                </tr>
            </thead>
            <tbody id="topics_list_body">
                {''.join(html_rows)}
            </tbody>
        </table>
        """
        return ui.HTML(html)

    # -------------------------------------------------------------------------
    # SELECTION SYNC
    # -------------------------------------------------------------------------
    @reactive.Effect
    @reactive.event(input.selected_row_indices)
    def sync_selection():
        # Ensure list
        val = input.selected_row_indices()
        if val is None: val = []
        elif isinstance(val, int): val = [val]
        selected_indices.set(val)

    # -------------------------------------------------------------------------
    # TOOLBAR & ACTIONS
    # -------------------------------------------------------------------------
    def ensure_edit_mode(s, cid, sesskey):
        if is_edit_mode_on(): return
        logger.info(f"Enabling Edit Mode for course {cid}")
        if enable_edit_mode(s, cid, sesskey): is_edit_mode_on.set(True)

    @output
    @render.ui
    def toolbar_selection_info():
        indices = selected_indices()
        count = len(indices)
        if count == 0:
            return ui.span("No selection", class_="text-muted fst-italic")
        elif count == 1:
            data = topics_list()
            idx = indices[0]
            if idx < len(data):
                return ui.span(f"Selected: {data[idx]['Topic Name']}", style="font-weight: 600;")
        return ui.span(f"{count} topics selected", style="font-weight: 600; color: var(--primary-color);")

    @output
    @render.ui
    def toolbar_actions():
        indices = selected_indices()
        count = len(indices)
        
        # Action Logic
        can_add = True
        can_rename = (count == 1)
        can_move = (count == 1)
        can_batch = (count > 0) # Hide/Delete
        
        # Determine Visibility State button text
        # If multiple, toggling might be complex. Let's say "Toggle".
        vis_label = "Toggle Vis"
        vis_icon = "eye"
        
        if count == 1:
             data = topics_list()
             idx = indices[0]
             if idx < len(data):
                 vis = data[idx]['Visible']
                 vis_label = "Hide" if vis else "Show"
                 vis_icon = "eye-slash" if vis else "eye"

        # Get available groups for the current course
        cid = input.course_id()
        groups_cache = course_groups_cache()
        available_groups = groups_cache.get(cid, []) if cid else []
        
        # Extract existing group names from selected topics' restrictions
        # Moodle displays: "You belong to GROUP_NAME" in the restriction summary
        import re
        existing_group_names = set()
        data = topics_list()
        for idx in indices:
            if idx < len(data):
                summary = data[idx].get('Restriction Summary', '').lower()
                # Check each available group name against the summary text
                for g in available_groups:
                    # Strip member count suffix like "(5)" from group names
                    group_name_clean = re.sub(r'\s*\(\d+\)$', '', g['name'])
                    if group_name_clean.lower() in summary:
                        existing_group_names.add(str(g['id']))
        
        # Build dropdown choices, marking existing groups with ✓
        group_choices = {"": "-- Select Group --"}
        for g in available_groups:
            gid = str(g['id'])
            name = g['name']
            if gid in existing_group_names:
                group_choices[gid] = f"✓ {name}"
            else:
                group_choices[gid] = name

        return ui.div(
             # Refresh button (Always available)
             ui.input_action_button("act_refresh_topics", "", icon=icon_svg("arrow-rotate-right"), class_="toolbar-btn me-3", title="Refresh topics from server"),
             # Add (Always available)
             ui.div(
                ui.div(
                     ui.input_numeric("add_count", None, value=1, min=1, width="70px"),
                     style="margin-bottom: -15px;"
                ),
                ui.input_action_button("act_add", "Add", icon=icon_svg("plus"), class_="toolbar-btn-primary"),
                class_="d-flex gap-2 align-items-center me-4", style="border-right: 1px solid #e5e7eb; padding-right: 16px;"
            ),
            # Edit (Single Check Only)
            ui.div(
                ui.div(ui.input_text("edit_name_float", None, placeholder="Rename...", width="200px"), style="margin-bottom: -15px;"),
                ui.input_action_button("act_rename", "Rename", icon=icon_svg("pen"), disabled=not can_rename, class_="toolbar-btn"),
                class_="d-flex gap-1 align-items-center me-3"
            ),
            # Batch Actions
            ui.input_action_button("act_vis", vis_label, icon=icon_svg(vis_icon), disabled=not can_batch, class_="toolbar-btn"),
            ui.input_action_button("act_del", "Delete", icon=icon_svg("trash"), disabled=not can_batch, class_="toolbar-btn text-danger ms-2"),
            # Group Restriction (Batch)
            ui.div(
                ui.div(
                    ui.input_select("toolbar_group_select", None, choices=group_choices, width="150px"),
                    style="margin-bottom: -15px;"
                ),
                ui.input_action_button("act_add_group", "Add Grp", icon=icon_svg("users"), disabled=not can_batch, class_="toolbar-btn"),
                class_="d-flex gap-1 align-items-center ms-3", style="border-left: 1px solid #e5e7eb; padding-left: 16px;"
            ),
            class_="d-flex align-items-center"
        )

    # -------------------------------------------------------------------------
    # ACTION HANDLERS
    # -------------------------------------------------------------------------
    @reactive.Effect
    @reactive.event(input.act_refresh_topics)
    def on_refresh_topics():
        """Manually refresh topics for the current course"""
        cid = input.course_id()
        if not cid:
            return

        logger.info(f"Manual refresh: fetching topics for course {cid}...")
        ui.notification_show("Refreshing topics...", duration=2)

        try:
            do_background_refresh(cid)
            ui.notification_show("✅ Topics refreshed", type="message", duration=2)
        except Exception as e:
            logger.error(f"Error refreshing topics: {e}")
            ui.notification_show("❌ Failed to refresh topics", type="error")

    @reactive.Effect
    @reactive.event(input.drag_move)
    def on_drag_drop():
        move_info = input.drag_move()
        if not move_info: return
        
        old_idx = move_info['from']
        new_idx = move_info['to']
        if old_idx == new_idx: return
        
        current = list(topics_list())
        if old_idx >= len(current) or new_idx >= len(current): return # Safety
        
        # Optimistic UI Update
        item = current.pop(old_idx)
        current.insert(new_idx, item)
        topics_list.set(current)
        
        # Reset selection on drag for simplicity
        # selected_indices.set([])
        
        # API Call
        s = setup_session(user_session_id())
        cid = input.course_id()
        sesskey = item.get('Sesskey')
        
        ensure_edit_mode(s, cid, sesskey)
        logger.info(f"Drag drop: moving index {old_idx} to {new_idx}")
        move_topic(s, old_idx, sesskey, cid, target_section_number=new_idx)

    @reactive.Effect
    @reactive.event(input.act_rename)
    def do_rename():
        indices = selected_indices()
        if len(indices) != 1: return
        idx = indices[0]
        
        new_name = input.edit_name_float()
        if not new_name: return
        
        current = list(topics_list())
        row = current[idx]
        row['Topic Name'] = new_name
        topics_list.set(current)
        s = setup_session(user_session_id())
        cid = input.course_id()
        ensure_edit_mode(s, cid, row.get('Sesskey'))
        rename_topic_inplace(s, row.get('Sesskey'), row['DB ID'], new_name)
    
    @reactive.Effect
    @reactive.event(input.act_vis)
    def do_vis():
        indices = selected_indices()
        if not indices: return
        
        current = list(topics_list())
        s = setup_session(user_session_id())
        cid = input.course_id()
        
        # Batch Process
        with ui.Progress(min=0, max=len(indices)) as p:
            p.set(message="Toggling visibility...")
            for i, idx in enumerate(indices):
                if idx >= len(current): continue
                row = current[idx]
                
                # Toggle logic: just simple toggle for each
                new_state = not row['Visible']
                row['Visible'] = new_state
                
                ensure_edit_mode(s, cid, row.get('Sesskey'))
                toggle_topic_visibility(s, cid, idx, row.get('Sesskey'), hide=not new_state)
                p.set(i+1, message=f"Processed {i+1}/{len(indices)}")

        topics_list.set(current)

    @reactive.Effect
    @reactive.event(input.act_del)
    def do_del():
        indices = selected_indices()
        if not indices: return
        
        # DELETE FROM BOTTOM UP to strictly preserve indices
        sorted_indices = sorted(indices, reverse=True)
        
        current = list(topics_list())
        s = setup_session(user_session_id())
        cid = input.course_id()
        
        with ui.Progress(min=0, max=len(indices)) as p:
            p.set(message="Deleting topics...")
            for i, idx in enumerate(sorted_indices):
                if idx >= len(current): continue
                row = current[idx]
                
                ensure_edit_mode(s, cid, row.get('Sesskey'))
                # API Call
                delete_topic(s, row['DB ID'], row.get('Sesskey'))
                
                # Update Local UI after API (safer for batch delete)
                current.pop(idx)
                p.set(i+1, message=f"Deleted {i+1}/{len(indices)}")
        
        topics_list.set(current)
        selected_indices.set([])
        ui.notification_show("Batch delete complete")

    # -------------------------------------------------------------------------
    # HELPER: Extract Group IDs from Restriction JSON
    # -------------------------------------------------------------------------
    def extract_group_ids_from_json(json_str):
        """
        Recursively extracts all group IDs from restriction JSON.
        Returns a list of group ID strings.
        """
        import json
        if not json_str:
            return []
        
        try:
            data = json.loads(json_str)
        except:
            return []
        
        groups_found = []
        
        def find_groups(c_list):
            for cond in c_list:
                if 'c' in cond:  # Nested restriction set
                    find_groups(cond['c'])
                elif cond.get('type') == 'group':
                    groups_found.append(str(cond.get('id')))
            return groups_found
        
        if isinstance(data, dict) and 'c' in data:
            find_groups(data['c'])
        
        return groups_found

    # -------------------------------------------------------------------------
    # BATCH ADD GROUP RESTRICTION
    # -------------------------------------------------------------------------
    @reactive.Effect
    @reactive.event(input.act_add_group)
    def do_add_group():
        indices = selected_indices()
        if not indices:
            ui.notification_show("No topics selected", type="warning")
            return
        
        group_id = input.toolbar_group_select()
        if not group_id:
            ui.notification_show("Please select a group", type="warning")
            return
        
        cid = input.course_id()
        if not cid:
            return
        
        current = list(topics_list())
        s = setup_session(user_session_id())
        
        # Ensure groups cache is populated
        groups_cache = course_groups_cache()
        if cid not in groups_cache:
            from core.api import get_course_groups
            groups = get_course_groups(s, cid)
            groups_cache[cid] = groups
            course_groups_cache.set(groups_cache)
        
        # Get group name for notification
        available_groups = groups_cache.get(cid, [])
        group_name = next((g['name'] for g in available_groups if str(g['id']) == group_id), f"Group {group_id}")
        
        success_count = 0
        with ui.Progress(min=0, max=len(indices)) as p:
            p.set(message=f"Adding '{group_name}' restriction...")
            
            for i, idx in enumerate(indices):
                if idx >= len(current):
                    continue
                
                row = current[idx]
                topic_id = row['DB ID']
                sesskey = row.get('Sesskey')
                
                try:
                    # 1. Fetch current restriction JSON
                    current_json = get_topic_restriction(s, topic_id)
                    
                    # 2. Extract existing group IDs
                    existing_groups = extract_group_ids_from_json(current_json)
                    
                    # 3. Add new group ID if not present
                    if group_id not in existing_groups:
                        existing_groups.append(group_id)
                    
                    # 4. Build updated restriction JSON (merges with OR for groups)
                    updated_json = add_or_update_group_restriction(current_json, existing_groups)
                    
                    # 5. Update topic restriction
                    ensure_edit_mode(s, cid, sesskey)
                    if update_topic_restriction(s, cid, topic_id, sesskey, updated_json):
                        success_count += 1
                        # Update local restriction summary
                        new_summary_list = get_restriction_summary(updated_json)
                        current[idx]['Restriction Summary'] = '\n'.join(new_summary_list) if new_summary_list else ''
                    
                except Exception as e:
                    logger.error(f"Error adding group to topic {topic_id}: {e}")
                
                p.set(i + 1, message=f"Processed {i + 1}/{len(indices)}")
        
        # Refresh UI
        topics_list.set(current)
        ui.notification_show(f"Added '{group_name}' to {success_count}/{len(indices)} topics", type="message")

    @reactive.Effect
    @reactive.event(input.act_add)
    def do_add():
        count = input.add_count()
        if not count or count < 1: return
        
        # Capture context BEFORE async/long operations
        cid = input.course_id()
        indices = selected_indices()
        rename_text = input.edit_name_float()
        
        # Determine selection for Move (Only if exactly 1 is selected)
        sel_idx = indices[0] if len(indices) == 1 else None
        
        # Basic Validation
        data = topics_list()
        if not data: return
        sesskey = data[0].get('Sesskey')
        
        # 1. ADD
        s = setup_session(user_session_id())
        ensure_edit_mode(s, cid, sesskey)
        
        ui.notification_show(f"Adding {count} topic(s)...", duration=1)
        if not add_topic(s, cid, sesskey, count=int(count)):
            ui.notification_show("Add failed!", type="error")
            return

        # Refetch to get the NEW topics (we need their IDs/Sesskeys)
        # This is strictly needed because add_topic returns bool, not ID
        current_data = get_topics(s, cid)
        topics_list.set(current_data)
        
        # Calculate how many new topics were added (compare before/after counts)
        original_count = len(data)
        new_count = len(current_data)
        added_count = new_count - original_count
        
        # The newly added topics are at the END of the list
        # We'll operate on all of them
        
        # 2. RENAME (Optional) - only rename the FIRST newly added topic
        if rename_text and rename_text.strip() and added_count > 0:
            first_new_idx = original_count  # Index of first new topic
            first_new_topic = current_data[first_new_idx]
            ui.notification_show(f"Renaming to '{rename_text}'...", duration=1)
            if rename_topic_inplace(s, first_new_topic.get('Sesskey'), first_new_topic['DB ID'], rename_text):
                current_data[first_new_idx]['Topic Name'] = rename_text
                topics_list.set(current_data) 
            else:
                 ui.notification_show("Rename failed", type="warning")

        # 3. MOVE (Optional) - move ALL newly added topics to above the selection
        # Move from bottom to top, each time moving the last added topic to the target position
        if sel_idx is not None and added_count > 0:
            ui.notification_show(f"Moving {added_count} topic(s) to selection...", duration=1)
            
            # Move each new topic, starting from the last one
            # After each move, the next topic to move will be at a different position
            for i in range(added_count):
                # After the i-th move, the next topic to move is at:
                # (original_count + added_count - 1 - i) before move, but since we're moving from end,
                # we always move from the current last position of "new topics"
                # Actually simpler: always move from (len(current_data) - 1 - i) to (sel_idx + i)
                
                # Refetch current state after each move
                if i > 0:
                    current_data = get_topics(s, cid)
                
                # The topic to move is always the last one of the "unmoved" new topics
                topic_to_move_idx = len(current_data) - 1 - i + i  # = len - 1 (always the last "new" one before it moves)
                # Simpler: the last new topic that hasn't been moved yet is at position:
                # original_count + (added_count - 1 - i) = len(current_data) - 1 - i
                move_from_idx = len(current_data) - 1
                
                if move_from_idx <= sel_idx:
                    continue  # Already above selection, skip
                
                topic_to_move = current_data[move_from_idx]
                if move_topic(s, move_from_idx, topic_to_move.get('Sesskey'), cid, target_section_number=sel_idx):
                    pass  # Success
                else:
                    ui.notification_show(f"Move {i+1} failed", type="warning")
                    break
            
            # Final Refresh to ensure order is perfect
            final_data = get_topics(s, cid)
            topics_list.set(final_data)
            # Update selection to the new items
            selected_indices.set(list(range(sel_idx, sel_idx + added_count)))
        
        ui.notification_show("Done!", type="message")

    @reactive.Effect
    @reactive.event(input.row_action_vis)
    def on_row_vis():
        evt = input.row_action_vis()
        if not evt: return
        idx = evt['index']
        
        current = list(topics_list())
        if idx >= len(current): return
        
        row = current[idx]
        new_state = not row['Visible']
        row['Visible'] = new_state
        topics_list.set(current)
        
        s = setup_session(user_session_id())
        cid = input.course_id()
        toggle_topic_visibility(s, cid, idx, row.get('Sesskey'), hide=not new_state)

    @reactive.Effect
    @reactive.event(input.row_action_del)
    def on_row_del():
        evt = input.row_action_del()
        if not evt: return
        idx = evt['index']
        
        current = list(topics_list())
        if idx >= len(current): return
        
        row = current[idx]
        current.pop(idx)
        topics_list.set(current)
        
        s = setup_session(user_session_id())
        cid = input.course_id()
        ensure_edit_mode(s, cid, row.get('Sesskey'))
        delete_topic(s, row['DB ID'], row.get('Sesskey'))

        ensure_edit_mode(s, cid, row.get('Sesskey'))
        delete_topic(s, row['DB ID'], row.get('Sesskey'))

    @reactive.Effect
    @reactive.event(input.inline_rename_event)
    def on_inline_rename():
        evt = input.inline_rename_event()
        if not evt: return
        idx = evt['index']
        new_name = evt['name']
        
        current = list(topics_list())
        if idx >= len(current): return
        
        row = current[idx]
        if row['Topic Name'] == new_name: return
        
        row['Topic Name'] = new_name
        topics_list.set(current)
        
        s = setup_session(user_session_id())
        cid = input.course_id()
        ensure_edit_mode(s, cid, row.get('Sesskey'))
        rename_topic_inplace(s, row.get('Sesskey'), row['DB ID'], new_name)

    # -------------------------------------------------------------------------
    # ACTIVITIES MODAL LOGIC
    # -------------------------------------------------------------------------
    @reactive.Effect
    @reactive.event(input.row_action_activities)
    def on_open_activities():
        evt = input.row_action_activities()
        if not evt: return
        idx = evt['index']
        
        current = list(topics_list())
        if idx >= len(current): return
        
        row = current[idx]
        topic_name = row.get('Topic Name', 'Topic')
        activities = row.get('Activities', [])
        
        # Build activities table
        if not activities:
            content = ui.div(
                ui.p("No activities found in this topic.", class_="text-muted text-center p-4")
            )
        else:
            # Build table rows
            activity_rows = []
            for act in activities:
                act_type = act.get('type', 'unknown')
                act_name = act.get('name', 'Unnamed')
                act_url = act.get('url', '')
                act_visible = act.get('visible', True)
                act_id = act.get('id', '')
                
                # Type icon/badge
                type_icons = {
                    'quiz': '📝',
                    'assign': '📋',
                    'page': '📄',
                    'resource': '📁',
                    'url': '🔗',
                    'forum': '💬',
                    'folder': '📂',
                    'book': '📖',
                    'scorm': '🎓',
                    'lesson': '📚',
                    'label': '🏷️',
                    'certificate': '🏆'
                }
                type_icon = type_icons.get(act_type, '📦')

                # Make name clickable link if URL exists
                if act_url:
                    name_html = f'<a href="{act_url}" target="_blank" class="text-primary">{act_name}</a>'
                else:
                    name_html = act_name
                
                # Escape name for data attribute
                escaped_name = act_name.replace('"', '&quot;')
                section_id = row.get('Section ID', '')

                # Visibility toggle icon
                vis_icon = "👁️" if act_visible else "🚫"
                vis_toggle_title = "Hide" if act_visible else "Show"

                activity_rows.append(f"""
                <tr data-activity-id="{act_id}" data-activity-name="{escaped_name}" data-section-id="{section_id}" data-visible="{str(act_visible).lower()}">
                    <td class="text-center drag-handle" title="Drag to reorder">⋮⋮</td>
                    <td class="text-center">{type_icon}</td>
                    <td>{name_html}</td>
                    <td><span class="badge bg-secondary">{act_type}</span></td>
                    <td class="text-center">
                        <button class="btn-toggle-visibility-activity" data-activity-id="{act_id}" data-visible="{str(act_visible).lower()}" title="{vis_toggle_title}">{vis_icon}</button>
                    </td>
                    <td class="text-center" style="white-space: nowrap;">
                        <button class="btn-rename-activity" data-activity-id="{act_id}" data-activity-name="{escaped_name}" data-activity-type="{act_type}" title="Rename">✏️</button>
                        <button class="btn-duplicate-activity" data-activity-id="{act_id}" data-activity-name="{escaped_name}" title="Duplicate">⧉</button>
                        <button class="btn-delete-activity" data-activity-id="{act_id}" data-activity-name="{escaped_name}" title="Delete">🗑️</button>
                    </td>
                </tr>
                """)
            
            table_html = f"""
            <table class="table table-sm table-hover">
                <thead>
                    <tr>
                        <th style="width: 30px;"></th>
                        <th style="width: 40px;"></th>
                        <th>Activity Name</th>
                        <th style="width: 100px;">Type</th>
                        <th style="width: 60px;" class="text-center">Visible</th>
                        <th style="width: 50px;"></th>
                    </tr>
                </thead>
                <tbody id="activities_table_body">
                    {''.join(activity_rows)}
                </tbody>
            </table>
            """
            content = ui.HTML(table_html)
        
        # Build topics data for context menu (JavaScript global)
        import json
        topics_for_js = []
        for t in current:
            topics_for_js.append({
                "sectionId": t.get('Section ID', ''),
                "dbId": t.get('DB ID', ''),
                "name": t.get('Topic Name', 'Untitled')
            })
        topics_json = json.dumps(topics_for_js)
        
        # Script to inject topics data and initialize sortable
        inject_script = ui.HTML(f"""
        <script>
            window.activityModalTopics = {topics_json};
            window.activityModalSesskey = "{row.get('Sesskey', '')}";
            // Initialize sortable after DOM is ready
            setTimeout(function() {{
                if (typeof initActivitySortable === 'function') {{
                    initActivitySortable();
                }}
            }}, 100);
        </script>
        """)
        
        m = ui.modal(
            inject_script,
            content,
            title=f"Activities in: {topic_name}",
            size="l",
            easy_close=True,
            footer=ui.div(
                ui.span("💡 Drag to reorder • Right-click to move • 📋 to duplicate", 
                        class_="text-muted small", style="margin-right: auto;"),
                ui.input_action_button("close_activities_modal", "Close", class_="btn-secondary"),
                class_="d-flex align-items-center w-100"
            )
        )
        ui.modal_show(m)
    
    @reactive.Effect
    @reactive.event(input.close_activities_modal)
    def on_close_activities():
        ui.modal_remove()

    @reactive.Effect
    @reactive.event(input.activity_move_to_topic)
    def on_activity_move():
        """Handle moving an activity to a different topic via context menu"""
        evt = input.activity_move_to_topic()
        if not evt: return
        
        activity_id = evt.get('activityId')
        activity_name = evt.get('activityName', 'Activity')
        target_section_id = evt.get('targetSectionId')
        target_section_name = evt.get('targetSectionName', 'Target')
        
        if not activity_id or not target_section_id:
            ui.notification_show("Missing activity or section information", type="error")
            return
        
        s = setup_session(user_session_id())
        cid = input.course_id()
        
        # Get sesskey from topics
        current = list(topics_list())
        if not current:
            ui.notification_show("No topics loaded", type="error")
            return
        sesskey = current[0].get('Sesskey', '')
        
        # Ensure edit mode
        ensure_edit_mode(s, cid, sesskey)
        
        # Move the activity
        ui.notification_show(f"Moving '{activity_name}' to '{target_section_name}'...", duration=1)
        success = move_activity_to_section(s, cid, activity_id, target_section_id, sesskey)
        
        if success:
            ui.notification_show(f"✅ Moved '{activity_name}' to '{target_section_name}'", type="message")
            # Refresh topics to reflect the change
            new_topics = get_topics(s, cid)
            topics_list.set(new_topics)
            # Close the current modal (activity will be in different topic now)
            ui.modal_remove()
        else:
            ui.notification_show(f"❌ Failed to move '{activity_name}'", type="error")

    @reactive.Effect
    @reactive.event(input.activity_reorder)
    def on_activity_reorder():
        """Handle drag-drop reordering of activities within a topic"""
        evt = input.activity_reorder()
        if not evt: return
        
        activity_id = evt.get('activityId')
        before_id = evt.get('beforeId')  # Can be None if moved to end
        
        if not activity_id:
            return
        
        s = setup_session(user_session_id())
        cid = input.course_id()
        
        current = list(topics_list())
        if not current: return
        sesskey = current[0].get('Sesskey', '')
        
        # Find the section ID for this activity
        section_id = None
        for topic in current:
            for act in topic.get('Activities', []):
                if str(act.get('id')) == str(activity_id):
                    section_id = topic.get('Section ID')
                    break
            if section_id:
                break
        
        if not section_id:
            ui.notification_show("Could not find activity section", type="error")
            return
        
        ensure_edit_mode(s, cid, sesskey)
        
        success = reorder_activity_within_section(s, cid, activity_id, section_id, before_id, sesskey)
        
        if success:
            ui.notification_show("✅ Activity reordered", type="message", duration=2)
            # Refresh topics to reflect the change
            new_topics = get_topics(s, cid)
            topics_list.set(new_topics)
        else:
            ui.notification_show("❌ Failed to reorder activity", type="error")

    @reactive.Effect
    @reactive.event(input.activity_duplicate)
    def on_activity_duplicate():
        """Handle duplicating an activity"""
        evt = input.activity_duplicate()
        if not evt: return
        
        activity_id = evt.get('activityId')
        activity_name = evt.get('activityName', 'Activity')
        
        if not activity_id:
            return
        
        s = setup_session(user_session_id())
        cid = input.course_id()
        
        # Get fresh sesskey (cached one may be stale)
        sesskey = get_fresh_sesskey(s, cid)
        if not sesskey:
            ui.notification_show("❌ Could not get session key", type="error")
            return
        
        ensure_edit_mode(s, cid, sesskey)
        
        ui.notification_show(f"Duplicating '{activity_name}'...", duration=1)
        success = duplicate_activity(s, activity_id, sesskey)
        
        if success:
            ui.notification_show(f"✅ Duplicated '{activity_name}'", type="message")
            # Refresh topics (background) and send message to update UI
            new_topics = get_topics(s, cid)
            topics_list.set(new_topics)
            # Find the new duplicated activity's info to render new row
            # For simplicity, just close and reopen the modal
            # (full optimistic UI for duplicate requires finding new activity ID)
            ui.modal_remove()
        else:
            ui.notification_show(f"❌ Failed to duplicate '{activity_name}'", type="error")

    @reactive.Effect
    @reactive.event(input.activity_delete)
    def on_activity_delete():
        """Handle deleting an activity"""
        evt = input.activity_delete()
        if not evt: return
        
        activity_id = evt.get('activityId')
        activity_name = evt.get('activityName', 'Activity')
        
        if not activity_id:
            return
        
        s = setup_session(user_session_id())
        cid = input.course_id()
        
        # Get fresh sesskey (cached one may be stale)
        sesskey = get_fresh_sesskey(s, cid)
        if not sesskey:
            ui.notification_show("❌ Could not get session key", type="error")
            return
        
        ensure_edit_mode(s, cid, sesskey)
        
        ui.notification_show(f"Deleting '{activity_name}'...", duration=1)
        success = delete_activity(s, activity_id, sesskey)
        
        if success:
            ui.notification_show(f"✅ Deleted '{activity_name}'", type="message")
            # Refresh topics
            new_topics = get_topics(s, cid)
            topics_list.set(new_topics)
            # Remove row via JS - inject a script to remove it
            ui.insert_ui(
                ui.HTML(f"""<script>
                    var row = document.querySelector('tr[data-activity-id="{activity_id}"]');
                    if (row) row.remove();
                </script>"""),
                selector="body"
            )
        else:
            ui.notification_show(f"❌ Failed to delete '{activity_name}'", type="error")

    @reactive.Effect
    @reactive.event(input.activity_rename)
    def on_activity_rename():
        """Handle renaming an activity"""
        evt = input.activity_rename()
        if not evt: return
        
        activity_id = evt.get('activityId')
        old_name = evt.get('oldName', 'Activity')
        new_name = evt.get('newName', '')
        activity_type = evt.get('activityType', '')
        
        if not activity_id or not new_name:
            return
        
        s = setup_session(user_session_id())
        cid = input.course_id()
        
        # Get fresh sesskey (cached one may be stale)
        sesskey = get_fresh_sesskey(s, cid)
        if not sesskey:
            ui.notification_show("❌ Could not get session key", type="error")
            return
        
        ensure_edit_mode(s, cid, sesskey)
        
        ui.notification_show(f"Renaming '{old_name}'...", duration=1)
        success = rename_activity(s, sesskey, activity_id, new_name, activity_type)
        
        if success:
            ui.notification_show(f"✅ Renamed to '{new_name}'", type="message")
            # Refresh topics to update the name
            new_topics = get_topics(s, cid)
            topics_list.set(new_topics)
            save_cache(f"course_{cid}_topics", new_topics)
            # Update the row name via JS
            escaped_new_name = new_name.replace('"', '\\"')
            ui.insert_ui(
                ui.HTML(f"""<script>
                    var row = document.querySelector('tr[data-activity-id="{activity_id}"]');
                    if (row) {{
                        var nameCell = row.querySelector('td:nth-child(3) a');
                        if (nameCell) nameCell.textContent = "{escaped_new_name}";
                        row.dataset.activityName = "{escaped_new_name}";
                    }}
                </script>"""),
                selector="body"
            )
        else:
            ui.notification_show(f"❌ Failed to rename '{old_name}'", type="error")

    @reactive.Effect
    @reactive.event(input.activity_toggle_visibility)
    def on_activity_toggle_visibility():
        """Handle toggling activity visibility"""
        evt = input.activity_toggle_visibility()
        if not evt: return

        activity_id = evt.get('activityId')
        hide = evt.get('hide', True)

        if not activity_id:
            return

        s = setup_session(user_session_id())
        cid = input.course_id()

        # Get fresh sesskey (cached one may be stale)
        sesskey = get_fresh_sesskey(s, cid)
        if not sesskey:
            ui.notification_show("❌ Could not get session key", type="error")
            return

        ensure_edit_mode(s, cid, sesskey)

        action_text = "Hiding" if hide else "Showing"
        ui.notification_show(f"{action_text} activity...", duration=1)
        success = toggle_activity_visibility(s, activity_id, sesskey, hide)

        if success:
            emoji = "👁️‍🗨️" if hide else "✅"
            status_text = "hidden" if hide else "visible"
            ui.notification_show(f"{emoji} Activity {status_text}", type="message")
            # Refresh topics to update visibility status
            new_topics = get_topics(s, cid)
            topics_list.set(new_topics)
            save_cache(f"course_{cid}_topics", new_topics)
        else:
            ui.notification_show(f"❌ Failed to toggle visibility", type="error")
            # Revert optimistic UI update
            new_visible = not hide
            ui.insert_ui(
                ui.HTML(f"""<script>
                    var row = document.querySelector('tr[data-activity-id="{activity_id}"]');
                    if (row) {{
                        var visBtn = row.querySelector('.btn-toggle-visibility-activity');
                        if (visBtn) {{
                            visBtn.dataset.visible = "{str(new_visible).lower()}";
                            visBtn.textContent = "{('👁️' if new_visible else '🚫')}";
                            visBtn.title = "{'Hide' if new_visible else 'Show'}";
                        }}
                        row.dataset.visible = "{str(new_visible).lower()}";
                    }}
                </script>"""),
                selector="body"
            )

    # -------------------------------------------------------------------------
    # RESTRICTION MODAL LOGIC
    # -------------------------------------------------------------------------
    restrict_topic_idx = reactive.Value(None)
    current_restriction_json = reactive.Value(None)
    current_grade_items_map = reactive.Value({})
    current_completion_items_map = reactive.Value({})
    
    @reactive.Effect
    @reactive.event(input.row_action_lock)
    def on_open_restriction():
        evt = input.row_action_lock()
        if not evt: return
        idx = evt['index']
        restrict_topic_idx.set(idx)
        
        s = setup_session(user_session_id())
        cid = input.course_id()
        
        # Load groups (with caching)
        groups_cache = course_groups_cache()
        if cid in groups_cache:
            groups = groups_cache[cid]
        else:
            ui.notification_show("Loading course groups...", duration=1)
            groups = get_course_groups(s, cid)
            groups_cache[cid] = groups
            course_groups_cache.set(groups_cache)
        
        choices = {g['id']: g['name'] for g in groups}
        
        # Fetch EXISTING restriction (this must always be fresh)
        current_topics = list(topics_list())
        if idx < len(current_topics):
            row = current_topics[idx]
            topic_id = row['DB ID']
            ui.notification_show("Fetching existing restrictions...", duration=1)
            existing_json = get_topic_restriction(s, topic_id)
        else:
            existing_json = None
            
        current_restriction_json.set(existing_json)

        # Parse existing groups
        import json
        selected_groups = []
        other_restrictions = []
        
        # Load Grade Items and Completion Activities (with caching)
        grade_cache = course_grade_items_cache()
        if cid in grade_cache:
            grade_items_map, completion_items_map = grade_cache[cid]
        else:
            ui.notification_show("Loading gradable activities...", duration=1)
            # Pass current topics to avoid redundant fetch
            current_topics = list(topics_list())
            result = get_course_grade_items(s, cid, topics=current_topics)
            # Handle both old (dict) and new (tuple) return formats
            if isinstance(result, tuple):
                grade_items_map, completion_items_map = result
            else:
                grade_items_map = result if result else {}
                completion_items_map = {}
            grade_cache[cid] = (grade_items_map, completion_items_map)
            course_grade_items_cache.set(grade_cache)
        
        current_grade_items_map.set(grade_items_map)
        current_completion_items_map.set(completion_items_map)
        
        # Parse existing restrictions to pre-populate form
        import json
        selected_groups = []
        has_date_restriction = False
        existing_date_val = None
        existing_date_dir = ">="
        existing_time_val = "00:00"
        has_grade_restriction = False
        existing_grade_item = None
        existing_grade_min = None
        existing_grade_max = None
        has_completion_restriction = False
        existing_completion_item = None
        existing_completion_state = 1
        existing_operator = "&"  # Default to AND
        hide_on_restriction_not_met = False  # Default to showing content even when restrictions not met
        
        try:
            if existing_json:
                data = json.loads(existing_json)
                
                # Get the top-level operator
                existing_operator = data.get('op', '&')

                # Parse showc to determine if content should be hidden when restriction not met
                # Based on Burp requests, showc is always an array: [true/false, true/false, ...]
                # If ALL conditions have showc=false, the topic is hidden when restrictions not met
                if 'showc' in data and data['showc']:
                    # Check if all values are False (meaning hide for all conditions)
                    hide_on_restriction_not_met = all(not val for val in data['showc'])

                # Recursive finder for all restriction types
                def find_restrictions(c_list):
                    nonlocal has_date_restriction, existing_date_val, existing_date_dir, existing_time_val
                    nonlocal has_grade_restriction, existing_grade_item, existing_grade_min, existing_grade_max
                    nonlocal has_completion_restriction, existing_completion_item, existing_completion_state
                    
                    groups_found = []
                    for cond in c_list:
                        if 'c' in cond:  # Nested
                            groups_found.extend(find_restrictions(cond['c']))
                        elif cond.get('type') == 'group':
                            groups_found.append(str(cond.get('id')))
                        elif cond.get('type') == 'date':
                            has_date_restriction = True
                            existing_date_dir = cond.get('d', '>=')
                            ts = cond.get('t', 0)
                            if ts:
                                import datetime
                                dt = datetime.datetime.fromtimestamp(ts)
                                existing_date_val = dt.date()
                                existing_time_val = dt.strftime("%H:%M")
                        elif cond.get('type') == 'grade':
                            has_grade_restriction = True
                            existing_grade_item = str(cond.get('id', ''))
                            existing_grade_min = cond.get('min')
                            existing_grade_max = cond.get('max')
                        elif cond.get('type') == 'completion':
                            has_completion_restriction = True
                            existing_completion_item = str(cond.get('cm', ''))
                            existing_completion_state = cond.get('e', 1)
                    return groups_found
                
                if 'c' in data:
                    selected_groups = find_restrictions(data['c'])
        except: pass


        # Accordion for adding/managing restrictions
        m = ui.modal(
            ui.div(
                ui.output_ui("existing_restriction_warning"),
                # Operator selector at the top
                ui.div(
                    ui.p("Condition Logic:", class_="fw-bold mb-1"),
                    ui.input_radio_buttons(
                        "restriction_operator",
                        None,
                        choices={"&": "ALL conditions must be met (AND)", "|": "ANY condition grants access (OR)"},
                        selected=existing_operator,
                        inline=True
                    ),
                    class_="mb-3 p-2 border rounded bg-light"
                ),
                # Hide when restriction not met toggle
                ui.div(
                    ui.input_checkbox(
                        "hide_on_restriction_not_met",
                        "🚫 Hide topic when restriction not met (students won't see it unless they meet the conditions)",
                        value=hide_on_restriction_not_met
                    ),
                    class_="mb-3 p-2 border rounded",
                    style="background-color: #fff3cd;"
                ),
                ui.accordion(
                    ui.accordion_panel("Group Access",
                        ui.p("Allow access only to members of these groups:", class_="small text-muted"),
                        ui.input_checkbox("enable_group_restriction", "Enable Group Restriction", value=len(selected_groups) > 0),
                        ui.input_select("restrict_group_id", "Select Groups", choices=choices, selected=selected_groups, multiple=True, width="100%"),
                    ),
                    ui.accordion_panel("Date Access",
                         ui.p("Prevent access until (or from) a specified date.", class_="small text-muted"),
                         ui.input_checkbox("enable_date_restriction", "Enable Date Restriction", value=has_date_restriction),
                         ui.input_date("restrict_date_val", "Date", value=existing_date_val),
                         ui.input_select("restrict_date_direction", "Direction", choices={">=": "From (>=)", "<": "Until (<)"}, selected=existing_date_dir),
                         ui.input_text("restrict_time_val", "Time (HH:MM)", value=existing_time_val)
                    ),
                    ui.accordion_panel("Grade Access",
                         ui.p("Require students to achieve a specified grade.", class_="small text-muted"),
                         ui.input_checkbox("enable_grade_restriction", "Enable Grade Restriction", value=has_grade_restriction),
                         ui.input_select("restrict_grade_item", "Grade Item", choices=grade_items_map, selected=existing_grade_item, width="100%"),
                         ui.input_numeric("restrict_grade_min", "Min %", value=existing_grade_min, min=0, max=100),
                         ui.input_numeric("restrict_grade_max", "Max %", value=existing_grade_max, min=0, max=100)
                    ),
                    ui.accordion_panel("Activity Completion",
                         ui.p("Require completion of another activity.", class_="small text-muted"),
                         ui.input_checkbox("enable_completion_restriction", "Enable Activity Completion Restriction", value=has_completion_restriction),
                         ui.input_select("restrict_completion_item", "Activity", choices=completion_items_map, selected=existing_completion_item, width="100%"),
                         ui.input_radio_buttons(
                             "restrict_completion_state",
                             "Required State",
                             choices={"1": "Must be complete", "0": "Must NOT be complete"},
                             selected=str(existing_completion_state),
                             inline=True
                         )
                    ),
                    id="restriction_accordion",
                    multiple=True
                )
            ),
            title="Manage Access Restrictions",
            footer=ui.div(
                ui.input_action_button("clear_restriction", "Clear All Restrictions", class_="btn-danger btn-sm"),
                ui.div(
                    ui.input_action_button("save_restriction", "Apply Changes", class_="btn-primary me-2"),
                    ui.modal_button("Cancel", class_="btn-secondary")
                ),
                class_="d-flex justify-content-between align-items-center w-100",
                style="gap: 10px;"
            ),
            easy_close=True,
            size="l"  # Make modal larger to fit content
        )
        ui.modal_show(m)

    @reactive.Effect
    @reactive.event(input.save_restriction)
    def on_save_restriction():
        idx = restrict_topic_idx()
        if idx is None:
             ui.modal_remove()
             return

        # Gather inputs - only if enabled, otherwise pass {} to trigger removal
        # Note: None means "don't touch", {} or [] means "remove this type"
        grp_ids = []  # Empty list = remove groups
        if input.enable_group_restriction():
            grp_ids = list(input.restrict_group_id() or [])
        
        # Date inputs - {} means remove, None means don't touch
        date_cond = {}  # Default to remove
        if input.enable_date_restriction():
            d_val = input.restrict_date_val()
            t_val_str = input.restrict_time_val()
            if d_val:
                import datetime
                try:
                    t_val = datetime.datetime.strptime(t_val_str, "%H:%M").time()
                    dt = datetime.datetime.combine(d_val, t_val)
                    ts = int(dt.timestamp())
                    direction = input.restrict_date_direction()
                    date_cond = {"type": "date", "d": direction, "t": ts}
                except: 
                    date_cond = {}  # Invalid date, remove it
            
        # Grade inputs - {} means remove
        grade_cond = {}  # Default to remove
        if input.enable_grade_restriction():
            g_item = input.restrict_grade_item()
            g_min = input.restrict_grade_min()
            g_max = input.restrict_grade_max()
            if g_item and (g_min is not None or g_max is not None):
                 c = {"type": "grade", "id": int(g_item)}
                 if g_min is not None: c['min'] = float(g_min)
                 if g_max is not None: c['max'] = float(g_max)
                 grade_cond = c
             
        existing_json = current_restriction_json()
        current = list(topics_list())
        if idx >= len(current): return
        row = current[idx]
        
        s = setup_session(user_session_id())
        cid = input.course_id()
        sesskey = row.get('Sesskey')
        
        # Activity completion - {} means remove
        completion_cond = {}  # Default to remove
        if input.enable_completion_restriction():
            c_item = input.restrict_completion_item()
            c_state = input.restrict_completion_state()
            if c_item:
                completion_cond = {"type": "completion", "cm": int(c_item), "e": int(c_state)}
        
        # Get the operator selection
        operator = input.restriction_operator()

        # Get the hide-on-restriction-not-met toggle state
        hide_on_not_met = input.hide_on_restriction_not_met()

        from core.api import update_restrictions_batch
        json_data = update_restrictions_batch(
            existing_json,
            grp_ids,
            date_cond,
            grade_cond,
            completion_cond=completion_cond,
            operator=operator,
            hide_on_restriction_not_met=hide_on_not_met
        )
        
        ui.notification_show("Applying restrictions...", duration=1)
        if update_topic_restriction(s, cid, row['DB ID'], sesskey, json_data):
            ui.notification_show("Restrictions applied!", type="message")

            # Optimistic update: Update local cache immediately with new restriction summary
            new_summary_list = get_restriction_summary(json_data)
            current[idx]['Restriction Summary'] = '\n'.join(new_summary_list) if new_summary_list else ''
            topics_list.set(current)

            # Also update disk cache immediately (background refresh will confirm later)
            save_cache(f"course_{cid}_topics", current)

            # Trigger background refresh to fetch fresh data and confirm changes
            trigger_background_refresh(cid)
        else:
            ui.notification_show("Failed to apply restrictions", type="error")

        ui.modal_remove()

    @output
    @render.ui
    def existing_restriction_warning():
        json_str = current_restriction_json()
        map_data = current_grade_items_map()
        
        if not json_str: return ui.div() # Empty
        
        # Check for empty op (cleared state)
        if json_str == '{"op":"&","c":[],"showc":[]}': return ui.div()

        other_restrictions = get_restriction_summary(json_str, map_data)
        if not other_restrictions: return ui.div()
        
        # Format as preformatted text to preserve tree structure
        tree_text = "\n".join(other_restrictions)
        return ui.div(
             ui.tags.div("⚠️ Existing restriction structure:", class_="text-warning fw-bold small"),
             ui.tags.pre(tree_text, class_="small text-muted bg-light p-2 rounded", 
                         style="font-family: 'Consolas', 'Monaco', monospace; font-size: 0.85em; white-space: pre;")
        )

    @reactive.Effect
    @reactive.event(input.clear_restriction)
    def on_clear_restriction():
        idx = restrict_topic_idx()
        if idx is None: return
        
        current = list(topics_list())
        if idx >= len(current): return
        row = current[idx]
        
        s = setup_session(user_session_id())
        cid = input.course_id()
        sesskey = row.get('Sesskey')
        
        # Clear JSON
        empty_json = '{"op":"&","c":[],"showc":[]}'
        
        ui.notification_show("Clearing restrictions...", duration=1)
        if update_topic_restriction(s, cid, row['DB ID'], sesskey, empty_json):
            ui.notification_show("Restrictions cleared! You can now set new ones.", type="message")

            # Reset UI Inputs to reflect cleared state
            ui.update_checkbox("enable_group_restriction", value=False)
            ui.update_select("restrict_group_id", selected=[])
            ui.update_checkbox("enable_date_restriction", value=False)
            ui.update_date("restrict_date_val", value=None)
            ui.update_text("restrict_time_val", value="00:00")
            ui.update_checkbox("enable_grade_restriction", value=False)
            ui.update_select("restrict_grade_item", selected=None)
            ui.update_numeric("restrict_grade_min", value=None)
            ui.update_numeric("restrict_grade_max", value=None)
            ui.update_checkbox("enable_completion_restriction", value=False)
            ui.update_select("restrict_completion_item", selected=None)
            ui.update_radio_buttons("restriction_operator", selected="&")
            ui.update_checkbox("hide_on_restriction_not_met", value=False)

            # Update internal state so subsequent Save builds on empty
            current_restriction_json.set(empty_json)

            # Trigger background refresh to update topic data after clearing restrictions
            trigger_background_refresh(cid)

        else:
            ui.notification_show("Failed to clear restrictions", type="error")
            
        # Keep modal open as requested

app = App(app_ui, server)
