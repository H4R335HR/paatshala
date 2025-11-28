#!/usr/bin/env python3
"""
Paatshala Unified Tool - Interactive Course Management

A single script to handle all Paatshala operations:
  - Browse and select courses
  - Fetch task lists (assignments)
  - Scrape quiz scores
  - Fetch submission grading details

Usage:
  Interactive mode (full guided flow):
    python paatshala.py
  
  Quick mode (skip to what you need):
    python paatshala.py --course 450 --tasks
    python paatshala.py --course 450 --quiz
    python paatshala.py --course 450 --submissions --module 12345
    python paatshala.py --course 450 --all
"""

import os
import re
import csv
import sys
import json
import argparse
import time
import threading
import getpass
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

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
# AUTHENTICATION MODULE
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
        if cookie:
            print(f"[Config] Read cookie from {config_path}")
        elif username and password:
            print(f"[Config] Read credentials from {config_path}")
        return cookie, username, password
    except Exception as e:
        print(f"[Config] Error reading {config_path}: {e}")
        return None, None, None


def write_config(config_path, cookie=None, username=None, password=None):
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
        
        if cookie and 'cookie' not in existing_keys:
            lines.append(f"cookie={cookie}\n")
        elif cookie:
            lines.insert(0, f"cookie={cookie}\n")
        
        if username and 'username' not in existing_keys:
            lines.append(f"username={username}\n")
        
        if password and 'password' not in existing_keys:
            lines.append(f"password={password}\n")
        
        with open(config_path, 'w') as f:
            f.writelines(lines)
        
        if cookie:
            print(f"[Config] Saved cookie to {config_path}")
        return True
    except Exception as e:
        print(f"[Config] Error writing to {config_path}: {e}")
        return False


def login_and_get_cookie(username, password):
    """Login to Paathshala and extract session cookie"""
    print(f"[Login] Attempting login as {username}...")
    
    try:
        response = requests.post(
            f"https://{PAATSHALA_HOST}/login/index.php",
            data={'username': username, 'password': password},
            allow_redirects=False,
            timeout=10
        )
        
        if 'MoodleSession' in response.cookies:
            session_cookie = response.cookies['MoodleSession']
            print(f"[Login] ✓ Successfully logged in!")
            return session_cookie
        else:
            print(f"[Login] ✗ Login failed - no session cookie received")
            if response.status_code == 200:
                print(f"[Login]   Hint: Check username/password")
            return None
            
    except Exception as e:
        print(f"[Login] ✗ Login error: {e}")
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


def prompt_for_credentials(save_option=False, first_time=False):
    """Interactively prompt user for username and password"""
    if not first_time:
        print("\n[Auth] Cookie appears to be invalid or expired.")
    print("[Auth] Please enter your credentials:\n")
    
    try:
        username = input("Username: ").strip()
        if not username:
            return None, None, False
        
        password = getpass.getpass("Password: ").strip()
        if not password:
            return None, None, False
        
        if save_option:
            save_creds = input("\nSave credentials to config file? (y/n): ").strip().lower()
            should_save = save_creds in ['y', 'yes']
        else:
            should_save = False
        
        return username, password, should_save
    except (KeyboardInterrupt, EOFError):
        print("\n[Auth] Login cancelled")
        return None, None, False


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


