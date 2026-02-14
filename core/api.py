import re
import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path
import logging
import time

logger = logging.getLogger(__name__)

from .auth import setup_session, PAATSHALA_HOST, BASE
from .parser import parse_assign_view, parse_grading_table, extract_assignment_id, extract_max_grade_from_grader
from .persistence import get_config

DEFAULT_THREADS = 4

def get_fresh_sesskey(session, course_id):
    """Fetch a fresh sesskey from the course page (needed for AJAX operations)"""
    url = f"{BASE}/course/view.php?id={course_id}"
    try:
        resp = session.get(url, timeout=10)
        if resp.ok:
            # Extract sesskey from page
            match = re.search(r'"sesskey":"([^"]+)"', resp.text)
            if match:
                return match.group(1)
            # Fallback: look in logout link
            match = re.search(r'sesskey=([a-zA-Z0-9]+)', resp.text)
            if match:
                return match.group(1)
    except Exception as e:
        logger.error(f"Error getting fresh sesskey: {e}")
    return None

# Thread-local storage for sessions
thread_local = threading.local()

def get_thread_session(session_id):
    """Get or create a session for the current thread"""
    if not hasattr(thread_local, 'session'):
        thread_local.session = requests.Session()
        thread_local.session.cookies.set("MoodleSession", session_id, domain=PAATSHALA_HOST)
        thread_local.session.headers.update({'User-Agent': 'Mozilla/5.0'})
    return thread_local.session

def get_courses(session):
    """Fetch all courses using Moodle's AJAX APIs"""
    courses_dict = {}
    
    logger.info("Function get_courses called")
    try:
        logger.info("Making request to /my/ ...")
        resp = session.get(f"{BASE}/my/", timeout=15)
        logger.info(f"Response: status={resp.status_code}, url={resp.url[:80]}")
        if not resp.ok:
            return []
        
        sesskey_match = re.search(r'"sesskey":"([^"]+)"', resp.text)
        sesskey = sesskey_match.group(1) if sesskey_match else ""
        
        if sesskey:
            # API 1: Enrolled courses
            api_url = f"{BASE}/lib/ajax/service.php?sesskey={sesskey}&info=core_course_get_enrolled_courses_by_timeline_classification"
            payload = [{
                "index": 0,
                "methodname": "core_course_get_enrolled_courses_by_timeline_classification",
                "args": {
                    "offset": 0, "limit": 0, "classification": "all",
                    "sort": "fullname", "customfieldname": "", "customfieldvalue": ""
                }
            }]
            
            api_resp = session.post(api_url, json=payload, timeout=15)
            if api_resp.ok:
                try:
                    data = api_resp.json()
                    if data and len(data) > 0 and not data[0].get("error"):
                        courses_data = data[0].get("data", {}).get("courses", [])
                        for course in courses_data:
                            course_id = str(course.get("id", ""))
                            if course_id and course_id not in courses_dict:
                                courses_dict[course_id] = {
                                    'id': course_id,
                                    'name': course.get("fullname", ""),
                                    'category': course.get("coursecategory", ""),
                                    'starred': course.get("isfavourite", False)
                                }
                except:
                    pass
            
            # API 2: Recent courses
            api_url2 = f"{BASE}/lib/ajax/service.php?sesskey={sesskey}&info=core_course_get_recent_courses"
            payload2 = [{
                "index": 0,
                "methodname": "core_course_get_recent_courses",
                "args": {"userid": 0, "limit": 0, "offset": 0, "sort": "fullname"}
            }]
            
            api_resp2 = session.post(api_url2, json=payload2, timeout=15)
            if api_resp2.ok:
                try:
                    data2 = api_resp2.json()
                    if data2 and len(data2) > 0 and not data2[0].get("error"):
                        courses_data2 = data2[0].get("data", [])
                        for course in courses_data2:
                            course_id = str(course.get("id", ""))
                            if course_id and course_id not in courses_dict:
                                courses_dict[course_id] = {
                                    'id': course_id,
                                    'name': course.get("fullname", ""),
                                    'category': course.get("coursecategory", ""),
                                    'starred': course.get("isfavourite", False)
                                }
                except:
                    pass
        
        # Fallback: Parse navigation
        if not courses_dict:
            soup = BeautifulSoup(resp.text, "html.parser")
            course_links = soup.find_all("a", href=lambda x: x and "/course/view.php?id=" in x)
            
            for link in course_links:
                href = link.get("href", "")
                if "?id=" in href:
                    course_id = href.split("?id=")[-1].split("&")[0]
                    if course_id.isdigit() and course_id not in courses_dict:
                        course_name = link.get_text(strip=True)
                        if course_name:
                            courses_dict[course_id] = {
                                'id': course_id,
                                'name': course_name,
                                'category': '',
                                'starred': False
                            }
        
        courses = list(courses_dict.values())
        courses.sort(key=lambda x: (not x['starred'], x['name'].lower()))
        return courses
        
    except Exception:
        return []

def get_tasks(session, course_id):
    """Get list of tasks (assignments) from course page"""
    url = f"{BASE}/course/view.php?id={course_id}"
    resp = session.get(url)
    if not resp.ok:
        return []
    
    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.find_all("li", class_=lambda c: c and "modtype_assign" in c)
    
    tasks = []
    for item in items:
        link = item.find("a", href=re.compile(r"mod/assign/view\.php\?id=\d+"))
        if not link:
            link = item.find("a", href=re.compile(r"/mod/assign/"))
        if link:
            name = link.get_text(strip=True)
            href = link.get("href", "")
            m = re.search(r"[?&]id=(\d+)", href)
            module_id = m.group(1) if m else ""
            if href.startswith("/"):
                href = BASE + href
            elif not href.startswith("http"):
                href = BASE + "/" + href.lstrip("/")
            tasks.append((name, module_id, href))
    
    return tasks

