"""
Restriction handlers for Shiny app.

Handles restriction modal: open, save, clear restrictions.
Supports group, date, grade, and activity completion restrictions.
"""
from shiny import reactive, ui
from core.auth import setup_session
from core.api import (
    get_course_groups, get_topic_restriction, get_course_grade_items,
    update_topic_restriction, get_restriction_summary
)
from core.persistence import save_cache
import json
import logging

logger = logging.getLogger(__name__)


def register_restriction_handlers(
    input,
    topics_list,
    user_session_id,
    course_groups_cache,
    course_grade_items_cache,
    trigger_background_refresh
):
    """
    Register restriction modal handlers.
    
    Args:
        input: Shiny input object
        topics_list: reactive.Value for topics data
        user_session_id: reactive.Value for session ID
        course_groups_cache: reactive.Value for groups cache
        course_grade_items_cache: reactive.Value for grade items cache
        trigger_background_refresh: Function to trigger background data refresh
        
    Returns:
        tuple: (current_restriction_json, current_grade_items_map) for use by main file's output function
    """
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
                    ui.accordion_panel("Grade Access",
                         ui.p("Require students to achieve a specified grade.", class_="small text-muted"),
                         ui.input_checkbox("enable_grade_restriction", "Enable Grade Restriction", value=has_grade_restriction),
                         ui.input_select("restrict_grade_item", "Grade Item", choices=grade_items_map, selected=existing_grade_item, width="100%"),
                         ui.input_numeric("restrict_grade_min", "Min %", value=existing_grade_min if existing_grade_min else 50, min=0, max=100),
                         ui.input_numeric("restrict_grade_max", "Max %", value=existing_grade_max, min=0, max=100)
                    ),
                    ui.accordion_panel("Date Access",
                         ui.p("Prevent access until (or from) a specified date.", class_="small text-muted"),
                         ui.input_checkbox("enable_date_restriction", "Enable Date Restriction", value=has_date_restriction),
                         ui.input_date("restrict_date_val", "Date", value=existing_date_val),
                         ui.input_select("restrict_date_direction", "Direction", choices={">=": "From (>=)", "<": "Until (<)"}, selected=existing_date_dir),
                         ui.input_text("restrict_time_val", "Time (HH:MM)", value=existing_time_val)
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

    # Auto-enable restriction checkboxes when user changes values
    @reactive.Effect
    @reactive.event(input.restrict_group_id)
    def auto_enable_group():
        """Auto-enable group restriction when user selects a group"""
        if input.restrict_group_id():
            ui.update_checkbox("enable_group_restriction", value=True)
    
    @reactive.Effect
    @reactive.event(input.restrict_date_val)
    def auto_enable_date():
        """Auto-enable date restriction when user picks a date"""
        if input.restrict_date_val():
            ui.update_checkbox("enable_date_restriction", value=True)
    
    @reactive.Effect
    @reactive.event(input.restrict_grade_item)
    def auto_enable_grade():
        """Auto-enable grade restriction when user selects a grade item"""
        if input.restrict_grade_item():
            ui.update_checkbox("enable_grade_restriction", value=True)
    
    @reactive.Effect
    @reactive.event(input.restrict_completion_item)
    def auto_enable_completion():
        """Auto-enable completion restriction when user selects an activity"""
        if input.restrict_completion_item():
            ui.update_checkbox("enable_completion_restriction", value=True)

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

    # NOTE: existing_restriction_warning() output function remains in main shiny_app.py
    # because it requires @output and @render.ui decorators from Shiny's session context


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

    # Return reactive values needed by main file's @output function
    return current_restriction_json, current_grade_items_map