def authenticate(config_path=CONFIG_FILE):
    """Complete authentication flow, returns session_id or exits"""
    SESSION_ID = None
    
    # 1. Environment variable
    if os.environ.get("MOODLE_SESSION_ID"):
        SESSION_ID = os.environ.get("MOODLE_SESSION_ID")
        print("[Auth] Using cookie from MOODLE_SESSION_ID environment variable")
    
    # 2. Config file
    else:
        cookie, username, password = read_config(config_path)
        
        if cookie:
            SESSION_ID = cookie
            print("[Auth] Using saved cookie from config")
        elif username and password:
            print("[Auth] Using credentials from config")
            SESSION_ID = login_and_get_cookie(username, password)
            if SESSION_ID:
                write_config(config_path, cookie=SESSION_ID)
            else:
                print("\n[Auth] ✗ Auto-login failed.")
                SESSION_ID = None
        else:
            print(f"\n[Auth] No authentication configured.")
            username, password, should_save = prompt_for_credentials(save_option=True, first_time=True)
            
            if username and password:
                SESSION_ID = login_and_get_cookie(username, password)
                if SESSION_ID:
                    if should_save:
                        write_config(config_path, cookie=SESSION_ID, username=username, password=password)
                    else:
                        write_config(config_path, cookie=SESSION_ID)
                else:
                    print("\n[Auth] ✗ Login failed.")
                    sys.exit(1)
            else:
                print("\n[Auth] ✗ No credentials provided.")
                sys.exit(1)
    
    # Validate session
    if SESSION_ID:
        print("[Auth] Validating session...")
        if not validate_session(SESSION_ID):
            print("[Auth] ✗ Cookie is invalid or expired")
            username, password, should_save = prompt_for_credentials()
            
            if username and password:
                SESSION_ID = login_and_get_cookie(username, password)
                if SESSION_ID:
                    if should_save:
                        write_config(config_path, cookie=SESSION_ID, username=username, password=password)
                    else:
                        write_config(config_path, cookie=SESSION_ID)
                else:
                    print("\n[Auth] ✗ Login failed.")
                    sys.exit(1)
            else:
                print("\n[Auth] ✗ No credentials provided.")
                sys.exit(1)
        else:
            print("[Auth] ✓ Session is valid")
    
    return SESSION_ID


# ============================================================================
# LAST SESSION MEMORY
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
    except Exception as e:
        print(f"[Session] Could not save session: {e}")


# ============================================================================
# OUTPUT DIRECTORY MANAGEMENT
# ============================================================================

def get_output_dir(course_id):
    """Get or create output directory for a course"""
    path = Path(OUTPUT_DIR) / f"course_{course_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ============================================================================
# COURSE SELECTION MODULE
# ============================================================================

def get_courses(session):
    """Fetch all courses using Moodle's AJAX APIs"""
    print(f"[Fetch] Getting your courses...")
    
    courses_dict = {}
    
    try:
        resp = session.get(f"{BASE}/my/", timeout=15)
        if not resp.ok:
            print(f"[Fetch] ✗ Failed to load dashboard: {resp.status_code}")
            return []
        
        # Extract sesskey
        sesskey_match = re.search(r'"sesskey":"([^"]+)"', resp.text)
        sesskey = sesskey_match.group(1) if sesskey_match else ""
        
        # API 1: Enrolled courses
        if sesskey:
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
        if courses:
            print(f"[Fetch] ✓ Found {len(courses)} courses")
        return courses
        
    except Exception as e:
        print(f"[Fetch] ✗ Error fetching courses: {e}")
        return []


def display_courses(courses):
    """Display courses in a formatted table"""
    if not courses:
        print("\n✗ No courses to display")
        return
    
    print("\n" + "=" * 80)
    print(f"{'#':<4} {'★':<2} {'ID':<6} {'Course Name':<45} {'Category':<20}")
    print("=" * 80)
    
    for idx, course in enumerate(courses, 1):
        star = "★" if course['starred'] else " "
        name = course['name'][:43] + ".." if len(course['name']) > 45 else course['name']
        category = course['category'][:18] + ".." if len(course['category']) > 20 else course['category']
        print(f"{idx:<4} {star:<2} {course['id']:<6} {name:<45} {category:<20}")
    
    print("=" * 80)


def select_course_interactive(session, last_session):
    """Interactive course selection"""
    # Check if we have a last course
    last_course_id = last_session.get('course_id')
    last_course_name = last_session.get('course_name')
    
    if last_course_id and last_course_name:
        print(f"\n[Session] Last used course: {last_course_name} (ID: {last_course_id})")
        use_last = input("Use this course? (y/n/Enter for yes): ").strip().lower()
        if use_last in ['', 'y', 'yes']:
            return {'id': last_course_id, 'name': last_course_name, 'category': '', 'starred': False}
    
    courses = get_courses(session)
    if not courses:
        print("✗ No courses found")
        return None
    
    # Sort: starred first, then alphabetically
    courses.sort(key=lambda x: (not x['starred'], x['name'].lower()))
    display_courses(courses)
    
    while True:
        print("\nOptions:")
        print(f"  - Enter a number (1-{len(courses)}) to select")
        print("  - Enter 's' to search by name")
        print("  - Enter 'q' to quit")
        
        try:
            choice = input("\nYour choice: ").strip().lower()
            
            if choice == 'q':
                return None
            
            elif choice == 's':
                search_term = input("Enter search term: ").strip().lower()
                if not search_term:
                    continue
                
                filtered = [c for c in courses if search_term in c['name'].lower() or search_term in c['category'].lower()]
                
                if not filtered:
                    print(f"✗ No courses found matching '{search_term}'")
                    continue
                
                print(f"\n✓ Found {len(filtered)} matching course(s):")
                display_courses(filtered)
                
                if len(filtered) == 1:
                    use_it = input(f"\nUse this course? (y/n): ").strip().lower()
                    if use_it in ['y', 'yes']:
                        return filtered[0]
            
            else:
                try:
                    num = int(choice)
                    if 1 <= num <= len(courses):
                        selected = courses[num - 1]
                        print(f"\n✓ Selected: {selected['name']} (ID: {selected['id']})")
                        return selected
                    else:
                        print(f"✗ Please enter a number between 1 and {len(courses)}")
                except ValueError:
                    print("✗ Invalid input")
        
        except (KeyboardInterrupt, EOFError):
            print("\n")
            return None


