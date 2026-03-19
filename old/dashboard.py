#!/usr/bin/env python3
"""
Zoom → Moodle Recording Pipeline Dashboard

A FastAPI-based dashboard for managing automated Zoom recording extraction
and Moodle upload pipelines. Runs alongside your existing zoomvshare.py and
moodlesharer.py scripts.

Usage:
    python dashboard.py                          # default: 0.0.0.0:8099
    python dashboard.py --port 9000              # custom port
    python dashboard.py --scripts-dir /path/to   # custom scripts location

Author: Hareesh (ICT Academy of Kerala)
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import uvicorn


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_FILE = os.environ.get("DASHBOARD_DB", "dashboard.sqlite3")
SCRIPTS_DIR = os.environ.get("SCRIPTS_DIR", ".")
PYTHON_BIN = os.environ.get("PYTHON_BIN", sys.executable)

# The xvfb-run prefix for headless Playwright
XVFB_PREFIX = os.environ.get("XVFB_PREFIX", "xvfb-run")

app = FastAPI(title="Zoom→Moodle Dashboard", version="1.0.0")

# Global lock so only one pipeline runs at a time (Playwright / Zoom auth)
_pipeline_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db_path() -> str:
    return app.state.db_path if hasattr(app.state, "db_path") else DB_FILE


@contextmanager
def get_db():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS batch_mappings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            search_term     TEXT NOT NULL,
            course_id       INTEGER NOT NULL,
            section_name    TEXT NOT NULL DEFAULT 'Recordings',
            check_settings  INTEGER NOT NULL DEFAULT 1,
            limit_count     INTEGER NOT NULL DEFAULT 0,
            enabled         INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_mapping_id    INTEGER REFERENCES batch_mappings(id) ON DELETE SET NULL,
            batch_name          TEXT NOT NULL DEFAULT '',
            status              TEXT NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','running','completed','failed')),
            trigger_type        TEXT NOT NULL DEFAULT 'manual'
                                CHECK (trigger_type IN ('manual','cron','api')),
            started_at          TEXT,
            finished_at         TEXT,
            zoom_stdout         TEXT DEFAULT '',
            zoom_stderr         TEXT DEFAULT '',
            moodle_stdout       TEXT DEFAULT '',
            moodle_stderr       TEXT DEFAULT '',
            recordings_found    INTEGER DEFAULT 0,
            uploaded_count      INTEGER DEFAULT 0,
            skipped_count       INTEGER DEFAULT 0,
            failed_count        INTEGER DEFAULT 0,
            error_summary       TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS recording_entries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
            title           TEXT NOT NULL,
            share_url       TEXT DEFAULT '',
            meeting_id      TEXT DEFAULT '',
            course_id       INTEGER,
            section_name    TEXT DEFAULT '',
            status          TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','uploaded','skipped','failed')),
            error_log       TEXT DEFAULT '',
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_runs_status ON pipeline_runs(status);
        CREATE INDEX IF NOT EXISTS idx_runs_started ON pipeline_runs(started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_entries_run ON recording_entries(pipeline_run_id);
        """)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class BatchMappingCreate(BaseModel):
    name: str
    search_term: str
    course_id: int
    section_name: str = "Recordings"
    check_settings: bool = True
    limit_count: int = 0
    enabled: bool = True


class BatchMappingUpdate(BaseModel):
    name: Optional[str] = None
    search_term: Optional[str] = None
    course_id: Optional[int] = None
    section_name: Optional[str] = None
    check_settings: Optional[bool] = None
    limit_count: Optional[int] = None
    enabled: Optional[bool] = None


class TriggerRequest(BaseModel):
    trigger_type: str = "manual"