def get_topics(session, course_id, max_retries=3):
    """Get all topics (sections) from course page with robust ID extraction"""
    logger.info(f"Fetching topics for course {course_id}")
    base_url = f"{BASE}/course/view.php"
    params = {"id": course_id}
    
    # Retry loop: Attempt 1 (Normal), Attempt 2 (Force Edit Mode)
    for attempt in range(2):
        # On second attempt, force edit mode
        if attempt == 1:
            params["edit"] = "on"
            # If we found a sesskey in the first attempt (even if IDs were missing), use it
            # But usually sesskey is in the page we just fetched. 
            # We'll rely on the fact that 'edit=on' usually works or redirects to a link with sesskey
        
        # Retry with backoff for connection errors
        for retry in range(max_retries):
            try:
                resp = session.get(base_url, params=params, timeout=30)
                if not resp.ok:
                    logger.warning(f"get_topics: Response not OK: {resp.status_code}")
                    return []
                break  # Success, exit retry loop
            except Exception as e:
                logger.warning(f"get_topics: Attempt {retry+1}/{max_retries} failed: {e}")
                if retry < max_retries - 1:
                    wait_time = (2 ** retry)  # 1s, 2s, 4s
                    logger.info(f"Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"get_topics: All retries exhausted")
                    return []
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Standard Moodle sections
        # Use a more flexible search since classes can be "section main clearfix..."
        sections = soup.find_all("li", class_=lambda c: c and "section" in c.split() and "main" in c.split())
        if not sections:
            # Fallback for other themes (e.g. tiles, grid) or if 'main' is missing
            sections = soup.find_all("li", class_=lambda c: c and "section" in c.split())
        
        # Extract sesskey from the page (needed for actions)
        sesskey = ""
        logout_link = soup.find("a", href=lambda h: h and "sesskey=" in h)
        if logout_link:
            m = re.search(r"sesskey=([^&]+)", logout_link["href"])
            if m:
                sesskey = m.group(1)
                
        # If forcing edit mode, we might need to append sesskey to the params for next time?
        # Actually, if we are here, we just parsed the page.
        
        topics = []
        missing_ids = False
        
        for section in sections:
            section_id = section.get("id", "").replace("section-", "")
            
            # Try to find the name
            name = "Untitled Section"
            name_node = section.find(class_="sectionname")
            if not name_node:
                name_node = section.find(class_="section-title")
            
            if name_node:
                name = name_node.get_text(strip=True)
            else:
                # Try aria-label on the section itself
                label = section.get("aria-label")
                if label:
                    name = label
            
            # Count activities and extract details
            activities = section.find_all("li", class_=lambda c: c and "activity" in c)
            activity_count = len(activities)
            
            # Extract activity details
            activity_list = []
            for act in activities:
                # Get activity ID
                act_id = act.get("id", "").replace("module-", "")
                
                # Get activity name
                act_name = ""
                act_instance = act.find(class_="activityinstance") or act.find(class_="activity-instance")
                if act_instance:
                    act_name_el = act_instance.find("span", class_="instancename") or act_instance.find("a")
                    if act_name_el:
                        act_name = act_name_el.get_text(strip=True)
                        # Remove trailing type suffixes (with or without space)
                        # e.g. "Pre-Learning DiaryURL" -> "Pre-Learning Diary"
                        # e.g. "Practice Quiz 1 Quiz" -> "Practice Quiz 1"
                        type_suffixes = r'(Quiz|Assignment|File|URL|Forum|Page|Folder|Book|Lesson|SCORM|Certificate|Label)$'
                        act_name = re.sub(r'\s*' + type_suffixes, '', act_name, flags=re.IGNORECASE)
                
                # Get activity type from class
                act_type = ""
                act_classes = act.get("class", [])
                for cls in act_classes:
                    if cls.startswith("modtype_"):
                        act_type = cls.replace("modtype_", "")
                        break
                
                # Get activity URL
                act_url = ""
                act_link = act.find("a", href=lambda h: h and "/mod/" in h)
                if act_link:
                    act_url = act_link.get("href", "")
                
                # Get visibility - check for "ishidden" class in availabilityinfo div
                act_visible = act.find("div", class_=lambda c: c and "ishidden" in c) is None
                
                if act_id:
                    activity_list.append({
                        "id": act_id,
                        "name": act_name,
                        "type": act_type,
                        "url": act_url,
                        "visible": act_visible
                    })
            
            # Extract summary text if available
            summary = ""
            summary_node = section.find(class_="summary")
            if summary_node:
                summary = summary_node.get_text(" ", strip=True)[:100] + "..." if len(summary_node.get_text(strip=True)) > 100 else summary_node.get_text(" ", strip=True)
            
            # Extract restriction summary (look for availability info at SECTION level only)
            # We need to exclude availability info that belongs to activities inside the section
            restriction_summary = ""
            for availability_info in section.find_all(class_=lambda c: c and ("availabilityinfo" in c or "availability-info" in c)):
                # Check if this availability info is inside an activity (nested) - if so, skip it
                parent_activity = availability_info.find_parent(class_=lambda c: c and "activity" in c)
                if parent_activity:
                    continue  # This belongs to an activity, not the section
                
                # This is section-level availability info
                restriction_summary = availability_info.get_text(" ", strip=True)[:150]
                # Clean up common phrases
                restriction_summary = restriction_summary.replace("Not available unless:", "").strip()
                break  # Found section-level restriction, stop looking
    
            # Find the DB ID for editing (often in the edit link or inplace editable attributes)
            db_id = ""
            
            # 1. Try inplace editable attributes (most robust for section name)
            # <span class="inplaceeditable" ... data-itemid="10013" ...>
            inplace_span = section.find("span", class_="inplaceeditable", attrs={"data-itemtype": "sectionname"})
            if inplace_span:
                db_id = inplace_span.get("data-itemid")
                
            # 2. Fallback: Search for editsection.php link (Broader regex)
            if not db_id:
                edit_link = section.find("a", href=lambda h: h and "editsection.php" in h and "delete" not in h)
                if edit_link:
                    m = re.search(r"[?&]id=(\d+)", edit_link["href"])
                    if m:
                        db_id = m.group(1)
            
            # 3. Last resort: Regex search in section HTML
            if not db_id:
                m = re.search(r"editsection\.php\?id=(\d+)", str(section))
                if m:
                    db_id = m.group(1)
    
            # Check visibility
            visible = True
            if "hidden" in section.get("class", []):
                visible = False
    
            # Only add if it looks like a real section (has ID or content)
            if section_id or activity_count > 0:
                topics.append({
                    "Section ID": section_id,
                    "DB ID": db_id,
                    "Topic Name": name,
                    "Activity Count": activity_count,
                    "Activities": activity_list,
                    "Summary": summary,
                    "Restriction Summary": restriction_summary,
                    "Visible": visible,
                    "Sesskey": sesskey # Include sesskey in each row for convenience
                })
                
                if not db_id:
                    missing_ids = True
                    
        # Decision Logic:
        # If we found topics but some are missing IDs (especially the last one), and this is attempt 0,
        # then we should retry with Edit Mode.
        if attempt == 0 and topics and missing_ids:
            # Check if we have a "Turn editing on" link to use its specific URL/sesskey
            turn_editing_on = soup.find("a", href=lambda h: h and "edit=on" in h)
            if turn_editing_on:
                edit_href = turn_editing_on.get("href")
                if edit_href:
                    # Use this full URL for the next attempt
                    base_url = edit_href
                    params = {} # URL already has params
            elif sesskey:
                 # Append sesskey to params for next attempt if we constructed it manually
                 params["sesskey"] = sesskey
            
            continue # Try again
            
        # If we are here, either we have all IDs, or we are on attempt 1 (gave up), or no topics found.
        return topics
    
    return []

def add_topic(session, course_id, sesskey, count=1):
    """Add a new topic to the course"""
    # We need to find the current number of sections to know where to insert?
    # Actually changenumsections.php usually appends.
    # We might need to find the 'insertsection' param which is usually 0 for append?
    # Or use course/edit.php?action=addsection
    
    # Based on inspection: course/changenumsections.php?courseid=237&insertsection=0&sesskey=...
    url = f"{BASE}/course/changenumsections.php"
    params = {
        "courseid": course_id,
        "insertsection": 0, # 0 usually means append
        "sesskey": sesskey,
        "sectionreturn": 0,
        "numsections": count
    }
    resp = session.get(url, params=params)
    return resp.ok

def delete_topic(session, db_id, sesskey):
    """Delete a topic"""
    logger.info(f"Deleting topic {db_id}")
    # course/editsection.php?id=5431&sr&delete=1&sesskey=...
    url = f"{BASE}/course/editsection.php"
    params = {
        "id": db_id,
        "sr": "",
        "delete": 1,
        "sesskey": sesskey
    }
    resp = session.get(url, params=params)
    return resp.ok

def enable_edit_mode(session, course_id, sesskey):
    """
    Enable edit mode for the course using POST request.
    """
    url = f"{BASE}/course/view.php"
    data = {
        "id": course_id,
        "sesskey": sesskey,
        "edit": "on"
    }
    resp = session.post(url, data=data)
    return resp.ok

def move_topic(session, section_number, sesskey, course_id, target_section_number=None, direction=None):
    """
    Move a topic using the REST API.
    
    Args:
        session: Requests session
        section_number: The Section Number (e.g. 68) to move. NOT the DB ID.
        sesskey: The session key
        course_id: The course ID
        target_section_number: The Section Number to move BEFORE (swapping/reordering).
        direction: (Deprecated) 'up' or 'down' - kept for backward compatibility.
    """
    # New API based on Burp capture:
    # POST /course/rest.php
    # sesskey=...&courseId=345&class=section&field=move&id=68&value=66
    # Note: 'id' and 'value' here refer to the visible Section Numbers (1, 2, 3...), not the internal DB IDs.
    
    url = f"{BASE}/course/rest.php"
    
    if target_section_number is not None:
        logger.info(f"Moving section {section_number} before {target_section_number}")
        payload = {
            "class": "section",
            "field": "move",
            "id": section_number,
            "value": target_section_number,
            "courseId": course_id,
            "sesskey": sesskey
        }
        
        resp = session.post(url, data=payload)
        return resp.ok
        
    # Fallback to old method if no target_id provided (legacy support)
    # Note: The old method used DB ID. This might be confusing if we renamed the param.
    # But for now, we assume if direction is used, the caller might be using DB ID or we might need to handle it.
    # However, since we are moving to the new API, we focus on that.
    if direction:
        # Warning: The old API expected DB ID. If section_number is passed, this might fail.
        # We'll assume for legacy calls, the caller knows what they are doing or we should deprecate this path.
        url = f"{BASE}/course/editsection.php"
        params = {
            "id": section_number, # This might need to be DB ID for this specific endpoint
            "sesskey": sesskey
        }
        
        if direction == "up":
            params["moveup"] = 1
        else:
            params["movedown"] = 1
            
        resp = session.get(url, params=params)
        return resp.ok
        
    return False

def move_activity_to_section(session, course_id, activity_id, section_id, sesskey, before_id=None):
    """
    Move an activity (course module) to a different section.
    
    Args:
        session: Requests session
        course_id: The course ID
        activity_id: The course module ID (from module-{id} in HTML)
        section_id: The target section ID (the visible section number, e.g. 36)
        sesskey: Session key
        before_id: Optional - place the activity before this activity ID
    
    Returns:
        bool: Success status
    """
    # API captured from Burp:
    # POST /course/rest.php
    # sesskey=...&courseId=345&class=resource&field=move&id=32008&sectionId=36&beforeId=22924
    
    url = f"{BASE}/course/rest.php"
    payload = {
        "sesskey": sesskey,
        "courseId": course_id,
        "class": "resource",
        "field": "move",
        "id": activity_id,
        "sectionId": section_id
    }
    
    if before_id:
        payload["beforeId"] = before_id
    
    logger.info(f"Moving activity {activity_id} to section {section_id}")
    resp = session.post(url, data=payload)
    return resp.ok

def duplicate_activity(session, activity_id, sesskey):
    """
    Duplicate an activity (course module).
    
    Args:
        session: Requests session
        activity_id: The course module ID to duplicate
        sesskey: Session key
    
    Returns:
        bool: Success status
    """
    # API captured from Burp:
    # POST /lib/ajax/service.php?sesskey=...&info=core_course_edit_module
    # [{"index":0,"methodname":"core_course_edit_module","args":{"id":23222,"action":"duplicate","sectionreturn":"0"}}]
    
    url = f"{BASE}/lib/ajax/service.php"
    params = {
        "sesskey": sesskey,
        "info": "core_course_edit_module"
    }
    
    payload = [{
        "index": 0,
        "methodname": "core_course_edit_module",
        "args": {
            "id": int(activity_id),
            "action": "duplicate",
            "sectionreturn": "0"
        }
    }]
    
    logger.info(f"Duplicating activity {activity_id}")
    resp = session.post(url, params=params, json=payload)
    
    if resp.ok:
        try:
            data = resp.json()
            logger.info(f"Duplicate response: {str(data)[:200]}")
            if isinstance(data, list) and data:
                if data[0].get("error"):
                    logger.error(f"Duplicate error: {data[0].get('exception', {}).get('message', 'Unknown')}")
                    return False
                return True
        except Exception as e:
            logger.error(f"Error parsing duplicate response: {e}")
    else:
        logger.error(f"Duplicate request failed: {resp.status_code}")
    return False

def reorder_activity_within_section(session, course_id, activity_id, section_id, before_id, sesskey):
    """
    Reorder an activity within the same section by placing it before another activity.
    This is a convenience wrapper around move_activity_to_section.
    
    Args:
        session: Requests session
        course_id: The course ID
        activity_id: The activity to move
        section_id: The section ID (stays the same)
        before_id: The activity ID to place before (or None to place at end)
        sesskey: Session key
    
    Returns:
        bool: Success status
    """
    return move_activity_to_section(session, course_id, activity_id, section_id, sesskey, before_id)

def delete_activity(session, activity_id, sesskey):
    """
    Delete an activity (course module).
    
    Args:
        session: Requests session
        activity_id: The course module ID to delete
        sesskey: Session key
    
    Returns:
        bool: Success status
    """
    # Uses the same API as duplicate but with action=delete
    # POST /lib/ajax/service.php?sesskey=...&info=core_course_edit_module
    # [{"index":0,"methodname":"core_course_edit_module","args":{"id":..., "action":"delete"}}]
    
    url = f"{BASE}/lib/ajax/service.php"
    params = {
        "sesskey": sesskey,
        "info": "core_course_edit_module"
    }
    
    payload = [{
        "index": 0,
        "methodname": "core_course_edit_module",
        "args": {
            "id": int(activity_id),
            "action": "delete",
            "sectionreturn": "0"
        }
    }]
    
    logger.info(f"Deleting activity {activity_id}")
    resp = session.post(url, params=params, json=payload)
    
    if resp.ok:
        try:
            data = resp.json()
            if isinstance(data, list) and data and not data[0].get("error"):
                return True
        except:
            pass
    return False

def toggle_topic_visibility(session, course_id, section_id, sesskey, hide=True):
    """Hide or Show a topic"""
    # course/view.php?id=237&sesskey=...&hide=59
    url = f"{BASE}/course/view.php"
    params = {
        "id": course_id,
        "sesskey": sesskey
    }
    if hide:
        params["hide"] = section_id # Use section_id (order)
    else:
        params["show"] = section_id # Use section_id (order)
        
    resp = session.get(url, params=params)
    return resp.ok

def toggle_activity_visibility(session, activity_id, sesskey, hide=True):
    """
    Toggle visibility of an activity (course module).

    Args:
        session: Requests session
        activity_id: The course module ID to show/hide
        sesskey: Session key
        hide: True to hide, False to show

    Returns:
        bool: Success status
    """
    # API captured from Burp:
    # POST /lib/ajax/service.php?sesskey=C1cd8L2Nmn&info=core_course_edit_module
    # [{"index":0,"methodname":"core_course_edit_module","args":{"id":32032,"action":"hide","sectionreturn":0}}]
    # For unhide, action is "show"

    url = f"{BASE}/lib/ajax/service.php"
    params = {
        "sesskey": sesskey,
        "info": "core_course_edit_module"
    }

    action = "hide" if hide else "show"
    payload = [{
        "index": 0,
        "methodname": "core_course_edit_module",
        "args": {
            "id": int(activity_id),
            "action": action,
            "sectionreturn": 0
        }
    }]

    logger.info(f"{'Hiding' if hide else 'Showing'} activity {activity_id}")
    resp = session.post(url, params=params, json=payload)

    if resp.ok:
        try:
            data = resp.json()
            logger.info(f"Toggle visibility response: {str(data)[:200]}")
            if isinstance(data, list) and data:
                if data[0].get("error"):
                    logger.error(f"Toggle visibility error: {data[0].get('exception', {}).get('message', 'Unknown')}")
                    return False
                return True
        except Exception as e:
            logger.error(f"Error parsing toggle visibility response: {e}")
    else:
        logger.error(f"Toggle visibility request failed: {resp.status_code}")
    return False

def rename_activity(session, sesskey, module_id, new_name, mod_type):
    """Rename activity using Moodle's inplace editable AJAX API"""
    logger.info(f"Renaming activity {module_id} to '{new_name}'")

    url = f"{BASE}/lib/ajax/service.php"
    params = {
        "sesskey": sesskey,
        "info": "core_update_inplace_editable"
    }

    # Component is core_course for activity names (not mod_{type})
    payload = [{
        "index": 0,
        "methodname": "core_update_inplace_editable",
        "args": {
            "itemid": str(module_id),
            "component": "core_course",
            "itemtype": "activityname",
            "value": new_name
        }
    }]

    try:
        resp = session.post(url, params=params, json=payload)
        if resp.ok:
            data = resp.json()
            logger.info(f"Rename response: {data}")
            if isinstance(data, list) and data:
                if data[0].get("error"):
                    logger.error(f"Rename error: {data[0].get('exception', {}).get('message', 'Unknown')}")
                    return False
                return True
            return False
        else:
            logger.error(f"Rename failed: {resp.status_code}")
            return False
    except Exception as e:
        logger.error(f"Error renaming activity: {e}")
        return False

def rename_topic_inplace(session, sesskey, itemid, new_name):
    """Rename topic using Moodle's inplace editable AJAX API"""
    logger.info(f"Renaming topic {itemid} to '{new_name}'")
    # POST /lib/ajax/service.php?sesskey=...&info=core_update_inplace_editable
    url = f"{BASE}/lib/ajax/service.php"
    params = {
        "sesskey": sesskey,
        "info": "core_update_inplace_editable"
    }
    
    payload = [{
        "index": 0,
        "methodname": "core_update_inplace_editable",
        "args": {
            "itemid": str(itemid),
            "component": "format_topics",
            "itemtype": "sectionname",
            "value": new_name
        }
    }]
    
    try:
        resp = session.post(url, params=params, json=payload)
        if resp.ok:
            data = resp.json()
            # Moodle returns a list of results. Check for error.
            if isinstance(data, list) and data:
                if data[0].get("error"):
                    return False
                return True
            return False # Unexpected response format
        return False
    except Exception as e:
        logger.error(f"Error renaming topic: {e}")
        print(f"Error renaming topic: {e}")
        return False

# Cache for module IDs to avoid repeated lookups
_module_id_cache = {}

def get_module_id(session, course_id, module_name='page'):
    """
    Get the module ID for a given module type using Moodle's web service API.
    
    Args:
        session: Requests session
        course_id: The course ID
        module_name: The module name (e.g., 'page', 'assign', 'quiz')
    
    Returns:
        str: Module ID or '15' as fallback
    """
    # Check cache first
    cache_key = f"{course_id}_{module_name}"
    if cache_key in _module_id_cache:
        return _module_id_cache[cache_key]
    
    try:
        # Try method 1: Use Moodle's web service to get module list
        # This is the most reliable method
        url = f"{BASE}/lib/ajax/service.php"
        params = {
            'info': 'core_course_get_course_module_info'
        }
        
        # First, try to get the list of available modules from the course
        # We'll make a request to the course page in edit mode to see available modules
        course_url = f"{BASE}/course/view.php"
        course_params = {'id': course_id}
        
        resp = session.get(course_url, params=course_params, timeout=30)
        
        if resp.ok:
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Method 1: Look for module chooser data in JavaScript
            # Moodle often includes module information in data attributes or JS
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string and 'modules' in script.string.lower():
                    # Look for module definitions in format like: {"name":"page","id":15}
                    # or similar patterns
                    match = re.search(rf'["\']name["\']\s*:\s*["\']page["\']\s*,\s*["\'](?:module)?id["\']\s*:\s*(\d+)', script.string, re.IGNORECASE)
                    if match:
                        module_id = match.group(1)
                        logger.info(f"Found module ID {module_id} for '{module_name}' in JavaScript")
                        _module_id_cache[cache_key] = module_id
                        return module_id
                    
                    # Alternative pattern: {"page":15} or similar
                    match = re.search(rf'["\']page["\']\s*:\s*(\d+)', script.string)
                    if match:
                        module_id = match.group(1)
                        logger.info(f"Found module ID {module_id} for '{module_name}' in JavaScript (pattern 2)")
                        _module_id_cache[cache_key] = module_id
                        return module_id
            
            # Method 2: Look in the activity chooser modal/data
            # Find elements with data-internal or data-modulename attributes
            module_links = soup.find_all(attrs={'data-modulename': module_name})
            if module_links:
                # Check for data-moduleid or similar
                for link in module_links:
                    if link.get('data-moduleid'):
                        module_id = link.get('data-moduleid')
                        logger.info(f"Found module ID {module_id} for '{module_name}' in data attribute")
                        _module_id_cache[cache_key] = module_id
                        return module_id
            
            # Method 3: Parse the activity chooser if it exists
            # Look for the module in the chooser
            chooser = soup.find('div', class_=re.compile(r'chooser|activity-chooser'))
            if chooser:
                page_option = chooser.find(attrs={'data-internal': re.compile(module_name)})
                if page_option:
                    # Try to extract module ID from the data-internal or href
                    data_internal = page_option.get('data-internal', '')
                    match = re.search(r'module[=/](\d+)', data_internal)
                    if match:
                        module_id = match.group(1)
                        logger.info(f"Found module ID {module_id} for '{module_name}' in chooser")
                        _module_id_cache[cache_key] = module_id
                        return module_id
            
            # Method 4: Try to find it in any modedit.php links
            all_links = soup.find_all('a', href=re.compile(r'modedit\.php'))
            for link in all_links:
                href = link.get('href', '')
                if f'add={module_name}' in href:
                    # Check if module ID is in the URL
                    match = re.search(r'[?&]module=(\d+)', href)
                    if match:
                        module_id = match.group(1)
                        logger.info(f"Found module ID {module_id} for '{module_name}' in modedit link")
                        _module_id_cache[cache_key] = module_id
                        return module_id
        
        # If all methods fail, use the default
        logger.warning(f"Could not find module ID for '{module_name}', using default 15")
        _module_id_cache[cache_key] = '15'
        return '15'
        
    except Exception as e:
        logger.error(f"Error getting module ID: {e}")
        _module_id_cache[cache_key] = '15'
        return '15'

def add_page_with_embed(session, course_id, section_id, sesskey, page_name, embed_html, visible=True, description=None):

    """
    Add a new page resource with embedded content to a course section.
    Fetches the actual form first to ensure all required fields are included.
    
    Args:
        session: Requests session
        course_id: The course ID
        section_id: The section ID (visible section number)
        sesskey: Session key
        page_name: Display name for the page
        embed_html: HTML content to embed (e.g., iframe code)
        visible: Whether the page should be visible (default: True)
        description: Optional description text for the page intro (defaults to page_name)
    
    Returns:
        bool: Success status
    """
    logger.info(f"Adding page '{page_name}' to course {course_id}, section {section_id}")
    
    # Step 1: GET the form to extract all required fields
    get_url = f"{BASE}/course/modedit.php"
    get_params = {
        'add': 'page',
        'course': course_id,
        'section': section_id,
        'return': 0,
        'sr': 0
    }
    
    try:
        logger.info("Fetching page creation form...")
        get_resp = session.get(get_url, params=get_params, timeout=30)
        
        if not get_resp.ok:
            logger.error(f"Failed to fetch form: HTTP {get_resp.status_code}")
            return False
        
        # Parse the form
        soup = BeautifulSoup(get_resp.text, 'html.parser')
        form = soup.find('form', class_='mform')
        
        if not form:
            logger.error("Could not find mform in response")
            return False
        
        # Extract all form fields
        form_data = {}
        
        for input_el in form.find_all(['input', 'select', 'textarea']):
            name = input_el.get('name')
            if not name:
                continue
            
            # Skip submit buttons
            input_type = input_el.get('type', '').lower()
            if input_type in {'submit', 'button', 'image', 'reset'}:
                continue
            
            if input_el.name == 'select':
                # Get first option value as default
                first_option = input_el.find('option')
                form_data[name] = first_option.get('value', '') if first_option else ''
            elif input_el.name == 'textarea':
                form_data[name] = input_el.get_text()
            elif input_type == 'checkbox':
                # Only include if checked by default
                if input_el.has_attr('checked'):
                    form_data[name] = input_el.get('value', '1')
            elif input_type == 'radio':
                if input_el.has_attr('checked'):
                    form_data[name] = input_el.get('value', '')
            else:
                form_data[name] = input_el.get('value', '')
        
        logger.info(f"Extracted {len(form_data)} form fields")
        
        # Step 2: Override with our specific values
        import random
        intro_itemid = random.randint(100000000, 999999999)
        page_itemid = random.randint(100000000, 999999999)
        
        # Use provided description or default to page name
        intro_text = description if description else page_name
        if not intro_text.startswith('<'):
            intro_text = f'<p>{intro_text}</p>'
        
        # Update the fields we care about
        form_data.update({
            'name': page_name,
            'page[text]': embed_html,
            'page[format]': '1',
            'page[itemid]': str(page_itemid),
            'introeditor[text]': intro_text,  # Fixed: was empty, now includes description
            'introeditor[format]': '1',
            'introeditor[itemid]': str(intro_itemid),
            'visible': '1' if visible else '0',
            'sesskey': sesskey,
            'submitbutton2': 'Save and return to course'
        })
        
        # Step 3: POST the form
        post_url = f"{BASE}/course/modedit.php"
        
        logger.info("Submitting page creation form...")
        resp = session.post(post_url, data=form_data, timeout=30, allow_redirects=True)
        
        # Check for successful response (including 303 redirects)
        if resp.ok or resp.status_code == 303:
            final_url = resp.url
            logger.info(f"Page add response: status={resp.status_code}, final_url={final_url}")
            
            # Success: Redirected to course view page (this is the expected behavior)
            if 'course/view.php' in final_url:
                logger.info(f"Successfully added page '{page_name}' (redirected to course view)")
                return True
            
            # Success: Redirected to the new page's edit form
            elif 'course/modedit.php' in final_url and 'update=' in final_url:
                logger.info(f"Successfully added page '{page_name}' (at edit page)")
                return True
            
            # Still on modedit.php - check for errors
            elif 'course/modedit.php' in final_url:
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Save response for debugging
                try:
                    from pathlib import Path
                    debug_dir = Path("output") / "debug"
                    debug_dir.mkdir(parents=True, exist_ok=True)
                    debug_file = debug_dir / "page_add_response.html"
                    with open(debug_file, 'w', encoding='utf-8') as f:
                        f.write(resp.text)
                    logger.info(f"Saved response HTML to {debug_file}")
                except Exception as e:
                    logger.warning(f"Could not save debug HTML: {e}")
                
                # Look for errors
                errors = []
                error_elements = soup.find_all(class_=re.compile(r'error|alert-danger|alert-error', re.IGNORECASE))
                if error_elements:
                    errors.extend([e.get_text(strip=True) for e in error_elements if e.get_text(strip=True)])
                
                if errors:
                    error_text = ' | '.join(errors)
                    logger.error(f"Page add failed with validation errors: {error_text}")
                    return False
                else:
                    logger.warning(f"Stayed on modedit.php without obvious errors - page may not have been created")
                    logger.warning(f"Check output/debug/page_add_response.html for details")
                    return False
            else:
                logger.warning(f"Unexpected redirect to {final_url}")
                return False
        else:
            logger.error(f"Failed to add page: HTTP {resp.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Error adding page: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def fetch_task_details(session_id, name, mid, url):
    """Fetch task details using thread-local session"""
    s = get_thread_session(session_id)
    
    try:
        resp = s.get(url, timeout=30)
        if not resp.ok:
            return name, mid, url, {}
        
        info = parse_assign_view(resp.text)
        return name, mid, url, info
    except Exception:
        return name, mid, url, {}


def fetch_task_description(session, module_id):
    """
    Fetch only the task description from an assignment page.
    
    Args:
        session: Moodle session object
        module_id: Assignment module ID
    
    Returns:
        str: The task description HTML, or None on error
    """
    url = f"{BASE}/mod/assign/view.php?id={module_id}"
    
    try:
        resp = session.get(url, timeout=30)
        if not resp.ok:
            return None
        
        info = parse_assign_view(resp.text)
        return info.get('description')
    except Exception as e:
        logger.error(f"Error fetching task description: {e}")
        return None

def fetch_tasks_list(session_id, course_id, progress_callback=None):
    """Fetch all tasks for a course with details"""
    logger.info(f"Fetching full task list for course {course_id}")
    main_session = setup_session(session_id)
    tasks = get_tasks(main_session, course_id)
    
    if not tasks:
        logger.warning("No tasks found locally on course page")
        return []
    
    rows = []
    total = len(tasks)
    
    with ThreadPoolExecutor(max_workers=DEFAULT_THREADS) as executor:
        futures = {
            executor.submit(fetch_task_details, session_id, name, mid, url): (name, mid, url)
            for name, mid, url in tasks
        }
        
        completed = 0
        for fut in as_completed(futures):
            name, mid, url = futures[fut]
            try:
                returned_name, returned_mid, returned_url, info = fut.result()
                rows.append({
                    "Task Name": returned_name,
                    "Module ID": returned_mid,
                    "Due Date": info.get("due_date", ""),
                    "Time Remaining": info.get("time_remaining", ""),
                    "Max Grade": info.get("max_grade", ""),
                    "Participants": info.get("participants", ""),
                    "Submitted": info.get("submitted", ""),
                    "Needs Grading": info.get("needs_grading", ""),
                    "description": info.get("description", ""),
                    "URL": returned_url
                })
            except Exception as e:
                logger.error(f"Error fetching task detail: {e}")
                pass
            
            completed += 1
            if progress_callback:
                progress_callback(completed / total)
    
    # Sort by original order
    task_order = {(name, mid): i for i, (name, mid, _) in enumerate(tasks)}
    rows.sort(key=lambda r: task_order.get((r["Task Name"], r["Module ID"]), 999))
    
    return rows


# =============================================================================
# ASSIGNMENT DATE MANAGEMENT
# =============================================================================

def get_assignment_dates(session, module_id):
    """
    Fetch current assignment dates from modedit.php.
    
    Args:
        session: Moodle session
        module_id: Assignment module ID (cmid)
    
    Returns:
        dict with:
        - due_date: datetime or None
        - cutoff_date: datetime or None
        - allow_submissions_from: datetime or None
        - due_date_enabled: bool
        - cutoff_date_enabled: bool
        - allow_submissions_enabled: bool
        - form_data: dict with all form field values for resubmission
        Returns None on error.
    """
    url = f"{BASE}/course/modedit.php"
    params = {"update": module_id, "return": 1}
    
    try:
        resp = session.get(url, params=params, timeout=30)
        if not resp.ok:
            logger.error(f"Failed to load modedit.php: {resp.status_code}")
            return None
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Find the form - Moodle uses dynamically generated IDs like "mform1_ABC123"
        # So we search by class "mform" and method "post"
        form = soup.find("form", class_="mform", method="post")
        if not form:
            # Fallback 1: try finding any form with action containing modedit.php
            form = soup.find("form", action=lambda a: a and "modedit.php" in a and "?" not in a)
        if not form:
            # Fallback 2: try finding form by id pattern (mform1_*)
            form = soup.find("form", id=lambda i: i and i.startswith("mform"))
        if not form:
            # Fallback 3: try finding any form on the page with method="post"
            all_forms = soup.find_all("form", method="post")
            if all_forms:
                form = all_forms[0]
                logger.info(f"Using first POST form: id={form.get('id')}, action={form.get('action')[:50] if form.get('action') else 'N/A'}")
        if not form:
            logger.error("Could not find modedit form")
            # Save the response HTML for debugging
            try:
                from pathlib import Path
                debug_dir = Path("output") / "debug"
                debug_dir.mkdir(parents=True, exist_ok=True)
                debug_file = debug_dir / f"modedit_form_error_{module_id}.html"
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(resp.text)
                logger.error(f"Saved response HTML for debugging: {debug_file}")
                
                # Log what forms ARE on the page
                all_forms = soup.find_all("form")
                logger.error(f"Found {len(all_forms)} form(s) on page:")
                for i, f in enumerate(all_forms):
                    logger.error(f"  Form {i}: id={f.get('id')}, class={f.get('class')}, action={str(f.get('action'))[:60]}")
            except Exception as e:
                logger.warning(f"Could not save debug HTML: {e}")
            return None
        
        # Helper function to extract date from Moodle's multi-field date selector
        def extract_date(prefix):
            """Extract datetime from Moodle's date fields"""
            # Check if enabled - Moodle uses presence of 'checked' attribute
            enabled_el = soup.find("input", {"name": f"{prefix}[enabled]"})
            is_enabled = enabled_el and enabled_el.has_attr("checked")
            
            if not is_enabled:
                return None, False
            
            day_el = soup.find("select", {"name": f"{prefix}[day]"})
            month_el = soup.find("select", {"name": f"{prefix}[month]"})
            year_el = soup.find("select", {"name": f"{prefix}[year]"})
            hour_el = soup.find("select", {"name": f"{prefix}[hour]"})
            minute_el = soup.find("select", {"name": f"{prefix}[minute]"})
            
            def get_selected_value(select_el):
                if not select_el:
                    return None
                # HTML 'selected' is a boolean attribute - check for presence
                selected = select_el.find("option", selected=lambda x: x is not None)
                if not selected:
                    # Fallback: look for 'selected' attribute with any value
                    selected = select_el.find("option", attrs={"selected": True})
                return selected.get("value") if selected else None
            
            day = get_selected_value(day_el)
            month = get_selected_value(month_el)
            year = get_selected_value(year_el)
            hour = get_selected_value(hour_el)
            minute = get_selected_value(minute_el)
            
            logger.debug(f"{prefix}: day={day}, month={month}, year={year}, hour={hour}, minute={minute}")
            
            if all([day, month, year, hour, minute]):
                try:
                    dt = datetime(int(year), int(month), int(day), int(hour), int(minute))
                    return dt, True
                except ValueError as e:
                    logger.error(f"Error parsing date for {prefix}: {e}")
                    return None, True
            return None, True
        
        # Extract all dates
        due_date, due_enabled = extract_date("duedate")
        cutoff_date, cutoff_enabled = extract_date("cutoffdate")
        allow_from, allow_enabled = extract_date("allowsubmissionsfromdate")
        grading_due, grading_due_enabled = extract_date("gradingduedate")
        
        # Extract all form fields for later resubmission
        # IMPORTANT: Skip button/submit inputs - they would cause form to cancel!
        form_data = {}
        skip_types = {"submit", "button", "image", "reset"}
        
        for input_el in form.find_all(["input", "select", "textarea"]):
            name = input_el.get("name")
            if not name:
                continue
            
            # Skip button-type inputs (submit, cancel, etc.)
            input_type = input_el.get("type", "").lower()
            if input_type in skip_types:
                continue
            
            if input_el.name == "select":
                # Find selected option - check for 'selected' attribute presence
                selected = input_el.find("option", selected=lambda x: x is not None)
                if not selected:
                    selected = input_el.find("option", attrs={"selected": True})
                form_data[name] = selected.get("value", "") if selected else ""
            elif input_el.name == "textarea":
                form_data[name] = input_el.get_text()
            elif input_type == "checkbox":
                # Only include checked checkboxes - use has_attr for proper detection
                if input_el.has_attr("checked"):
                    form_data[name] = input_el.get("value", "1")
            elif input_type == "radio":
                if input_el.has_attr("checked"):
                    form_data[name] = input_el.get("value", "")
            else:
                form_data[name] = input_el.get("value", "")
        
        # Log key form fields for debugging
        logger.debug(f"Form data keys: {list(form_data.keys())[:20]}...")
        logger.debug(f"duedate fields: day={form_data.get('duedate[day]')}, month={form_data.get('duedate[month]')}, year={form_data.get('duedate[year]')}, enabled={form_data.get('duedate[enabled]')}")
        
        return {
            "due_date": due_date,
            "due_date_enabled": due_enabled,
            "cutoff_date": cutoff_date,
            "cutoff_date_enabled": cutoff_enabled,
            "allow_submissions_from": allow_from,
            "allow_submissions_enabled": allow_enabled,
            "grading_due_date": grading_due,
            "grading_due_date_enabled": grading_due_enabled,
            "form_data": form_data
        }
        
    except Exception as e:
        logger.error(f"Error getting assignment dates: {e}")
        return None


def check_submission_timeliness(last_modified: str, due_date) -> dict:
    """
    Check if a submission was on time.
    
    Args:
        last_modified: Submission timestamp string (format: "Monday, 15 December 2025, 3:35 PM")
        due_date: datetime object for the due date
    
    Returns:
        dict with:
        - is_on_time: bool (True if submitted on/before due date)
        - status: str ("On Time", "Late", or "Unknown")
        - hours_late: float or None (how many hours after due date, if late)
    """
    result = {
        "is_on_time": None,
        "status": "Unknown",
        "hours_late": None
    }
    
    if not last_modified or not due_date:
        return result
    
    try:
        # Parse the Last Modified timestamp (format: "Monday, 15 December 2025, 3:35 PM")
        sub_time = datetime.strptime(last_modified.strip(), "%A, %d %B %Y, %I:%M %p")
        
        if sub_time <= due_date:
            result["is_on_time"] = True
            result["status"] = "On Time"
            result["hours_late"] = 0
        else:
            result["is_on_time"] = False
            result["status"] = "Late"
            delta = sub_time - due_date
            result["hours_late"] = delta.total_seconds() / 3600  # Convert to hours
    except ValueError as e:
        logger.debug(f"Could not parse submission timestamp '{last_modified}': {e}")
    
    return result


def update_assignment_dates(session, module_id, 
                            due_date=None, due_date_enabled=None,
                            cutoff_date=None, cutoff_date_enabled=None,
                            grading_due_date=None, grading_due_date_enabled=None):
    """
    Update assignment dates by POSTing to modedit.php.
    
    Args:
        session: Moodle session
        module_id: Assignment module ID
        due_date: datetime object for new due date (or None to keep current)
        due_date_enabled: bool to enable/disable (or None to keep current)
        cutoff_date: datetime object for cut-off date (or None to keep current)
        cutoff_date_enabled: bool to enable/disable (or None to keep current)
        grading_due_date: datetime for 'Remind me to grade by' (or None to keep current)
        grading_due_date_enabled: bool to enable/disable (or None to keep current)
    
    Returns:
        True on success, False on failure
    """
    # First, get current form data
    current = get_assignment_dates(session, module_id)
    if not current or "form_data" not in current:
        logger.error("Could not get current assignment dates")
        return False
    
    form_data = current["form_data"].copy()
    
    # Helper to set date fields
    def set_date_fields(prefix, dt, enabled):
        if enabled is not None:
            if enabled:
                form_data[f"{prefix}[enabled]"] = "1"
            else:
                # Remove the enabled field to disable
                form_data.pop(f"{prefix}[enabled]", None)
        
        if dt is not None and (enabled is None or enabled):
            form_data[f"{prefix}[day]"] = str(dt.day)
            form_data[f"{prefix}[month]"] = str(dt.month)
            form_data[f"{prefix}[year]"] = str(dt.year)
            form_data[f"{prefix}[hour]"] = str(dt.hour)
            form_data[f"{prefix}[minute]"] = str(dt.minute)
    
    # Apply changes
    if due_date is not None or due_date_enabled is not None:
        set_date_fields("duedate", due_date, due_date_enabled)
    
    if cutoff_date is not None or cutoff_date_enabled is not None:
        set_date_fields("cutoffdate", cutoff_date, cutoff_date_enabled)
    
    # Handle gradingduedate ("Remind me to grade by")
    if grading_due_date is not None or grading_due_date_enabled is not None:
        # User explicitly set grading due date options
        set_date_fields("gradingduedate", grading_due_date, grading_due_date_enabled)
    elif due_date is not None and form_data.get("gradingduedate[enabled]") == "1":
        # Auto-update: Moodle requires gradingduedate >= duedate
        # If user didn't explicitly set grading options, auto-sync with new due date
        set_date_fields("gradingduedate", due_date, True)
        logger.info(f"Auto-updating gradingduedate to match new duedate")
    
    # Ensure submit button is included
    form_data["submitbutton"] = "Save and display"
    
    # Debug: Log what we're about to send for date fields
    logger.info(f"Sending duedate: day={form_data.get('duedate[day]')}, month={form_data.get('duedate[month]')}, year={form_data.get('duedate[year]')}, enabled={form_data.get('duedate[enabled]')}")
    logger.info(f"Sending cutoffdate: enabled={form_data.get('cutoffdate[enabled]')}")
    logger.info(f"Sending gradingduedate: day={form_data.get('gradingduedate[day]')}, enabled={form_data.get('gradingduedate[enabled]')}")
    
    # POST the form
    url = f"{BASE}/course/modedit.php"
    
    try:
        logger.info(f"Updating assignment {module_id} dates")
        resp = session.post(url, data=form_data, timeout=30)
        
        # Debug: Log response details
        logger.info(f"Response status: {resp.status_code}, URL: {resp.url[:100]}")
        
        # Moodle typically redirects on success
        if resp.ok:
            # Check if we got redirected to the assignment page (success)
            if "mod/assign/view.php" in resp.url or "course/view.php" in resp.url:
                logger.info("Assignment dates updated successfully")
                return True
            
            # Still on modedit.php means form validation failed or form wasn't accepted
            if "modedit.php" in resp.url:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                
                # Save response HTML for debugging
                try:
                    from pathlib import Path
                    debug_dir = Path("output") / "debug"
                    debug_dir.mkdir(parents=True, exist_ok=True)
                    debug_file = debug_dir / f"date_update_{module_id}.html"
                    with open(debug_file, 'w', encoding='utf-8') as f:
                        f.write(resp.text)
                    logger.info(f"Saved response HTML to {debug_file}")
                except Exception as e:
                    logger.warning(f"Could not save debug HTML: {e}")
                
                # Look for error messages - Moodle uses various classes
                errors = []
                
                # Check for alert boxes
                for alert in soup.find_all(class_=re.compile(r'alert-danger|alert-error')):
                    text = alert.get_text(strip=True)
                    if text:
                        errors.append(text)
                
                # Check for form field errors (class="error" near form fields)
                for err in soup.find_all(class_="error"):
                    text = err.get_text(strip=True)
                    if text and "error" not in text.lower()[:10]:  # Skip if just "error" label
                        errors.append(text)
                
                # Check for fdescription errors
                for err in soup.find_all(class_="fdescription"):
                    text = err.get_text(strip=True)
                    if "error" in text.lower() or "must" in text.lower():
                        errors.append(text)
                
                if errors:
                    logger.warning(f"Form validation errors: {'; '.join(errors[:3])}")
                else:
                    logger.warning(f"Stayed on modedit.php without redirect - check output/debug/date_update_{module_id}.html")
                
                return False
            
            # Some other page - unexpected
            logger.warning(f"Unexpected redirect to: {resp.url}")
            return False
        else:
            logger.error(f"Failed to update assignment dates: {resp.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Error updating assignment dates: {e}")
        return False


def get_quizzes(session, course_id):
    """Get list of practice quizzes from course.
    
    Returns:
        List of tuples: (display_name, module_id) where display_name includes the topic name
        For example: ("#07 - Cybersecurity Principles", "12345")
    """
    url = f"https://{PAATSHALA_HOST}/course/view.php?id={course_id}"
    resp = session.get(url)
    if not resp.ok:
        return []
    
    soup = BeautifulSoup(resp.text, "html.parser")
    
    # Find all sections to build a mapping of activities to section names
    sections = soup.find_all("li", class_=lambda c: c and "section" in c and "main" in c)
    
    quizzes = []
    
    for section in sections:
        # Get the section/topic name
        section_name = ""
        name_node = section.find(class_="sectionname")
        if not name_node:
            name_node = section.find(class_="section-title")
        if name_node:
            section_name = name_node.get_text(strip=True)
        else:
            # Try aria-label on the section itself
            label = section.get("aria-label")
            if label:
                section_name = label
        
        # Extract topic name without "Day XX - " prefix if present
        topic_name = ""
        day_match = re.search(r'Day\s*\d+\s*[-–—]\s*(.+)', section_name)
        if day_match:
            topic_name = day_match.group(1).strip()
        else:
            topic_name = section_name
        
        # Find all quiz items within this section
        quiz_items = section.find_all("li", class_="modtype_quiz")
        
        for item in quiz_items:
            link = item.find("a", href=re.compile(r"mod/quiz/view\.php\?id=\d+"))
            if not link:
                continue
            name = link.get_text(strip=True)
            name = re.sub(r'\s+(Quiz)$', '', name)
            if "practice quiz" in name.lower():
                m = re.search(r"id=(\d+)", link.get("href", ""))
                if m:
                    # Extract session number from quiz name (e.g., "#07" from "Practice Quiz - Session #07")
                    session_match = re.search(r'#(\d+)', name)
                    if session_match and topic_name:
                        # Create display name: "#07 - Topic Name"
                        session_num = session_match.group(1)
                        display_name = f"#{session_num} - {topic_name}"
                    else:
                        # Fallback to original name if no session number or topic
                        display_name = name
                    
                    quizzes.append((display_name, m.group(1)))
    
    return quizzes

def fetch_quiz_scores(session_id, module_id, group_id=None):
    """Fetch scores for a quiz module"""
    s = get_thread_session(session_id)
    
    report_url = f"https://{PAATSHALA_HOST}/mod/quiz/report.php?id={module_id}&mode=overview"
    if group_id:
        report_url += f"&group={group_id}"
    
    report_resp = s.get(report_url)
    if not report_resp.ok:
        return module_id, {}, 0
    
    soup = BeautifulSoup(report_resp.text, "html.parser")
    table = soup.find("table", class_="generaltable")
    if not table:
        return module_id, {}, 0
    
    scores = defaultdict(float)
    attempt_count = 0
    
    for row in table.find_all("tr")[1:]:
        if "emptyrow" in row.get("class", []):
            continue
        cols = row.find_all(["th", "td"])
        if len(cols) < 9:
            continue
        name_link = cols[2].find("a", href=re.compile(r"user/view\.php"))
        if name_link:
            name = name_link.get_text(strip=True)
            grade_text = cols[8].get_text(strip=True)
            grade_match = re.search(r'(\d+\.?\d*)', grade_text)
            if grade_match:
                grade = float(grade_match.group(1))
                scores[name] = max(scores[name], grade)
                attempt_count += 1
    
    return module_id, dict(scores), attempt_count

def fetch_quiz_scores_all(session_id, course_id, group_id=None, progress_callback=None):
    """Fetch all quiz scores for a course"""
    logger.info(f"Fetching all quiz scores for course {course_id} (Group: {group_id})")
    main_session = setup_session(session_id)
    quizzes = get_quizzes(main_session, course_id)
    
    if not quizzes:
        logger.warning("No quizzes found")
        return None, []
    
    all_scores = defaultdict(dict)
    quiz_names_ordered = [name for name, _ in quizzes]
    mid_to_name = {mid: name for name, mid in quizzes}
    total = len(quizzes)
    
    with ThreadPoolExecutor(max_workers=DEFAULT_THREADS) as executor:
        futures = {executor.submit(fetch_quiz_scores, session_id, mid, group_id): mid for _, mid in quizzes}
        
        completed = 0
        for fut in as_completed(futures):
            mid = futures[fut]
            try:
                _mid, scores, _ = fut.result()
                quiz_name = mid_to_name.get(_mid, f"module_{_mid}")
                for student, grade in scores.items():
                    all_scores[student][quiz_name] = grade
            except:
                pass
            
            completed += 1
            if progress_callback:
                progress_callback(completed / total)
    
    if not all_scores:
        return quiz_names_ordered, []
    
    # Build rows
    rows = []
    for student in sorted(all_scores.keys()):
        row = {"Student Name": student}
        for quiz_name in quiz_names_ordered:
            row[quiz_name] = all_scores[student].get(quiz_name, None)
        rows.append(row)
    
    return quiz_names_ordered, rows

def get_available_groups(session, module_id, activity_type='assign'):
    """Get list of available groups for an assignment or quiz.
    
    Returns:
        List of tuples: (group_id, group_name, member_count)
        - member_count may be None if not available
    """
    if activity_type == 'quiz':
        url = f"{BASE}/mod/quiz/report.php?id={module_id}&mode=overview"
    else:
        url = f"{BASE}/mod/assign/view.php?id={module_id}&action=grading"
    
    try:
        resp = session.get(url, timeout=30)
        if not resp.ok:
            return []
        
        soup = BeautifulSoup(resp.text, "html.parser")
        group_select = soup.find("select", {"name": "group"})
        
        if not group_select:
            return []
        
        groups = []
        for option in group_select.find_all("option"):
            group_id = option.get("value", "")
            group_name = option.get_text(strip=True)
            
            # Try to extract member count from group name if it's in format "Name (N)"
            # Otherwise we'll fetch it separately
            member_count = None
            if group_id and group_name:
                # Skip "All participants" or similar
                if group_id == "0" or "all" in group_name.lower():
                    continue
                groups.append((group_id, group_name, member_count))
        
        return groups
    except Exception:
        return []

def _extract_max_grade_from_edit_page(html):
    """
    Extract max_grade from the assignment edit/settings page.
    
    The edit page (modedit.php) has a form field for grade with the max value.
    Look for input fields like:
    - <input ... name="grade[modgrade_point]" ... value="100" />
    - <select ... name="grade[modgrade_type]" ...>  with <option value="point">Point</option>
    - Text patterns like "Maximum grade" or grade configuration
    
    Args:
        html: HTML content of the assignment edit page
        
    Returns:
        float: The max grade value, or None if not found
    """
    soup = BeautifulSoup(html, "html.parser")
    
    # Pattern 1: Look for grade point input
    # <input type="text" name="grade[modgrade_point]" id="id_grade_modgrade_point" value="100" ...>
    grade_input = soup.find('input', {'name': re.compile(r'grade\[modgrade_point\]', re.I)})
    if grade_input:
        try:
            max_grade = float(grade_input.get('value', 0))
            if max_grade >= 1:
                logger.info(f"[_extract_max_grade_from_edit_page] Found max_grade={max_grade} via grade[modgrade_point]")
                return max_grade
        except (ValueError, TypeError):
            pass
    
    # Pattern 2: Look for any input with "grade" and "point" in the name/id
    for inp in soup.find_all('input', {'type': 'text'}):
        name = inp.get('name', '').lower()
        inp_id = inp.get('id', '').lower()
        if ('grade' in name or 'grade' in inp_id) and ('point' in name or 'point' in inp_id):
            try:
                max_grade = float(inp.get('value', 0))
                if max_grade >= 1:
                    logger.info(f"[_extract_max_grade_from_edit_page] Found max_grade={max_grade} via input {inp.get('name')}")
                    return max_grade
            except (ValueError, TypeError):
                pass
    
    # Pattern 3: Look for "Maximum grade" label with value
    text = soup.get_text()
    match = re.search(r'Maximum\s+grade[:\s]*(\d+(?:\\.\d+)?)', text, re.I)
    if match:
        try:
            max_grade = float(match.group(1))
            if max_grade >= 1:
                logger.info(f"[_extract_max_grade_from_edit_page] Found max_grade={max_grade} via 'Maximum grade' text")
                return max_grade
        except ValueError:
            pass
    
    # Pattern 4: Look for "Grade" section with "out of" pattern
    match = re.search(r'(?:Grade|Points?)\s+out\s+of\s*(\d+(?:\\.\d+)?)', text, re.I)
    if match:
        try:
            max_grade = float(match.group(1))
            if max_grade >= 1:
                logger.info(f"[_extract_max_grade_from_edit_page] Found max_grade={max_grade} via 'out of' text")
                return max_grade
        except ValueError:
            pass
    
    logger.debug("[_extract_max_grade_from_edit_page] Could not find max_grade in edit page")
    return None


def fetch_max_grade(session_id, module_id):
    """
    Quickly fetch just the max_grade for an assignment without parsing all submissions.
    This is a lightweight API call used as a fallback when max_grade is not already cached.
    
    Args:
        session_id: The Moodle session ID
        module_id: The module/assignment ID
        
    Returns:
        float: The max grade value, or None if not found
    """
    import re
    session = setup_session(session_id)
    
    # Try the grading page first - it has the max grade in the header
    url = f"{BASE}/mod/assign/view.php?id={module_id}&action=grading"
    
    try:
        resp = session.get(url, timeout=10)
        if not resp.ok:
            return None
        
        html = resp.text
        
        # Sanity check helper: Moodle max grades are typically 1-1000
        def _valid_grade(val):
            return 1 <= val <= 1000
        
        # Quick extraction from header: "Grade / 15.00" or similar
        match = re.search(r'Grade\s*/\s*(\d+(?:\.\d+)?)', html, re.I)
        if match:
            max_grade = float(match.group(1))
            if _valid_grade(max_grade):
                logger.debug(f"[fetch_max_grade] Found max_grade={max_grade} from grading page header")
                return max_grade
            logger.debug(f"[fetch_max_grade] Rejected max_grade={max_grade} from header (out of range)")
        
        # Fallback: look for "Grade out of X"
        match = re.search(r'Grade out of\s*(\d+(?:\.\d+)?)', html, re.I)
        if match:
            max_grade = float(match.group(1))
            if _valid_grade(max_grade):
                logger.debug(f"[fetch_max_grade] Found max_grade={max_grade} from 'Grade out of' pattern")
                return max_grade
            logger.debug(f"[fetch_max_grade] Rejected max_grade={max_grade} from 'Grade out of' (out of range)")
        
        # Fallback: data-max-grade attribute
        match = re.search(r'data-max-grade="(\d+(?:\.\d+)?)"', html)
        if match:
            max_grade = float(match.group(1))
            if _valid_grade(max_grade):
                logger.debug(f"[fetch_max_grade] Found max_grade={max_grade} from data-max-grade attribute")
                return max_grade
            logger.debug(f"[fetch_max_grade] Rejected max_grade={max_grade} from data-max-grade (out of range)")
        
        # Fallback: extract from any "X / Y" grade cell
        # Search narrowly: look for grade-like patterns (small numbers)
        for match in re.finditer(r'(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)', html):
            max_grade = float(match.group(2))
            if _valid_grade(max_grade):
                logger.debug(f"[fetch_max_grade] Found max_grade={max_grade} from grade cell pattern")
                return max_grade
                
    except Exception as e:
        logger.debug(f"[fetch_max_grade] Error fetching max_grade: {e}")
    
    return None

def fetch_submissions(session_id, module_id, group_id=None):
    """
    Fetch submissions for a specific task/module.
    
    Returns:
        tuple: (submissions_list, assignment_id, max_grade) where:
            - submissions_list: List of submission dicts from parse_grading_table
            - assignment_id: The Moodle assignment instance ID (for grade submission API)
            - max_grade: The maximum grade for this assignment (float) or None
    """
    session = setup_session(session_id)
    
    url = f"{BASE}/mod/assign/view.php?id={module_id}&action=grading"
    if group_id:
        url += f"&group={group_id}"
    
    try:
        resp = session.get(url, timeout=30)
        if not resp.ok:
            return [], None, None
        
        submissions, max_grade = parse_grading_table(resp.text)
        
        # The grading table page doesn't contain assignment_id
        # We need to fetch the grader page for one student to get it
        assignment_id = None
        
        # Try to get assignment_id from the grading table first (might work for some Moodle versions)
        assignment_id = extract_assignment_id(resp.text)
        
        # If not found and we have submissions, fetch the grader page for the first student
        # The grader page contains both assignment_id and max_grade ("Grade out of X")
        if (not assignment_id or not max_grade) and submissions:
            first_user_id = submissions[0].get('User_ID')
            if first_user_id:
                grader_url = f"{BASE}/mod/assign/view.php?id={module_id}&action=grader&userid={first_user_id}"
                try:
                    grader_resp = session.get(grader_url, timeout=15)
                    if grader_resp.ok:
                        if not assignment_id:
                            assignment_id = extract_assignment_id(grader_resp.text)
                        # Extract max_grade from grader page - this is the reliable source
                        # It shows "Grade out of X" even when no students have been graded
                        if not max_grade:
                            max_grade = extract_max_grade_from_grader(grader_resp.text)
                            if max_grade:
                                logger.info(f"Extracted max_grade={max_grade} from grader page")
                except Exception as e:
                    logger.debug(f"Failed to get grader page: {e}")
        
        # ADDITIONAL FALLBACK: Try to get max_grade from assignment edit/settings page
        # This is the most reliable source as it directly shows the configured grade
        if not max_grade:
            try:
                edit_url = f"{BASE}/course/modedit.php?update={module_id}&return=1"
                edit_resp = session.get(edit_url, timeout=15)
                if edit_resp.ok:
                    max_grade = _extract_max_grade_from_edit_page(edit_resp.text)
                    if max_grade:
                        logger.info(f"Extracted max_grade={max_grade} from assignment edit page")
            except Exception as e:
                logger.debug(f"Failed to get assignment edit page: {e}")
        
        return submissions, assignment_id, max_grade
    except Exception as e:
        logger.error(f"Error in fetch_submissions: {e}")
        return [], None, None


def fetch_full_feedback(session_id, module_id, user_id):
    """
    Fetch the complete feedback comment for a student from the grade form.
    
    The grading table shows truncated feedback. This function fetches the 
    grade form page which contains the full feedback in the editor textarea.
    
    Args:
        session_id: Moodle session cookie
        module_id: Assignment module ID (cmid)
        user_id: The Moodle user ID of the student
    
    Returns:
        dict: {
            'success': bool,
            'feedback': str (full feedback text),
            'feedback_html': str (HTML formatted feedback if available),
            'error': str or None
        }
    """
    session = setup_session(session_id)
    
    try:
        # Fetch the grade form URL which renders server-side with feedback populated
        grade_url = f"{BASE}/mod/assign/view.php?id={module_id}&action=grade&rownum=0&userid={user_id}"
        
        resp = session.get(grade_url, timeout=30)
        if not resp.ok:
            logger.error(f"Failed to fetch grade form: {resp.status_code}")
            return {'success': False, 'feedback': '', 'feedback_html': '', 'error': f"HTTP {resp.status_code}"}
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # The form contains a textarea with the feedback HTML
        editor_textarea = soup.find("textarea", {"name": re.compile(r"assignfeedbackcomments_editor\[text\]", re.I)})
        if editor_textarea:
            feedback_html = editor_textarea.get_text()
            if feedback_html.strip():
                feedback_text = BeautifulSoup(feedback_html, "html.parser").get_text(" ", strip=True)
                logger.info(f"Got feedback from grade form for user {user_id} ({len(feedback_text)} chars)")
                return {'success': True, 'feedback': feedback_text, 'feedback_html': feedback_html, 'error': None}
        
        logger.info(f"No feedback found for user {user_id}")
        return {'success': True, 'feedback': '', 'feedback_html': '', 'error': None}
            
    except Exception as e:
        logger.error(f"Error fetching full feedback: {e}")
        return {'success': False, 'feedback': '', 'feedback_html': '', 'error': str(e)}



def submit_grade(session, assignment_id, user_id, module_id, grade, feedback_html, sesskey):
    """
    Submit a grade and feedback comment to Moodle for a student.
    
    Uses the mod_assign_submit_grading_form AJAX API.
    
    Args:
        session: Moodle session object
        assignment_id: The assignment instance ID (NOT module ID)
        user_id: The Moodle user ID of the student
        module_id: The course module ID (cmid)
        grade: The numeric grade to assign
        feedback_html: HTML-formatted feedback comment
        sesskey: Session key for AJAX requests
    
    Returns:
        dict: {'success': bool, 'error': str or None}
    """
    import urllib.parse
    import json as _json
    from datetime import datetime as _dt
    
    logger.info(f"[submit_grade] assignment_id={assignment_id}, user_id={user_id}, "
                f"module_id={module_id}, grade={grade}, sesskey={sesskey[:6]}...")
    
    # Safeguard: reject clearly invalid grade values
    try:
        grade_num = float(grade)
        if grade_num > 1000 or grade_num < -1:
            logger.error(f"[submit_grade] REJECTED: grade={grade} is out of bounds (>1000 or <-1). "
                         f"This indicates a bug in grade calculation upstream.")
            return {"success": False, "error": f"Grade value {grade} is invalid (exceeds 1000). Check total_score and max_grade calculation."}
    except (ValueError, TypeError):
        pass  # Let Moodle handle non-numeric grades
    
    url = f"{BASE}/lib/ajax/service.php"
    params = {
        "sesskey": sesskey,
        "info": "mod_assign_submit_grading_form"
    }
    
    # Build the form data that goes inside jsonformdata
    # This mimics the actual Moodle grading form
    form_data = {
        "id": module_id,
        "rownum": 0,
        "useridlistid": "",
        "attemptnumber": -1,
        "ajax": 0,
        "userid": 0,  # This is for the form, not the actual student
        "sendstudentnotifications": "false",
        "action": "submitgrade",
        "sesskey": sesskey,
        f"_qf__mod_assign_grade_form_{user_id}": 1,
        "grade": grade,
        "assignfeedbackcomments_editor[text]": feedback_html,
        "assignfeedbackcomments_editor[format]": 1,  # HTML format
        "assignfeedbackcomments_editor[itemid]": 0,  # Will be auto-assigned
        "assignfeedback_editpdf_haschanges": "false"
    }
    
    # URL-encode the form data
    encoded_form_data = urllib.parse.urlencode(form_data)
    # Add quotes around it as Moodle expects
    json_form_data = f'"{encoded_form_data}"'
    
    payload = [{
        "index": 0,
        "methodname": "mod_assign_submit_grading_form",
        "args": {
            "assignmentid": str(assignment_id),
            "userid": int(user_id),
            "jsonformdata": json_form_data
        }
    }]
    
    try:
        resp = session.post(url, params=params, json=payload, timeout=30)
        logger.info(f"Submit grade response status: {resp.status_code}")
        
        # Log full request/response to file for debugging
        try:
            debug_log_path = Path("output") / "debug_grade_submissions.log"
            debug_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(debug_log_path, "a", encoding="utf-8") as dbg:
                dbg.write(f"\n{'='*80}\n")
                dbg.write(f"Timestamp: {_dt.now().isoformat()}\n")
                dbg.write(f"assignment_id={assignment_id}, user_id={user_id}, module_id={module_id}, grade={grade}\n")
                dbg.write(f"URL: {url}?{urllib.parse.urlencode(params)}\n")
                dbg.write(f"Payload: {_json.dumps(payload, indent=2)[:2000]}\n")
                dbg.write(f"Response status: {resp.status_code}\n")
                dbg.write(f"Response body: {resp.text[:1000]}\n")
        except Exception as dbg_err:
            logger.debug(f"Could not write debug log: {dbg_err}")
        
        if resp.ok:
            try:
                data = resp.json()
                logger.info(f"Submit grade response: {str(data)[:500]}")
                
                if isinstance(data, list) and data:
                    result = data[0]
                    if result.get("error"):
                        error_msg = result.get("exception", {}).get("message", "Unknown error")
                        logger.error(f"Moodle returned error: {error_msg}")
                        return {"success": False, "error": error_msg}
                    
                    # Check for warnings in data array (e.g. couldnotsavegrade)
                    warnings = result.get("data", [])
                    if isinstance(warnings, list) and warnings:
                        for w in warnings:
                            if isinstance(w, dict) and w.get("warningcode"):
                                warn_msg = w.get("message", w.get("item", "Unknown warning"))
                                logger.error(f"Moodle grade warning: {w.get('warningcode')} - {warn_msg}")
                                return {"success": False, "error": f"{w.get('warningcode')}: {warn_msg}"}
                    
                    # Success - no errors or warnings
                    return {"success": True, "error": None}
                else:
                    return {"success": False, "error": "Unexpected response format"}
            except Exception as e:
                logger.error(f"Error parsing grade submission response: {e}")
                return {"success": False, "error": f"Response parse error: {e}"}
        else:
            logger.error(f"Grade submission request failed: {resp.status_code}")
            return {"success": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        logger.error(f"Error submitting grade: {e}")
        return {"success": False, "error": str(e)}


def get_workshops(session, course_id):
    """
    Get list of workshop activities from course page.
    
    Returns list of tuples: (name, module_id, href, restricted_group)
    where restricted_group is the group name if the parent topic has a group restriction,
    or None if the workshop is available to all groups.
    """
    url = f"{BASE}/course/view.php?id={course_id}"
    resp = session.get(url)
    if not resp.ok:
        return []
    
    soup = BeautifulSoup(resp.text, "html.parser")
    
    # Find all topic sections that might contain workshops
    # The structure is: <li class="section"> contains topic info and activities
    workshops = []
    
    # Find all workshop items
    items = soup.find_all("li", class_=lambda c: c and "modtype_workshop" in c)
    
    for item in items:
        link = item.find("a", href=re.compile(r"mod/workshop/view\.php\?id=\d+"))
        if not link:
            link = item.find("a", href=re.compile(r"/mod/workshop/"))
        if link:
            name = link.get_text(strip=True)
            href = link.get("href", "")
            m = re.search(r"[?&]id=(\d+)", href)
            module_id = m.group(1) if m else ""
            if href.startswith("/"):
                href = BASE + href
            elif not href.startswith("http"):
                href = BASE + "/" + href.lstrip("/")
            
            # Try to find the parent topic's group restriction
            # Navigate up to find the section container
            restricted_group = None
            parent = item.parent
            
            # Keep going up until we find a section with availabilityinfo
            for _ in range(10):  # Limit depth to avoid infinite loop
                if parent is None:
                    break
                
                # Check if this parent has section_availability info
                avail_div = parent.find("div", class_="section_availability")
                if avail_div:
                    # Extract group name from <strong> tag inside availabilityinfo
                    avail_info = avail_div.find("div", class_="availabilityinfo")
                    if avail_info:
                        strong = avail_info.find("strong")
                        if strong:
                            restricted_group = strong.get_text(strip=True)
                            break
                
                parent = parent.parent
            
            workshops.append((name, module_id, href, restricted_group))
    
    return workshops



def fetch_workshop_submissions(session_id, module_id, group_id=None):
    """
    Fetch workshop submissions data.
    Returns a tuple: (phase_name, list of dicts with student info and grades)
    
    Workshop phases detected from table headers:
    - Submission phase: Only Name + Submission columns (no grades)
    - Assessment phase: Has Grades received/given columns (peer grades only)
    - Grading Evaluation phase: Has Grade for submission/assessment columns (final grades)
    """
    session = setup_session(session_id)
    
    url = f"{BASE}/mod/workshop/view.php?id={module_id}"
    if group_id:
        url += f"&group={group_id}"
    
    try:
        resp = session.get(url, timeout=60)
        if not resp.ok:
            logger.warning(f"Workshop fetch failed: {resp.status_code}")
            return None, []
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Detect phase from the active phase indicator in the userplan
        # The phase is indicated by dt elements with class like "phase10 active"
        # phase10=Setup, phase20=Submission, phase30=Assessment, phase40=Grading Evaluation, phase50=Closed
        phase = "Unknown"
        phase_mapping = {
            "phase10": "Setup",
            "phase20": "Submission", 
            "phase30": "Assessment",
            "phase40": "Grading Evaluation",
            "phase50": "Closed"
        }
        
        # Look for the active phase indicator
        active_phase_dt = soup.find("dt", class_="active")
        if active_phase_dt:
            dt_classes = active_phase_dt.get("class", [])
            for cls in dt_classes:
                if cls in phase_mapping:
                    phase = phase_mapping[cls]
                    break
        
        # Fallback: detect from h3 heading if no active indicator found
        if phase == "Unknown":
            phase_heading = soup.find("h3", id="mod_workshop-userplanheading")
            if phase_heading:
                heading_text = phase_heading.get_text(strip=True)
                if "Setup" in heading_text:
                    phase = "Setup"
                elif "Submission" in heading_text:
                    phase = "Submission"
                elif "Assessment" in heading_text:
                    phase = "Assessment"
                elif "Grading" in heading_text or "Evaluation" in heading_text:
                    phase = "Grading Evaluation"
                elif "Closed" in heading_text:
                    phase = "Closed"
        
        logger.info(f"Workshop phase detected: {phase}")
        
        # Find the grading report table
        table = soup.find("table", class_="grading-report")
        if not table:
            logger.info("No grading-report table found")
            return phase, []
        
        # Get tbody or use table directly
        tbody = table.find("tbody")
        if not tbody:
            tbody = table
        
        # Group rows by student - the table uses rowspan, so we need to collect
        # all rows belonging to each student (rows without participant cell belong to previous student)
        all_trs = tbody.find_all("tr")
        student_groups = []  # List of (first_tr, [all_trs_for_student])
        current_group = None
        
        for tr in all_trs:
            participant_cell = tr.find("td", class_="participant")
            if participant_cell:
                # Start a new student group
                current_group = {"first_tr": tr, "all_trs": [tr]}
                student_groups.append(current_group)
            elif current_group:
                # This row belongs to the current student (continuation row)
                current_group["all_trs"].append(tr)
        
        rows = []
        
        for group in student_groups:
            first_tr = group["first_tr"]
            all_student_trs = group["all_trs"]
            
            # Extract student name from first row
            participant_cell = first_tr.find("td", class_="participant")
            name_span = participant_cell.find("span")
            student_name = name_span.get_text(strip=True) if name_span else participant_cell.get_text(strip=True)
            
            row_data = {
                "Student Name": student_name,
                "Submission Title": "",
                "Last Modified": "",
                "Submission Grade": "-",
                "Assessment Grade": "-",
                "Phase": phase
            }
            
            # Extract submission info from first row
            submission_cell = first_tr.find("td", class_="submission")
            if submission_cell:
                title_link = submission_cell.find("a", class_="title")
                if title_link:
                    row_data["Submission Title"] = title_link.get_text(strip=True)
                
                info_div = submission_cell.find("div", class_="info")
                if info_div and "No submission" in info_div.get_text():
                    row_data["Submission Title"] = "No submission"
                
                lastmod_div = submission_cell.find("div", class_="lastmodified")
                if lastmod_div:
                    date_span = lastmod_div.find("span")
                    if date_span:
                        row_data["Last Modified"] = date_span.get_text(strip=True)
            
            # Extract grades based on phase
            if phase in ("Grading Evaluation", "Closed"):
                # Final grades are in dedicated cells (only in first row due to rowspan)
                for td in first_tr.find_all("td"):
                    td_classes = td.get("class", [])
                    if "submissiongrade" in td_classes:
                        grade_text = td.get_text(strip=True)
                        if grade_text and grade_text != "-":
                            row_data["Submission Grade"] = grade_text
                    elif "gradinggrade" in td_classes:
                        grade_text = td.get_text(strip=True)
                        if grade_text and grade_text != "-":
                            row_data["Assessment Grade"] = grade_text
            
            elif phase == "Assessment":
                # Collect ALL peer grades from ALL rows belonging to this student
                grades_received = []
                grades_given = []
                
                for tr in all_student_trs:
                    for td in tr.find_all("td"):
                        td_classes = td.get("class", [])
                        if "receivedgrade" in td_classes:
                            grade_span = td.find("span", class_="grade")
                            if grade_span:
                                grade_text = grade_span.get_text(strip=True)
                                if grade_text and grade_text != "-":
                                    grades_received.append(grade_text)
                        elif "givengrade" in td_classes:
                            grade_span = td.find("span", class_="grade")
                            if grade_span:
                                grade_text = grade_span.get_text(strip=True)
                                if grade_text and grade_text != "-":
                                    grades_given.append(grade_text)
                
                if grades_received:
                    row_data["Submission Grade"] = ", ".join(grades_received)
                if grades_given:
                    row_data["Assessment Grade"] = ", ".join(grades_given)
            
            rows.append(row_data)
        
        logger.info(f"Parsed {len(rows)} workshop submissions in {phase} phase")
        return phase, rows
        
    except Exception as e:
        logger.error(f"Error fetching workshop submissions: {e}")
        return None, []


# Workshop phase codes
WORKSHOP_PHASES = {
    "Setup": 10,
    "Submission": 20,
    "Assessment": 30,
    "Grading Evaluation": 40,
    "Closed": 50
}

WORKSHOP_PHASE_NAMES = {v: k for k, v in WORKSHOP_PHASES.items()}


def switch_workshop_phase(session_id, module_id, phase_code):
    """
    Switch workshop to a different phase.
    
    Args:
        session_id: Moodle session cookie
        module_id: Workshop module ID (cmid)
        phase_code: Phase number (10=Setup, 20=Submission, 30=Assessment, 40=Grading Evaluation, 50=Closed)
    
    Returns:
        True if successful, False otherwise
    """
    session = setup_session(session_id)
    
    # First, get the sesskey from the workshop page
    url = f"{BASE}/mod/workshop/view.php?id={module_id}"
    try:
        resp = session.get(url, timeout=30)
        if not resp.ok:
            logger.error(f"Failed to load workshop page: {resp.status_code}")
            return False
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Extract sesskey
        sesskey_input = soup.find("input", {"name": "sesskey"})
        if not sesskey_input:
            # Try from URL
            import re
            sesskey_match = re.search(r'sesskey=([a-zA-Z0-9]+)', resp.text)
            if sesskey_match:
                sesskey = sesskey_match.group(1)
            else:
                logger.error("Could not find sesskey")
                return False
        else:
            sesskey = sesskey_input.get("value")
        
        # POST to switch phase
        switch_url = f"{BASE}/mod/workshop/switchphase.php"
        payload = {
            "cmid": str(module_id),
            "phase": str(phase_code),
            "confirm": "1",
            "sesskey": sesskey
        }
        
        resp = session.post(switch_url, data=payload, timeout=30)
        
        if resp.ok:
            logger.info(f"Successfully switched workshop {module_id} to phase {phase_code}")
            return True
        else:
            logger.error(f"Failed to switch phase: {resp.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Error switching workshop phase: {e}")
        return False

def evaluate_submission(row):
    """Run link verification and GitHub checks for a submission row"""
    submission_text = row.get('Submission', '')
    
    # Initialize/Reset fields
    row['Eval_Link'] = ""
    row['Eval_Link_Valid'] = ""
    row['Eval_Repo_Status'] = ""
    row['Eval_Is_Fork'] = ""
    row['Eval_Parent'] = ""
    row['Eval_Last_Checked'] = datetime.now().isoformat()
    
    # Determine type if missing (backward compatibility)
    sub_type = row.get('Submission_Type')
    if not sub_type:
        if row.get('Submission_Files'):
            sub_type = 'file'
        elif "http" in submission_text:
            sub_type = 'link'
        elif submission_text:
            sub_type = 'text'
        else:
            sub_type = 'empty'
        row['Submission_Type'] = sub_type

    # Only evaluate links
    if sub_type != 'link':
        return row

    # Extract URL
    url_match = re.search(r'(https?://[^\s]+)', submission_text)
    if not url_match:
        return row
        
    url = url_match.group(1)
    
    # Normalize URL - handle common student input errors EARLY (affects all downstream uses)
    # 1. Remove trailing brackets and punctuation (but preserve dots before .git - repo might have trailing dot)
    url = url.rstrip(']').rstrip(')').rstrip(',').rstrip(';')  # Don't strip dots!
    # 2. Remove leading brackets if URL was wrapped like [url]
    if url.startswith('['):
        url = url.lstrip('[')
    if url.startswith('('):
        url = url.lstrip('(')
    # 3. Don't normalize ..git - repo name might have trailing dot (e.g., OSI_Wireshark. + .git = OSI_Wireshark..git)
    # 4. Remove trailing slashes
    url = url.rstrip('/')
    
    row['Eval_Link'] = url
    
    # 1. Verify Link
    try:
        resp = requests.head(url, timeout=5, allow_redirects=True)
        row['Eval_Link_Valid'] = "✅" if resp.ok else "❌"
    except:
        row['Eval_Link_Valid'] = "❌ (Unreachable)"
    
    # 2. GitHub Checks (using PAT for better rate limits and reliability)
    if "github.com" in url:
        parts = url.split('/')
        if len(parts) >= 5:
            owner = parts[-2]
            # Handle repo name - remove only .git suffix (preserve trailing dots in repo name)
            repo = parts[-1].removesuffix('.git')
            # Only strip slashes, not dots (dots are valid in repo names)
            repo = repo.rstrip('/')
            api_url = f"https://api.github.com/repos/{owner}/{repo}"
            
            # Set up headers with PAT if available
            headers = {"Accept": "application/vnd.github.v3+json"}
            pat = get_config("github_pat")
            if pat:
                headers["Authorization"] = f"token {pat}"
            
            try:
                api_resp = requests.get(api_url, headers=headers, timeout=10)
                
                if api_resp.status_code == 200:
                    repo_data = api_resp.json()
                    row['Eval_Repo_Status'] = "Public" if not repo_data.get('private') else "Private"
                    
                    if repo_data.get('fork'):
                        row['Eval_Is_Fork'] = "Yes"
                        row['Eval_Parent'] = repo_data.get('parent', {}).get('full_name', 'Unknown')
                    else:
                        row['Eval_Is_Fork'] = "No"
                        
                elif api_resp.status_code == 404:
                    row['Eval_Repo_Status'] = "Not Found/Private"
                elif api_resp.status_code == 403:
                    row['Eval_Repo_Status'] = "Rate Limit"
                elif api_resp.status_code == 401:
                    row['Eval_Repo_Status'] = "Auth Error"
                else:
                    row['Eval_Repo_Status'] = f"Error {api_resp.status_code}"
                    
            except requests.exceptions.Timeout:
                row['Eval_Repo_Status'] = "Timeout"
            except requests.exceptions.RequestException as e:
                logger.debug(f"GitHub API error for {api_url}: {e}")
                row['Eval_Repo_Status'] = "API Error"
    
    return row

def download_file(session, url, course_id, student_name, filename):
    """Download a file from Moodle using the session and save it locally"""
    try:
        # Create directory structure: output/course_X/downloads/Student_Name/
        # Sanitize names to be safe for filesystem
        safe_student = "".join([c for c in student_name if c.isalnum() or c in (' ', '-', '_')]).strip()
        safe_filename = "".join([c for c in filename if c.isalnum() or c in (' ', '-', '_', '.')]).strip()
        
        base_dir = Path(f"output/course_{course_id}/downloads/{safe_student}")
        base_dir.mkdir(parents=True, exist_ok=True)
        
        local_path = base_dir / safe_filename
        
        # If already exists, return it (caching)
        if local_path.exists():
            return str(local_path)
            
        response = session.get(url, stream=True)
        if response.status_code == 200:
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return str(local_path)
        else:
            return None
        return None
    except Exception as e:
        print(f"Download error: {e}")
        return None

def get_course_groups(session, course_id):
    """
    Fetch all groups for a given course.
    Returns: List of dicts [{'id': '123', 'name': 'Group A'}, ...]
    """
    groups_url = f"{BASE}/group/index.php?id={course_id}"
    try:
        resp = session.get(groups_url, timeout=10)
        if not resp.ok:
            logger.error(f"Failed to fetch groups: {resp.status_code}")
            return []
        
        soup = BeautifulSoup(resp.text, "html.parser")
        select = soup.find("select", {"id": "groups"})
        if not select:
            # Maybe there are no groups or no access?
            return []
            
        groups = []
        for option in select.find_all("option"):
            groups.append({
                "id": option.get("value"),
                "name": option.text.strip()
            })
        return groups
    except Exception as e:
        logger.error(f"Error fetching course groups: {e}")
        return []

def update_topic_restriction(session, course_id, topic_id, sesskey, restriction_json):
    """
    Update access restrictions for a topic.
    First fetches current section data to preserve the name.
    """
    url = f"{BASE}/course/editsection.php"
    
    # First GET the edit form to extract current name and other values
    get_url = f"{BASE}/course/editsection.php?id={topic_id}&sr=0"
    
    try:
        get_resp = session.get(get_url, timeout=15)
        if not get_resp.ok:
            logger.warning(f"Could not GET section edit page: {get_resp.status_code}")
            return False
            
        soup = BeautifulSoup(get_resp.text, "html.parser")
        
        # Extract current name value - field is name[customize] and name[value]
        name_customize = "0"
        name_value = ""
        
        # Look for name[customize] checkbox/hidden field
        name_customize_input = soup.find("input", {"name": "name[customize]", "value": "1"})
        if name_customize_input and name_customize_input.get("checked"):
            name_customize = "1"
        
        # Also check hidden input with value="1"
        for inp in soup.find_all("input", {"name": "name[customize]"}):
            if inp.get("type") == "hidden" and inp.get("value") == "1":
                # Check if the corresponding checkbox exists and is checked
                pass
            if inp.get("type") == "checkbox" and inp.get("checked"):
                name_customize = "1"
        
        # Get the name value from the text input
        name_value_input = soup.find("input", {"name": "name[value]"})
        if name_value_input:
            name_value = name_value_input.get("value", "")
            logger.info(f"Found name[value] = '{name_value}'")
        
        # Extract summary_editor fields
        summary_text = ""
        summary_format = "1"
        summary_itemid = ""
        
        summary_text_el = soup.find("textarea", {"name": "summary_editor[text]"})
        if summary_text_el:
            summary_text = summary_text_el.get_text() or ""
        
        summary_format_el = soup.find("input", {"name": "summary_editor[format]"})
        if summary_format_el:
            summary_format = summary_format_el.get("value", "1")
            
        summary_itemid_el = soup.find("input", {"name": "summary_editor[itemid]"})
        if summary_itemid_el:
            summary_itemid = summary_itemid_el.get("value", "")
        
        # If name[value] has a value, it means customize is enabled
        if name_value:
            name_customize = "1"
        
        # CRITICAL: Extract fresh sesskey from the form page (passed sesskey may be stale)
        fresh_sesskey = sesskey  # Fallback to passed value
        sesskey_input = soup.find("input", {"name": "sesskey"})
        if sesskey_input and sesskey_input.get("value"):
            fresh_sesskey = sesskey_input.get("value")
            logger.info(f"Using fresh sesskey from form: {fresh_sesskey[:8]}...")
        
        logger.info(f"[DEBUG] topic_id={topic_id}, name_customize={name_customize}, name_value='{name_value[:50] if name_value else ''}'")
        
        # Build payload matching Moodle's actual form structure
        # Note: Moodle sends name[customize] twice (0 and 1) when checkbox is checked
        payload = {
            "id": topic_id,
            "sr": "0", 
            "sesskey": fresh_sesskey,  # Use fresh sesskey
            "_qf__editsection_form": "1",
            "mform_isexpanded_id_availabilityconditions": "1",
            "mform_isexpanded_id_generalhdr": "1",
            "name[value]": name_value,
            "summary_editor[text]": summary_text,
            "summary_editor[format]": summary_format,
            "summary_editor[itemid]": summary_itemid,
            "availabilityconditionsjson": restriction_json,
            "submitbutton": "Save changes"
        }
        
        # Handle name[customize] - Moodle expects it twice when checked
        if name_customize == "1":
            # When custom name is enabled, send both values
            payload_list = list(payload.items())
            # Insert name[customize]=0 and name[customize]=1 after sr
            insert_idx = 2
            payload_list.insert(insert_idx, ("name[customize]", "0"))
            payload_list.insert(insert_idx + 1, ("name[customize]", "1"))
            
            # Use requests with a list of tuples to allow duplicate keys
            logger.info(f"Updating restriction for topic {topic_id} (name='{name_value[:30] if name_value else 'EMPTY'}...')")
            resp = session.post(url, data=payload_list, timeout=15)
        else:
            # Default section name - just send customize=0
            payload["name[customize]"] = "0"
            logger.info(f"Updating restriction for topic {topic_id} (default name)")
            resp = session.post(url, data=payload, timeout=15)
        
        if resp.ok:
            logger.info("Restriction update successful (likely)")
            return True
        else:
             logger.warning(f"Restriction update failed: {resp.status_code}")
             return False
    except Exception as e:
        logger.error(f"Error updating restriction: {e}")
        return False


def add_or_update_group_restriction(existing_json_str, group_ids):
    """
    Safely adds or updates group restrictions.
    - If multiple groups are provided, creates a nested OR restriction set (Access Set).
    - Preserves other conditions.
    - Ensures showc array matches 'c' length.
    
    Args:
        existing_json_str: Current JSON string.
        group_ids: List of group IDs (strings or ints).
    """
    import json
    
    # Identify groups
    if group_ids is None: group_ids = []
    if not isinstance(group_ids, list): group_ids = [group_ids]
    group_ids = [int(g) for g in group_ids if g]
    
    # 1. Parse or Init
    data = {"op": "&", "c": [], "showc": [True]}
    if existing_json_str:
        try:
            parsed = json.loads(existing_json_str)
            if isinstance(parsed, dict):
                data = parsed
                if 'c' not in data: data['c'] = []
        except:
            pass

    # 2. Recursively remove ALL existing group conditions
    # This is a simplification: we assume we want to replace ALL group rules with the new selection.
    # To be safer, maybe we only remove top-level? 
    # But usually, if managing groups via this UI, we want to control the 'Group' aspect fully.
    
    def remove_groups_recursive(cond_list):
        kept = []
        for c in cond_list:
            if 'c' in c: # Nested
                # Recurse
                remove_groups_recursive(c['c'])
                # If nested block becomes empty/useless, maybe drop it? 
                # For now let's keep it to be safe, unless empty.
                # Update showc for the nested block too
                if 'showc' in c:
                     c['showc'] = [True] * len(c['c'])
                kept.append(c)
            elif c.get('type') == 'group':
                continue # Skip groups
            else:
                kept.append(c)
        
        # Modify list in place? No, we need to return new list or modify the passed one.
        # Since we are iterating, let's just clear and extend.
        cond_list[:] = kept

    remove_groups_recursive(data['c'])

    # 3. Construct New Group Condition(s)
    if group_ids:
        if len(group_ids) == 1:
            # Single group: Add directly to root
            data['c'].append({
                "type": "group",
                "id": group_ids[0]
            })
        else:
            # Multiple groups: Wrap in OR block (Nested Restriction Set)
            # "Student must match ANY of the following groups"
            nested_set = {
                "op": "|",
                "c": [{"type": "group", "id": gid} for gid in group_ids],
                "showc": [True] * len(group_ids)
            }
            data['c'].append(nested_set)

    # 4. CRITICAL: Fix root 'showc' length
    # The user warned us: showc must match c length.
    data['showc'] = [True] * len(data['c'])
    
    return json.dumps(data)


def add_grade_restriction_to_json(existing_json_str, grade_item_id, min_grade=50, max_grade=None):
    """
    Add a grade restriction to existing restriction JSON.
    Preserves other conditions (groups, dates, etc).
    
    Args:
        existing_json_str: Current JSON string (can be None or empty)
        grade_item_id: The grade item ID (from get_course_grade_items)
        min_grade: Minimum grade percentage (default 50)
        max_grade: Maximum grade percentage (optional)
    
    Returns:
        Updated JSON string
    """
    import json
    
    # Parse or initialize
    data = {"op": "&", "c": [], "showc": []}
    if existing_json_str:
        try:
            parsed = json.loads(existing_json_str)
            if isinstance(parsed, dict):
                data = parsed
                if 'c' not in data: data['c'] = []
                if 'showc' not in data: data['showc'] = []
        except:
            pass
    
    # Remove any existing grade restrictions (we'll add the new one)
    # We want to ADD, not replace, so let's just add without removing
    # But if the same grade item already exists, update it
    existing_grade_idx = None
    for i, c in enumerate(data['c']):
        if c.get('type') == 'grade' and str(c.get('id')) == str(grade_item_id):
            existing_grade_idx = i
            break
    
    # Build the grade condition
    grade_cond = {
        "type": "grade",
        "id": int(grade_item_id)
    }
    if min_grade is not None:
        grade_cond["min"] = float(min_grade)
    if max_grade is not None:
        grade_cond["max"] = float(max_grade)
    
    if existing_grade_idx is not None:
        # Update existing
        data['c'][existing_grade_idx] = grade_cond
    else:
        # Add new
        data['c'].append(grade_cond)
    
    # Fix showc to match c length
    data['showc'] = [True] * len(data['c'])
    
    return json.dumps(data)


def update_restrictions_batch(existing_json_str, group_ids=None, date_cond=None, grade_cond=None,
                              completion_cond=None, operator="&", hide_on_restriction_not_met=False):
    """
    Updates the JSON with new restriction settings.
    - operator: "&" for ALL conditions must be met, "|" for ANY condition
    - Groups: REPLACES all existing group restrictions with the new list (or removes if empty).
    - Date: REPLACES any existing date restriction (if provided).
    - Grade: REPLACES any existing grade restriction (if provided).
    - Completion: REPLACES any existing completion restriction (if provided).
    - hide_on_restriction_not_met: If True, sets showc to [false] to hide content when restriction not met
    """
    import json

    # 1. Parse or Init
    data = {"op": operator, "c": [], "showc": []}
    if existing_json_str:
        try:
            parsed = json.loads(existing_json_str)
            if isinstance(parsed, dict):
                data = parsed
                data["op"] = operator  # Update operator to user's choice
                if 'c' not in data: data['c'] = []
        except: pass

    # Helper to remove conditions by type (recursively)
    def remove_type_recursive(cond_list, cond_type):
        kept = []
        for c in cond_list:
            if 'c' in c:  # Nested set
                remove_type_recursive(c['c'], cond_type)
                if 'showc' in c: c['showc'] = [True] * len(c['c'])
                # Only keep nested set if it still has conditions
                if c['c']:
                    kept.append(c)
            elif c.get('type') == cond_type:
                continue  # Remove this condition
            else:
                kept.append(c)
        cond_list[:] = kept

    # 2. Handle Groups (Replace Logic)
    if group_ids is not None:
        remove_type_recursive(data['c'], 'group')
        
        if not isinstance(group_ids, list): group_ids = [group_ids]
        group_ids = [int(g) for g in group_ids if g]
        
        if group_ids:
            if len(group_ids) == 1:
                # Single group: Add directly
                data['c'].append({"type": "group", "id": group_ids[0]})
            elif operator == "|":
                # Top-level is OR: Add each group directly (no nesting needed)
                # Because "any of" already applies to all conditions
                for gid in group_ids:
                    data['c'].append({"type": "group", "id": gid})
            else:
                # Top-level is AND: Wrap groups in OR block
                # "ALL conditions must be met, AND student must be in ANY of these groups"
                nested_set = {
                    "op": "|",
                    "c": [{"type": "group", "id": gid} for gid in group_ids],
                    "showc": [True] * len(group_ids)
                }
                data['c'].append(nested_set)

    # 3. Handle Date (Replace Logic)
    if date_cond is not None:
        remove_type_recursive(data['c'], 'date')
        if date_cond:  # Only add if not empty dict
            data['c'].append(date_cond)

    # 4. Handle Grade (Replace Logic)
    if grade_cond is not None:
        remove_type_recursive(data['c'], 'grade')
        if grade_cond:
            data['c'].append(grade_cond)

    # 5. Handle Activity Completion (Replace Logic)
    if completion_cond is not None:
        remove_type_recursive(data['c'], 'completion')
        if completion_cond:
            data['c'].append(completion_cond)

    # 6. Fix showc - Moodle always uses showc as an array (one boolean per condition)
    # Based on real Burp requests, Moodle expects showc=[true/false, true/false, ...]
    # where each element corresponds to whether that condition should be shown when not met

    # Determine visibility value based on hide_on_restriction_not_met parameter
    visibility_value = not hide_on_restriction_not_met

    # Always use showc array format (one per condition)
    if len(data['c']) > 0:
        data['showc'] = [visibility_value] * len(data['c'])
    else:
        # No conditions - remove showc
        data['showc'] = []

    # Remove 'show' if it exists (old format, not used by Moodle in restriction context)
    if 'show' in data:
        del data['show']

    return json.dumps(data)


def get_course_grade_items(session, course_id, topics=None):
    """
    Fetch valid GRADE ITEM IDs from the Moodle Availability Configuration.
    This requires fetching a Topic Edit page to access the M.core_availability.form.init JSON.
    Returns a dict: { '4602': 'Practice Quiz 15', ... } (Keys are Grade Item IDs, NOT Module IDs)

    Args:
        session: Requests session
        course_id: Course ID
        topics: Optional pre-fetched topics list to avoid redundant fetch
    """
    import re
    import json

    logger.info(f"Fetching grade items for course {course_id} via Availability Config")

    # 1. We need a valid Topic ID to access the editsection page.
    # Use provided topics or fetch if not provided
    if topics is None:
        topics = get_topics(session, course_id)

    if not topics:
        logger.warning("No topics found. Cannot fetch grade configuration.")
        return {}

    # Use the first available topic that has a valid DB ID
    valid_topic_id = None
    for t in topics:
        if t.get("DB ID"):
            valid_topic_id = t["DB ID"]
            break

    if not valid_topic_id:
        logger.warning("No topic with valid DB ID found. Cannot fetch grade config.")
        return {}
    
    url = f"{BASE}/course/editsection.php?id={valid_topic_id}"
    
    for attempt in range(2):
        try:
            resp = session.get(url, timeout=30)
            if not resp.ok:
                logger.warning(f"Failed to fetch edit page: {resp.status_code}")
                continue
                
            # 2. Extract M.core_availability.form.init({...})
            # This JSON contains the "grade" plugin configuration with ID mapping.
            pattern = r"M\.core_availability\.form\.init\((.*?)\);"
            match = re.search(pattern, resp.text, re.DOTALL)
            
            if not match:
                logger.warning("Availability Init JSON not found in edit page.")
                continue # Retry or fail
                
            json_text = match.group(1)
            data = json.loads(json_text)
            
            # 3. Parse 'grade' items
            # Structure: data['grade'] -> [plugin_name, is_enabled, [ [ {id: ..., name: ...}, ... ] ]]
            # The structure is deeply nested lists.
            # We look for the list containing dicts with "id" and "name".
            
            items = {}
            
            # Helper to recursively search for dicts with id/name in a structure
            def extract_items(obj, items_dict):
                if isinstance(obj, dict):
                    if 'id' in obj and 'name' in obj:
                        if obj['name']:  # Ignore empty names
                            items_dict[str(obj['id'])] = obj['name']
                    return
                if isinstance(obj, list):
                    for x in obj:
                        extract_items(x, items_dict)

            grade_items = {}
            completion_items = {}
            
            if 'grade' in data:
                extract_items(data['grade'], grade_items)
            
            # Extract completion activities (similar structure)
            if 'completion' in data:
                extract_items(data['completion'], completion_items)
                
            logger.info(f"Found {len(grade_items)} Grade Items, {len(completion_items)} Completion Activities")
            return grade_items, completion_items
            
        except Exception as e:
            logger.error(f"Error extracting grade items: {e}")
            
    return {}, {}


def get_restriction_summary(json_str, grade_items_map=None):
    """
    Returns a list of descriptions for existing restrictions (Recursive).
    Uses visual tree characters for nesting.
    """
    import json
    if not json_str: return []
    if grade_items_map is None: grade_items_map = {}
    
    descriptions = []
    
    def parse_cond(c_list, indent=0):
        for i, c in enumerate(c_list):
            is_last = (i == len(c_list) - 1)
            prefix = "│  " * indent
            bullet = "└─ " if is_last else "├─ "
            
            if 'c' in c: # Nested operator
                op = c.get('op', '&')
                op_str = "[ALL of]:" if op == '&' else "[ANY of]:"
                descriptions.append(f"{prefix}{bullet}{op_str}")
                parse_cond(c.get('c', []), indent + 1)
                continue
                
            ctype = c.get('type')
            if ctype == 'date':
                d = c.get('d', '')
                t = c.get('t', 0)
                from datetime import datetime
                dt = datetime.fromtimestamp(int(t)).strftime('%Y-%m-%d %H:%M')
                direction = "From" if ">" in d else "Until"
                descriptions.append(f"{prefix}{bullet}Date: {direction} {dt}")
                
            elif ctype == 'completion':
                cm = str(c.get('cm', ''))
                name = grade_items_map.get(cm, f"Activity #{cm}")
                state = c.get('e', 1)
                state_str = "Complete" if state == 1 else "Incomplete"
                descriptions.append(f"{prefix}{bullet}Completion: '{name}' → {state_str}")
                
            elif ctype == 'grade':
                gid = str(c.get('id', ''))
                name = grade_items_map.get(gid, f"Item #{gid}")
                min_g = c.get('min', '')
                max_g = c.get('max', '')
                cond_str = ""
                if min_g: cond_str += f" >= {min_g}%"
                if max_g: cond_str += f" < {max_g}%"
                descriptions.append(f"{prefix}{bullet}Grade: '{name}'{cond_str}")
                
            elif ctype == 'profile':
                sf = c.get('sf', 'field')
                op = c.get('op', 'is')
                v = c.get('v', '')
                descriptions.append(f"{prefix}{bullet}Profile: {sf} {op} '{v}'")
                
            elif ctype == 'group':
                gid = c.get('id')
                descriptions.append(f"{prefix}{bullet}Group (ID: {gid})")
                
    try:
        data = json.loads(json_str)
        if 'c' in data:
            # Check if conditions array is empty - no actual restrictions
            if not data['c']:
                return []
            # Show the TOP-LEVEL operator
            top_op = data.get('op', '&')
            top_op_str = "Match ALL of:" if top_op == '&' else "Match ANY of:"
            descriptions.append(f"• {top_op_str}")
            # Then parse conditions
            parse_cond(data['c'], indent=0)
        return descriptions
    except:
        return ["Error parsing restriction JSON"]

def get_topic_restriction(session, topic_id):
    """
    Fetch the existing availability restriction JSON for a topic.
    GET /course/editsection.php?id=...
    """
    url = f"{BASE}/course/editsection.php?id={topic_id}"
    try:
        resp = session.get(url, timeout=10)
        if not resp.ok: 
            logger.error(f"Failed to fetch restriction page: {resp.status_code}")
            return None
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # 1. Try hidden input (Standard Moodle) or Textarea (Some themes)
        inp = soup.find("input", {"name": "availabilityconditionsjson"})
        if not inp:
            inp = soup.find("textarea", {"name": "availabilityconditionsjson"})
            
        if inp:
            val = inp.get("value", "") if inp.name == "input" else inp.text
            logger.info(f"Fetched restriction JSON for {topic_id} ({inp.name}): {val:.100}...")
            return val
            
        # 2. Try JavaScript Init (Newer Moodle / Theme)
        # Search for M.core_availability.form.init(...)
        import json
        pattern = r"M\.core_availability\.form\.init\((.*?)\);"
        logger.info(f"Searching for pattern in {len(resp.text)} chars")
        matches = re.findall(pattern, resp.text, re.DOTALL)
        logger.info(f"Found {len(matches)} matches")
        
        for i, m in enumerate(matches):
            logger.info(f"Checking match {i} length {len(m)}")
            try:
                data = json.loads(m)
                # Structure: {"fields": {"availabilityconditionsjson": {"value": "..."}}}
                if 'fields' in data and 'availabilityconditionsjson' in data['fields']:
                     val = data['fields']['availabilityconditionsjson'].get('value', '')
                     logger.info(f"Fetched restriction JSON for {topic_id} (JS): {val:.100}...")
                     return val
            except Exception as e:
                logger.error(f"JSON load error in get_topic_restriction: {e}")
                pass
        
        logger.warning(f"No availability input found for topic {topic_id}")
        return None
    except Exception as e:
        logger.error(f"Error fetching restriction: {e}")
        return None


# ============================================================================
# FEEDBACK MODULE FUNCTIONS
# ============================================================================

def get_feedbacks(session, course_id):
    """
    Get list of feedback activities from course page.
    
    Returns list of tuples: (name, module_id, url)
    """
    url = f"{BASE}/course/view.php?id={course_id}"
    resp = session.get(url)
    if not resp.ok:
        return []
    
    soup = BeautifulSoup(resp.text, "html.parser")
    
    feedbacks = []
    items = soup.find_all("li", class_=lambda c: c and "modtype_feedback" in c)
    
    for item in items:
        link = item.find("a", href=re.compile(r"mod/feedback/view\.php\?id=\d+"))
        if not link:
            link = item.find("a", href=re.compile(r"/mod/feedback/"))
        if link:
            name = link.get_text(strip=True)
            href = link.get("href", "")
            m = re.search(r"[?&]id=(\d+)", href)
            module_id = m.group(1) if m else ""
            if href.startswith("/"):
                href = BASE + href
            elif not href.startswith("http"):
                href = BASE + "/" + href.lstrip("/")
            
            feedbacks.append((name, module_id, href))
    
    return feedbacks


def fetch_feedback_overview(session_id, module_id, group_id=None):
    """
    Fetch overview data from feedback view page.
    
    Returns dict with:
    - name: Feedback name
    - submitted_answers: Number of responses
    - questions: Number of questions
    - allow_from: Start date
    - allow_until: End date (if available)
    """
    session = setup_session(session_id)
    url = f"{BASE}/mod/feedback/view.php?id={module_id}"
    if group_id:
        url += f"&group={group_id}"
    
    try:
        resp = session.get(url, timeout=30)
        if not resp.ok:
            return {}
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        overview = {
            'name': '',
            'submitted_answers': 0,
            'questions': 0,
            'allow_from': '',
            'allow_until': ''
        }
        
        # Get feedback name from h2
        h2 = soup.find('h2')
        if h2:
            overview['name'] = h2.get_text(strip=True)
        
        # Parse overview section using feedback_info divs
        # Structure: <div class="feedback_info"><span class="feedback_info">Label:</span><span class="feedback_info_value">Value</span></div>
        info_divs = soup.find_all('div', class_='feedback_info')
        
        for div in info_divs:
            label_span = div.find('span', class_='feedback_info')
            value_span = div.find('span', class_='feedback_info_value')
            
            if label_span and value_span:
                label = label_span.get_text(strip=True).lower()
                value = value_span.get_text(strip=True)
                
                if 'submitted answers' in label:
                    try:
                        overview['submitted_answers'] = int(value)
                    except ValueError:
                        pass
                elif 'questions' in label:
                    try:
                        overview['questions'] = int(value)
                    except ValueError:
                        pass
                elif 'allow answers from' in label:
                    overview['allow_from'] = value
                elif 'allow answers to' in label:
                    # Note: Moodle uses "Allow answers to" not "until"
                    overview['allow_until'] = value
        
        return overview
    except Exception as e:
        logger.error(f"Error fetching feedback overview: {e}")
        return {}


def fetch_feedback_responses(session_id, module_id, group_id=None):
    """
    Fetch feedback responses from show_entries page.
    
    Returns tuple: (column_names, list of dicts with response data)
    
    The table has dynamic columns based on the feedback questions.
    Standard columns: User picture (skipped), First name/Surname, Groups, Date
    Dynamic columns: Question responses (classes like val12136, val12137, etc.)
    """
    session = setup_session(session_id)
    url = f"{BASE}/mod/feedback/show_entries.php?id={module_id}"
    if group_id:
        url += f"&group={group_id}"
    
    try:
        resp = session.get(url, timeout=60)
        if not resp.ok:
            return [], []
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Find the responses table
        table = soup.find("table", id="showentrytable")
        if not table:
            table = soup.find("table", class_="generaltable")
        
        if not table:
            logger.warning("No feedback responses table found")
            return [], []
        
        # Parse headers to get column names
        headers = []
        header_row = table.find("thead")
        if header_row:
            for th in header_row.find_all("th"):
                # Get the column class to identify column type
                classes = th.get("class", [])
                col_class = ""
                for cls in classes:
                    if cls.startswith("c") and cls[1:].isdigit():
                        continue  # Skip position classes like c0, c1
                    if cls != "header":
                        col_class = cls
                        break
                
                # Get header text (clean up sort links, etc.)
                header_text = ""
                # Try to get text from links first
                link = th.find("a")
                if link:
                    header_text = link.get_text(strip=True)
                else:
                    header_text = th.get_text(strip=True)
                
                # Clean up hidden accessibility text
                accesshide = th.find("span", class_="accesshide")
                if accesshide:
                    accesshide_text = accesshide.get_text()
                    header_text = header_text.replace(accesshide_text, "").strip()
                
                # Skip userpic, deleteentry, and groups columns
                if col_class in ("userpic", "deleteentry", "groups"):
                    headers.append(None)  # Placeholder to keep index alignment
                else:
                    headers.append(header_text if header_text else col_class)
        
        # Parse data rows
        rows = []
        tbody = table.find("tbody")
        if tbody:
            for tr in tbody.find_all("tr"):
                # Skip empty rows
                if "emptyrow" in tr.get("class", []):
                    continue
                
                row_data = {}
                cells = tr.find_all("td")
                
                for i, td in enumerate(cells):
                    if i >= len(headers):
                        break
                    
                    header = headers[i]
                    if header is None:  # Skip userpic/deleteentry columns
                        continue
                    
                    # Get cell text
                    cell_text = ""
                    link = td.find("a")
                    if link:
                        cell_text = link.get_text(strip=True)
                    else:
                        cell_text = td.get_text(strip=True)
                    
                    row_data[header] = cell_text
                
                if row_data:  # Only add non-empty rows
                    rows.append(row_data)
        
        # Get clean list of column names (excluding None placeholders)
        column_names = [h for h in headers if h is not None]
        
        return column_names, rows
    except Exception as e:
        logger.error(f"Error fetching feedback responses: {e}")
        return [], []


def fetch_feedback_non_respondents(session_id, module_id, group_id=None):
    """
    Fetch list of users who haven't responded to the feedback.
    
    Returns list of dicts with user info (name, groups, etc.)
    """
    session = setup_session(session_id)
    url = f"{BASE}/mod/feedback/show_nonrespondents.php?id={module_id}"
    if group_id:
        url += f"&group={group_id}"
    
    try:
        resp = session.get(url, timeout=60)
        if not resp.ok:
            return []
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Find the non-respondents table
        table = soup.find("table", class_="generaltable")
        if not table:
            # Check for "No users" message
            page_text = soup.get_text()
            if "no users" in page_text.lower() or "all users have responded" in page_text.lower():
                return []
            logger.warning("No non-respondents table found")
            return []
        
        # Parse headers
        headers = []
        header_row = table.find("thead") or table.find("tr")
        if header_row:
            for th in header_row.find_all(["th", "td"]):
                header_text = th.get_text(strip=True)
                # Skip picture column
                if "picture" in header_text.lower():
                    headers.append(None)
                else:
                    headers.append(header_text)
        
        # Parse data rows
        rows = []
        tbody = table.find("tbody") or table
        for tr in tbody.find_all("tr"):
            # Skip header row if no thead
            if tr.find("th"):
                continue
            
            # Skip empty rows (Moodle uses emptyrow class for placeholder rows)
            tr_classes = tr.get("class", [])
            if "emptyrow" in tr_classes:
                continue
            
            row_data = {}
            cells = tr.find_all("td")
            
            for i, td in enumerate(cells):
                if i >= len(headers):
                    break
                
                header = headers[i]
                if header is None:  # Skip picture column
                    continue
                
                cell_text = ""
                link = td.find("a")
                if link:
                    cell_text = link.get_text(strip=True)
                else:
                    cell_text = td.get_text(strip=True)
                
                row_data[header] = cell_text
            
            # Only add rows that have actual data (not just empty cells)
            if row_data and any(v.strip() for v in row_data.values()):
                rows.append(row_data)
        
        return rows
    except Exception as e:
        logger.error(f"Error fetching non-respondents: {e}")
        return []


# =============================================================================
# TryHackMe API Functions
# =============================================================================

def clean_name(name):
    """
    Remove batch suffix from participant names.
    E.g., 'Jovan Jacob CL-SMP-CSA-14-NOV-2025-TVM' -> 'Jovan Jacob'
    """
    if not name:
        return name
    # Pattern: space followed by batch code starting with CL- or similar pattern
    # Common patterns: CL-SMP-..., CL-FSD-..., etc.
    import re
    # Match pattern: space + uppercase letters + hyphen + more chars (batch code)
    cleaned = re.sub(r'\s+[A-Z]{2,}-[A-Z]{2,}-.*$', '', name)
    return cleaned.strip()


def extract_thm_username(raw_value):
    """
    Extract TryHackMe username from URL or raw text.
    
    Handles:
    - Full URLs: 'https://tryhackme.com/p/username' -> 'username'
    - Direct username: 'username' -> 'username'
    - URLs with extra paths: 'https://tryhackme.com/p/user/path' -> 'user'
    """
    if not raw_value:
        return None
    
    value = raw_value.strip()
    
    # Handle URLs
    if 'tryhackme.com' in value:
        import re
        # Match /p/username or /r/username pattern
        match = re.search(r'tryhackme\.com/(?:p|r)/([a-zA-Z0-9._-]+)', value)
        if match:
            return match.group(1)
        # Try to get last path segment if /p/ pattern not found
        match = re.search(r'tryhackme\.com/([a-zA-Z0-9._-]+)/?$', value)
        if match:
            return match.group(1)
    
    # Direct username - just return as-is (remove any whitespace/special chars at edges)
    # But validate it looks like a username (alphanumeric, dots, underscores, hyphens)
    import re
    if re.match(r'^[a-zA-Z0-9._-]+$', value):
        return value
    
    return None


def fetch_thm_user_data(username):
    """
    Fetch TryHackMe user data from public API.
    
    Returns dict with:
    - username: The username
    - completed_rooms: Number of completed rooms
    - avatar: Avatar URL
    - error: Error message if failed
    """
    if not username:
        return {"username": username, "completed_rooms": 0, "avatar": None, "error": "No username"}
    
    result = {
        "username": username,
        "completed_rooms": 0,
        "avatar": None,
        "error": None
    }
    
    try:
        import requests
        
        # Add small delay to avoid rate limiting
        time.sleep(0.2)
        
        # Fetch completed rooms count
        rooms_url = f"https://tryhackme.com/api/no-completed-rooms-public/{username}"
        rooms_resp = requests.get(rooms_url, timeout=10)
        if rooms_resp.ok:
            try:
                result["completed_rooms"] = int(rooms_resp.text.strip())
            except ValueError:
                result["completed_rooms"] = 0
        
        # Fetch user info (avatar)
        user_url = f"https://tryhackme.com/api/discord/user/{username}"
        user_resp = requests.get(user_url, timeout=10)
        if user_resp.ok:
            user_data = user_resp.json()
            result["avatar"] = user_data.get("avatar", "")
        
    except requests.exceptions.Timeout:
        result["error"] = "Timeout"
    except requests.exceptions.RequestException as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = str(e)
    
    return result
