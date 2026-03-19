#!/usr/bin/env python3
"""
Upload Zoom recording share links to Moodle as URL activities.

Examples:
  python moodle_recordings_uploader.py --course 491 --section-name "Recordings" \
      --title "CSA SGOU Feb 2026 Batch (Mar 9, 2026 06:15 PM)" \
      --url "https://ictkerala-org.zoom.us/rec/share/..."

  python moodle_recordings_uploader.py --course 491 --section-name "Recordings" \
      --input zoom_links.json
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from paatshala import (
    BASE,
    CONFIG_FILE,
    authenticate,
    load_last_session,
    save_last_session,
    select_course_interactive,
    setup_session,
)


def load_entries(input_path: str | None, title: str | None, url: str | None, description: str | None) -> list[dict]:
    """Load recording entries from JSON/CSV or a single CLI-provided item."""
    if input_path:
        path = Path(input_path)
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("JSON input must contain a list of entries")

            entries = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                entry_title = item.get("title") or item.get("topic")
                entry_url = item.get("share_url") or item.get("url")
                entry_description = item.get("description") or entry_title
                if entry_title and entry_url:
                    entries.append({
                        "title": entry_title,
                        "url": entry_url,
                        "description": entry_description,
                    })
            return entries

        if path.suffix.lower() == ".csv":
            entries = []
            with path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    entry_title = row.get("title") or row.get("Title")
                    entry_url = row.get("share_url") or row.get("url") or row.get("Share")
                    entry_description = row.get("description") or row.get("Description") or entry_title
                    if entry_title and entry_url:
                        entries.append({
                            "title": entry_title,
                            "url": entry_url,
                            "description": entry_description,
                        })
            return entries

        raise ValueError("Unsupported input file type. Use JSON or CSV.")

    if title and url:
        return [{
            "title": title,
            "url": url,
            "description": description or title,
        }]

    raise ValueError("Provide either --input or both --title and --url")


def get_course_sections(session, course_id: str) -> list[dict]:
    """Extract course section numbers and names from a Moodle course page."""
    resp = session.get(f"{BASE}/course/view.php?id={course_id}", timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    sections = []

    for node in soup.select('[id^="section-"]'):
        section_id = node.get("id", "")
        match = re.match(r"section-(\d+)", section_id)
        if not match:
            continue

        section_num = match.group(1)
        name_node = (
            node.select_one(".sectionname")
            or node.select_one("h3")
            or node.select_one("h4")
            or node.select_one(".content .summary")
        )
        section_name = name_node.get_text(" ", strip=True) if name_node else f"Section {section_num}"
        sections.append({"number": section_num, "name": section_name})

    return sections


def find_section_number(session, course_id: str, section_name: str) -> str:
    """Find a course section by name or explicit numeric section ID."""
    if section_name.isdigit():
        return section_name

    sections = get_course_sections(session, course_id)
    wanted = section_name.strip().lower()

    exact = next((s for s in sections if s["name"].strip().lower() == wanted), None)
    if exact:
        return exact["number"]

    partial = next((s for s in sections if wanted in s["name"].strip().lower()), None)
    if partial:
        return partial["number"]

    print("[Moodle] Could not find the requested section.")
    print("[Moodle] Available sections:")
    for section in sections:
        print(f"  {section['number']}: {section['name']}")
    raise ValueError(f"Section not found: {section_name}")


def get_url_activity_form(session, course_id: str, section_num: str) -> tuple[str, dict]:
    """Open the Moodle add-URL form and extract default form fields."""
    form_url = (
        f"{BASE}/course/modedit.php?add=url&type=&course={course_id}"
        f"&section={section_num}&return=0&sr=0"
    )
    resp = session.get(form_url, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    form = soup.find("form", id="mform1")
    if form is None:
        for candidate in soup.find_all("form"):
            action = candidate.get("action", "")
            names = {field.get("name") for field in candidate.find_all(["input", "textarea", "select"]) if field.get("name")}
            if "externalurl" in names and "name" in names:
                form = candidate
                break
            if "modedit.php" in action and ("name" in names or "externalurl" in names):
                form = candidate
                break

    if form is None:
        debug_path = Path(f"moodle_modedit_debug_course{course_id}_section{section_num}.html")
        debug_path.write_text(resp.text, encoding="utf-8")
        raise RuntimeError(
            f"Could not find Moodle URL activity form. Saved page HTML to {debug_path}"
        )

    payload = {}

    for field in form.find_all(["input", "textarea", "select"]):
        name = field.get("name")
        if not name:
            continue

        tag = field.name
        field_type = field.get("type", "").lower()

        if tag == "input":
            if field_type in {"submit", "button", "image", "file"}:
                continue
            if field_type in {"checkbox", "radio"} and not field.has_attr("checked"):
                continue
            payload[name] = field.get("value", "")
            continue

        if tag == "textarea":
            payload[name] = field.text or ""
            continue

        if tag == "select":
            selected = field.find("option", selected=True)
            if selected is None:
                selected = field.find("option")
            payload[name] = selected.get("value", "") if selected else ""

    action = form.get("action") or form_url
    return urljoin(resp.url, action), payload


def create_url_activity(session, course_id: str, section_num: str, entry: dict) -> str:
    """Create a Moodle URL activity for a Zoom recording."""
    action_url, payload = get_url_activity_form(session, course_id, section_num)

    payload.update({
        "name": entry["title"],
        "externalurl": entry["url"],
        "introeditor[text]": f"<p>{entry['description']}</p>",
        "introeditor[format]": payload.get("introeditor[format]", "1"),
        "showdescription": payload.get("showdescription", "0"),
        "display": payload.get("display", "0"),
        "printintro": payload.get("printintro", "1"),
        "visible": payload.get("visible", "1"),
        "submitbutton2": "Save and return to course",
    })

    resp = session.post(action_url, data=payload, allow_redirects=False, timeout=30)
    if resp.status_code not in {302, 303}:
        raise RuntimeError(f"Moodle rejected activity creation: HTTP {resp.status_code} for POST {action_url}")

    location = resp.headers.get("Location", "")
    if not location:
        raise RuntimeError("Moodle did not return a redirect after activity creation")

    return location


def get_existing_activity_titles(session, course_id: str, section_num: str) -> set[str]:
    """Fetch all activity names existing in a specific course section."""
    resp = session.get(f"{BASE}/course/view.php?id={course_id}", timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    section_node = soup.select_one(f'#section-{section_num}')
    if not section_node:
        return set()

    titles = set()
    for node in section_node.select('.activityinstance .instancename, .activity-instance-name, span.instancename'):
        # Moodle often appends hidden text for accessibility (e.g. " URL" or " Forum")
        for hidden in node.select('.accesshide'):
            hidden.extract()
            
        title = node.get_text(strip=True)
        if title:
            titles.add(title)

    return titles


def upload_entries(session, course_id: str, section_num: str, entries: list[dict]):
    """Upload multiple recording entries as Moodle URL resources."""
    existing_titles = get_existing_activity_titles(session, course_id, section_num)
    
    for index, entry in enumerate(entries, 1):
        title = entry['title']
        print(f"[{index}/{len(entries)}] Processing: {title}")
        
        if title in existing_titles:
            print(f"    [Skipping] Activity '{title}' already exists in this section.")
            continue
            
        print(f"    Creating URL activity...")
        location = create_url_activity(session, course_id, section_num, entry)
        print(f"    Redirect: {location}")
        
        # Add to existing titles to prevent duplicates within the same run
        existing_titles.add(title)


def main():
    parser = argparse.ArgumentParser(
        description="Upload Zoom recording links to Moodle as URL activities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--course", "-c", type=int, help="Course ID (skip course selection)")
    parser.add_argument("--section-name", default="Recordings", help='Target section name or numeric section ID (default: "Recordings")')
    parser.add_argument("--input", help="JSON or CSV file containing entries with title/share_url/description")
    parser.add_argument("--title", help="Single entry title")
    parser.add_argument("--url", help="Single entry share URL")
    parser.add_argument("--description", help="Single entry description; defaults to title")
    parser.add_argument("--config", default=CONFIG_FILE, help=f"Config file (default: {CONFIG_FILE})")

    args = parser.parse_args()

    try:
        entries = load_entries(args.input, args.title, args.url, args.description)
    except Exception as e:
        print(f"[Input] {e}")
        sys.exit(1)

    session_id = authenticate(args.config)
    session = setup_session(session_id)
    last_session = load_last_session()

    if args.course:
        course = {"id": str(args.course), "name": f"Course {args.course}"}
    else:
        course = select_course_interactive(session, last_session)
        if not course:
            print("Goodbye!")
            return

    course_id = str(course["id"])
    save_last_session({"course_id": course_id, "course_name": course.get("name", "")})

    try:
        section_num = find_section_number(session, course_id, args.section_name)
    except Exception as e:
        print(f"[Moodle] {e}")
        sys.exit(1)

    print(f"[Moodle] Using course {course_id}, section {section_num}")
    upload_entries(session, course_id, section_num, entries)


if __name__ == "__main__":
    main()
