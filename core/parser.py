import re
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)

def text_or_none(node):
    return node.get_text(" ", strip=True) if node else ""

def clean_grade_value(text):
    """
    Extract the grade value from a cell text.
    Handles formats like:
    - "12.30 / 15.00" (graded)
    - "30.00 / 50.00" (graded, file submission)
    - "-" (not graded)
    - Empty string
    
    Returns grade value or original text. Only returns empty for actually empty input,
    "-" (ungraded marker), or exact match on header keywords.
    """
    if not text:
        return ""
    
    stripped = text.strip()
    
    # Handle not-graded marker
    if stripped == "-":
        return "-"
    
    # Filter out exact matches on table header keywords (case-insensitive)
    if stripped.lower() in ['score', 'criterion', 'feedback', 'grade']:
        return ""
    
    # Look for the grade pattern: number / number (with possible decimals)
    # Using regex to find patterns like "12.30 / 15.00" or "30 / 50"
    grade_pattern = re.compile(r'(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)')
    match = grade_pattern.search(stripped)
    if match:
        # Return the full matched grade string, preserving format
        return f"{match.group(1)} / {match.group(2)}"
    
    # If no grade pattern found, check if it's just a simple number
    simple_number = re.compile(r'^(\d+(?:\.\d+)?)$')
    simple_match = simple_number.match(stripped)
    if simple_match:
        return simple_match.group(1)
    
    # Return the original stripped text if we can't parse it
    # This is safer than returning empty - preserves unknown formats
    return stripped

def find_table_label_value(soup, wanted_labels, debug_context=""):
    """Scan tables for label-value pairs"""
    out = {}
    all_labels_found = []  # For debugging
    
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not th or not td:
                continue
            label = text_or_none(th).strip().lower()
            value = text_or_none(td).strip()
            all_labels_found.append((label, value[:50] if value else ""))  # Truncate for logging
            for key in wanted_labels:
                if key in label and value:
                    out[key] = value
    
    # Warning when searching for grade-related info and not finding it
    if debug_context and ("grade" in str(wanted_labels).lower()) and not out:
        logger.warning(f"[{debug_context}] No grade info found! Searched for: {wanted_labels}")
        logger.warning(f"[{debug_context}] All table labels on page: {all_labels_found}")
    
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
    
    grade_info = find_table_label_value(soup, ["maximum grade", "max grade"], debug_context="parse_assign_view")
    max_grade = grade_info.get("maximum grade") or grade_info.get("max grade") or ""
    
    # Additional debug logging for max_grade
    if not max_grade:
        logger.debug(f"[parse_assign_view] max_grade NOT FOUND - grade_info was: {grade_info}")
    
    comments_count = ""
    for a in soup.find_all("a"):
        txt = a.get_text(" ", strip=True)
        m = re.search(r"Comments\s*\((\d+)\)", txt, flags=re.I)
        if m:
            comments_count = m.group(1)
            break
    
    due_date = mapped_status.get("due_date_status") or mapped_overview.get("due_date_overview") or ""
    time_remaining = mapped_status.get("time_remaining_status") or mapped_overview.get("time_remaining_overview") or ""
    
    # Extract task description from intro div
    description = ""
    intro_div = soup.find("div", {"id": "intro"})
    if intro_div:
        # Get the inner content, preserving some structure
        no_overflow = intro_div.find("div", class_="no-overflow")
        content_div = no_overflow if no_overflow else intro_div
        
        # Convert lists to readable format
        description_parts = []
        for child in content_div.children:
            if hasattr(child, 'name'):
                if child.name in ['ol', 'ul']:
                    for i, li in enumerate(child.find_all('li'), 1):
                        li_text = li.get_text(" ", strip=True)
                        if child.name == 'ol':
                            description_parts.append(f"{i}. {li_text}")
                        else:
                            description_parts.append(f"• {li_text}")
                elif child.name == 'p':
                    p_text = child.get_text(" ", strip=True)
                    if p_text:
                        description_parts.append(p_text)
                elif child.name in ['br']:
                    pass  # Skip line breaks between elements
                else:
                    text = child.get_text(" ", strip=True)
                    if text:
                        description_parts.append(text)
            elif hasattr(child, 'strip'):
                text = child.strip()
                if text:
                    description_parts.append(text)
        
        description = "\n".join(description_parts)
    
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
        "description": description,
    }

