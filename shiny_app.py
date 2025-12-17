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

from shiny_modules.ui import get_custom_css, get_custom_js
from shiny_modules.server import register_auth_handlers, register_restriction_handlers, register_activity_handlers, register_course_handlers

# CSS & JS from modules
custom_css = get_custom_css()
custom_js = get_custom_js()


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
        ui.nav_control(
            ui.tags.button(
                ui.HTML('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>'),
                id="theme-toggle-btn",
                class_="theme-toggle",
                onclick="toggleTheme()",
                title="Toggle theme"
            )
        ),
        title=None
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
    
    # Register auth handlers from module
    register_auth_handlers(
        input,
        auth_initialized,
        user_session_id,
        user_authenticated,
        current_username
    )

    # -------------------------------------------------------------------------
    # COURSE DATA - Handlers registered from course_handlers module
    # -------------------------------------------------------------------------
    courses_data, available_courses, trigger_background_refresh, do_background_refresh = register_course_handlers(
        input,
        user_authenticated,
        user_session_id,
        topics_list,
        course_groups_cache,
        course_grade_items_cache,
        is_edit_mode_on,
        selected_indices
    )

    @output
    @render.ui
    def nav_course_selector():
        if not user_authenticated(): return None
        # Build choices with custom option at the bottom
        choices = {str(c['id']): c['name'] for c in available_courses()}
        choices["__custom__"] = "📝 Enter Course ID..."
        
        return ui.div(
            ui.input_select("course_id", None, choices=choices, width="300px"),
            ui.output_ui("custom_course_id_input"),
            class_="d-flex align-items-center gap-2",
            style="margin-top: 10px;"
        )

    @output
    @render.ui
    def custom_course_id_input():
        """Show text input when 'Custom Course ID' is selected"""
        if input.course_id() != "__custom__":
            return None
        # Use raw HTML with JS onclick to read value and trigger action
        return ui.HTML('''
            <div class="custom-course-input">
                <input type="text" id="custom_course_id_text" placeholder="Course ID" />
                <button class="btn btn-primary"
                        onclick="var val = document.getElementById('custom_course_id_text').value; Shiny.setInputValue('load_custom_course_id', val);">Go</button>
            </div>
        ''')

    @reactive.Effect
    @reactive.event(input.load_custom_course_id)
    def on_load_custom_course():
        """Load custom course when Go button is clicked"""
        custom_id = input.load_custom_course_id()
        if not custom_id or not str(custom_id).strip():
            ui.notification_show("Please enter a course ID", type="warning")
            return
        
        custom_id = str(custom_id).strip()
        logger.info(f"Loading custom course ID: {custom_id}")
        
        # Add to courses list if not already present
        current_courses = list(courses_data())
        existing_ids = [str(c['id']) for c in current_courses]
        
        if custom_id not in existing_ids:
            # Add as a placeholder course
            current_courses.insert(0, {'id': custom_id, 'name': f"Course {custom_id}"})
            courses_data.set(current_courses)
        
        # Update the dropdown to show the custom course
        ui.update_select("course_id", selected=custom_id)

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
                ui.div(ui.output_ui("toolbar_selection_info"), class_="d-flex align-items-center flex-grow-1"),
                ui.div(ui.output_ui("toolbar_actions"), class_="ms-auto d-flex gap-1"),
                class_="toolbar"
            ),
            # CUSTOM TABLE
            ui.div(
                ui.output_ui("topics_table_html"),
                class_="topics-table-container"
            ),
            class_="app-card"
        )



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
            return ui.span("1 topic selected", style="font-weight: 600; color: var(--primary-color);")
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
        
        # Build dropdown choices with special actions and groups
        group_choices = {"": "-- Select Action --"}

        # Add special actions at the top (always visible)
        group_choices["__clear_groups__"] = "[Clear All Groups]"
        group_choices["__clear_all__"] = "[Clear All Restrictions]"
        group_choices["__chain_quiz__"] = "[Chain with Previous Quiz]"
        group_choices["__divider__"] = "-------------------"

        # Add group options
        for g in available_groups:
            gid = str(g['id'])
            name = g['name']
            if gid in existing_group_names:
                group_choices[gid] = f"✓ {name}"
            else:
                group_choices[gid] = name

        return ui.div(
            # Refresh
            ui.input_action_button(
                "act_refresh_topics",
                "",
                icon=icon_svg("arrow-rotate-right"),
                class_="toolbar-icon-btn",
                title="Refresh topics from server"
            ),

            # Divider
            ui.div(class_="toolbar-divider"),

            # Add topic section
            ui.div(
                ui.input_numeric("add_count", None, value=1, min=1, width="60px"),
            ui.input_action_button(
                    "act_add",
                    "+",
                    class_="toolbar-icon-btn toolbar-icon-btn-primary",
                    title="Add topic(s)"
                ),
                class_="d-flex gap-1 align-items-center"
            ),

            # Divider
            ui.div(class_="toolbar-divider"),

            # Rename section
            ui.div(
                ui.input_text("edit_name_float", None, placeholder="New name...", width="150px"),
                ui.input_action_button(
                    "act_rename",
                    "",
                    icon=icon_svg("pen"),
                    disabled=not can_rename,
                    class_="toolbar-icon-btn",
                    title="Rename selected topic"
                ),
                class_="d-flex gap-1 align-items-center"
            ),

            # Divider
            ui.div(class_="toolbar-divider"),

            # Visibility & Delete
            ui.div(
                ui.input_action_button(
                    "act_vis",
                    "",
                    icon=icon_svg(vis_icon),
                    disabled=not can_batch,
                    class_="toolbar-icon-btn",
                    title=f"{vis_label} selected topic(s)"
                ),
                ui.input_action_button(
                    "act_del",
                    "",
                    icon=icon_svg("trash"),
                    disabled=not can_batch,
                    class_="toolbar-icon-btn toolbar-icon-btn-danger",
                    title="Delete selected topic(s)"
                ),
                class_="d-flex gap-1 align-items-center"
            ),

            # Divider
            ui.div(class_="toolbar-divider"),

            # Group restrictions section
            ui.div(
                ui.input_select("toolbar_group_select", None, choices=group_choices, width="220px"),
                ui.input_action_button(
                    "act_apply_group_action",
                    "",
                    icon=icon_svg("circle-check"),
                    disabled=not can_batch,
                    class_="toolbar-icon-btn toolbar-icon-btn-primary",
                    title="Apply selected action"
                ),
                class_="d-flex gap-1 align-items-center"
            ),

            class_="d-flex align-items-center gap-1"
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
    @reactive.event(input.act_apply_group_action)
    def do_apply_group_action():
        """Unified handler for all group restriction operations"""
        selection = input.toolbar_group_select()

        if not selection or selection == "__divider__":
            ui.notification_show("Please select an action or group", type="warning")
            return

        # Route to appropriate handler based on selection
        if selection == "__clear_groups__":
            do_clear_groups_batch()
        elif selection == "__clear_all__":
            do_clear_all_restrictions_batch()
        elif selection == "__chain_quiz__":
            do_chain_with_previous_quiz()
        else:
            # It's a group ID - add the group
            do_add_group_batch(selection)

        # Reset dropdown to default
        ui.update_select("toolbar_group_select", selected="")

    def do_add_group_batch(group_id):
        """Add a group restriction to selected topics"""
        indices = selected_indices()
        if not indices:
            ui.notification_show("No topics selected", type="warning")
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
        save_cache(f"course_{cid}_topics", current)
        ui.notification_show(f"Added '{group_name}' to {success_count}/{len(indices)} topics", type="message")

        # Trigger background refresh
        trigger_background_refresh(cid)

    def do_clear_groups_batch():
        """Clear all group restrictions from selected topics"""
        indices = selected_indices()
        if not indices:
            ui.notification_show("No topics selected", type="warning")
            return

        cid = input.course_id()
        if not cid:
            return

        current = list(topics_list())
        s = setup_session(user_session_id())

        success_count = 0
        with ui.Progress(min=0, max=len(indices)) as p:
            p.set(message="Clearing group restrictions...")

            for i, idx in enumerate(indices):
                if idx >= len(current):
                    continue

                row = current[idx]
                topic_id = row['DB ID']
                sesskey = row.get('Sesskey')

                try:
                    # 1. Fetch current restriction JSON
                    current_json = get_topic_restriction(s, topic_id)

                    # 2. Remove all group restrictions (pass empty list)
                    updated_json = add_or_update_group_restriction(current_json, [])

                    # 3. Update topic restriction
                    ensure_edit_mode(s, cid, sesskey)
                    if update_topic_restriction(s, cid, topic_id, sesskey, updated_json):
                        success_count += 1
                        # Update local restriction summary
                        new_summary_list = get_restriction_summary(updated_json)
                        current[idx]['Restriction Summary'] = '\n'.join(new_summary_list) if new_summary_list else ''

                except Exception as e:
                    logger.error(f"Error clearing groups from topic {topic_id}: {e}")

                p.set(i + 1, message=f"Processed {i + 1}/{len(indices)}")

        # Refresh UI
        topics_list.set(current)
        save_cache(f"course_{cid}_topics", current)
        ui.notification_show(f"Cleared group restrictions from {success_count}/{len(indices)} topics", type="message")

        # Trigger background refresh
        trigger_background_refresh(cid)

    def do_clear_all_restrictions_batch():
        """Clear ALL restrictions from selected topics"""
        indices = selected_indices()
        if not indices:
            ui.notification_show("No topics selected", type="warning")
            return

        cid = input.course_id()
        if not cid:
            return

        current = list(topics_list())
        s = setup_session(user_session_id())

        empty_json = '{"op":"&","c":[],"showc":[]}'

        success_count = 0
        with ui.Progress(min=0, max=len(indices)) as p:
            p.set(message="Clearing all restrictions...")

            for i, idx in enumerate(indices):
                if idx >= len(current):
                    continue

                row = current[idx]
                topic_id = row['DB ID']
                sesskey = row.get('Sesskey')

                try:
                    ensure_edit_mode(s, cid, sesskey)
                    if update_topic_restriction(s, cid, topic_id, sesskey, empty_json):
                        success_count += 1
                        # Clear local restriction summary
                        current[idx]['Restriction Summary'] = ''

                except Exception as e:
                    logger.error(f"Error clearing restrictions from topic {topic_id}: {e}")

                p.set(i + 1, message=f"Processed {i + 1}/{len(indices)}")

        # Refresh UI
        topics_list.set(current)
        save_cache(f"course_{cid}_topics", current)
        ui.notification_show(f"Cleared all restrictions from {success_count}/{len(indices)} topics", type="message")

        # Trigger background refresh
        trigger_background_refresh(cid)

    def do_chain_with_previous_quiz():
        """Chain selected topics with previous quiz (require 50% grade)"""
        indices = selected_indices()
        if not indices:
            ui.notification_show("No topics selected", type="warning")
            return

        cid = input.course_id()
        if not cid:
            return

        current = list(topics_list())
        s = setup_session(user_session_id())

        # Fetch grade items for the course (Option A: batch fetch)
        grade_items_cache = course_grade_items_cache()
        if cid not in grade_items_cache:
            ui.notification_show("Loading grade items...", duration=2)
            from core.api import get_course_grade_items
            result = get_course_grade_items(s, cid, current)
            # get_course_grade_items returns (grade_items_dict, completion_items_dict)
            grade_items_cache[cid] = result
            course_grade_items_cache.set(grade_items_cache)
        
        # Handle both tuple (grade_items, completion_items) and raw dict formats
        cached = grade_items_cache.get(cid, {})
        if isinstance(cached, tuple):
            grade_items = cached[0] if cached else {}
        else:
            grade_items = cached
        
        # Build module_id -> grade_item_id mapping
        # Grade items are keyed by grade_item_id with quiz name as value
        # We need to match quiz module_id to grade_item_id
        # Unfortunately, the mapping isn't direct - we need to match by name
        
        success_count = 0
        skip_count = 0
        warnings = []
        
        with ui.Progress(min=0, max=len(indices)) as p:
            p.set(message="Chaining with previous quizzes...")

            for i, idx in enumerate(indices):
                if idx >= len(current):
                    continue

                row = current[idx]
                topic_name = row['Topic Name']
                topic_id = row['DB ID']
                sesskey = row.get('Sesskey')

                # Edge case: First topic (index 0)
                if idx == 0:
                    warnings.append(f"'{topic_name}': First topic, skipped")
                    skip_count += 1
                    p.set(i + 1, message=f"Processed {i + 1}/{len(indices)}")
                    continue

                # Find previous quiz - walk backwards
                quiz_found = None
                quiz_topic_name = None
                
                for prev_idx in range(idx - 1, -1, -1):
                    prev_topic = current[prev_idx]
                    activities = prev_topic.get('Activities', [])
                    
                    # Find last visible quiz in this topic (iterate in reverse)
                    for act in reversed(activities):
                        if act.get('type') == 'quiz' and act.get('visible', True):
                            quiz_found = act
                            quiz_topic_name = prev_topic['Topic Name']
                            break
                    
                    if quiz_found:
                        break

                if not quiz_found:
                    warnings.append(f"'{topic_name}': No preceding quiz found")
                    skip_count += 1
                    p.set(i + 1, message=f"Processed {i + 1}/{len(indices)}")
                    continue

                # Find grade item ID for this quiz
                # Match by name (grade items are stored as {grade_item_id: name})
                quiz_name = quiz_found.get('name', '')
                quiz_module_id = quiz_found.get('id', '')
                grade_item_id = None
                
                for gid, gname in grade_items.items():
                    # Match by name (case-insensitive, partial match)
                    if quiz_name.lower() in gname.lower() or gname.lower() in quiz_name.lower():
                        grade_item_id = gid
                        break
                
                if not grade_item_id:
                    warnings.append(f"'{topic_name}': Could not find grade item for '{quiz_name}'")
                    skip_count += 1
                    p.set(i + 1, message=f"Processed {i + 1}/{len(indices)}")
                    continue

                try:
                    # Fetch current restriction JSON
                    current_json = get_topic_restriction(s, topic_id)
                    
                    # Add grade restriction (min 50%)
                    from core.api import add_grade_restriction_to_json
                    updated_json = add_grade_restriction_to_json(current_json, grade_item_id, min_grade=50)
                    
                    # Apply restriction
                    ensure_edit_mode(s, cid, sesskey)
                    if update_topic_restriction(s, cid, topic_id, sesskey, updated_json):
                        success_count += 1
                        # Update local restriction summary
                        new_summary_list = get_restriction_summary(updated_json)
                        current[idx]['Restriction Summary'] = '\n'.join(new_summary_list) if new_summary_list else ''
                    else:
                        warnings.append(f"'{topic_name}': Failed to update restriction")

                except Exception as e:
                    logger.error(f"Error chaining topic {topic_id}: {e}")
                    warnings.append(f"'{topic_name}': Error - {str(e)[:50]}")

                p.set(i + 1, message=f"Processed {i + 1}/{len(indices)}")

        # Refresh UI
        topics_list.set(current)
        save_cache(f"course_{cid}_topics", current)
        
        # Show result notification
        if warnings:
            # Show first few warnings
            warn_text = "; ".join(warnings[:3])
            if len(warnings) > 3:
                warn_text += f" (+{len(warnings)-3} more)"
            ui.notification_show(f"Chained {success_count}/{len(indices)} topics. Warnings: {warn_text}", type="warning", duration=8)
        else:
            ui.notification_show(f"Chained {success_count}/{len(indices)} topics with previous quiz (≥50%)", type="message")

        # Trigger background refresh
        trigger_background_refresh(cid)

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
    # ACTIVITIES MODAL - Handlers registered from activity_handlers module
    # -------------------------------------------------------------------------
    register_activity_handlers(
        input,
        topics_list,
        user_session_id,
        ensure_edit_mode
    )

    # -------------------------------------------------------------------------
    # RESTRICTION MODAL - Handlers registered from restriction_handlers module
    # -------------------------------------------------------------------------
    current_restriction_json, current_grade_items_map = register_restriction_handlers(
        input,
        topics_list,
        user_session_id,
        course_groups_cache,
        course_grade_items_cache,
        trigger_background_refresh
    )

    # Output function for existing restriction warning (requires @output decorator)
    @output
    @render.ui
    def existing_restriction_warning():
        json_str = current_restriction_json()
        map_data = current_grade_items_map()
        
        if not json_str: return ui.div()  # Empty
        
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

app = App(app_ui, server)
