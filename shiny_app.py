from shiny import App, render, ui, reactive
import pandas as pd
from core.auth import login_and_get_cookie, setup_session, validate_session
from core.api import get_courses, get_topics, rename_topic_inplace, move_topic, toggle_topic_visibility, delete_topic, enable_edit_mode, add_topic, get_course_groups, update_topic_restriction, add_or_update_group_restriction, get_topic_restriction, get_restriction_summary, get_course_grade_items, update_restrictions_batch
from core.persistence import read_config
import logging
from faicons import icon_svg

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
            ui.notification_show("Validating saved session...", duration=2)
            if validate_session(loaded_cookie):
                user_session_id.set(loaded_cookie)
                user_authenticated.set(True)
                current_username.set(loaded_user if loaded_user else "User")
                ui.notification_show("Session restored!", type="message", duration=2)
                return
        
        if loaded_user and loaded_pwd:
            ui.notification_show("Logging in...", duration=2)
            sid = login_and_get_cookie(loaded_user, loaded_pwd)
            if sid:
                user_session_id.set(sid)
                user_authenticated.set(True)
                current_username.set(loaded_user)
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

    @reactive.Calc
    def available_courses():
        input.refresh_courses()
        if not user_authenticated(): return []
        s = setup_session(user_session_id())
        return get_courses(s)

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
        
        try:
            with ui.Progress(min=0, max=1) as p:
                p.set(message="Loading topics...")
                s = setup_session(user_session_id())
                data = get_topics(s, cid)
                topics_list.set(data)
                if not data:
                    ui.notification_show("No topics found (or connection issue)", type="warning")
        except Exception as e:
            logger.error(f"Error loading topics: {e}")
            ui.notification_show(f"Failed to load topics: Connection error", type="error")
            topics_list.set([])

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

        return ui.div(
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
            class_="d-flex align-items-center"
        )

    # -------------------------------------------------------------------------
    # ACTION HANDLERS
    # -------------------------------------------------------------------------
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
                
                vis_badge = "✓" if act_visible else "👁️‍🗨️"
                vis_class = "text-success" if act_visible else "text-muted"
                
                # Make name clickable link if URL exists
                if act_url:
                    name_html = f'<a href="{act_url}" target="_blank" class="text-primary">{act_name}</a>'
                else:
                    name_html = act_name
                
                activity_rows.append(f"""
                <tr>
                    <td class="text-center">{type_icon}</td>
                    <td>{name_html}</td>
                    <td><span class="badge bg-secondary">{act_type}</span></td>
                    <td class="text-center {vis_class}">{vis_badge}</td>
                </tr>
                """)
            
            table_html = f"""
            <table class="table table-sm table-hover">
                <thead>
                    <tr>
                        <th style="width: 40px;"></th>
                        <th>Activity Name</th>
                        <th style="width: 100px;">Type</th>
                        <th style="width: 60px;" class="text-center">Visible</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(activity_rows)}
                </tbody>
            </table>
            """
            content = ui.HTML(table_html)
        
        m = ui.modal(
            content,
            title=f"Activities in: {topic_name}",
            size="l",
            easy_close=True,
            footer=ui.div(
                ui.input_action_button("close_activities_modal", "Close", class_="btn-secondary"),
                class_="d-flex justify-content-end"
            )
        )
        ui.modal_show(m)
    
    @reactive.Effect
    @reactive.event(input.close_activities_modal)
    def on_close_activities():
        ui.modal_remove()

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
            result = get_course_grade_items(s, cid)
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
        
        try:
            if existing_json:
                data = json.loads(existing_json)
                
                # Get the top-level operator
                existing_operator = data.get('op', '&')
                
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
        
        from core.api import update_restrictions_batch
        json_data = update_restrictions_batch(
            existing_json, 
            grp_ids, 
            date_cond, 
            grade_cond, 
            completion_cond=completion_cond,
            operator=operator
        )
        
        ui.notification_show("Applying restrictions...", duration=1)
        if update_topic_restriction(s, cid, row['DB ID'], sesskey, json_data):
            ui.notification_show("Restrictions applied!", type="message")
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
            
            # Update internal state so subsequent Save builds on empty
            current_restriction_json.set(empty_json)
            
        else:
            ui.notification_show("Failed to clear restrictions", type="error")
            
        # Keep modal open as requested

app = App(app_ui, server)
