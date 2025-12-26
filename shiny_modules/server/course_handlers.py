"""
Course data handlers for Shiny app.

Handles course data loading, caching, and background refresh.
"""
from shiny import reactive, ui
from core.auth import setup_session
from core.api import get_courses, get_topics, get_course_groups, get_course_grade_items
from core.persistence import save_cache, load_cache, save_last_session, load_last_session
import threading
from queue import Queue
import logging

logger = logging.getLogger(__name__)

# Thread-safe queue for background refresh results
refresh_queue = Queue()


def register_course_handlers(
    input,
    user_authenticated,
    user_session_id,
    topics_list,
    course_groups_cache,
    course_grade_items_cache,
    is_edit_mode_on,
    selected_indices
):
    """
    Register course data loading handlers.
    
    Args:
        input: Shiny input object
        user_authenticated: reactive.Value for auth state
        user_session_id: reactive.Value for session ID
        topics_list: reactive.Value for topics
        course_groups_cache: reactive.Value for groups cache
        course_grade_items_cache: reactive.Value for grade items cache
        is_edit_mode_on: reactive.Value for edit mode
        selected_indices: reactive.Value for selection
        
    Returns:
        tuple: (courses_data, available_courses, trigger_background_refresh, do_background_refresh)
    """
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
            
            # Restore last selected course from session
            last_session = load_last_session()
            last_course_id = last_session.get("last_course_id")
            if last_course_id:
                # Check if the saved course exists in available courses
                course_ids = [str(c['id']) for c in cached]
                if last_course_id in course_ids:
                    logger.info(f"Restoring last selected course: {last_course_id}")
                    ui.update_select("course_id", selected=last_course_id)
                else:
                    logger.info(f"Last course {last_course_id} not in available courses, skipping restore")
        else:
            # No cache - must fetch live
            logger.info("No cached courses, fetching live...")
            try:
                s = setup_session(user_session_id())
                live = get_courses(s)
                courses_data.set(live)
                save_cache("courses", live)
                
                # Restore last selected course from session
                last_session = load_last_session()
                last_course_id = last_session.get("last_course_id")
                if last_course_id:
                    course_ids = [str(c['id']) for c in live]
                    if last_course_id in course_ids:
                        logger.info(f"Restoring last selected course: {last_course_id}")
                        ui.update_select("course_id", selected=last_course_id)
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

    # Background refresh trigger
    background_refresh_trigger = reactive.Value(None)
    background_refresh_counter = reactive.Value(0)

    def trigger_background_refresh(cid):
        """Helper to trigger background refresh with counter to ensure it always fires"""
        counter = background_refresh_counter.get() + 1
        background_refresh_counter.set(counter)
        background_refresh_trigger.set((cid, counter))

    @reactive.Effect
    @reactive.event(input.course_id)
    def load_data():
        cid = input.course_id()
        if not cid: return
        
        # Save selected course to session for persistence across refreshes
        if cid and cid != "__custom__":
            save_last_session({"last_course_id": cid})
            logger.info(f"Saved last course ID: {cid}")
        
        is_edit_mode_on.set(False)
        selected_indices.set([])  # Reset selection
        
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
        trigger_background_refresh(cid)
        
        # If no cache, fetch immediately (blocking)
        if not has_cache:
            logger.info(f"No cache for course {cid}, fetching live data...")
            do_background_refresh(cid)

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

    # Return reactive values needed by @output functions in main file
    return courses_data, available_courses, trigger_background_refresh, do_background_refresh
