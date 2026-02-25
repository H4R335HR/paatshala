"""
Moodle course content import automation.

Drives the multi-step /backup/import.php wizard programmatically:
1. Select source course
2. Initial settings (what to include)
3. Schema settings (which sections/activities)
4. Confirmation → Execute
"""
import re
import logging
from bs4 import BeautifulSoup
from .auth import BASE

logger = logging.getLogger(__name__)


def _extract_form_fields(html, form_selector=None):
    """
    Extract all form fields (hidden inputs, checkboxes, selects, etc.)
    from a Moodle HTML page.
    
    Returns:
        dict: {field_name: field_value}
    """
    soup = BeautifulSoup(html, 'html.parser')
    
    # Find the form
    if form_selector:
        form = soup.select_one(form_selector)
    else:
        # Try to find the backup/import form
        form = soup.find('form', {'method': 'post'})
        if not form:
            form = soup  # Fall back to entire page
    
    fields = {}
    
    # Hidden inputs
    for inp in form.find_all('input', {'type': 'hidden'}):
        name = inp.get('name')
        if name:
            fields[name] = inp.get('value', '')
    
    # Checkboxes - include if checked, or if it's a "setting" checkbox include it checked
    for inp in form.find_all('input', {'type': 'checkbox'}):
        name = inp.get('name')
        if name:
            # Include all checkboxes as checked (we want to import everything)
            fields[name] = inp.get('value', '1')
    
    # Text/number inputs
    for inp in form.find_all('input', {'type': ['text', 'number']}):
        name = inp.get('name')
        if name:
            fields[name] = inp.get('value', '')
    
    # NOTE: We intentionally skip submit buttons here.
    # Browsers only send the CLICKED submit button's name/value.
    # Including multiple submit buttons (e.g. oneclickbackup + submitbutton)
    # confuses Moodle. The caller should explicitly add the desired button.
    
    # Select elements - get selected value
    for sel in form.find_all('select'):
        name = sel.get('name')
        if name:
            selected = sel.find('option', selected=True)
            if selected:
                fields[name] = selected.get('value', '')
            else:
                # Use first option
                first = sel.find('option')
                if first:
                    fields[name] = first.get('value', '')
    
    return fields


def _parse_schema_modules(html):
    """
    Parse the schema/selection page (Step 3 of Moodle import wizard)
    to extract the list of importable sections and activities.
    
    Activities include a 'parent_section' field linking them to their
    containing section (by field_key), determined by DOM order.
    
    Returns:
        list: [{'name': str, 'field_key': str, 'type': 'section'|'activity',
                'checked': bool, 'parent_section': str|None}, ...]
    """
    soup = BeautifulSoup(html, 'html.parser')
    form = soup.find('form', {'method': 'post'})
    if not form:
        form = soup
    
    modules = []
    current_section_key = None
    
    # Find all checkboxes whose name matches setting_*_included
    for inp in form.find_all('input', {'type': 'checkbox'}):
        name = inp.get('name', '')
        if not name.endswith('_included'):
            continue
        
        # Determine type from the field name pattern
        # Sections: setting_section_<N>_included
        # Activities: setting_activity_<type>_<id>_included
        if name.startswith('setting_section_'):
            mod_type = 'section'
            current_section_key = name
        elif name.startswith('setting_activity_'):
            mod_type = 'activity'
        else:
            continue
        
        # Get human-readable name from the associated label
        input_id = inp.get('id', '')
        label = None
        if input_id:
            label = form.find('label', {'for': input_id})
        
        if label:
            display_name = label.get_text(strip=True)
        else:
            # Try the parent element for text
            parent = inp.find_parent(['div', 'td', 'li'])
            if parent:
                display_name = parent.get_text(strip=True)
            else:
                display_name = name
        
        checked = inp.has_attr('checked')
        
        modules.append({
            'name': display_name,
            'field_key': name,
            'type': mod_type,
            'checked': checked,
            'parent_section': current_section_key if mod_type == 'activity' else None,
        })
    
    return modules


