# Zoom → Moodle Pipeline Dashboard

A web dashboard for managing automated Zoom recording extraction and Moodle upload pipelines. Wraps your existing `zoomvshare.py` and `moodlesharer.py` scripts with a status board, run history, batch configuration, and on-demand triggers.

## Architecture

```
┌─────────────────────────────────────────────┐
│  dashboard.py (FastAPI + SQLite)            │
│  ├─ REST API (/api/*)                       │
│  ├─ Background pipeline runner              │
│  │   ├─ xvfb-run python zoomvshare.py ...   │
│  │   └─ python moodlesharer.py ...          │
│  └─ Serves dashboard.html                   │
├─────────────────────────────────────────────┤
│  dashboard.html (Vanilla JS, no build step) │
│  ├─ Stats overview                          │
│  ├─ Run history + log viewer                │
│  ├─ Recording entries + status filter       │
│  └─ Batch → Course config CRUD              │
├─────────────────────────────────────────────┤
│  dashboard.sqlite3                          │
│  ├─ batch_mappings                          │
│  ├─ pipeline_runs (stdout/stderr captured)  │
│  └─ recording_entries (per-item status)     │
└─────────────────────────────────────────────┘
```

## Quick Start

1. **Install dependencies** (in your existing paatshala venv):

```bash
cd /home/ictuser1/git/paatshala
pip install fastapi uvicorn pydantic
```

2. **Copy dashboard files** into your scripts directory:

```bash
cp dashboard.py dashboard.html /home/ictuser1/git/paatshala/
chmod +x cron_trigger.sh
```

3. **Run the dashboard**:

```bash
cd /home/ictuser1/git/paatshala
python dashboard.py --scripts-dir . --port 8099
```

4. **Open in browser**: `http://<your-machine-ip>:8099`

5. **Add a batch mapping** via the Config tab:
   - Name: `CSA SGOU Feb 2026`
   - Search Term: `CSA SGOU`
   - Course ID: `491`
   - Section: `Recordings`

6. **Hit "Run All Enabled"** or the ▶ button next to a mapping.

## Running as a Systemd Service

```bash
sudo cp zoom-moodle-dashboard.service /etc/systemd/system/
# Edit the service file to match your paths if different
sudo systemctl daemon-reload
sudo systemctl enable --now zoom-moodle-dashboard
sudo systemctl status zoom-moodle-dashboard
```

## Cron Scheduling

Use `cron_trigger.sh` to trigger pipelines on a schedule:

```bash
# Copy to scripts dir
cp cron_trigger.sh /home/ictuser1/git/paatshala/

# Run every night at 10 PM
crontab -e
# Add: 0 22 * * * /home/ictuser1/git/paatshala/cron_trigger.sh >> /var/log/zoom-moodle-cron.log 2>&1
```

## Configuration

| Env Variable     | Default            | Description                         |
|------------------|--------------------|-------------------------------------|
| `DASHBOARD_DB`   | `dashboard.sqlite3`| SQLite database file path           |
| `SCRIPTS_DIR`    | `.`                | Directory with zoomvshare/moodlesharer |
| `PYTHON_BIN`     | Current interpreter| Python binary for subprocess calls  |
| `XVFB_PREFIX`    | `xvfb-run`         | Display wrapper for Playwright      |

CLI equivalents: `--scripts-dir`, `--db`, `--port`, `--host`.

## API Endpoints

| Method | Path                     | Description                    |
|--------|--------------------------|--------------------------------|
| GET    | `/api/mappings`          | List batch mappings            |
| POST   | `/api/mappings`          | Create a mapping               |
| PUT    | `/api/mappings/{id}`     | Update a mapping               |
| DELETE | `/api/mappings/{id}`     | Delete a mapping               |
| GET    | `/api/runs`              | List pipeline runs             |
| GET    | `/api/runs/{id}`         | Run detail + entries + logs    |
| POST   | `/api/trigger/{id}`      | Trigger one mapping            |
| POST   | `/api/trigger-all`       | Trigger all enabled mappings   |
| GET    | `/api/recordings`        | List recording entries         |
| GET    | `/api/status`            | Pipeline status + totals       |
| GET    | `/api/health/moodle`     | Moodle session health check    |

FastAPI auto-docs available at `/docs`.

## Notes

- **One pipeline at a time**: The dashboard uses a threading lock so Zoom browser auth doesn't collide. Queued runs wait up to 10 minutes for the lock.
- **xvfb-run**: Required because Playwright needs a display. Install with `sudo apt install xvfb` if missing.
- **Idempotent uploads**: `moodlesharer.py` checks existing activity titles before creating, so re-runs are safe.
- **Log retention**: All stdout/stderr from both stages is stored in SQLite (capped at 50KB per field).