def parse_grading_table(html):
    """Parse the grading table from assignment view page.
    
    Returns:
        tuple: (rows, max_grade) where:
            - rows: List of submission dicts
            - max_grade: Extracted max grade value (float) or None if not found
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="flexible generaltable generalbox")
    if not table:
        return [], None
    
    rows = []
    max_grade = None
    
    # Detect assignment type and column indices from headers
    assignment_type = "link"  # Default
    grade_col_idx = 5  # Default grade column (fallback)
    
    thead = table.find("thead")
    if thead:
        header_ths = thead.find_all("th")
        headers = [text_or_none(th).lower() for th in header_ths]
        
        # Detect assignment type
        if any("file submissions" in h for h in headers):
            assignment_type = "file"
        elif any("online text" in h for h in headers):
            assignment_type = "link"
        
        # Find the grade column index dynamically
        # Look for "grade" header (but not "final grade" which is calculated differently)
        for i, h in enumerate(headers):
            # Match "grade" but not "final grade" - the "grade" column has the editable score
            if h.strip().startswith("grade") and "final" not in h:
                grade_col_idx = i
                
                # Try to extract max grade from header text (format: "Grade / 15.00" or "Grade / 100.00")
                header_text = text_or_none(header_ths[i])
                grade_match = re.search(r'/\s*(\d+(?:\.\d+)?)', header_text)
                if grade_match:
                    try:
                        max_grade = float(grade_match.group(1))
                        logger.info(f"[parse_grading_table] Extracted max_grade={max_grade} from header: '{header_text}'")
                    except ValueError:
                        pass
                break
    
    # Alternative: Try to find max_grade from grade input fields (data-gradedesc attribute)
    # Format: "Grade out of 15.00" or similar
    if max_grade is None:
        grade_input = soup.find("input", attrs={"data-gradedesc": True})
        if grade_input:
            grade_desc = grade_input.get("data-gradedesc", "")
            # Look for "Grade out of XX" or "XX.XX" at the end
            out_of_match = re.search(r'out of\s*(\d+(?:\.\d+)?)', grade_desc, re.I)
            if out_of_match:
                try:
                    max_grade = float(out_of_match.group(1))
                    logger.info(f"[parse_grading_table] Extracted max_grade={max_grade} from input data-gradedesc: '{grade_desc}'")
                except ValueError:
                    pass
    
    tbody = table.find("tbody")
    if not tbody:
        return [], max_grade

    for tr in tbody.find_all("tr"):
        if "emptyrow" in tr.get("class", []):
            continue
        
        cells = tr.find_all(["th", "td"])
        if len(cells) < 14:
            continue
        
        name_cell = cells[2]
        name_link = name_cell.find("a")
        name = name_link.get_text(strip=True) if name_link else ""
        
        # Extract user ID from profile link (e.g., /user/view.php?id=56674)
        user_id = None
        if name_link:
            href = name_link.get("href", "")
            user_match = re.search(r'/user/view\.php\?id=(\d+)', href)
            if user_match:
                user_id = user_match.group(1)
        
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
            submission_files = []
            for div in file_divs:
                file_link = div.find("a", href=lambda h: h and "pluginfile.php" in h)
                if file_link:
                    fname = file_link.get_text(strip=True)
                    furl = file_link.get("href", "")
                    submissions.append(fname)
                    submission_files.append((fname, furl))
            submissions = ", ".join(submissions)
        else:
            submission_files = []
            no_overflow_div = submission_cell.find("div", class_="no-overflow")
            if no_overflow_div:
                submissions = no_overflow_div.get_text(" ", strip=True)
            else:
                submissions = text_or_none(submission_cell)
        
        feedback = text_or_none(cells[11])
        final_grade = clean_grade_value(text_or_none(cells[grade_col_idx]))
        
        rows.append({
            "Name": name,
            "Email": email,
            "User_ID": user_id,
            "Status": status,
            "Last Modified": last_modified,
            "Submission": submissions,
            "Submission_Files": submission_files,
            "Submission_Type": "file" if submission_files else ("link" if "http" in submissions else ("text" if submissions else "empty")),
            "Assignment_Type": assignment_type,
            "Feedback Comments": feedback,
            "Final Grade": final_grade
        })
    
    return rows, max_grade


def extract_assignment_id(html):
    """
    Extract the assignment instance ID from the grading page.
    This is different from the module ID (cmid) - it's the database ID of the assignment.
    
    Returns:
        str: The assignment ID, or None if not found
    """
    soup = BeautifulSoup(html, "html.parser")
    
    # Method 1: Look for hidden input with name containing 'assignmentid'
    for inp in soup.find_all("input", {"type": "hidden"}):
        name = inp.get("name", "")
        if "assignmentid" in name.lower() or "assignment" in name.lower():
            val = inp.get("value", "")
            if val and val.isdigit():
                return val
    
    # Method 2: Look in JavaScript M.cfg or similar
    for script in soup.find_all("script"):
        if script.string:
            # Look for assignmentid in JSON-like structures
            match = re.search(r'["\']assignmentid["\']\s*:\s*["\']?(\d+)["\']?', script.string, re.I)
            if match:
                return match.group(1)
            # Also try without quotes around key
            match = re.search(r'assignmentid\s*[=:]\s*["\']?(\d+)["\']?', script.string, re.I)
            if match:
                return match.group(1)
    
    # Method 3: Look in form action URLs
    for form in soup.find_all("form"):
        action = form.get("action", "")
        match = re.search(r'assignmentid=(\d+)', action)
        if match:
            return match.group(1)
    
    # Method 4: Look for data attributes
    for elem in soup.find_all(attrs={"data-assignmentid": True}):
        return elem.get("data-assignmentid")
    
    return None
