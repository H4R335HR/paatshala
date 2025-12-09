# Paatshala Tool

A unified tool for managing and extracting data from [Paatshala](https://paatshala.ictkerala.org) (ICT Academy of Kerala's Moodle LMS).

## Architecture

| App | File | Purpose |
|-----|------|---------|
| 💎 **Shiny** | `shiny_app.py` | Topic & activity management with real-time UI |
| 🎈 **Streamlit** | `app.py` | Data extraction (tasks, quizzes, submissions) |

> [!NOTE]
> The CLI (`paatshala.py`) and legacy GUIs have been retired to the `old/` directory.

## Features

### Shiny App (Topic Management)
- **Topic Operations**: Rename, move (drag-and-drop), delete, visibility toggle
- **Batch Mode**: Queue multiple operations, preview changes, save all at once
- **Activity Management**: View, reorder, duplicate, and delete activities within topics
- **Access Restrictions**: Add/remove group restrictions, clear all restrictions
- **Real-time UI**: Optimistic updates with immediate visual feedback
- **Dark Mode**: Full dark theme support

### Streamlit App (Data Extraction)
- **Task Fetching**: Download all course tasks as CSV
- **Quiz Scores**: Extract grade data for quizzes
- **Submissions**: Bulk export student submissions
- **Session Memory**: Remembers your course selection
- **Parallel Processing**: Threaded requests for fast extraction

## Requirements

- Python 3.8+
- Dependencies in `requirements.txt`

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/paatshala-tool.git
cd paatshala-tool

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Shiny App (Recommended for Topic Management)

```bash
shiny run shiny_app.py
```
Opens at `http://localhost:8000`

**Development mode with auto-reload:**
```bash
shiny run shiny_app.py --reload
```

### Streamlit App (Data Extraction)

```bash
streamlit run app.py
```
Opens at `http://localhost:8501`

> [!TIP]
> **Disable Telemetry**: This project includes `.streamlit/config.toml` that disables Streamlit's usage statistics collection:
> ```toml
> [browser]
> gatherUsageStats = false
> ```

## Configuration

### First Run
You'll be prompted for credentials. Optionally save them to a `.config` file.

### Config File (`.config`)
```ini
cookie=your_moodle_session_cookie
# OR
username=your_username
password=your_password
```

## Project Structure

```
paatshala-main/
├── app.py              # Streamlit app entry point
├── shiny_app.py        # Shiny app entry point
├── core/               # Core API and authentication
│   ├── api.py          # Moodle API wrapper
│   ├── auth.py         # Session management
│   ├── parser.py       # HTML/data parsing
│   └── persistence.py  # Local storage
├── shiny_modules/      # Shiny UI components
│   ├── ui/             # CSS, JS, layouts
│   └── server/         # Server-side handlers
├── streamlit_modules/  # Streamlit UI modules
├── output/             # Extracted data
│   └── course_<id>/    # Per-course exports
└── old/                # Legacy tools (archived)
```

## Output

Extracted data is saved as:
```
output/course_<id>/
├── tasks_<id>.csv
├── quiz_scores_<id>.csv
└── submissions_<id>_mod<mod_id>.csv
```

## Troubleshooting

See [HOW_TO_RUN.md](HOW_TO_RUN.md) for detailed setup and troubleshooting.

## Legacy Tools

The old CLI and Tkinter-based GUIs are in the `old/` directory for reference.
