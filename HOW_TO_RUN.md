# How to Run

## Quick Start

### 1. Activate Virtual Environment

**Windows (PowerShell/CMD):**
```bash
venv\Scripts\activate
```

**Windows (Git Bash) / Linux / Mac:**
```bash
source venv/bin/activate
```

### 2. Run the Apps

**Shiny App** (Topic Management):
```bash
shiny run shiny_app.py
```
→ Opens at `http://127.0.0.1:8000`

**Streamlit App** (Data Extraction):
```bash
streamlit run app.py
```
→ Opens at `http://localhost:8501`

### 3. Development Mode

For auto-reload on file changes:
```bash
shiny run shiny_app.py --reload
```

## Troubleshooting

### Module not found errors

Make sure you're running from the project root:
```bash
cd c:/Users/ICTAK-Cyber/Code/python/paatshala-main
venv\Scripts\activate
shiny run shiny_app.py
```

### PowerShell execution policy error

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Port already in use

```bash
shiny run shiny_app.py --port 8080
streamlit run app.py --server.port 8502
```

## Quick Commands

```bash
# Shiny (default)
venv\Scripts\shiny.exe run shiny_app.py

# Shiny with reload
venv\Scripts\shiny.exe run shiny_app.py --reload

# Streamlit
venv\Scripts\streamlit.exe run app.py

# Deactivate when done
deactivate
```
