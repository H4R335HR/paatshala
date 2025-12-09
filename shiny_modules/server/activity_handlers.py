"""
Activity handlers for Shiny app.

Handles activity modal: open, close, move, reorder, duplicate, delete, rename, visibility.
"""
from shiny import reactive, ui
from core.auth import setup_session
from core.api import (
    get_topics, move_activity_to_section, duplicate_activity, 
    reorder_activity_within_section, delete_activity, rename_activity,
    get_fresh_sesskey, toggle_activity_visibility
)
from core.persistence import save_cache
import json
import logging

logger = logging.getLogger(__name__)


def register_activity_handlers(
    input,
    topics_list,
    user_session_id,
    ensure_edit_mode
):
    """
    Register activity modal handlers.
    
    Args:
        input: Shiny input object
        topics_list: reactive.Value for topics data
        user_session_id: reactive.Value for session ID
        ensure_edit_mode: Function to ensure edit mode is enabled
    """
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

