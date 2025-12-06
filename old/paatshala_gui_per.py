#!/usr/bin/env python3
"""
Paatshala Tool - GUI Version (Streamlit) with Full Persistence

Features:
- Auto-login from .config
- Remember credentials option
- Last session memory
- Auto-save to output folder
- Load existing data with staleness indicator
- Browser download + local storage

Usage:
    pip install streamlit
    streamlit run paatshala_gui.py
"""

import os
import re
import csv
import json
import time
import threading
from io import StringIO
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st
import requests
from bs4 import BeautifulSoup

# ============================================================================
# CONFIGURATION
# ============================================================================

BASE = "https://paatshala.ictkerala.org"
PAATSHALA_HOST = "paatshala.ictkerala.org"
CONFIG_FILE = ".config"
LAST_SESSION_FILE = ".last_session"
OUTPUT_DIR = "output"
DEFAULT_THREADS = 4

# Thread-local storage for sessions
thread_local = threading.local()

# ============================================================================
# PAGE CONFIG
# ============================================================================

st.set_page_config(
    page_title="Paatshala Tool",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# CUSTOM CSS
# ============================================================================

st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1f77b4;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .stale-badge {
        padding: 0.25rem 0.75rem;
        border-radius: 1rem;
        background-color: #f0f2f6;
        color: #666;
        font-size: 0.85rem;
        display: inline-block;
        margin-bottom: 1rem;
    }
    .fresh-badge {
        padding: 0.25rem 0.75rem;
        border-radius: 1rem;
        background-color: #d4edda;
        color: #155724;
        font-size: 0.85rem;
        display: inline-block;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

def init_session_state():
    """Initialize all session state variables"""
    defaults = {
        'authenticated': False,
        'session_id': None,
        'auth_source': None,  # 'config', 'manual', 'cookie'
        'courses': [],
        'selected_course': None,
        'tasks_data': None,
        'tasks_loaded_from_disk': False,
        'quiz_data': None,
        'quiz_loaded_from_disk': False,
        'submissions_data': None,
        'submissions_loaded_from_disk': False,
        'auto_login_attempted': False,
        'selected_task_for_submissions': None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# ============================================================================
# PERSISTENCE: CONFIG FILE
# ============================================================================

def read_config(config_path=CONFIG_FILE):
    """Read cookie, username, and password from config file"""
    if not os.path.exists(config_path):
        return None, None, None
    
    cookie, username, password = None, None, None
    try:
        with open(config_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip().lower()
                    value = value.strip().strip('"').strip("'")
                    if key == 'cookie':
                        cookie = value
                    elif key == 'username':
                        username = value
                    elif key == 'password':
                        password = value
        return cookie, username, password
    except Exception:
        return None, None, None


def write_config(config_path=CONFIG_FILE, cookie=None, username=None, password=None):
    """Write cookie or credentials to config file"""
    try:
        lines = []
        existing_keys = set()
        
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                for line in f:
                    line_stripped = line.strip()
                    if not line_stripped or line_stripped.startswith('#'):
                        lines.append(line)
                        continue
                    if '=' in line_stripped:
                        key = line_stripped.split('=', 1)[0].strip().lower()
                        existing_keys.add(key)
                        if cookie and key == 'cookie':
                            continue
                        if username and key == 'username':
                            continue
                        if password and key == 'password':
                            continue
                        lines.append(line)
                    else:
                        lines.append(line)
        
        if cookie:
            if 'cookie' in existing_keys:
                lines.insert(0, f"cookie={cookie}\n")
            else:
                lines.append(f"cookie={cookie}\n")
        
        if username and 'username' not in existing_keys:
            lines.append(f"username={username}\n")
        
        if password and 'password' not in existing_keys:
            lines.append(f"password={password}\n")
        
        with open(config_path, 'w') as f:
            f.writelines(lines)
        
        return True
    except Exception:
        return False


def clear_config(config_path=CONFIG_FILE):
    """Remove saved credentials from config file"""
    try:
        if os.path.exists(config_path):
            os.remove(config_path)
        return True
    except Exception:
        return False


# ============================================================================
# PERSISTENCE: LAST SESSION
# ============================================================================

def load_last_session():
    """Load last session data"""
    if os.path.exists(LAST_SESSION_FILE):
        try:
            with open(LAST_SESSION_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_last_session(data):
    """Save session data for next run"""
    try:
        existing = load_last_session()
        existing.update(data)
        with open(LAST_SESSION_FILE, 'w') as f:
            json.dump(existing, f, indent=2)
        return True
    except:
        return False


# ============================================================================
# PERSISTENCE: OUTPUT FOLDER & META
# ============================================================================

def get_output_dir(course_id):
    """Get or create output directory for a course"""
    path = Path(OUTPUT_DIR) / f"course_{course_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_meta_path(course_id):
    """Get path to meta.json for a course"""
    return get_output_dir(course_id) / ".meta.json"


def load_meta(course_id):
    """Load metadata for a course"""
    meta_path = get_meta_path(course_id)
    if meta_path.exists():
        try:
            with open(meta_path, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_meta(course_id, key, rows_count):
    """Save metadata for a specific data type"""
    meta = load_meta(course_id)
    meta[key] = {
        "updated": datetime.now().isoformat(),
        "rows": rows_count
    }
    try:
        with open(get_meta_path(course_id), 'w') as f:
            json.dump(meta, f, indent=2)
    except:
        pass


def format_timestamp(iso_string):
    """Format ISO timestamp for display"""
    try:
        dt = datetime.fromisoformat(iso_string)
        now = datetime.now()
        diff = now - dt
        
        if diff.days == 0:
            if diff.seconds < 60:
                return "just now"
            elif diff.seconds < 3600:
                mins = diff.seconds // 60
                return f"{mins} min{'s' if mins > 1 else ''} ago"
            else:
                hours = diff.seconds // 3600
                return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif diff.days == 1:
            return f"yesterday at {dt.strftime('%I:%M %p')}"
        elif diff.days < 7:
            return f"{diff.days} days ago"
        else:
            return dt.strftime('%b %d, %Y at %I:%M %p')
    except:
        return iso_string


def save_csv_to_disk(course_id, filename, rows, fieldnames=None):
    """Save data to CSV file in output folder"""
    output_dir = get_output_dir(course_id)
    output_path = output_dir / filename
    
    if not rows:
        return None
    
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    
    try:
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return output_path
    except:
        return None


def load_csv_from_disk(course_id, filename):
    """Load data from CSV file in output folder"""
    output_dir = get_output_dir(course_id)
    file_path = output_dir / filename
    
    if not file_path.exists():
        return None
    
    try:
        rows = []
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
        return rows
    except:
        return None


# ============================================================================
# AUTHENTICATION FUNCTIONS
# ============================================================================

def login_and_get_cookie(username, password):
    """Login to Paathshala and extract session cookie"""
    try:
        response = requests.post(
            f"https://{PAATSHALA_HOST}/login/index.php",
            data={'username': username, 'password': password},
            allow_redirects=False,
            timeout=10
        )
        
        if 'MoodleSession' in response.cookies:
            return response.cookies['MoodleSession']
        return None
    except Exception:
        return None


def validate_session(session_id):
    """Check if a session cookie is valid"""
    try:
        s = requests.Session()
        s.cookies.set("MoodleSession", session_id, domain=PAATSHALA_HOST)
        s.headers.update({'User-Agent': 'Mozilla/5.0'})
        resp = s.get(f"{BASE}/my/", timeout=10)
        return resp.ok and 'login' not in resp.url.lower()
    except Exception:
        return False


def setup_session(session_id):
    """Create a requests session with auth cookie"""
    s = requests.Session()
    s.cookies.set("MoodleSession", session_id, domain=PAATSHALA_HOST)
    s.headers.update({'User-Agent': 'Mozilla/5.0'})
    return s


def get_thread_session(session_id):
    """Get or create a session for the current thread"""
    if not hasattr(thread_local, 'session'):
        thread_local.session = requests.Session()
        thread_local.session.cookies.set("MoodleSession", session_id, domain=PAATSHALA_HOST)
        thread_local.session.headers.update({'User-Agent': 'Mozilla/5.0'})
    return thread_local.session


def attempt_auto_login():
    """Try to auto-login from config file"""
    if st.session_state.auto_login_attempted:
        return False
    
    st.session_state.auto_login_attempted = True
    
    cookie, username, password = read_config()
    
    # Try cookie first
    if cookie:
        if validate_session(cookie):
            st.session_state.session_id = cookie
            st.session_state.authenticated = True
            st.session_state.auth_source = 'config_cookie'
            return True
    
    # Try credentials
    if username and password:
        session_id = login_and_get_cookie(username, password)
        if session_id:
            st.session_state.session_id = session_id
            st.session_state.authenticated = True
            st.session_state.auth_source = 'config_credentials'
            # Save new cookie for faster login next time
            write_config(cookie=session_id)
            return True
    
    return False


# ============================================================================
# COURSE FUNCTIONS
# ============================================================================

def get_courses(session):
    """Fetch all courses using Moodle's AJAX APIs"""
    courses_dict = {}
    
    try:
        resp = session.get(f"{BASE}/my/", timeout=15)
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


# ============================================================================
# TASKS FUNCTIONS
# ============================================================================

def text_or_none(node):
    return node.get_text(" ", strip=True) if node else ""


def find_table_label_value(soup, wanted_labels):
    """Scan tables for label-value pairs"""
    out = {}
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not th or not td:
                continue
            label = text_or_none(th).strip().lower()
            value = text_or_none(td).strip()
            for key in wanted_labels:
                if key in label and value:
                    out[key] = value
    return out


def parse_assign_view(html):
    """Extract assignment details from view page"""
    soup = BeautifulSoup(html, "html.parser")
    
    overview_labels = {
        "participants": "participants", "drafts": "drafts",
        "submitted": "submitted", "needs grading": "needs_grading",
        "due date": "due_date_overview", "time remaining": "time_remaining_overview",
        "late submissions": "late_policy",
    }
    overview = find_table_label_value(soup, overview_labels.keys())
    mapped_overview = {overview_labels[k]: v for k, v in overview.items()}
    
    status_labels = {
        "submission status": "submission_status", "grading status": "grading_status",
        "due date": "due_date_status", "time remaining": "time_remaining_status",
        "last modified": "last_modified", "submission comments": "submission_comments",
    }
    status = find_table_label_value(soup, status_labels.keys())
    mapped_status = {status_labels[k]: v for k, v in status.items()}
    
    grade_info = find_table_label_value(soup, ["maximum grade", "max grade"])
    max_grade = grade_info.get("maximum grade") or grade_info.get("max grade") or ""
    
    comments_count = ""
    for a in soup.find_all("a"):
        txt = a.get_text(" ", strip=True)
        m = re.search(r"Comments\s*\((\d+)\)", txt, flags=re.I)
        if m:
            comments_count = m.group(1)
            break
    
    due_date = mapped_status.get("due_date_status") or mapped_overview.get("due_date_overview") or ""
    time_remaining = mapped_status.get("time_remaining_status") or mapped_overview.get("time_remaining_overview") or ""
    
    return {
        "participants": mapped_overview.get("participants", ""),
        "drafts": mapped_overview.get("drafts", ""),
        "submitted": mapped_overview.get("submitted", ""),
        "needs_grading": mapped_overview.get("needs_grading", ""),
        "late_policy": mapped_overview.get("late_policy", ""),
        "due_date": due_date,
        "time_remaining": time_remaining,
        "submission_status": mapped_status.get("submission_status", ""),
        "grading_status": mapped_status.get("grading_status", ""),
        "last_modified": mapped_status.get("last_modified", ""),
        "submission_comments": comments_count,
        "max_grade": max_grade,
    }


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


def fetch_tasks_list(session_id, course_id, progress_callback=None):
    """Fetch all tasks for a course with details"""
    main_session = setup_session(session_id)
    tasks = get_tasks(main_session, course_id)
    
    if not tasks:
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
                    "URL": returned_url
                })
            except:
                pass
            
            completed += 1
            if progress_callback:
                progress_callback(completed / total)
    
    # Sort by original order
    task_order = {(name, mid): i for i, (name, mid, _) in enumerate(tasks)}
    rows.sort(key=lambda r: task_order.get((r["Task Name"], r["Module ID"]), 999))
    
    return rows


# ============================================================================
# QUIZ FUNCTIONS
# ============================================================================

def get_quizzes(session, course_id):
    """Get list of practice quizzes from course"""
    url = f"https://{PAATSHALA_HOST}/course/view.php?id={course_id}"
    resp = session.get(url)
    if not resp.ok:
        return []
    
    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.find_all("li", class_="modtype_quiz")
    
    quizzes = []
    for item in items:
        link = item.find("a", href=re.compile(r"mod/quiz/view\.php\?id=\d+"))
        if not link:
            continue
        name = link.get_text(strip=True)
        name = re.sub(r'\s+(Quiz)$', '', name)
        if "practice quiz" in name.lower():
            m = re.search(r"id=(\d+)", link.get("href", ""))
            if m:
                quizzes.append((name, m.group(1)))
    
    return quizzes


def fetch_quiz_scores(session_id, module_id):
    """Fetch scores for a quiz module"""
    s = get_thread_session(session_id)
    
    report_url = f"https://{PAATSHALA_HOST}/mod/quiz/report.php?id={module_id}&mode=overview"
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


def fetch_quiz_scores_all(session_id, course_id, progress_callback=None):
    """Fetch all quiz scores for a course"""
    main_session = setup_session(session_id)
    quizzes = get_quizzes(main_session, course_id)
    
    if not quizzes:
        return None, []
    
    all_scores = defaultdict(dict)
    quiz_names_ordered = [name for name, _ in quizzes]
    mid_to_name = {mid: name for name, mid in quizzes}
    total = len(quizzes)
    
    with ThreadPoolExecutor(max_workers=DEFAULT_THREADS) as executor:
        futures = {executor.submit(fetch_quiz_scores, session_id, mid): mid for _, mid in quizzes}
        
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
            row[quiz_name] = all_scores[student].get(quiz_name, "")
        rows.append(row)
    
    return quiz_names_ordered, rows


# ============================================================================
# SUBMISSIONS FUNCTIONS
# ============================================================================

def parse_grading_table(html):
    """Parse the grading table from assignment view page"""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="flexible generaltable generalbox")
    if not table:
        return []
    
    rows = []
    tbody = table.find("tbody")
    if not tbody:
        return []
    
    for tr in tbody.find_all("tr"):
        if "emptyrow" in tr.get("class", []):
            continue
        
        cells = tr.find_all(["th", "td"])
        if len(cells) < 14:
            continue
        
        name_cell = cells[2]
        name_link = name_cell.find("a")
        name = name_link.get_text(strip=True) if name_link else ""
        
        # Email is typically in cell 3
        email = text_or_none(cells[3])
        
        status_cell = cells[4]
        status_divs = status_cell.find_all("div")
        status = " | ".join([div.get_text(strip=True) for div in status_divs])
        
        last_modified = text_or_none(cells[7])
        
        submission_cell = cells[8]
        file_divs = submission_cell.find_all("div", class_="fileuploadsubmission")
        if file_divs:
            submissions = []
            for div in file_divs:
                file_link = div.find("a", href=lambda h: h and "pluginfile.php" in h)
                if file_link:
                    submissions.append(file_link.get_text(strip=True))
            submissions = ", ".join(submissions)
        else:
            no_overflow_div = submission_cell.find("div", class_="no-overflow")
            if no_overflow_div:
                submissions = no_overflow_div.get_text(" ", strip=True)
            else:
                submissions = text_or_none(submission_cell)
        
        feedback = text_or_none(cells[11])
        final_grade = text_or_none(cells[13])
        
        rows.append({
            "Name": name,
            "Email": email,
            "Status": status,
            "Last Modified": last_modified,
            "Submission": submissions,
            "Feedback Comments": feedback,
            "Final Grade": final_grade
        })
    
    return rows


def get_available_groups(session, module_id):
    """Get list of available groups for an assignment"""
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
            if group_id and group_name:
                groups.append((group_id, group_name))
        
        return groups
    except:
        return []


def fetch_submissions(session_id, module_id, group_id=None):
    """Fetch submissions for a specific task/module"""
    session = setup_session(session_id)
    
    url = f"{BASE}/mod/assign/view.php?id={module_id}&action=grading"
    if group_id:
        url += f"&group={group_id}"
    
    try:
        resp = session.get(url, timeout=30)
        if not resp.ok:
            return []
        return parse_grading_table(resp.text)
    except:
        return []


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
    
    if not submission_text:
        return row

    # Extract URL
    url_match = re.search(r'(https?://[^\s]+)', submission_text)
    if not url_match:
        return row
        
    url = url_match.group(1)
    row['Eval_Link'] = url
    
    # 1. Verify Link
    try:
        resp = requests.head(url, timeout=5, allow_redirects=True)
        row['Eval_Link_Valid'] = "✅" if resp.ok else "❌"
    except:
        row['Eval_Link_Valid'] = "❌ (Unreachable)"
    
    # 2. GitHub Checks
    if "github.com" in url:
        parts = url.rstrip('/').split('/')
        if len(parts) >= 5:
            owner = parts[-2]
            repo = parts[-1]
            api_url = f"https://api.github.com/repos/{owner}/{repo}"
            
            try:
                api_resp = requests.get(api_url, timeout=5)
                
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
                else:
                    row['Eval_Repo_Status'] = f"Error {api_resp.status_code}"
                    
            except:
                row['Eval_Repo_Status'] = "API Error"
    
    return row


def get_display_dataframe(data):
    """Create a display-friendly dataframe for the Evaluation tab"""
    display_data = []
    for r in data:
        display_data.append({
            "Name": r.get('Name'),
            "Status": r.get('Status'),
            "Link": r.get('Eval_Link'),
            "Valid?": r.get('Eval_Link_Valid'),
            "Repo Status": r.get('Eval_Repo_Status'),
            "Fork?": r.get('Eval_Is_Fork'),
            "Parent": r.get('Eval_Parent'),
            "Checked": format_timestamp(r.get('Eval_Last_Checked', ''))
        })
    return display_data


# ============================================================================
# CSV HELPERS
# ============================================================================

def dataframe_to_csv(rows, columns=None):
    """Convert list of dicts to CSV string"""
    if not rows:
        return ""
    
    output = StringIO()
    if columns is None:
        columns = list(rows[0].keys())
    
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    
    return output.getvalue()


# ============================================================================
# UI HELPERS
# ============================================================================

def show_data_status(meta, data_key, data_name):
    """Show status badge for data (loaded from disk or fresh)"""
    if data_key in meta:
        info = meta[data_key]
        timestamp = format_timestamp(info.get('updated', ''))
        rows = info.get('rows', 0)
        st.markdown(
            f'<span class="stale-badge">📂 Loaded from disk • {rows} rows • Updated {timestamp}</span>',
            unsafe_allow_html=True
        )
        return True
    return False


def show_fresh_status(rows_count):
    """Show fresh data status"""
    st.markdown(
        f'<span class="fresh-badge">✓ Fresh data • {rows_count} rows • Just now</span>',
        unsafe_allow_html=True
    )


# ============================================================================
# MAIN APP
# ============================================================================

def main():
    # Attempt auto-login on first load
    if not st.session_state.authenticated and not st.session_state.auto_login_attempted:
        if attempt_auto_login():
            st.rerun()
    
    # Header
    st.markdown('<p class="main-header">🎓 Paatshala Tool</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Extract data from ICT Academy Kerala\'s Moodle LMS</p>', unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.header("🔐 Authentication")
        
        if not st.session_state.authenticated:
            auth_method = st.radio(
                "Login method",
                ["Credentials", "Session Cookie"],
                horizontal=True
            )
            
            if auth_method == "Credentials":
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                remember_me = st.checkbox("Remember me", value=True)
                
                if st.button("Login", type="primary", use_container_width=True):
                    if username and password:
                        with st.spinner("Logging in..."):
                            session_id = login_and_get_cookie(username, password)
                            if session_id:
                                st.session_state.session_id = session_id
                                st.session_state.authenticated = True
                                st.session_state.auth_source = 'manual'
                                
                                # Save to config
                                if remember_me:
                                    write_config(cookie=session_id, username=username, password=password)
                                else:
                                    write_config(cookie=session_id)
                                
                                st.success("✓ Logged in!")
                                st.rerun()
                            else:
                                st.error("✗ Login failed. Check credentials.")
                    else:
                        st.warning("Please enter username and password")
            
            else:  # Cookie method
                cookie = st.text_input("MoodleSession Cookie", type="password")
                remember_cookie = st.checkbox("Save cookie", value=True)
                
                if st.button("Validate & Login", type="primary", use_container_width=True):
                    if cookie:
                        with st.spinner("Validating session..."):
                            if validate_session(cookie):
                                st.session_state.session_id = cookie
                                st.session_state.authenticated = True
                                st.session_state.auth_source = 'cookie'
                                
                                if remember_cookie:
                                    write_config(cookie=cookie)
                                
                                st.success("✓ Session valid!")
                                st.rerun()
                            else:
                                st.error("✗ Invalid or expired cookie")
                    else:
                        st.warning("Please enter cookie")
        
        else:
            # Logged in state
            auth_source_text = {
                'config_cookie': 'saved cookie',
                'config_credentials': 'saved credentials',
                'manual': 'this session',
                'cookie': 'session cookie'
            }.get(st.session_state.auth_source, 'unknown')
            
            st.success(f"✓ Logged in ({auth_source_text})")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Logout", use_container_width=True):
                    st.session_state.authenticated = False
                    st.session_state.session_id = None
                    st.session_state.auth_source = None
                    st.session_state.courses = []
                    st.session_state.selected_course = None
                    st.session_state.tasks_data = None
                    st.session_state.quiz_data = None
                    st.session_state.submissions_data = None
                    st.rerun()
            
            with col2:
                if st.button("🗑️ Forget", use_container_width=True, help="Clear saved credentials"):
                    clear_config()
                    st.toast("Saved credentials cleared")
        
        st.divider()
        
        # Course Selection
        if st.session_state.authenticated:
            st.header("📚 Course")
            
            # Load courses if not loaded
            if not st.session_state.courses:
                if st.button("Load Courses", type="primary", use_container_width=True):
                    with st.spinner("Fetching courses..."):
                        session = setup_session(st.session_state.session_id)
                        st.session_state.courses = get_courses(session)
                        if st.session_state.courses:
                            st.success(f"Found {len(st.session_state.courses)} courses")
                            
                            # Check for last session
                            last = load_last_session()
                            if last.get('course_id'):
                                for c in st.session_state.courses:
                                    if c['id'] == last['course_id']:
                                        st.session_state.selected_course = c
                                        break
                            
                            st.rerun()
                        else:
                            st.warning("No courses found")
            else:
                if st.button("🔄 Refresh", use_container_width=True):
                    with st.spinner("Refreshing..."):
                        session = setup_session(st.session_state.session_id)
                        st.session_state.courses = get_courses(session)
                        st.rerun()
                
                # Course dropdown
                course_options = {
                    f"{'⭐ ' if c['starred'] else ''}{c['name']}": c
                    for c in st.session_state.courses
                }
                
                # Find current index
                current_index = 0
                if st.session_state.selected_course:
                    for i, (name, course) in enumerate(course_options.items()):
                        if course['id'] == st.session_state.selected_course['id']:
                            current_index = i
                            break
                
                selected_name = st.selectbox(
                    "Select Course",
                    options=list(course_options.keys()),
                    index=current_index,
                    label_visibility="collapsed"
                )
                
                if selected_name:
                    new_course = course_options[selected_name]
                    if st.session_state.selected_course is None or new_course['id'] != st.session_state.selected_course['id']:
                        st.session_state.selected_course = new_course
                        # Clear data when course changes
                        st.session_state.tasks_data = None
                        st.session_state.tasks_loaded_from_disk = False
                        st.session_state.quiz_data = None
                        st.session_state.quiz_loaded_from_disk = False
                        st.session_state.submissions_data = None
                        st.session_state.submissions_loaded_from_disk = False
                        # Save to last session
                        save_last_session({
                            'course_id': new_course['id'],
                            'course_name': new_course['name']
                        })
                        st.rerun()
                
                # Show last session indicator
                last = load_last_session()
                if last.get('course_id') and st.session_state.selected_course:
                    if last['course_id'] == st.session_state.selected_course['id']:
                        st.caption("📌 From last session")
            
            st.divider()
            
            # Output folder info
            st.header("⚙️ Output")
            st.caption(f"📁 `{OUTPUT_DIR}/`")
            
            if st.session_state.selected_course:
                output_path = get_output_dir(st.session_state.selected_course['id'])
                st.caption(f"└─ `course_{st.session_state.selected_course['id']}/`")
    
    # Main content area
    if not st.session_state.authenticated:
        st.info("👈 Please login using the sidebar to get started.")
        
        st.markdown("### Features")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("#### 📋 Tasks")
            st.write("Fetch all assignments with due dates, grades, and submission statistics.")
        
        with col2:
            st.markdown("#### 📊 Quiz Scores")
            st.write("Scrape practice quiz scores for all students in a course.")
        
        with col3:
            st.markdown("#### 📝 Submissions")
            st.write("Get detailed grading data for specific assignments with group filtering.")
        
        return
    
    if not st.session_state.courses:
        st.info("👈 Click 'Load Courses' in the sidebar to get started.")
        return
    
    if not st.session_state.selected_course:
        st.info("👈 Select a course from the sidebar.")
        return
    
    # Course is selected
    course = st.session_state.selected_course
    meta = load_meta(course['id'])
    
    st.markdown(f"### 📖 {course['name']}")
    st.caption(f"Course ID: {course['id']} | Category: {course['category'] or 'N/A'}")
    
    st.divider()
    
    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Tasks", "📊 Quiz Scores", "📝 Submissions", "🔍 Evaluation"])
    
    # -------------------------------------------------------------------------
    # TAB 1: TASKS
    # -------------------------------------------------------------------------
    with tab1:
        st.subheader("Assignment Tasks")
        
        # Try to load from disk if not loaded
        if st.session_state.tasks_data is None:
            disk_data = load_csv_from_disk(course['id'], f"tasks_{course['id']}.csv")
            if disk_data:
                st.session_state.tasks_data = disk_data
                st.session_state.tasks_loaded_from_disk = True
        
        col1, col2 = st.columns([3, 1])
        with col1:
            if st.session_state.tasks_loaded_from_disk and 'tasks' in meta:
                show_data_status(meta, 'tasks', 'Tasks')
            elif st.session_state.tasks_data:
                show_fresh_status(len(st.session_state.tasks_data))
        
        with col2:
            fetch_tasks = st.button(
                "🔄 Refresh" if st.session_state.tasks_data else "📥 Fetch",
                key="fetch_tasks",
                use_container_width=True
            )
        
        if fetch_tasks:
            progress_bar = st.progress(0, text="Fetching tasks...")
            
            def update_progress(value):
                progress_bar.progress(value, text=f"Fetching tasks... {int(value * 100)}%")
            
            rows = fetch_tasks_list(st.session_state.session_id, course['id'], update_progress)
            
            progress_bar.progress(1.0, text="Complete!")
            
            if rows:
                st.session_state.tasks_data = rows
                st.session_state.tasks_loaded_from_disk = False
                
                # Save to disk
                save_csv_to_disk(course['id'], f"tasks_{course['id']}.csv", rows)
                save_meta(course['id'], 'tasks', len(rows))
                
                st.success(f"✓ Fetched {len(rows)} tasks → Saved to `output/course_{course['id']}/`")
                time.sleep(0.5)
                st.rerun()
            else:
                st.warning("No tasks found")
        
        if st.session_state.tasks_data:
            st.dataframe(
                st.session_state.tasks_data,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "URL": st.column_config.LinkColumn("URL", display_text="Open")
                }
            )
            
            csv_data = dataframe_to_csv(st.session_state.tasks_data)
            st.download_button(
                label="📥 Download CSV",
                data=csv_data,
                file_name=f"tasks_{course['id']}.csv",
                mime="text/csv"
            )
    
    # -------------------------------------------------------------------------
    # TAB 2: QUIZ SCORES
    # -------------------------------------------------------------------------
    with tab2:
        st.subheader("Practice Quiz Scores")
        
        # Try to load from disk if not loaded
        if st.session_state.quiz_data is None:
            disk_data = load_csv_from_disk(course['id'], f"quiz_scores_{course['id']}.csv")
            if disk_data:
                st.session_state.quiz_data = disk_data
                st.session_state.quiz_loaded_from_disk = True
        
        col1, col2 = st.columns([3, 1])
        with col1:
            if st.session_state.quiz_loaded_from_disk and 'quiz' in meta:
                show_data_status(meta, 'quiz', 'Quiz')
            elif st.session_state.quiz_data:
                show_fresh_status(len(st.session_state.quiz_data))
        
        with col2:
            fetch_quiz = st.button(
                "🔄 Refresh" if st.session_state.quiz_data else "📥 Fetch",
                key="fetch_quiz",
                use_container_width=True
            )
        
        if fetch_quiz:
            progress_bar = st.progress(0, text="Fetching quiz scores...")
            
            def update_progress(value):
                progress_bar.progress(value, text=f"Fetching quiz scores... {int(value * 100)}%")
            
            quiz_names, rows = fetch_quiz_scores_all(
                st.session_state.session_id, course['id'], update_progress
            )
            
            progress_bar.progress(1.0, text="Complete!")
            
            if rows:
                st.session_state.quiz_data = rows
                st.session_state.quiz_loaded_from_disk = False
                
                # Save to disk
                save_csv_to_disk(course['id'], f"quiz_scores_{course['id']}.csv", rows)
                save_meta(course['id'], 'quiz', len(rows))
                
                st.success(f"✓ Fetched scores for {len(rows)} students → Saved to `output/course_{course['id']}/`")
                time.sleep(0.5)
                st.rerun()
            else:
                st.warning("No quiz data found (no practice quizzes or no attempts)")
        
        if st.session_state.quiz_data:
            st.dataframe(
                st.session_state.quiz_data,
                use_container_width=True,
                hide_index=True
            )
            
            csv_data = dataframe_to_csv(st.session_state.quiz_data)
            st.download_button(
                label="📥 Download CSV",
                data=csv_data,
                file_name=f"quiz_scores_{course['id']}.csv",
                mime="text/csv"
            )
    
    # -------------------------------------------------------------------------
    # TAB 3: SUBMISSIONS
    # -------------------------------------------------------------------------
    with tab3:
        st.subheader("Assignment Submissions")
        
        # Need tasks first
        if not st.session_state.tasks_data:
            # Try loading from disk
            disk_data = load_csv_from_disk(course['id'], f"tasks_{course['id']}.csv")
            if disk_data:
                st.session_state.tasks_data = disk_data
                st.session_state.tasks_loaded_from_disk = True
                st.rerun()
            else:
                st.info("⚠️ Please fetch tasks first (in Tasks tab) to see available assignments.")
                
                if st.button("Quick Fetch Tasks", key="quick_fetch_tasks"):
                    with st.spinner("Fetching tasks..."):
                        rows = fetch_tasks_list(st.session_state.session_id, course['id'])
                        if rows:
                            st.session_state.tasks_data = rows
                            save_csv_to_disk(course['id'], f"tasks_{course['id']}.csv", rows)
                            save_meta(course['id'], 'tasks', len(rows))
                            st.success(f"✓ Fetched {len(rows)} tasks")
                            st.rerun()
        else:
            # Task selector
            task_options = {
                f"{t['Task Name']} (ID: {t['Module ID']})": t
                for t in st.session_state.tasks_data
            }
            
            selected_task_name = st.selectbox(
                "Select Assignment",
                options=list(task_options.keys())
            )
            
            selected_task = task_options.get(selected_task_name)
            
            # Group selector
            selected_group_id = None
            selected_group_name = None
            
            if selected_task:
                session = setup_session(st.session_state.session_id)
                groups = get_available_groups(session, selected_task['Module ID'])
                
                if groups:
                    group_options = {"All Groups": (None, None)}
                    group_options.update({
                        f"{g[1]} (ID: {g[0]})": (g[0], g[1])
                        for g in groups
                    })
                    
                    selected_group_label = st.selectbox(
                        "Filter by Group (optional)",
                        options=list(group_options.keys())
                    )
                    selected_group_id, selected_group_name = group_options.get(selected_group_label, (None, None))
                else:
                    st.caption("No groups available for this assignment")
                
                # Check for existing data
                module_id = selected_task['Module ID']
                submissions_filename = f"submissions_{course['id']}_mod{module_id}"
                if selected_group_id:
                    submissions_filename += f"_grp{selected_group_id}"
                submissions_filename += ".csv"
                
                meta_key = f"submissions_{module_id}"
                if selected_group_id:
                    meta_key += f"_grp{selected_group_id}"
                
                # Try to load existing data
                existing_data = load_csv_from_disk(course['id'], submissions_filename)
                
                # Show status if data exists
                col1, col2 = st.columns([3, 1])
                with col1:
                    if existing_data and meta_key in meta:
                        show_data_status(meta, meta_key, 'Submissions')
                
                with col2:
                    fetch_btn = st.button(
                        "🔄 Refresh" if existing_data else "📥 Fetch",
                        key="fetch_submissions",
                        use_container_width=True
                    )
                
                # Load existing or fetch new
                if existing_data and not fetch_btn:
                    st.session_state.submissions_data = existing_data
                
                if fetch_btn:
                    with st.spinner("Fetching submissions..."):
                        rows = fetch_submissions(
                            st.session_state.session_id,
                            selected_task['Module ID'],
                            selected_group_id
                        )
                        
                        if rows:
                            # Add task info to rows
                            for row in rows:
                                row['Task Name'] = selected_task['Task Name']
                                row['Module ID'] = selected_task['Module ID']
                            
                            st.session_state.submissions_data = rows
                            st.session_state.submissions_loaded_from_disk = False
                            
                            # Save to disk
                            save_csv_to_disk(course['id'], submissions_filename, rows)
                            save_meta(course['id'], meta_key, len(rows))
                            
                            st.success(f"✓ Fetched {len(rows)} submissions → Saved to `output/course_{course['id']}/`")
                            st.rerun()
                        else:
                            st.warning("No submission data found")
            
            if st.session_state.submissions_data:
                st.dataframe(
                    st.session_state.submissions_data,
                    use_container_width=True,
                    hide_index=True
                )
                
                csv_data = dataframe_to_csv(st.session_state.submissions_data)
                st.download_button(
                    label="📥 Download CSV",
                    data=csv_data,
                    file_name=f"submissions_{course['id']}.csv",
                    mime="text/csv"
                )

    # -------------------------------------------------------------------------
    # TAB 4: EVALUATION
    # -------------------------------------------------------------------------
    with tab4:
        st.subheader("Submission Evaluation")
        
        if not st.session_state.submissions_data:
            st.info("⚠️ Please fetch submissions first (in Submissions tab) to evaluate them.")
        else:
            # --- Batch Actions ---
            data = st.session_state.submissions_data
            total = len(data)
            evaluated = sum(1 for r in data if r.get('Eval_Last_Checked'))
            
            # Placeholder for the table (defined early for real-time updates)
            table_placeholder = st.empty()
            
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                st.metric("Evaluated Submissions", f"{evaluated} / {total}")
            
            with col2:
                if st.button("🚀 Evaluate Pending", use_container_width=True, disabled=(evaluated == total)):
                    progress_bar = st.progress(0, text="Evaluating pending submissions...")
                    pending_indices = [i for i, r in enumerate(data) if not r.get('Eval_Last_Checked')]
                    count = len(pending_indices)
                    
                    for idx, i in enumerate(pending_indices):
                        data[i] = evaluate_submission(data[i])
                        progress_bar.progress((idx + 1) / count)
                        
                        # Real-time update
                        table_placeholder.dataframe(
                            get_display_dataframe(data),
                            use_container_width=True,
                            column_config={
                                "Link": st.column_config.LinkColumn("Link"),
                                "Valid?": st.column_config.TextColumn("Valid?", width="small"),
                                "Fork?": st.column_config.TextColumn("Fork?", width="small"),
                            },
                            selection_mode="single-row"
                        )
                        
                        # Check for Rate Limit to abort early
                        if data[i].get('Eval_Repo_Status') == "Rate Limit":
                            st.warning("⚠️ GitHub API Rate Limit reached. Stopping early.")
                            break
                    
                    # Save progress
                    if data and 'Module ID' in data[0]:
                        mid = data[0]['Module ID']
                        fname = f"submissions_{course['id']}_mod{mid}.csv"
                        save_csv_to_disk(course['id'], fname, data)
                    
                    st.rerun()

            with col3:
                if st.button("🔄 Force Refresh All", use_container_width=True):
                    progress_bar = st.progress(0, text="Re-evaluating all...")
                    for i in range(total):
                        data[i] = evaluate_submission(data[i])
                        progress_bar.progress((i + 1) / total)
                        
                        # Real-time update
                        table_placeholder.dataframe(
                            get_display_dataframe(data),
                            use_container_width=True,
                            column_config={
                                "Link": st.column_config.LinkColumn("Link"),
                                "Valid?": st.column_config.TextColumn("Valid?", width="small"),
                                "Fork?": st.column_config.TextColumn("Fork?", width="small"),
                            },
                            selection_mode="single-row"
                        )
                        
                        if data[i].get('Eval_Repo_Status') == "Rate Limit":
                            break
                    
                    if data and 'Module ID' in data[0]:
                         save_csv_to_disk(course['id'], f"submissions_{course['id']}_mod{data[0]['Module ID']}.csv", data)
                    st.rerun()

            st.divider()

            # --- Table View (Interactive) ---
            # Use the placeholder for the main display too
            event = table_placeholder.dataframe(
                get_display_dataframe(data),
                use_container_width=True,
                column_config={
                    "Link": st.column_config.LinkColumn("Link"),
                    "Valid?": st.column_config.TextColumn("Valid?", width="small"),
                    "Fork?": st.column_config.TextColumn("Fork?", width="small"),
                },
                on_select="rerun",
                selection_mode="single-row"
            )
            
            # Handle Selection
            selected_idx = None
            if len(event.selection.rows) > 0:
                selected_idx = event.selection.rows[0]
            
            st.divider()

            # --- Detail View ---
            st.markdown("### 🔍 Individual Detail")
            
            # Use indices for options to handle duplicate names correctly
            student_indices = list(range(len(data)))
            
            def format_student_option(i):
                row = data[i]
                return f"{row.get('Name', 'Unknown')} ({row.get('Status', 'Unknown')})"
            
            # Initialize session state for selection tracking
            if 'last_table_selection' not in st.session_state:
                st.session_state.last_table_selection = None
            if 'eval_selected_index' not in st.session_state:
                st.session_state.eval_selected_index = 0
            
            # Detect change in table selection
            if selected_idx != st.session_state.last_table_selection:
                st.session_state.last_table_selection = selected_idx
                if selected_idx is not None:
                    st.session_state.eval_selected_index = selected_idx
                    # Force update the widget state
                    st.session_state.eval_student_select = selected_idx
            
            # Ensure index is valid
            if st.session_state.eval_selected_index >= len(data):
                st.session_state.eval_selected_index = 0
                
            def on_change_selectbox():
                st.session_state.eval_selected_index = st.session_state.eval_student_select
            
            selected_index = st.selectbox(
                "Select Student for Details",
                options=student_indices,
                format_func=format_student_option,
                index=st.session_state.eval_selected_index,
                key="eval_student_select",
                on_change=on_change_selectbox
            )
            
            # Use the tracked index
            idx = st.session_state.eval_selected_index
            row = data[idx]
                
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**Name:** {row.get('Name')} | **Email:** {row.get('Email')}")
            with col2:
                if st.button("🔄 Refresh Analysis", key=f"refresh_{idx}"):
                    data[idx] = evaluate_submission(row)
                    if 'Module ID' in row:
                        save_csv_to_disk(course['id'], f"submissions_{course['id']}_mod{row['Module ID']}.csv", data)
                    st.rerun()

            # Show existing analysis
            if row.get('Eval_Last_Checked'):
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.info(f"Link: {row.get('Eval_Link') or 'None'}")
                with c2:
                    st.info(f"Valid: {row.get('Eval_Link_Valid') or 'N/A'}")
                with c3:
                    st.info(f"Repo: {row.get('Eval_Repo_Status') or 'N/A'}")
                    if row.get('Eval_Is_Fork') == 'Yes':
                        st.caption(f"Fork of: {row.get('Eval_Parent')}")
            
            with st.expander("Submission Content", expanded=True):
                st.text(row.get('Submission', ''))


if __name__ == "__main__":
    main()
