#!/usr/bin/env python3
"""
Paatshala Tool - GUI Version (Streamlit)

A web-based GUI for managing and extracting data from Paatshala.

Usage:
    pip install streamlit
    streamlit run paatshala_gui.py
"""

import os
import re
import csv
import time
import threading
from io import StringIO
from pathlib import Path
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
    .success-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
    }
    .info-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #e7f3ff;
        border: 1px solid #b6d4fe;
        color: #084298;
    }
    .stProgress > div > div > div > div {
        background-color: #1f77b4;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'session_id' not in st.session_state:
    st.session_state.session_id = None
if 'courses' not in st.session_state:
    st.session_state.courses = []
if 'selected_course' not in st.session_state:
    st.session_state.selected_course = None
if 'tasks_data' not in st.session_state:
    st.session_state.tasks_data = None
if 'quiz_data' not in st.session_state:
    st.session_state.quiz_data = None
if 'submissions_data' not in st.session_state:
    st.session_state.submissions_data = None

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


# ============================================================================
# CSV CONVERSION HELPERS
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
# MAIN APP
# ============================================================================

def main():
    # Header
    st.markdown('<p class="main-header">🎓 Paatshala Tool</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Extract data from ICT Academy Kerala\'s Moodle LMS</p>', unsafe_allow_html=True)
    
    # Sidebar - Authentication
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
                
                if st.button("Login", type="primary", use_container_width=True):
                    if username and password:
                        with st.spinner("Logging in..."):
                            session_id = login_and_get_cookie(username, password)
                            if session_id:
                                st.session_state.session_id = session_id
                                st.session_state.authenticated = True
                                st.success("✓ Logged in successfully!")
                                st.rerun()
                            else:
                                st.error("✗ Login failed. Check credentials.")
                    else:
                        st.warning("Please enter username and password")
            
            else:  # Cookie method
                cookie = st.text_input("MoodleSession Cookie", type="password")
                
                if st.button("Validate & Login", type="primary", use_container_width=True):
                    if cookie:
                        with st.spinner("Validating session..."):
                            if validate_session(cookie):
                                st.session_state.session_id = cookie
                                st.session_state.authenticated = True
                                st.success("✓ Session valid!")
                                st.rerun()
                            else:
                                st.error("✗ Invalid or expired cookie")
                    else:
                        st.warning("Please enter cookie")
        
        else:
            st.success("✓ Authenticated")
            if st.button("Logout", use_container_width=True):
                st.session_state.authenticated = False
                st.session_state.session_id = None
                st.session_state.courses = []
                st.session_state.selected_course = None
                st.session_state.tasks_data = None
                st.session_state.quiz_data = None
                st.session_state.submissions_data = None
                st.rerun()
        
        st.divider()
        
        # Course Selection (only if authenticated)
        if st.session_state.authenticated:
            st.header("📚 Course Selection")
            
            if st.button("🔄 Refresh Courses", use_container_width=True):
                with st.spinner("Fetching courses..."):
                    session = setup_session(st.session_state.session_id)
                    st.session_state.courses = get_courses(session)
                    if st.session_state.courses:
                        st.success(f"Found {len(st.session_state.courses)} courses")
                    else:
                        st.warning("No courses found")
            
            if st.session_state.courses:
                course_options = {
                    f"{'⭐ ' if c['starred'] else ''}{c['name']} (ID: {c['id']})": c
                    for c in st.session_state.courses
                }
                
                selected_name = st.selectbox(
                    "Select Course",
                    options=list(course_options.keys()),
                    index=0
                )
                
                if selected_name:
                    st.session_state.selected_course = course_options[selected_name]
    
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
        st.info("👈 Click 'Refresh Courses' in the sidebar to load your courses.")
        return
    
    if not st.session_state.selected_course:
        st.info("👈 Select a course from the sidebar.")
        return
    
    # Course is selected - show operations
    course = st.session_state.selected_course
    
    st.markdown(f"### 📖 {course['name']}")
    st.caption(f"Course ID: {course['id']} | Category: {course['category'] or 'N/A'}")
    
    st.divider()
    
    # Tabs for different operations
    tab1, tab2, tab3 = st.tabs(["📋 Tasks", "📊 Quiz Scores", "📝 Submissions"])
    
    # -------------------------------------------------------------------------
    # TAB 1: TASKS
    # -------------------------------------------------------------------------
    with tab1:
        st.subheader("Assignment Tasks")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write("Fetch all assignments with due dates, participants, and submission counts.")
        with col2:
            fetch_tasks = st.button("🔄 Fetch Tasks", key="fetch_tasks", use_container_width=True)
        
        if fetch_tasks:
            progress_bar = st.progress(0, text="Fetching tasks...")
            
            def update_progress(value):
                progress_bar.progress(value, text=f"Fetching tasks... {int(value * 100)}%")
            
            rows = fetch_tasks_list(st.session_state.session_id, course['id'], update_progress)
            
            progress_bar.progress(1.0, text="Complete!")
            
            if rows:
                st.session_state.tasks_data = rows
                st.success(f"✓ Fetched {len(rows)} tasks")
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
            
            # Download button
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
        
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write("Fetch scores for all practice quizzes (looks for 'practice quiz' in name).")
        with col2:
            fetch_quiz = st.button("🔄 Fetch Scores", key="fetch_quiz", use_container_width=True)
        
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
                st.success(f"✓ Fetched scores for {len(rows)} students across {len(quiz_names)} quizzes")
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
        
        st.write("Fetch detailed submission and grading data for a specific assignment.")
        
        # Need tasks first
        if not st.session_state.tasks_data:
            st.info("⚠️ Please fetch tasks first (in Tasks tab) to see available assignments.")
            
            if st.button("Quick Fetch Tasks", key="quick_fetch_tasks"):
                with st.spinner("Fetching tasks..."):
                    rows = fetch_tasks_list(st.session_state.session_id, course['id'])
                    if rows:
                        st.session_state.tasks_data = rows
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
            if selected_task:
                session = setup_session(st.session_state.session_id)
                groups = get_available_groups(session, selected_task['Module ID'])
                
                if groups:
                    group_options = {"All Groups": None}
                    group_options.update({
                        f"{g[1]} (ID: {g[0]})": g[0]
                        for g in groups
                    })
                    
                    selected_group_name = st.selectbox(
                        "Filter by Group (optional)",
                        options=list(group_options.keys())
                    )
                    selected_group_id = group_options.get(selected_group_name)
                else:
                    selected_group_id = None
                    st.caption("No groups available for this assignment")
                
                if st.button("🔄 Fetch Submissions", key="fetch_submissions", use_container_width=True):
                    with st.spinner("Fetching submissions..."):
                        rows = fetch_submissions(
                            st.session_state.session_id,
                            selected_task['Module ID'],
                            selected_group_id
                        )
                        
                        if rows:
                            st.session_state.submissions_data = rows
                            st.success(f"✓ Fetched {len(rows)} submissions")
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


if __name__ == "__main__":
    main()
