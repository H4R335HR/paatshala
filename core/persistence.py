import os
import json
import csv
from pathlib import Path
from datetime import datetime

# Constants
CONFIG_FILE = ".config"
LAST_SESSION_FILE = ".last_session"
OUTPUT_DIR = "output"

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


def read_wayground_config(config_path=CONFIG_FILE):
    """Read Wayground email and password from config file"""
    if not os.path.exists(config_path):
        return None, None
    
    email, password = None, None
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
                    if key == 'wayground_email':
                        email = value
                    elif key == 'wayground_password':
                        password = value
        return email, password
    except Exception:
        return None, None


def write_wayground_config(config_path=CONFIG_FILE, email=None, password=None):
    """Write Wayground credentials to config file"""
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
                        # Skip if we're updating this key
                        if email and key == 'wayground_email':
                            continue
                        if password and key == 'wayground_password':
                            continue
                        lines.append(line)
                    else:
                        lines.append(line)
        
        # Add wayground credentials
        if email:
            lines.append(f"wayground_email={email}\n")
        if password:
            lines.append(f"wayground_password={password}\n")
        
        with open(config_path, 'w') as f:
            f.writelines(lines)
        
        return True
    except Exception:
        return False

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

def save_csv_to_disk(course_id, filename, rows, fieldnames=None):
    """Save data to CSV file in output folder"""
    output_dir = get_output_dir(course_id)
    output_path = output_dir / filename
    
    if not rows:
        return None
    
    if fieldnames is None:
        # Preserve column order from the first row, but ensure all keys are included
        # (e.g. if some rows have 'Eval_Link' and others don't)
        # This keeps freshly fetched data order consistent with cached data
        fieldnames = list(rows[0].keys())
        seen = set(fieldnames)
        for r in rows[1:]:
            for key in r.keys():
                if key not in seen:
                    fieldnames.append(key)
                    seen.add(key)
    
    try:
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return output_path
    except Exception as e:
        print(f"Error saving CSV: {e}")
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

def dataframe_to_csv(rows, columns=None):
    """Convert list of dicts to CSV string"""
    if not rows:
        return ""
    
    from io import StringIO
    output = StringIO()
    if columns is None:
        columns = list(rows[0].keys())
    
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    # Handle None values by converting to empty string for CSV
    rows_clean = [{k: (v if v is not None else "") for k, v in r.items()} for r in rows]
    writer.writerows(rows_clean)
    
    return output.getvalue()

# =============================================================================
# DISK CACHE SYSTEM
# =============================================================================
CACHE_DIR = Path(OUTPUT_DIR) / ".cache"

def get_cache_dir():
    """Get or create cache directory"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR

def save_cache(key, data):
    """
    Save data to cache with timestamp.
    Key examples: 'courses', 'course_123_topics', 'course_123_groups'
    """
    cache_dir = get_cache_dir()
    cache_file = cache_dir / f"{key}.json"
    
    cache_entry = {
        "timestamp": datetime.now().isoformat(),
        "data": data
    }
    
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_entry, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving cache for {key}: {e}")
        return False

def load_cache(key):
    """
    Load data from cache.
    Returns the data if found, None otherwise.
    """
    cache_dir = get_cache_dir()
    cache_file = cache_dir / f"{key}.json"
    
    if not cache_file.exists():
        return None
    
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_entry = json.load(f)
            return cache_entry.get("data")
    except Exception as e:
        print(f"Error loading cache for {key}: {e}")
        return None

def clear_cache(key=None):
    """
    Clear cache. If key is provided, only clear that key.
    If key is None, clear all cache.
    """
    cache_dir = get_cache_dir()
    
    try:
        if key:
            cache_file = cache_dir / f"{key}.json"
            if cache_file.exists():
                cache_file.unlink()
        else:
            # Clear all cache files
            for f in cache_dir.glob("*.json"):
                f.unlink()
        return True
    except Exception as e:
        print(f"Error clearing cache: {e}")
        return False


def clear_output():
    """
    Clear entire output folder (all course data, CSVs, downloads).
    WARNING: This is destructive!
    """
    import shutil
    output_path = Path(OUTPUT_DIR)
    
    try:
        if output_path.exists():
            shutil.rmtree(output_path)
        return True
    except Exception as e:
        print(f"Error clearing output: {e}")
        return False
