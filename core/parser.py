import re
from bs4 import BeautifulSoup

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
    """Parse the grading table from assignment view page"""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="flexible generaltable generalbox")
    if not table:
        return []
    
    rows = []
    # Detect assignment type from headers
    assignment_type = "link" # Default
    thead = table.find("thead")
    if thead:
        headers = [text_or_none(th).lower() for th in thead.find_all("th")]
        if any("file submissions" in h for h in headers):
            assignment_type = "file"
        elif any("online text" in h for h in headers):
            assignment_type = "link"
    
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
        final_grade = text_or_none(cells[13])
        
        rows.append({
            "Name": name,
            "Email": email,
            "Status": status,
            "Last Modified": last_modified,
            "Submission": submissions,
            "Submission_Files": submission_files,
            "Submission_Type": "file" if submission_files else ("link" if "http" in submissions else ("text" if submissions else "empty")),
            "Assignment_Type": assignment_type,
            "Feedback Comments": feedback,
            "Final Grade": final_grade
        })
    
    return rows