# ---------------------------------------------------------------------------
# Pipeline runner (background thread)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_pipeline(run_id: int, mapping: dict):
    """Execute the two-stage pipeline in a background thread."""
    db_path = get_db_path()
    scripts_dir = Path(app.state.scripts_dir if hasattr(app.state, "scripts_dir") else SCRIPTS_DIR)

    def _update_run(**kwargs):
        placeholders = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [run_id]
        conn = sqlite3.connect(db_path)
        conn.execute(f"UPDATE pipeline_runs SET {placeholders} WHERE id=?", values)
        conn.commit()
        conn.close()

    _update_run(status="running", started_at=_now_iso())

    # --- Stage 1: Zoom link extraction ---
    zoom_links_file = scripts_dir / f".zoom_links_run{run_id}.json"
    zoom_cmd = [
        XVFB_PREFIX, PYTHON_BIN, str(scripts_dir / "zoomvshare.py"),
        "--links",
        "--search", mapping["search_term"],
        "--links-output", str(zoom_links_file),
        "--check-settings" if mapping["check_settings"] else "",
    ]
    if mapping["limit_count"] != 0:
        zoom_cmd.extend(["--limit", str(mapping["limit_count"])])
    zoom_cmd = [c for c in zoom_cmd if c]  # remove empty strings

    try:
        zoom_result = subprocess.run(
            zoom_cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(scripts_dir),
        )
        _update_run(
            zoom_stdout=zoom_result.stdout[-50000:],  # cap at 50KB
            zoom_stderr=zoom_result.stderr[-50000:],
        )

        if zoom_result.returncode != 0:
            _update_run(
                status="failed",
                finished_at=_now_iso(),
                error_summary=f"Zoom extraction failed (exit code {zoom_result.returncode})",
            )
            return

    except subprocess.TimeoutExpired:
        _update_run(
            status="failed",
            finished_at=_now_iso(),
            error_summary="Zoom extraction timed out after 5 minutes",
        )
        return
    except Exception as e:
        _update_run(
            status="failed",
            finished_at=_now_iso(),
            error_summary=f"Zoom extraction error: {str(e)[:500]}",
        )
        return

    # Parse the generated links file
    recordings_found = 0
    try:
        if zoom_links_file.exists():
            links_data = json.loads(zoom_links_file.read_text(encoding="utf-8"))
            recordings_found = len(links_data)
            _update_run(recordings_found=recordings_found)

            # Insert recording entries
            conn = sqlite3.connect(db_path)
            for entry in links_data:
                conn.execute(
                    """INSERT INTO recording_entries
                       (pipeline_run_id, title, share_url, meeting_id, course_id, section_name, status)
                       VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
                    (
                        run_id,
                        entry.get("title", "Untitled"),
                        entry.get("share_url", ""),
                        entry.get("meeting_id", ""),
                        mapping["course_id"],
                        mapping["section_name"],
                    ),
                )
            conn.commit()
            conn.close()
    except Exception as e:
        _update_run(
            status="failed",
            finished_at=_now_iso(),
            error_summary=f"Failed to parse zoom links: {str(e)[:500]}",
        )
        return

    if recordings_found == 0:
        _update_run(
            status="completed",
            finished_at=_now_iso(),
            error_summary="No recordings found matching search term",
        )
        return

    # --- Stage 2: Moodle upload ---
    moodle_cmd = [
        PYTHON_BIN, str(scripts_dir / "moodlesharer.py"),
        "-c", str(mapping["course_id"]),
        "--section-name", mapping["section_name"],
        "--input", str(zoom_links_file),
    ]

    try:
        moodle_result = subprocess.run(
            moodle_cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(scripts_dir),
        )
        _update_run(
            moodle_stdout=moodle_result.stdout[-50000:],
            moodle_stderr=moodle_result.stderr[-50000:],
        )

        # Parse moodle output to determine per-entry status
        uploaded = 0
        skipped = 0
        failed = 0

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        entries = conn.execute(
            "SELECT id, title FROM recording_entries WHERE pipeline_run_id=?",
            (run_id,),
        ).fetchall()

        moodle_out = moodle_result.stdout
        for entry in entries:
            title = entry["title"]
            entry_id = entry["id"]
            if f"[Skipping] Activity '{title}' already exists" in moodle_out:
                conn.execute(
                    "UPDATE recording_entries SET status='skipped' WHERE id=?",
                    (entry_id,),
                )
                skipped += 1
            elif f"Processing: {title}" in moodle_out:
                # Check if there's a redirect (success indicator)
                idx = moodle_out.find(f"Processing: {title}")
                chunk = moodle_out[idx:idx + 500]
                if "Redirect:" in chunk:
                    conn.execute(
                        "UPDATE recording_entries SET status='uploaded' WHERE id=?",
                        (entry_id,),
                    )
                    uploaded += 1
                else:
                    conn.execute(
                        "UPDATE recording_entries SET status='failed', error_log=? WHERE id=?",
                        ("No redirect after creation attempt", entry_id),
                    )
                    failed += 1
            else:
                conn.execute(
                    "UPDATE recording_entries SET status='failed', error_log=? WHERE id=?",
                    ("Entry not found in Moodle output", entry_id),
                )
                failed += 1

        conn.commit()
        conn.close()

        final_status = "completed" if moodle_result.returncode == 0 else "failed"
        error_summary = ""
        if moodle_result.returncode != 0:
            error_summary = f"Moodle upload exited with code {moodle_result.returncode}"

        _update_run(
            status=final_status,
            finished_at=_now_iso(),
            uploaded_count=uploaded,
            skipped_count=skipped,
            failed_count=failed,
            error_summary=error_summary,
        )

    except subprocess.TimeoutExpired:
        _update_run(
            status="failed",
            finished_at=_now_iso(),
            error_summary="Moodle upload timed out after 5 minutes",
        )
    except Exception as e:
        _update_run(
            status="failed",
            finished_at=_now_iso(),
            error_summary=f"Moodle upload error: {str(e)[:500]}",
        )
    finally:
        # Cleanup temp links file
        try:
            zoom_links_file.unlink(missing_ok=True)
        except Exception:
            pass


def trigger_pipeline(mapping_id: int, trigger_type: str = "manual") -> int:
    """Create a pipeline run and start it in a background thread."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM batch_mappings WHERE id=?", (mapping_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Batch mapping not found")

        mapping = dict(row)

        cursor = conn.execute(
            """INSERT INTO pipeline_runs (batch_mapping_id, batch_name, status, trigger_type)
               VALUES (?, ?, 'pending', ?)""",
            (mapping_id, mapping["name"], trigger_type),
        )
        run_id = cursor.lastrowid

    def _run_with_lock():
        acquired = _pipeline_lock.acquire(timeout=600)
        if not acquired:
            with get_db() as conn:
                conn.execute(
                    "UPDATE pipeline_runs SET status='failed', error_summary='Could not acquire pipeline lock (another run in progress)', finished_at=? WHERE id=?",
                    (_now_iso(), run_id),
                )
            return
        try:
            _run_pipeline(run_id, mapping)
        finally:
            _pipeline_lock.release()

    thread = threading.Thread(target=_run_with_lock, daemon=True)
    thread.start()
    return run_id


# ---------------------------------------------------------------------------
# API routes — Batch Mappings
# ---------------------------------------------------------------------------

@app.get("/api/mappings")
def list_mappings():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM batch_mappings ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/mappings", status_code=201)
def create_mapping(data: BatchMappingCreate):
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO batch_mappings
               (name, search_term, course_id, section_name, check_settings, limit_count, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                data.name,
                data.search_term,
                data.course_id,
                data.section_name,
                int(data.check_settings),
                data.limit_count,
                int(data.enabled),
            ),
        )
        return {"id": cursor.lastrowid, "message": "Created"}


@app.put("/api/mappings/{mapping_id}")
def update_mapping(mapping_id: int, data: BatchMappingUpdate):
    updates = {}
    for field in ("name", "search_term", "course_id", "section_name", "limit_count"):
        val = getattr(data, field)
        if val is not None:
            updates[field] = val
    for field in ("check_settings", "enabled"):
        val = getattr(data, field)
        if val is not None:
            updates[field] = int(val)

    if not updates:
        raise HTTPException(400, "No fields to update")

    updates["updated_at"] = _now_iso()
    placeholders = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [mapping_id]

    with get_db() as conn:
        affected = conn.execute(
            f"UPDATE batch_mappings SET {placeholders} WHERE id=?", values
        ).rowcount
        if affected == 0:
            raise HTTPException(404, "Not found")
    return {"message": "Updated"}


@app.delete("/api/mappings/{mapping_id}")
def delete_mapping(mapping_id: int):
    with get_db() as conn:
        affected = conn.execute(
            "DELETE FROM batch_mappings WHERE id=?", (mapping_id,)
        ).rowcount
        if affected == 0:
            raise HTTPException(404, "Not found")
    return {"message": "Deleted"}


# ---------------------------------------------------------------------------
# API routes — Pipeline Runs
# ---------------------------------------------------------------------------

@app.get("/api/runs")
def list_runs(
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
    mapping_id: Optional[int] = None,
    status: Optional[str] = None,
):
    where_clauses = []
    params = []
    if mapping_id is not None:
        where_clauses.append("batch_mapping_id=?")
        params.append(mapping_id)
    if status:
        where_clauses.append("status=?")
        params.append(status)

    where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params_count = list(params)
    params += [limit, offset]

    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT id, batch_mapping_id, batch_name, status, trigger_type,
                       started_at, finished_at, recordings_found,
                       uploaded_count, skipped_count, failed_count, error_summary
                FROM pipeline_runs {where}
                ORDER BY id DESC LIMIT ? OFFSET ?""",
            params,
        ).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM pipeline_runs {where}", params_count
        ).fetchone()[0]

    return {"runs": [dict(r) for r in rows], "total": total}


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    with get_db() as conn:
        run = conn.execute(
            "SELECT * FROM pipeline_runs WHERE id=?", (run_id,)
        ).fetchone()
        if not run:
            raise HTTPException(404, "Run not found")

        entries = conn.execute(
            "SELECT * FROM recording_entries WHERE pipeline_run_id=? ORDER BY id",
            (run_id,),
        ).fetchall()

    return {"run": dict(run), "entries": [dict(e) for e in entries]}


@app.post("/api/trigger/{mapping_id}")
def trigger_single(mapping_id: int, data: TriggerRequest = TriggerRequest()):
    if _pipeline_lock.locked():
        raise HTTPException(409, "A pipeline is already running. Wait for it to finish.")
    run_id = trigger_pipeline(mapping_id, data.trigger_type)
    return {"run_id": run_id, "message": "Pipeline triggered"}


@app.post("/api/trigger-all")
def trigger_all(data: TriggerRequest = TriggerRequest()):
    if _pipeline_lock.locked():
        raise HTTPException(409, "A pipeline is already running. Wait for it to finish.")

    with get_db() as conn:
        mappings = conn.execute(
            "SELECT id FROM batch_mappings WHERE enabled=1 ORDER BY id"
        ).fetchall()

    if not mappings:
        raise HTTPException(404, "No enabled batch mappings found")

    # Queue them sequentially in a thread
    mapping_ids = [m["id"] for m in mappings]

    def _run_all():
        for mid in mapping_ids:
            try:
                trigger_pipeline(mid, data.trigger_type)
                # Wait for the run to finish before starting next
                time.sleep(2)
                while _pipeline_lock.locked():
                    time.sleep(1)
            except Exception:
                continue

    thread = threading.Thread(target=_run_all, daemon=True)
    thread.start()

    return {
        "message": f"Triggered pipeline for {len(mapping_ids)} batch(es)",
        "mapping_ids": mapping_ids,
    }


# ---------------------------------------------------------------------------
# API routes — Recording Entries
# ---------------------------------------------------------------------------

@app.get("/api/recordings")
def list_recordings(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    run_id: Optional[int] = None,
):
    where_clauses = []
    params = []
    if status:
        where_clauses.append("status=?")
        params.append(status)
    if run_id is not None:
        where_clauses.append("pipeline_run_id=?")
        params.append(run_id)

    where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params += [limit, offset]

    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT * FROM recording_entries {where}
                ORDER BY id DESC LIMIT ? OFFSET ?""",
            params,
        ).fetchall()

    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# API routes — Status & Health