# ============================================================================
# TASKS LIST MODULE
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
        print(f"✗ Failed to load course page: {resp.status_code}")
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


def fetch_task_details(session_id, name, mid, url, index, total):
    """Fetch task details using thread-local session"""
    s = get_thread_session(session_id)
    
    try:
        resp = s.get(url, timeout=30)
        if not resp.ok:
            return name, mid, url, {}
        
        info = parse_assign_view(resp.text)
        print(f"  [{index}/{total}] ✓ {name[:50]}...")
        return name, mid, url, info
        
    except Exception as e:
        print(f"  [{index}/{total}] ✗ {name[:50]}: {e}")
        return name, mid, url, {}


def fetch_tasks_list(session_id, course_id, num_threads=DEFAULT_THREADS):
    """Fetch all tasks for a course with details"""
    print(f"\n[Tasks] Fetching task list for course {course_id}...")
    
    main_session = setup_session(session_id)
    tasks = get_tasks(main_session, course_id)
    
    if not tasks:
        print("✗ No tasks (assignments) found")
        return None, []
    
    print(f"[Tasks] Found {len(tasks)} tasks, fetching details...")
    
    start_time = time.perf_counter()
    task_results = {}
    
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {
            executor.submit(fetch_task_details, session_id, name, mid, url, i, len(tasks)): (name, mid, url)
            for i, (name, mid, url) in enumerate(tasks, 1)
        }
        
        for fut in as_completed(futures):
            name, mid, url = futures[fut]
            try:
                returned_name, returned_mid, returned_url, info = fut.result()
                task_results[(returned_name, returned_mid)] = (returned_url, info)
            except:
                continue
    
    # Build rows in original order
    rows = []
    for name, mid, url in tasks:
        if (name, mid) in task_results:
            url, info = task_results[(name, mid)]
            rows.append({
                "Task Name": name,
                "Module ID": mid,
                "Due Date": info.get("due_date", ""),
                "Time Remaining": info.get("time_remaining", ""),
                "Late Policy": info.get("late_policy", ""),
                "Max Grade": info.get("max_grade", ""),
                "Submission Status": info.get("submission_status", ""),
                "Grading Status": info.get("grading_status", ""),
                "Last Modified": info.get("last_modified", ""),
                "Submission Comments": info.get("submission_comments", ""),
                "Participants": info.get("participants", ""),
                "Drafts": info.get("drafts", ""),
                "Submitted": info.get("submitted", ""),
                "Needs Grading": info.get("needs_grading", ""),
                "URL": url
            })
    
    elapsed = time.perf_counter() - start_time
    
    # Save to CSV
    output_dir = get_output_dir(course_id)
    output_file = output_dir / f"tasks_{course_id}.csv"
    
    fieldnames = ["Task Name", "Module ID", "Due Date", "Time Remaining", "Late Policy",
                  "Max Grade", "Submission Status", "Grading Status", "Last Modified",
                  "Submission Comments", "Participants", "Drafts", "Submitted", "Needs Grading", "URL"]
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"\n[Tasks] ✓ Saved {len(rows)} tasks to {output_file}")
    print(f"[Tasks]   Time: {elapsed:.2f}s")
    
    return output_file, rows


# ============================================================================
# QUIZ SCORES MODULE
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
    
    return module_id, scores, attempt_count