def get_importable_courses(session, target_course_id):
    """
    Fetch the list of courses available for import into the target course.
    
    Returns:
        list: [{'id': str, 'shortname': str, 'fullname': str}, ...]
    """
    url = f"{BASE}/backup/import.php?id={target_course_id}"
    try:
        resp = session.get(url, timeout=30)
        if not resp.ok:
            logger.error(f"Failed to load import page: HTTP {resp.status_code}")
            return []
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        courses = []
        
        # Find all radio buttons for course selection
        for radio in soup.find_all('input', {'type': 'radio', 'name': 'importid'}):
            course_id = radio.get('value')
            if not course_id:
                continue
            
            # Get the row containing this radio
            tr = radio.find_parent('tr')
            if tr:
                cells = tr.find_all('td')
                shortname = cells[1].get_text(strip=True) if len(cells) > 1 else ''
                fullname = cells[2].get_text(strip=True) if len(cells) > 2 else shortname
                courses.append({
                    'id': course_id,
                    'shortname': shortname,
                    'fullname': fullname
                })
        
        return courses
    except Exception as e:
        logger.error(f"Error fetching importable courses: {e}")
        return []


def search_importable_courses(session, target_course_id, search_term):
    """
    Search for courses available for import (posts search form).
    
    Returns:
        list: [{'id': str, 'shortname': str, 'fullname': str}, ...]
    """
    url = f"{BASE}/backup/import.php"
    data = {
        'id': str(target_course_id),
        'target': '1',
        'search': search_term,
        'searchcourses': 'Search'
    }
    try:
        resp = session.post(url, data=data, timeout=30)
        if not resp.ok:
            logger.error(f"Failed to search import courses: HTTP {resp.status_code}")
            return []
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        courses = []
        
        for radio in soup.find_all('input', {'type': 'radio', 'name': 'importid'}):
            course_id = radio.get('value')
            if not course_id:
                continue
            
            tr = radio.find_parent('tr')
            if tr:
                cells = tr.find_all('td')
                shortname = cells[1].get_text(strip=True) if len(cells) > 1 else ''
                fullname = cells[2].get_text(strip=True) if len(cells) > 2 else shortname
                courses.append({
                    'id': course_id,
                    'shortname': shortname,
                    'fullname': fullname
                })
        
        return courses
    except Exception as e:
        logger.error(f"Error searching importable courses: {e}")
        return []