# ---------------------------------------------------------------------------

@app.get("/api/status")
def pipeline_status():
    is_running = _pipeline_lock.locked()
    with get_db() as conn:
        last_run = conn.execute(
            "SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        totals = conn.execute(
            """SELECT
                 COUNT(*) as total_runs,
                 SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed,
                 SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
                 SUM(uploaded_count) as total_uploaded,
                 SUM(skipped_count) as total_skipped,
                 SUM(failed_count) as total_failed_entries
               FROM pipeline_runs"""
        ).fetchone()

    return {
        "pipeline_running": is_running,
        "last_run": dict(last_run) if last_run else None,
        "totals": dict(totals) if totals else {},
    }


@app.get("/api/health/moodle")
def moodle_health():
    """Quick check if the Moodle session cookie is still valid."""
    scripts_dir = Path(app.state.scripts_dir if hasattr(app.state, "scripts_dir") else SCRIPTS_DIR)
    try:
        result = subprocess.run(
            [PYTHON_BIN, "-c", """
import sys
sys.path.insert(0, '.')
from paatshala import CONFIG_FILE, authenticate, setup_session, BASE
session_id = authenticate(CONFIG_FILE)
session = setup_session(session_id)
resp = session.get(f"{BASE}/my/", timeout=15, allow_redirects=False)
if resp.status_code in (200, 302, 303):
    loc = resp.headers.get("Location", "")
    if "login" in loc.lower():
        print("EXPIRED")
    else:
        print("OK")
else:
    print(f"HTTP_{resp.status_code}")
"""],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(scripts_dir),
        )
        output = result.stdout.strip()
        return {
            "status": "healthy" if output == "OK" else "unhealthy",
            "detail": output or result.stderr[:200],
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)[:200]}


# ---------------------------------------------------------------------------
# Serve the dashboard HTML
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    html_path = Path(__file__).parent / "dashboard.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>dashboard.html not found</h1>"


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def on_startup():
    init_db()


def main():
    parser = argparse.ArgumentParser(description="Zoom→Moodle Pipeline Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8099, help="Bind port (default: 8099)")
    parser.add_argument("--scripts-dir", default=".", help="Directory containing zoomvshare.py and moodlesharer.py")
    parser.add_argument("--db", default="dashboard.sqlite3", help="SQLite database file path")
    args = parser.parse_args()

    app.state.scripts_dir = os.path.abspath(args.scripts_dir)
    app.state.db_path = os.path.abspath(args.db)

    global DB_FILE, SCRIPTS_DIR
    DB_FILE = app.state.db_path
    SCRIPTS_DIR = app.state.scripts_dir

    init_db()

    print(f"[Dashboard] Scripts dir : {app.state.scripts_dir}")
    print(f"[Dashboard] Database    : {app.state.db_path}")
    print(f"[Dashboard] Starting on : http://{args.host}:{args.port}")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