def fetch_quiz_scores_all(session_id, course_id, num_threads=DEFAULT_THREADS):
    """Fetch all quiz scores for a course"""
    print(f"\n[Quiz] Fetching quiz scores for course {course_id}...")
    
    main_session = setup_session(session_id)
    quizzes = get_quizzes(main_session, course_id)
    
    if not quizzes:
        print("✗ No practice quizzes found")
        return None
    
    print(f"[Quiz] Found {len(quizzes)} practice quizzes")
    
    start_time = time.perf_counter()
    all_scores = defaultdict(dict)
    quiz_names_ordered = [name for name, _ in quizzes]
    mid_to_name = {mid: name for name, mid in quizzes}
    
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = {executor.submit(fetch_quiz_scores, session_id, mid): mid for _, mid in quizzes}
        for fut in as_completed(futures):
            mid = futures[fut]
            try:
                _mid, scores, attempt_count = fut.result()
                quiz_name = mid_to_name.get(_mid, f"module_{_mid}")
                for student, grade in scores.items():
                    all_scores[student][quiz_name] = grade
                print(f"  ✓ {quiz_name[:50]}... ({len(scores)} students)")
            except Exception as e:
                print(f"  ✗ Module {mid}: {e}")
    
    if not all_scores:
        print("✗ No student data found")
        return None
    
    elapsed = time.perf_counter() - start_time
    
    # Save to CSV
    output_dir = get_output_dir(course_id)
    output_file = output_dir / f"quiz_scores_{course_id}.csv"
    
    students = sorted(all_scores.keys())
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Student Name"] + quiz_names_ordered)
        for student in students:
            writer.writerow([student] + [all_scores[student].get(q, "") for q in quiz_names_ordered])
    
    print(f"\n[Quiz] ✓ Saved scores for {len(students)} students to {output_file}")
    print(f"[Quiz]   Quizzes: {len(quiz_names_ordered)}")
    print(f"[Quiz]   Time: {elapsed:.2f}s")
    
    return output_file


# ============================================================================
# SUBMISSIONS MODULE
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


def fetch_assignment_grading(session, module_id, group_id=None):
    """Fetch grading table for a specific assignment"""
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


