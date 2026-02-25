"""
Import handlers for Shiny app.

Handles the course content import modal: opening, source course selection,
module selection, and execution.
"""
from shiny import reactive, ui
from core.auth import setup_session
from core.importer import (
    get_importable_courses,
    search_importable_courses,
    fetch_importable_modules,
    import_course_content,
)
import logging

logger = logging.getLogger(__name__)


def register_import_handlers(
    input,
    user_session_id,
    topics_list,
    trigger_background_refresh,
    do_background_refresh
):
    """
    Register import modal handlers.
    
    Args:
        input: Shiny input object
        user_session_id: reactive.Value for session ID
        topics_list: reactive.Value for topics data
        trigger_background_refresh: Function to trigger async topic refresh
        do_background_refresh: Function to sync refresh topics
    """
    # Cached importable courses
    import_courses_list = reactive.Value([])
    import_in_progress = reactive.Value(False)
    # Wizard state saved between the two modal steps
    import_wizard_state = reactive.Value(None)
    import_modules_list = reactive.Value([])
    import_source_id = reactive.Value("")
    
    @reactive.Effect
    @reactive.event(input.act_import)
    def on_open_import_modal():
        """Open import modal and fetch available source courses"""
        cid = input.course_id()
        if not cid:
            ui.notification_show("Please select a course first", type="warning")
            return
        
        ui.notification_show("Loading importable courses...", duration=2)
        
        s = setup_session(user_session_id())
        courses = get_importable_courses(s, cid)
        import_courses_list.set(courses)
        
        if not courses:
            ui.notification_show("No importable courses found. Try searching.", type="warning")
        
        # Build modal with course list
        course_choices = {"": "-- Select source course --"}
        for c in courses:
            label = f"{c['shortname']} — {c['fullname']}" if c['shortname'] != c['fullname'] else c['fullname']
            course_choices[c['id']] = label
        
        modal = ui.modal(
            ui.h4("Import Course Content", class_="mb-3"),
            ui.p(
                "Import activities and resources from another course into the current course.",
                class_="text-muted mb-3"
            ),
            ui.input_select(
                "import_source_course",
                "Source course:",
                choices=course_choices,
                width="100%"
            ),
            ui.hr(),
            ui.p("Or search for a course:", class_="text-muted mb-2"),
            ui.div(
                ui.input_text("import_search_text", None, placeholder="Search courses...", width="250px"),
                ui.input_action_button("import_search_btn", "Search", class_="btn-sm btn-secondary"),
                class_="d-flex gap-2 align-items-end mb-3"
            ),
            ui.hr(),
            ui.div(
                ui.p("⚠️ This will add content to the current course. It does not delete existing content.",
                     class_="text-warning small"),
                class_="mb-2"
            ),
            title="Import Course Content",
            easy_close=True,
            footer=ui.div(
                ui.input_action_button("import_next_btn", "Next →", class_="btn-primary"),
                ui.modal_button("Cancel", class_="btn-secondary ms-2"),
                class_="d-flex"
            )
        )
        ui.modal_show(modal)
    
    @reactive.Effect
    @reactive.event(input.import_search_btn)
    def on_import_search():
        """Search for courses to import from"""
        search_text = input.import_search_text()
        if not search_text or not search_text.strip():
            ui.notification_show("Please enter a search term", type="warning")
            return
        
        cid = input.course_id()
        if not cid:
            return
        
        ui.notification_show(f"Searching for '{search_text}'...", duration=2)
        
        s = setup_session(user_session_id())
        courses = search_importable_courses(s, cid, search_text.strip())
        
        if courses:
            import_courses_list.set(courses)
            # Update the dropdown
            course_choices = {"": "-- Select source course --"}
            for c in courses:
                label = f"{c['shortname']} — {c['fullname']}" if c['shortname'] != c['fullname'] else c['fullname']
                course_choices[c['id']] = label
            ui.update_select("import_source_course", choices=course_choices)
            ui.notification_show(f"Found {len(courses)} course(s)", type="message", duration=2)
        else:
            ui.notification_show("No courses found", type="warning")
    
    @reactive.Effect
    @reactive.event(input.import_next_btn)
    def on_import_next():
        """Fetch importable modules and show module selection modal"""
        source_id = input.import_source_course()
        if not source_id:
            ui.notification_show("Please select a source course", type="warning")
            return
        
        cid = input.course_id()
        if not cid:
            return
        
        # Save selected source for the execute step
        import_source_id.set(source_id)
        
        # Close the course‐selection modal
        ui.modal_remove()
        
        # Get source course name for notifications
        courses = import_courses_list()
        source_name = next(
            (f"{c['shortname']}" for c in courses if c['id'] == source_id),
            f"Course {source_id}"
        )
        
        ui.notification_show(
            f"Fetching modules from {source_name}… This may take a moment.",
            type="message", duration=5
        )
        
        try:
            s = setup_session(user_session_id())
            
            with ui.Progress(min=0, max=2) as p:
                p.set(message=f"Loading modules from {source_name}...")
                
                def progress_cb(step, total, msg):
                    p.set(step, message=msg)
                
                success, modules_or_error, wizard_state = fetch_importable_modules(
                    s, source_id, cid, progress_callback=progress_cb
                )
            
            if not success:
                ui.notification_show(f"❌ {modules_or_error}", type="error", duration=10)
                return
            
            # Save wizard state and modules
            import_wizard_state.set(wizard_state)
            import_modules_list.set(modules_or_error)
            
            modules = modules_or_error
            sections = [m for m in modules if m['type'] == 'section']
            activities = [m for m in modules if m['type'] == 'activity']
            
            # Group activities by their parent section
            activities_by_section = {}
            for m in activities:
                parent = m.get('parent_section')
                if parent not in activities_by_section:
                    activities_by_section[parent] = []
                activities_by_section[parent].append(m)
            
            # Build the module selection modal with hierarchy
            modal_content = [
                ui.h4("Select Modules to Import", class_="mb-3"),
                ui.p(
                    f"Source: {source_name}  •  "
                    f"{len(sections)} section(s), {len(activities)} activity/activities",
                    class_="text-muted mb-2"
                ),
                ui.p(
                    "💡 Selecting a section automatically includes all its activities.",
                    class_="text-info small mb-3"
                ),
                # Select / Deselect all buttons
                ui.div(
                    ui.input_action_button("import_select_all", "Select All",
                                            class_="btn-sm btn-outline-primary me-2"),
                    ui.input_action_button("import_deselect_all", "Deselect All",
                                            class_="btn-sm btn-outline-secondary"),
                    class_="mb-3"
                ),
            ]
            
            # Render sections with their child activities grouped together
            for sec in sections:
                # Section checkbox
                modal_content.append(
                    ui.div(
                        ui.input_checkbox(
                            f"imp_mod_{sec['field_key']}",
                            ui.strong(f"📁 {sec['name']}"),
                            value=sec['checked']
                        ),
                        class_="ms-1 mt-2"
                    )
                )
                # Activities under this section
                child_activities = activities_by_section.get(sec['field_key'], [])
                for act in child_activities:
                    modal_content.append(
                        ui.div(
                            ui.input_checkbox(
                                f"imp_mod_{act['field_key']}",
                                f"📝 {act['name']}",
                                value=act['checked']
                            ),
                            class_="ms-4"
                        )
                    )
            
            # Activities without a parent section (if any)
            orphan_activities = activities_by_section.get(None, [])
            if orphan_activities:
                modal_content.append(ui.h6("📝 Other Activities", class_="mt-3 mb-1"))
                for act in orphan_activities:
                    modal_content.append(
                        ui.div(
                            ui.input_checkbox(
                                f"imp_mod_{act['field_key']}",
                                act['name'],
                                value=act['checked']
                            ),
                            class_="ms-3"
                        )
                    )
            
            modal_content.append(ui.hr())
            modal_content.append(
                ui.div(
                    ui.p("⚠️ Only selected items will be imported.",
                         class_="text-warning small"),
                    class_="mb-2"
                )
            )
            
            # Wrap in a scrollable div for long lists
            modal = ui.modal(
                ui.div(*modal_content, style="max-height: 60vh; overflow-y: auto;"),
                title="Select Modules to Import",
                easy_close=True,
                size="l",
                footer=ui.div(
                    ui.input_action_button("import_execute_btn", "⬇️ Import Selected",
                                            class_="btn-primary"),
                    ui.modal_button("Cancel", class_="btn-secondary ms-2"),
                    class_="d-flex"
                )
            )
            ui.modal_show(modal)
            
        except Exception as e:
            logger.error(f"Error fetching modules: {e}", exc_info=True)
            ui.notification_show(f"❌ Error: {str(e)}", type="error")
    
    @reactive.Effect
    @reactive.event(input.import_select_all)
    def on_select_all():
        """Check all module checkboxes"""
        modules = import_modules_list()
        for m in modules:
            ui.update_checkbox(f"imp_mod_{m['field_key']}", value=True)
    
    @reactive.Effect
    @reactive.event(input.import_deselect_all)
    def on_deselect_all():
        """Uncheck all module checkboxes"""
        modules = import_modules_list()
        for m in modules:
            ui.update_checkbox(f"imp_mod_{m['field_key']}", value=False)
    
    @reactive.Effect
    @reactive.event(input.import_execute_btn)
    def on_import_execute():
        """Execute the import with selected modules"""
        source_id = import_source_id()
        if not source_id:
            ui.notification_show("No source course selected", type="error")
            return
        
        cid = input.course_id()
        if not cid:
            return
        
        if import_in_progress():
            ui.notification_show("Import already in progress", type="warning")
            return
        
        modules = import_modules_list()
        
        if not modules:
            ui.notification_show("Import state lost. Please start over.", type="error")
            return
        
        # Collect which modules the user selected
        selected_keys = set()
        for m in modules:
            cb_id = f"imp_mod_{m['field_key']}"
            try:
                if input[cb_id]():
                    selected_keys.add(m['field_key'])
            except Exception:
                # If checkbox not found, skip it
                pass
        
        # Auto-include child activities for any selected section
        selected_sections = {k for k in selected_keys
                             if k.startswith('setting_section_')}
        if selected_sections:
            for m in modules:
                if (m['type'] == 'activity' and
                    m.get('parent_section') in selected_sections):
                    selected_keys.add(m['field_key'])
            
            logger.info(f"Auto-included child activities for {len(selected_sections)} "
                         f"selected section(s). Total selected: {len(selected_keys)}")
        
        if not selected_keys:
            ui.notification_show("No modules selected. Please select at least one.", type="warning")
            return
        
        import_in_progress.set(True)
        ui.modal_remove()
        
        # Get source course name for notifications
        courses = import_courses_list()
        source_name = next(
            (f"{c['shortname']}" for c in courses if c['id'] == source_id),
            f"Course {source_id}"
        )
        
        total_modules = len(modules)
        selected_count = len(selected_keys)
        
        try:
            s = setup_session(user_session_id())
            
            with ui.Progress(min=0, max=4) as p:
                p.set(message=f"Importing {selected_count}/{total_modules} modules from {source_name}...")
                
                def progress_cb(step, total, msg):
                    p.set(step, message=msg)
                
                success, message = import_course_content(
                    s, source_id, cid,
                    selected_modules=list(selected_keys),
                    progress_callback=progress_cb
                )
            
            if success:
                ui.notification_show(
                    f"✅ {message} ({selected_count} module(s) imported)",
                    type="message", duration=5
                )
                # Refresh topics to show newly imported content
                try:
                    do_background_refresh(cid)
                    ui.notification_show("Topics refreshed with imported content", type="message", duration=3)
                except Exception as e:
                    logger.error(f"Error refreshing after import: {e}")
                    ui.notification_show("Import done. Click refresh to see changes.", type="message")
            else:
                ui.notification_show(f"❌ {message}", type="error", duration=10)
        except Exception as e:
            logger.error(f"Import error: {e}", exc_info=True)
            ui.notification_show(f"❌ Import error: {str(e)}", type="error")
        finally:
            import_in_progress.set(False)
            # Clear wizard state
            import_wizard_state.set(None)
            import_modules_list.set([])

