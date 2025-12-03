import re
import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path

from .auth import setup_session, PAATSHALA_HOST, BASE
from .parser import parse_assign_view, parse_grading_table

DEFAULT_THREADS = 4

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
    main_session = setup_session(session_id)
    quizzes = get_quizzes(main_session, course_id)
    
    if not quizzes:
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
    """Get list of available groups for an assignment or quiz"""
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
    except Exception as e:
        print(f"Download error: {e}")
        return None