def load_tasks_csv(course_id):
    """Load tasks from existing CSV file"""
    output_dir = get_output_dir(course_id)
    tasks_file = output_dir / f"tasks_{course_id}.csv"
    
    if not tasks_file.exists():
        return None
    
    tasks = []
    try:
        with open(tasks_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("Task Name", "")
                module_id = row.get("Module ID", "")
                if name and module_id:
                    tasks.append((name, module_id))
        return tasks
    except:
        return None


def select_task_interactive(tasks):
    """Interactive task selection"""
    print("\n" + "=" * 70)
    print(f"{'#':<4} {'Module ID':<12} {'Task Name'}")
    print("=" * 70)
    
    for idx, (name, mid) in enumerate(tasks, 1):
        display_name = name[:55] + ".." if len(name) > 57 else name
        print(f"{idx:<4} {mid:<12} {display_name}")
    
    print("=" * 70)
    
    while True:
        try:
            choice = input(f"\nSelect task (1-{len(tasks)}) or 'q' to cancel: ").strip().lower()
            
            if choice == 'q':
                return None
            
            num = int(choice)
            if 1 <= num <= len(tasks):
                selected = tasks[num - 1]
                print(f"✓ Selected: {selected[0]}")
                return selected
            else:
                print(f"✗ Enter a number between 1 and {len(tasks)}")
        except ValueError:
            print("✗ Invalid input")
        except (KeyboardInterrupt, EOFError):
            return None


def select_group_interactive(session, module_id):
    """Interactive group selection"""
    groups = get_available_groups(session, module_id)
    
    if not groups:
        print("[Groups] No groups available for this assignment")
        return None
    
    print("\n" + "=" * 50)
    print(f"{'#':<4} {'ID':<8} {'Group Name'}")
    print("=" * 50)
    
    for idx, (gid, gname) in enumerate(groups, 1):
        print(f"{idx:<4} {gid:<8} {gname}")
    
    print("=" * 50)
    
    while True:
        try:
            choice = input(f"\nSelect group (1-{len(groups)}) or Enter to skip: ").strip().lower()
            
            if choice == '' or choice == 'q':
                return None
            
            num = int(choice)
            if 1 <= num <= len(groups):
                selected = groups[num - 1]
                print(f"✓ Selected: {selected[1]}")
                return selected
            else:
                print(f"✗ Enter a number between 1 and {len(groups)}")
        except ValueError:
            print("✗ Invalid input")
        except (KeyboardInterrupt, EOFError):
            return None


def fetch_submissions(session_id, course_id, module_id, module_name, group_id=None, group_name=None):
    """Fetch submissions for a specific task/module"""
    print(f"\n[Submissions] Fetching for: {module_name}")
    if group_name:
        print(f"[Submissions] Group filter: {group_name}")
    
    session = setup_session(session_id)
    grading_data = fetch_assignment_grading(session, module_id, group_id)
    
    if not grading_data:
        print("✗ No submission data found")
        return None
    
    # Add metadata
    for row in grading_data:
        row["Task Name"] = module_name
        row["Module ID"] = module_id
        if group_id:
            row["Group ID"] = group_id
    
    # Save to CSV
    output_dir = get_output_dir(course_id)
    filename_parts = [f"submissions_{course_id}", f"mod{module_id}"]
    if group_id:
        filename_parts.append(f"grp{group_id}")
    output_file = output_dir / ("_".join(filename_parts) + ".csv")
    
    fieldnames = ["Task Name", "Module ID"]
    if group_id:
        fieldnames.append("Group ID")
    fieldnames.extend(["Name", "Status", "Last Modified", "Submission", "Feedback Comments", "Final Grade"])
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(grading_data)
    
    print(f"[Submissions] ✓ Saved {len(grading_data)} records to {output_file}")
    
    return output_file


# ============================================================================
# MAIN INTERACTIVE MENU
# ============================================================================

def print_banner():
    """Print application banner"""
    print("\n" + "=" * 60)
    print("  PAATSHALA TOOL - Unified Course Management")
    print("=" * 60)


def print_main_menu(course_name, course_id):
    """Print main operation menu"""
    print("\n" + "═" * 60)
    print(f"  Course: {course_name[:45]}")
    print(f"  ID: {course_id}")
    print("═" * 60)
    print("""
  1. Fetch task list (assignments)
  2. Fetch quiz scores
  3. Fetch submissions (for specific task)
  4. Do everything (tasks + quiz + all submissions)
  
  c. Change course
  q. Quit
""")


def do_everything(session_id, course_id, num_threads):
    """Execute all operations for a course"""
    print("\n" + "=" * 60)
    print("  EXECUTING ALL OPERATIONS")
    print("=" * 60)
    
    # 1. Tasks
    tasks_file, tasks_data = fetch_tasks_list(session_id, course_id, num_threads)
    
    # 2. Quiz
    quiz_file = fetch_quiz_scores_all(session_id, course_id, num_threads)
    
    # 3. Submissions for all tasks
    if tasks_data:
        print(f"\n[Submissions] Processing {len(tasks_data)} tasks...")
        session = setup_session(session_id)
        
        for i, task in enumerate(tasks_data, 1):
            task_name = task["Task Name"]
            module_id = task["Module ID"]
            print(f"\n  [{i}/{len(tasks_data)}] {task_name[:50]}...")
            
            grading_data = fetch_assignment_grading(session, module_id)
            if grading_data:
                for row in grading_data:
                    row["Task Name"] = task_name
                    row["Module ID"] = module_id
                
                output_dir = get_output_dir(course_id)
                output_file = output_dir / f"submissions_{course_id}_mod{module_id}.csv"
                
                fieldnames = ["Task Name", "Module ID", "Name", "Status", "Last Modified",
                              "Submission", "Feedback Comments", "Final Grade"]
                
                with open(output_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(grading_data)
                
                print(f"    ✓ Saved {len(grading_data)} records")
            else:
                print(f"    ✗ No data")
    
    print("\n" + "=" * 60)
    print("  ALL OPERATIONS COMPLETE")
    output_dir = get_output_dir(course_id)
    print(f"  Output directory: {output_dir}")
    print("=" * 60)


def interactive_main(args):
    """Main interactive flow"""
    print_banner()
    
    # Authenticate
    session_id = authenticate(args.config)
    session = setup_session(session_id)
    
    # Load last session
    last_session = load_last_session()
    
    # Course selection loop
    while True:
        # Select course
        if args.course:
            course = {'id': str(args.course), 'name': f"Course {args.course}", 'category': '', 'starred': False}
            args.course = None  # Clear so we can change later
        else:
            course = select_course_interactive(session, last_session)
        
        if not course:
            print("\nGoodbye!")
            break
        
        course_id = course['id']
        course_name = course['name']
        
        # Save to last session
        save_last_session({'course_id': course_id, 'course_name': course_name})
        
        # Quick mode handling
        if args.tasks:
            fetch_tasks_list(session_id, course_id, args.threads)
            args.tasks = False
            continue
        
        if args.quiz:
            fetch_quiz_scores_all(session_id, course_id, args.threads)
            args.quiz = False
            continue
        
        if args.submissions:
            # Need to ensure tasks exist
            tasks = load_tasks_csv(course_id)
            if not tasks:
                print("[Auto] Tasks list not found, fetching first...")
                _, tasks_data = fetch_tasks_list(session_id, course_id, args.threads)
                tasks = [(t["Task Name"], t["Module ID"]) for t in tasks_data] if tasks_data else []
            
            if args.module:
                module_id = str(args.module)
                module_name = next((t[0] for t in tasks if t[1] == module_id), f"Module {module_id}")
                fetch_submissions(session_id, course_id, module_id, module_name, args.group)
            else:
                task = select_task_interactive(tasks)
                if task:
                    group = select_group_interactive(session, task[1])
                    fetch_submissions(session_id, course_id, task[1], task[0],
                                      group[0] if group else None,
                                      group[1] if group else None)
            args.submissions = False
            continue
        
        if args.all:
            do_everything(session_id, course_id, args.threads)
            args.all = False
            continue
        
        # Main menu loop
        while True:
            print_main_menu(course_name, course_id)
            
            try:
                choice = input("Your choice: ").strip().lower()
                
                if choice == '1':
                    fetch_tasks_list(session_id, course_id, args.threads)
                
                elif choice == '2':
                    fetch_quiz_scores_all(session_id, course_id, args.threads)
                
                elif choice == '3':
                    # Submissions flow
                    tasks = load_tasks_csv(course_id)
                    if not tasks:
                        print("\n[Auto] Tasks list not found, fetching first...")
                        _, tasks_data = fetch_tasks_list(session_id, course_id, args.threads)
                        tasks = [(t["Task Name"], t["Module ID"]) for t in tasks_data] if tasks_data else []
                    
                    if not tasks:
                        print("✗ No tasks available")
                        continue
                    
                    task = select_task_interactive(tasks)
                    if task:
                        group = select_group_interactive(session, task[1])
                        fetch_submissions(session_id, course_id, task[1], task[0],
                                          group[0] if group else None,
                                          group[1] if group else None)
                
                elif choice == '4':
                    do_everything(session_id, course_id, args.threads)
                
                elif choice == 'c':
                    break  # Back to course selection
                
                elif choice == 'q':
                    print("\nGoodbye!")
                    return
                
                else:
                    print("✗ Invalid choice")
                
            except (KeyboardInterrupt, EOFError):
                print("\n\nGoodbye!")
                return


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Paatshala Unified Tool - Interactive Course Management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full interactive mode
  python paatshala.py
  
  # Quick mode - specific operations
  python paatshala.py --course 450 --tasks
  python paatshala.py --course 450 --quiz
  python paatshala.py --course 450 --submissions --module 12345
  python paatshala.py --course 450 --all
  
  # With custom thread count
  python paatshala.py --course 450 --tasks --threads 8

Output:
  All files are saved to: output/course_<id>/
        """
    )
    
    parser.add_argument('--course', '-c', type=int, help='Course ID (skip course selection)')
    parser.add_argument('--tasks', action='store_true', help='Fetch task list')
    parser.add_argument('--quiz', action='store_true', help='Fetch quiz scores')
    parser.add_argument('--submissions', action='store_true', help='Fetch submissions')
    parser.add_argument('--module', '-m', type=int, help='Module ID for submissions')
    parser.add_argument('--group', '-g', type=int, help='Group ID for submissions')
    parser.add_argument('--all', action='store_true', help='Do everything (tasks + quiz + submissions)')
    parser.add_argument('--threads', '-t', type=int, default=DEFAULT_THREADS, help=f'Thread count (default: {DEFAULT_THREADS})')
    parser.add_argument('--config', type=str, default=CONFIG_FILE, help=f'Config file (default: {CONFIG_FILE})')
    
    args = parser.parse_args()
    
    try:
        interactive_main(args)
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()