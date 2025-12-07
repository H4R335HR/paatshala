# Paatshala Tool

A unified tool for managing and extracting data from [Paatshala](https://paatshala.ictkerala.org) (ICT Academy of Kerala's Moodle LMS).

**Current Architecture:**
- 🎈 **Streamlit App** (`app.py`) — The primary dashboard for downloading tasks, quiz scores, and submissions.
- 💎 **Shiny App** (`shiny_app.py`) — A high-performance, reactive interface for real-time analysis and data exploration.

> [!NOTE]
> The CLI (`paatshala.py`) and legacy monolithic GUI have been retired and moved to the `old/` directory.

## Features

- **Dual Interface**: Choose between Streamlit for workflows or Shiny for reactive data exploration.
- **Session Memory**: Remembers your course selection.
- **Smart Fetching**: Auto-fetches dependencies (tasks before submissions).
- **Parallel Processing**: Threaded requests for fast data extraction.
- **Organized Output**: Data saved to `output/course_<id>/`.

## Requirements

- Python 3.8+
- Dependencies listed in `requirements.txt`

## Installation

Ideally, run this project within a virtual environment.

```bash
# Clone the repository
git clone https://github.com/yourusername/paatshala-tool.git
cd paatshala-tool

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

Ensure your virtual environment is activated before running the apps.

### 1. Streamlit Dashboard (`app.py`)

Best for standard workflows: Downloading tasks, fetching grades, and bulk exporting submissions.

```bash
streamlit run app.py
```

*Opens automatically at `http://localhost:8501`*

### 2. Shiny Reactive App (`shiny_app.py`)

Best for interactive analysis and fast responsiveness.

```bash
shiny run shiny_app.py
```

*Opens automatically at `http://localhost:8000`*

## Configuration

The applications use a unified configuration system.

### First Run
You will be prompted for credentials. You can optionally save them to a `.config` file or usage session cookies.

### Config File (`.config`)
```ini
cookie=your_moodle_session_cookie
# OR
username=your_username
password=your_password
```

## Output Structure

All extracted data matches the following structure:

```
output/
└── course_<id>/
    ├── tasks_<id>.csv
    ├── quiz_scores_<id>.csv
    └── submissions_<id>_mod<mod_id>.csv
```

## Legacy Tools

The old CLI and Tkinter/Per-based GUIs are available in the `old/` directory for reference but are no longer maintained.