def _drive_wizard_to_schema(session, source_course_id, target_course_id):
    """
    Drive the Moodle import wizard through Steps 0-2 and return the schema
    page HTML + extracted form fields.
    
    Returns:
        tuple: (success: bool, result_or_error: dict|str)
        On success, result dict has keys: 'schema_html', 'step3_fields', 'sesskey'
        On failure, result is an error message string.
    """
    import_url = f"{BASE}/backup/import.php"
    
    # STEP 0: GET the import page to obtain sesskey
    logger.info("Fetching import page to get sesskey...")
    resp = session.get(f"{import_url}?id={target_course_id}", timeout=30)
    if not resp.ok:
        return False, f"Failed to load import page: HTTP {resp.status_code}"
    
    # Extract sesskey
    sesskey = None
    match = re.search(r'"sesskey":"([^"]+)"', resp.text)
    if match:
        sesskey = match.group(1)
    else:
        match = re.search(r'sesskey=([a-zA-Z0-9]+)', resp.text)
        if match:
            sesskey = match.group(1)
    
    if not sesskey:
        return False, "Could not extract sesskey from import page"
    
    logger.info(f"Got sesskey: {sesskey[:4]}...")
    
    # STEP 1: Select source course
    page0_fields = _extract_form_fields(resp.text)
    step1_data = dict(page0_fields)
    step1_data['id'] = str(target_course_id)
    step1_data['target'] = '1'
    step1_data['importid'] = str(source_course_id)
    step1_data['sesskey'] = sesskey
    for key in list(step1_data.keys()):
        if key in ('searchcourses',):
            del step1_data[key]
    
    logger.info(f"Step 1 POST with {len(step1_data)} fields: {list(step1_data.keys())}")
    resp = session.post(import_url, data=step1_data, timeout=60)
    if not resp.ok:
        return False, f"Step 1 failed: HTTP {resp.status_code}"
    
    step2_fields = _extract_form_fields(resp.text)
    if not step2_fields:
        return False, "Step 1 failed: Could not extract form fields"
    
    setting_keys = [k for k in step2_fields if k.startswith('setting_')]
    logger.info(f"Step 1 complete: got {len(step2_fields)} form fields, {len(setting_keys)} setting fields")
    
    # STEP 2: Initial settings
    step2_post = {
        'id': step2_fields.get('id', str(target_course_id)),
        'stage': step2_fields.get('stage', '1'),
        'backup': step2_fields.get('backup', ''),
        'importid': step2_fields.get('importid', str(source_course_id)),
        'target': step2_fields.get('target', '1'),
        'sesskey': step2_fields.get('sesskey', sesskey),
        '_qf__backup_initial_form': step2_fields.get('_qf__backup_initial_form', '1'),
        'setting_root_users': '0',
        'setting_root_activities': '1',
        'setting_root_files': '1',
        'setting_root_questionbank': '1',
        'submitbutton': 'Next',
    }
    
    logger.info(f"Step 2 POST with {len(step2_post)} fields:")
    for k, v in step2_post.items():
        logger.info(f"  {k} = {v}")
    
    resp = session.post(import_url, data=step2_post, timeout=60)
    logger.info(f"Step 2 response: status={resp.status_code}, url={resp.url}")
    if not resp.ok:
        body_snippet = resp.text[:500] if resp.text else '(empty)'
        logger.error(f"Step 2 FAILED body snippet: {body_snippet}")
        return False, f"Step 2 failed: HTTP {resp.status_code} - URL: {resp.url}"
    
    step3_fields = _extract_form_fields(resp.text)
    if not step3_fields:
        return False, "Step 2 failed: Could not extract form fields for schema page"
    
    setting_keys = [k for k in step3_fields if k.startswith('setting_')]
    logger.info(f"Step 2 complete: got {len(step3_fields)} form fields, {len(setting_keys)} setting fields")
    
    return True, {
        'schema_html': resp.text,
        'step3_fields': step3_fields,
        'sesskey': sesskey,
    }


def fetch_importable_modules(session, source_course_id, target_course_id, progress_callback=None):
    """
    Drive the Moodle import wizard through the initial steps and return
    the list of importable sections/activities for user selection.
    
    Args:
        session: Authenticated requests.Session
        source_course_id: ID of the course to import FROM
        target_course_id: ID of the course to import INTO
        progress_callback: Optional callable(step, total_steps, message)
    
    Returns:
        tuple: (success: bool, modules_or_error: list|str, wizard_state: dict|None)
        On success: modules is a list of dicts with keys:
            name, field_key, type ('section'|'activity'), checked (bool)
        On failure: modules_or_error is an error message string.
    """
    def notify(step, msg):
        logger.info(f"Import step {step}/2: {msg}")
        if progress_callback:
            progress_callback(step, 2, msg)
    
    try:
        notify(1, "Connecting to Moodle import wizard...")
        ok, result = _drive_wizard_to_schema(session, source_course_id, target_course_id)
        
        if not ok:
            return False, result, None
        
        notify(2, "Parsing available modules...")
        modules = _parse_schema_modules(result['schema_html'])
        
        if not modules:
            logger.warning("No modules found on schema page; the source course may be empty.")
            return False, "No importable modules found in the source course.", None
        
        logger.info(f"Found {len(modules)} importable modules: "
                     f"{sum(1 for m in modules if m['type'] == 'section')} sections, "
                     f"{sum(1 for m in modules if m['type'] == 'activity')} activities")
        
        # The wizard_state captures everything needed to resume at Step 3
        wizard_state = {
            'step3_fields': result['step3_fields'],
            'sesskey': result['sesskey'],
        }
        
        return True, modules, wizard_state
        
    except Exception as e:
        logger.error(f"Error fetching importable modules: {e}", exc_info=True)
        return False, f"Error: {str(e)}", None


