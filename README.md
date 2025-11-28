# Paatshala Tool

A unified command-line tool for managing and extracting data from [Paatshala](https://paatshala.ictkerala.org) (ICT Academy of Kerala's Moodle LMS).

## Features

- **Interactive Mode** — Full guided workflow when you're coming in cold
- **Quick Mode** — Skip directly to what you need with command-line flags
- **Session Memory** — Remembers your last course selection
- **Smart Dependencies** — Auto-fetches prerequisites (e.g., tasks list before submissions)
- **Threaded Fetching** — Parallel requests for faster data extraction
- **Organized Output** — All files saved to `output/course_<id>/` subfolders

## What It Does

| Operation | Description | Output |
|-----------|-------------|--------|
| **Tasks** | Fetches all assignments with due dates, grades, submission stats | `tasks_<course_id>.csv` |
| **Quiz Scores** | Scrapes practice quiz scores for all students | `quiz_scores_<course_id>.csv` |
| **Submissions** | Gets detailed grading data for specific assignments | `submissions_<course_id>_mod<id>.csv` |
| **Everything** | Runs all of the above in one go | Multiple CSV files |

## Requirements

- Python 3.7+
- `requests`
- `beautifulsoup4`

## Installation

```bash
git clone https://github.com/yourusername/paatshala-tool.git
cd paatshala-tool
pip install -r requirements.txt
```

Or simply download `paatshala.py` and run it directly.

## Configuration

### First Run
On first run, you'll be prompted for credentials. You can optionally save them to a `.config` file.

### Config File Format (`.config`)
```ini
# Option 1: Session cookie (fastest, but expires)
cookie=your_moodle_session_cookie

# Option 2: Credentials (auto-generates cookie on login)
username=your_username
password=your_password
```

### Environment Variable
```bash
export MOODLE_SESSION_ID="your_cookie_here"
```

**Priority order:** Environment variable → Config file cookie → Config file credentials → Interactive prompt

## Usage

### Interactive Mode (Recommended for Discovery)

```bash
python paatshala.py
```

This walks you through:
1. Authentication (auto or prompted)
2. Course selection (with search and last-used memory)
3. Operation menu (tasks, quiz, submissions, or all)
4. For submissions: task selection → optional group filter
5. Loop back for more operations or change course

### Quick Mode (When You Know What You Want)

```bash
# Fetch task list for course 450
python paatshala.py --course 450 --tasks

# Fetch quiz scores
python paatshala.py --course 450 --quiz

# Fetch submissions for a specific module
python paatshala.py --course 450 --submissions --module 12345

# Fetch submissions with group filter
python paatshala.py --course 450 --submissions --module 12345 --group 2

# Do everything (tasks + quiz + all submissions)
python paatshala.py --course 450 --all

# Custom thread count (default: 4)
python paatshala.py --course 450 --tasks --threads 8
```

### Command-Line Options

| Option | Short | Description |
|--------|-------|-------------|
| `--course` | `-c` | Course ID (skips course selection) |
| `--tasks` | | Fetch task/assignment list |
| `--quiz` | | Fetch practice quiz scores |
| `--submissions` | | Fetch submission grading details |
| `--module` | `-m` | Module ID for submissions |
| `--group` | `-g` | Group ID filter for submissions |
| `--all` | | Execute all operations |
| `--threads` | `-t` | Number of parallel threads (default: 4) |
| `--config` | | Config file path (default: `.config`) |

## Output Structure

```
output/
└── course_450/
    ├── tasks_450.csv
    ├── quiz_scores_450.csv
    ├── submissions_450_mod12345.csv
    ├── submissions_450_mod12345_grp2.csv
    └── submissions_450_mod12346.csv
```

### Output Files

#### `tasks_<course_id>.csv`
| Column | Description |
|--------|-------------|
| Task Name | Assignment name |
| Module ID | Moodle module ID |
| Due Date | Submission deadline |
| Time Remaining | Time until due |
| Late Policy | Late submission rules |
| Max Grade | Maximum possible grade |
| Submission Status | Your submission status |
| Grading Status | Current grading state |
| Participants | Number of enrolled students |
| Submitted | Number of submissions |
| Needs Grading | Submissions awaiting grading |
| URL | Direct link to assignment |

#### `quiz_scores_<course_id>.csv`
| Column | Description |
|--------|-------------|
| Student Name | Student's full name |
| Quiz 1, Quiz 2, ... | Best score for each practice quiz |

#### `submissions_<course_id>_mod<id>.csv`
| Column | Description |
|--------|-------------|
| Task Name | Assignment name |
| Module ID | Moodle module ID |
| Group ID | Group filter (if applied) |
| Name | Student name |
| Status | Submission status |
| Last Modified | Last submission time |
| Submission | Submitted content/files |
| Feedback Comments | Grader feedback |
| Final Grade | Assigned grade |

## Interactive Menu

```
══════════════════════════════════════════════════════════════
  Course: Cyber Security Analyst - Batch 12
  ID: 450
══════════════════════════════════════════════════════════════

  1. Fetch task list (assignments)
  2. Fetch quiz scores
  3. Fetch submissions (for specific task)
  4. Do everything (tasks + quiz + all submissions)
  
  c. Change course
  q. Quit

Your choice: _
```

## Session Memory

The tool remembers your last used course in `.last_session`:

```json
{
  "course_id": "450",
  "course_name": "Cyber Security Analyst - Batch 12"
}
```

On next run, you'll be prompted:
```
[Session] Last used course: Cyber Security Analyst - Batch 12 (ID: 450)
Use this course? (y/n/Enter for yes): 
```

## Examples

### Typical Workflow

```bash
# First time - discover courses and explore
python paatshala.py

# Later - quick export of everything for a known course
python paatshala.py -c 450 --all

# Export just quiz scores for grading
python paatshala.py -c 450 --quiz

# Check submissions for a specific assignment
python paatshala.py -c 450 --submissions -m 28922

# Filter by group for large courses
python paatshala.py -c 450 --submissions -m 28922 -g 3345
```

### Automation / Scripting

```bash
#!/bin/bash
# Export all data for multiple courses

for course_id in 450 451 452; do
    python paatshala.py --course $course_id --all
done
```

## Troubleshooting

### "Cookie is invalid or expired"
Your session has expired. You'll be prompted to re-enter credentials. Consider saving credentials in `.config` for auto-login.

### "No courses found"
Check that your credentials are correct and you're enrolled in at least one course.

### "No practice quizzes found"
The quiz scraper only finds items with "practice quiz" in the name. Regular quizzes are not included.

### Slow performance
Try reducing thread count if the server is rate-limiting:
```bash
python paatshala.py --course 450 --tasks --threads 2
```

## License

MIT License - feel free to use and modify.

## Contributing

Pull requests welcome! Please ensure any changes maintain backward compatibility with the existing CLI interface.

---

**Note:** This tool is for authorized users of Paatshala (ICT Academy of Kerala). Use responsibly and in accordance with your institution's policies.