def import_course_content(session, source_course_id, target_course_id,
                          selected_modules=None, wizard_state=None,
                          progress_callback=None):
    """
    Import course content from source to target course by driving the
    Moodle import wizard programmatically.
    
    Args:
        session: Authenticated requests.Session
        source_course_id: ID of the course to import FROM
        target_course_id: ID of the course to import INTO
        selected_modules: Optional list of field_key strings to import.
                         If None, imports everything (old behavior).
        wizard_state: Ignored (kept for backward compatibility).
                     The wizard is always re-driven from scratch to avoid
                     stale session/backup hashes.
        progress_callback: Optional callable(step, total_steps, message)
    
    Returns:
        tuple: (success: bool, message: str)
    """
    import_url = f"{BASE}/backup/import.php"
    
    def notify(step, msg):
        logger.info(f"Import step {step}/4: {msg}")
        if progress_callback:
            progress_callback(step, 4, msg)
    
    try:
        # =====================================================================
        # Steps 0-2: Always re-drive the wizard from scratch.
        # Saved wizard_state is NOT reused because the backup hash and sesskey
        # expire after a few minutes (while the user is selecting modules).
        # =====================================================================
        notify(1, "Selecting source course...")
        notify(2, "Configuring import settings...")
        ok, result = _drive_wizard_to_schema(session, source_course_id, target_course_id)
        if not ok:
            return False, result
        step3_fields = result['step3_fields']
        
        # =====================================================================
        # STEP 3: Schema settings (select sections/activities to import)
        # =====================================================================
        notify(3, "Selecting content to import...")
        
        if selected_modules is not None:
            # User selected specific modules — only include those checkboxes.
            # Build the POST data with only the selected _included fields checked.
            selected_set = set(selected_modules)
            keys_to_remove = []
            for key in step3_fields:
                if key.endswith('_included') and key.startswith('setting_'):
                    if key not in selected_set:
                        keys_to_remove.append(key)
                        # Also remove the associated _userinfo field if present
                        userinfo_key = key.replace('_included', '_userinfo')
                        if userinfo_key in step3_fields:
                            keys_to_remove.append(userinfo_key)
            
            for key in keys_to_remove:
                del step3_fields[key]
            
            logger.info(f"User selected {len(selected_modules)} modules; "
                         f"removed {len(keys_to_remove)} unchecked fields")
            # Log which modules are being imported
            remaining = [k for k in step3_fields if k.endswith('_included')]
            logger.info(f"Modules being imported: {remaining}")
        
        step3_fields['submitbutton'] = 'Next'
        
        logger.info(f"Step 3 POST with {len(step3_fields)} fields:")
        for k, v in step3_fields.items():
            logger.info(f"  {k} = {v}")
        resp = session.post(import_url, data=step3_fields, timeout=60)
        
        logger.info(f"Step 3 response: status={resp.status_code}, url={resp.url}")
        if not resp.ok:
            return False, f"Step 3 failed: HTTP {resp.status_code}"
        
        # Extract form fields for step 4 (confirmation)
        step4_fields = _extract_form_fields(resp.text)
        
        if not step4_fields:
            return False, "Step 3 failed: Could not extract confirmation form fields"
        
        logger.info(f"Step 3 complete: got {len(step4_fields)} form fields")
        
        # =====================================================================
        # STEP 4: Confirm and execute import
        # =====================================================================
        notify(4, "Executing import...")
        
        # Set the correct submit button for final confirmation
        step4_fields['submitbutton'] = 'Perform import'
        
        logger.info(f"Step 4 POST with {len(step4_fields)} fields")
        resp = session.post(import_url, data=step4_fields, timeout=120)
        
        logger.info(f"Step 4 response: status={resp.status_code}, url={resp.url}")
        if not resp.ok:
            logger.error(f"Step 4 FAILED: HTTP {resp.status_code}")
            body_snippet = resp.text[:500] if resp.text else '(empty)'
            logger.error(f"Step 4 response body snippet: {body_snippet}")
            return False, f"Step 4 failed: HTTP {resp.status_code}"
        
        # Parse the response for diagnostics
        soup = BeautifulSoup(resp.text, 'html.parser')
        page_text = resp.text.lower()
        resp_len = len(resp.text)
        
        title_tag = soup.find('title')
        page_title = title_tag.get_text(strip=True) if title_tag else '(no title)'
        
        # Check if we're still on the wizard (stage field present = import didn't execute)
        stage_input = soup.find('input', {'name': 'stage', 'type': 'hidden'})
        stage_val = stage_input.get('value', '?') if stage_input else None
        
        logger.info(f"Step 4 response: {resp_len} chars, title='{page_title}', "
                     f"stage={stage_val}")
        
        # Check if we got redirected to the course page (definite success)
        if f'/course/view.php?id={target_course_id}' in resp.url:
            logger.info("Import success: redirected to course page")
            return True, "Import completed successfully!"
        
        # Check for the specific Moodle "Import complete" success indicator.
        # On a successful import, Moodle shows a page with heading "Import complete"
        # and a single "Continue" button linking back to the course.
        # The page is typically small (< 20KB) compared to wizard pages (100KB+).
        backup_div = soup.find('div', class_='backup-restore')
        if backup_div:
            div_text = backup_div.get_text(strip=True).lower()
            if 'import complete' in div_text:
                logger.info("Import success: found 'import complete' in backup-restore div")
                return True, "Import completed successfully!"
        
        # Also check for "Import complete" as a heading anywhere
        for heading in soup.find_all(['h2', 'h3']):
            if 'import complete' in heading.get_text(strip=True).lower():
                logger.info("Import success: found 'import complete' heading")
                return True, "Import completed successfully!"
        
        # Check for a "Continue" button/link that goes to the course (success page)
        continue_link = soup.find('a', string=re.compile(r'^\s*Continue\s*$', re.IGNORECASE))
        if continue_link:
            href = continue_link.get('href', '')
            if f'id={target_course_id}' in href:
                logger.info(f"Import success: found Continue link to course: {href}")
                return True, "Import completed successfully!"
        
        # Check for a single "Continue" button (Moodle sometimes uses a form button)
        continue_btn = soup.find('button', string=re.compile(r'^\s*Continue\s*$', re.IGNORECASE))
        if continue_btn:
            logger.info("Import success: found Continue button")
            return True, "Import completed successfully!"
        
        # Check for error messages
        error_div = soup.find('div', class_='alert-danger') or soup.find('div', class_='notifyproblem')
        if error_div:
            error_text = error_div.get_text(strip=True)
            logger.error(f"Import failed with error: {error_text}")
            return False, f"Import failed: {error_text}"
        
        # If we're still on the wizard (stage field found), the import didn't complete
        if stage_val is not None:
            logger.error(f"Import did NOT complete: still on wizard stage {stage_val}. "
                          f"Page title: '{page_title}'")
            # Log more of the page for debugging
            logger.error(f"Response body snippet: {resp.text[:500]}")
            return False, (f"Import did not complete — Moodle wizard stuck at stage {stage_val}. "
                           f"The import form may have been rejected.")
        
        # Ambiguous result — log details and report uncertain
        logger.warning(f"Import result ambiguous. Title: '{page_title}', "
                        f"response length: {resp_len}")
        logger.warning(f"Response body snippet: {resp.text[:500]}")
        return True, "Import appears to have completed. Please verify the course content."
        
    except Exception as e:
        logger.error(f"Import error: {e}", exc_info=True)
        return False, f"Import error: {str(e)}"

