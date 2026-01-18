"""
Skill Matrix functionality for mapping quiz scores to skill competencies.

Features:
- Dynamic skill configuration (JSON-based)
- Manual quiz-to-skill mapping
- Score aggregation (average) across multiple quizzes per skill
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

from core.persistence import get_output_dir

logger = logging.getLogger(__name__)


def normalize_student_name(name: str) -> str:
    """
    Normalize student name to consolidate variations.
    - Removes batch suffixes (e.g., "CL-SMP-CSA-14-NOV-2025-TVM")
    - Normalizes case to title case
    - Strips whitespace
    - Handles "nan" and empty values
    """
    if not name or str(name).lower() in ('nan', 'none', ''):
        return ''
    
    name = str(name).strip()
    
    # Remove batch suffix pattern: CL-XXX-XXX-...
    name = re.sub(r'\s+[A-Z]{2,}-[A-Z]{2,}-.*$', '', name)
    
    # Also try removing common patterns with numbers
    name = re.sub(r'\s+\d{2}-[A-Z]{3}-\d{4}.*$', '', name)
    
    # Normalize case to title
    name = name.strip().title()
    
    return name


# =============================================================================
# Default Skill Definitions (24 skills across 10 milestones)
# =============================================================================

DEFAULT_SKILLS = {
    "milestones": [
        {
            "id": "M01",
            "name": "IT Foundations & Computer Basics",
            "skills": [
                {"id": "S01", "name": "OS & Hardware Basics"},
                {"id": "S02", "name": "Productivity Tools & Internet Use"}
            ]
        },
        {
            "id": "M02",
            "name": "Software Engineering & Collaboration",
            "skills": [
                {"id": "S03", "name": "SDLC Concepts"},
                {"id": "S04", "name": "JIRA & Project Tracking"},
                {"id": "S05", "name": "Version Control (Git) & Collaboration"}
            ]
        },
        {
            "id": "M03",
            "name": "Networking Fundamentals",
            "skills": [
                {"id": "S06", "name": "Network Concepts & Protocols"},
                {"id": "S07", "name": "IP Addressing & Subnetting"},
                {"id": "S08", "name": "Network Troubleshooting Basics"}
            ]
        },
        {
            "id": "M04",
            "name": "Linux & Command Line",
            "skills": [
                {"id": "S09", "name": "Shell Navigation & Filesystem"},
                {"id": "S10", "name": "Permissions & Process Management"},
                {"id": "S11", "name": "CLI Tools & Basic Scripting"}
            ]
        },
        {
            "id": "M05",
            "name": "Cybersecurity Fundamentals",
            "skills": [
                {"id": "S12", "name": "Security Principles & CIA"},
                {"id": "S13", "name": "Common Threats & Attack Vectors"},
                {"id": "S14", "name": "Social Engineering Awareness"}
            ]
        },
        {
            "id": "M06",
            "name": "Compliance & Frameworks",
            "skills": [
                {"id": "S15", "name": "Security Standards (ISO 27001, NIST, OWASP)"},
                {"id": "S16", "name": "Regulatory & Policy Awareness"}
            ]
        },
        {
            "id": "M07",
            "name": "Web Application Security",
            "skills": [
                {"id": "S17", "name": "Web Architecture & HTTP Basics"},
                {"id": "S18", "name": "OWASP Top 10 Awareness"},
                {"id": "S19", "name": "Basic Web App Testing Skills"}
            ]
        },
        {
            "id": "M08",
            "name": "Cloud Fundamentals",
            "skills": [
                {"id": "S20", "name": "Cloud Concepts & Service Models"},
                {"id": "S21", "name": "Cloud Security Basics"}
            ]
        },
        {
            "id": "M09",
            "name": "Analytical Thinking & Problem Solving",
            "skills": [
                {"id": "S22", "name": "Problem Decomposition & Approach"},
                {"id": "S23", "name": "Debugging & Investigation Mindset"}
            ]
        },
        {
            "id": "M10",
            "name": "Professionalism & Workplace Skills",
            "skills": [
                {"id": "S24", "name": "Communication (Written & Verbal)"},
                {"id": "S25", "name": "Timeliness & Reliability"},
                {"id": "S26", "name": "Teamwork & Professional Conduct"}
            ]
        }
    ]
}


# =============================================================================
# Skill Configuration Storage
# =============================================================================

def get_skill_config_dir(course_id: int) -> Path:
    """Get the skill configuration directory for a course."""
    output_dir = get_output_dir(course_id)
    skill_dir = output_dir / "skill_config"
    skill_dir.mkdir(parents=True, exist_ok=True)
    return skill_dir


def load_skills(course_id: int) -> Dict:
    """
    Load skill definitions from JSON config.
    Returns default skills if no custom config exists.
    """
    skill_dir = get_skill_config_dir(course_id)
    skills_file = skill_dir / "skills.json"
    
    if skills_file.exists():
        try:
            with open(skills_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error loading skills config: {e}, using defaults")
    
    return DEFAULT_SKILLS.copy()


def save_skills(course_id: int, skills: Dict) -> bool:
    """Save skill definitions to JSON config."""
    skill_dir = get_skill_config_dir(course_id)
    skills_file = skill_dir / "skills.json"
    
    try:
        with open(skills_file, 'w', encoding='utf-8') as f:
            json.dump(skills, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving skills config: {e}")
        return False


def get_flat_skill_list(skills: Dict) -> List[Dict]:
    """
    Flatten the milestone/skill hierarchy into a simple list.
    Returns list of dicts with 'id', 'name', 'milestone_id', 'milestone_name'.
    """
    result = []
    for milestone in skills.get('milestones', []):
        for skill in milestone.get('skills', []):
            result.append({
                'id': skill['id'],
                'name': skill['name'],
                'milestone_id': milestone['id'],
                'milestone_name': milestone['name']
            })
    return result


# =============================================================================
# Quiz-to-Skill Mappings
# =============================================================================

def load_quiz_mappings(course_id: int) -> Dict[str, List[str]]:
    """
    Load Practice Quiz to Skill mappings.
    Returns dict: {quiz_name: [skill_id, ...]}
    """
    skill_dir = get_skill_config_dir(course_id)
    mappings_file = skill_dir / "quiz_mappings.json"
    
    if mappings_file.exists():
        try:
            with open(mappings_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error loading quiz mappings: {e}")
    
    return {}


def save_quiz_mappings(course_id: int, mappings: Dict[str, List[str]]) -> bool:
    """Save Practice Quiz to Skill mappings."""
    skill_dir = get_skill_config_dir(course_id)
    mappings_file = skill_dir / "quiz_mappings.json"
    
    try:
        with open(mappings_file, 'w', encoding='utf-8') as f:
            json.dump(mappings, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving quiz mappings: {e}")
        return False


def load_quizizz_mappings(course_id: int) -> Dict[str, List[str]]:
    """
    Load Quizizz to Skill mappings.
    Returns dict: {quiz_name: [skill_id, ...]}
    """
    skill_dir = get_skill_config_dir(course_id)
    mappings_file = skill_dir / "quizizz_mappings.json"
    
    if mappings_file.exists():
        try:
            with open(mappings_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error loading quizizz mappings: {e}")
    
    return {}


def save_quizizz_mappings(course_id: int, mappings: Dict[str, List[str]]) -> bool:
    """Save Quizizz to Skill mappings."""
    skill_dir = get_skill_config_dir(course_id)
    mappings_file = skill_dir / "quizizz_mappings.json"
    
    try:
        with open(mappings_file, 'w', encoding='utf-8') as f:
            json.dump(mappings, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving quizizz mappings: {e}")
        return False


def load_name_aliases(course_id: int) -> Dict[str, str]:
    """
    Load name aliases for merging duplicate names.
    Returns dict: {alias_name: canonical_name}
    """
    skill_dir = get_skill_config_dir(course_id)
    aliases_file = skill_dir / "name_aliases.json"
    
    if aliases_file.exists():
        try:
            with open(aliases_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error loading name aliases: {e}")
    
    return {}


def save_name_aliases(course_id: int, aliases: Dict[str, str]) -> bool:
    """Save name aliases for merging duplicate names."""
    skill_dir = get_skill_config_dir(course_id)
    aliases_file = skill_dir / "name_aliases.json"
    
    try:
        with open(aliases_file, 'w', encoding='utf-8') as f:
            json.dump(aliases, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving name aliases: {e}")
        return False


def apply_name_aliases(name: str, aliases: Dict[str, str]) -> str:
    """Apply aliases to get canonical name."""
    return aliases.get(name, name)


def load_task_mappings(course_id: int) -> Dict[str, List[str]]:
    """
    Load Task to Skill mappings.
    Returns dict: {task_name_or_module_id: [skill_id, ...]}
    """
    skill_dir = get_skill_config_dir(course_id)
    mappings_file = skill_dir / "task_mappings.json"
    
    if mappings_file.exists():
        try:
            with open(mappings_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error loading task mappings: {e}")
    
    return {}


def save_task_mappings(course_id: int, mappings: Dict[str, List[str]]) -> bool:
    """Save Task to Skill mappings."""
    skill_dir = get_skill_config_dir(course_id)
    mappings_file = skill_dir / "task_mappings.json"
    
    try:
        with open(mappings_file, 'w', encoding='utf-8') as f:
            json.dump(mappings, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving task mappings: {e}")
        return False


# =============================================================================
# Score Calculation
# =============================================================================

def calculate_skill_scores(
    quiz_data: Optional[List[Dict]],
    quizizz_data: Optional[List[Dict]],
    task_submissions: Optional[Dict[str, List[Dict]]],
    quiz_mappings: Dict[str, List[str]],
    quizizz_mappings: Dict[str, List[str]],
    task_mappings: Dict[str, List[str]],
    skills: Dict,
    name_aliases: Optional[Dict[str, str]] = None
) -> Tuple[List[Dict], List[str]]:
    """
    Calculate skill scores for each student by averaging scores per skill.
    
    Args:
        quiz_data: List of dicts from Practice Quiz tab (rows with student scores)
        quizizz_data: List of dicts from Quizizz tab (individual attempts)
        task_submissions: Dict of {task_key: [submission_rows]} for each task
        quiz_mappings: {quiz_name: [skill_id, ...]}
        quizizz_mappings: {quizizz_name: [skill_id, ...]}
        task_mappings: {task_name_or_module_id: [skill_id, ...]}
        skills: Skill definitions
        name_aliases: Optional dict {alias_name: canonical_name} for merging duplicates
    
    Returns:
        Tuple of (results, skill_columns) where:
        - results: List of dicts with 'Student Name' and skill scores
        - skill_columns: Ordered list of skill column names
    """
    if name_aliases is None:
        name_aliases = {}
    
    flat_skills = get_flat_skill_list(skills)
    skill_ids = [s['id'] for s in flat_skills]
    skill_names = {s['id']: s['name'] for s in flat_skills}
    
    # Track scores per student per skill: {student: {skill_id: [scores]}}
    student_skill_scores = defaultdict(lambda: defaultdict(list))
    
    # Process Practice Quiz data
    # Quiz scores are typically in format "X/Y" or percentage - normalize to 0-10
    if quiz_data:
        for row in quiz_data:
            student = normalize_student_name(row.get('Student Name', ''))
            student = name_aliases.get(student, student)  # Apply alias
            if not student:
                continue
            
            for quiz_name, score in row.items():
                if quiz_name == 'Student Name':
                    continue
                
                # Check if this quiz is mapped to any skills
                skill_ids_for_quiz = quiz_mappings.get(quiz_name, [])
                
                if skill_ids_for_quiz and score is not None:
                    try:
                        # Parse score and normalize to 0-10 scale
                        score_val = _parse_score_normalized(score)
                        if score_val is not None:
                            for skill_id in skill_ids_for_quiz:
                                student_skill_scores[student][skill_id].append(score_val)
                    except (ValueError, TypeError):
                        pass
    
    # Process Quizizz data (may be DataFrame or list of dicts)
    if quizizz_data is not None:
        # Convert DataFrame to list of dicts if needed
        if hasattr(quizizz_data, 'iterrows'):
            quizizz_rows = quizizz_data.to_dict('records')
        else:
            quizizz_rows = quizizz_data if quizizz_data else []
        
        for row in quizizz_rows:
            # Handle different name formats - Quizizz uses First Name + Last Name
            student = row.get('Matched Name') or row.get('Name') or row.get('Student Name', '')
            if not student and row.get('First Name'):
                first = str(row.get('First Name', '')).strip()
                last = str(row.get('Last Name', '')).strip()
                student = f"{first} {last}".strip()
            
            # Normalize to consolidate name variations
            student = normalize_student_name(student)
            student = name_aliases.get(student, student)  # Apply alias
            if not student:
                continue
            
            quiz_name = row.get('Quiz Name', '')
            skill_ids_for_quiz = quizizz_mappings.get(quiz_name, [])
            
            if skill_ids_for_quiz:
                # Calculate normalized score (0-10) from Correct/Total
                correct = row.get('Correct') or row.get('Total Correct')
                total = row.get('Total Questions Attempted') or row.get('Total Questions')
                
                score_val = None
                if correct is not None and total is not None:
                    try:
                        correct_num = float(correct)
                        total_num = float(total)
                        if total_num > 0:
                            score_val = (correct_num / total_num) * 10  # Normalize to 0-10
                    except (ValueError, TypeError):
                        pass
                
                # Fallback to Accuracy if no correct/total available
                if score_val is None:
                    accuracy = row.get('Accuracy')
                    if accuracy is not None:
                        score_val = _parse_score_normalized(accuracy)
                
                if score_val is not None:
                    for skill_id in skill_ids_for_quiz:
                        student_skill_scores[student][skill_id].append(score_val)
    
    # Process Task submissions
    # task_submissions is a dict: {task_key: [submission_rows]}
    if task_submissions and task_mappings:
        for task_key, submissions in task_submissions.items():
            skill_ids_for_task = task_mappings.get(task_key, [])
            
            if not skill_ids_for_task:
                continue
            
            for row in submissions:
                student = normalize_student_name(row.get('Name') or row.get('Student Name', ''))
                student = name_aliases.get(student, student)  # Apply alias
                if not student:
                    continue
                
                # Check if S25 (Timeliness & Reliability) is mapped - use Is_On_Time
                if 'S25' in skill_ids_for_task:
                    timeliness_status = row.get('Is_On_Time', '')
                    if timeliness_status == 'On Time':
                        student_skill_scores[student]['S25'].append(10)
                    elif timeliness_status == 'Pending':
                        student_skill_scores[student]['S25'].append(10)  # Benefit of doubt
                    elif timeliness_status == 'Late':
                        student_skill_scores[student]['S25'].append(0)
                    # 'Unknown' is not counted
                
                # For other skills, use grades
                other_skill_ids = [sid for sid in skill_ids_for_task if sid != 'S25']
                if not other_skill_ids:
                    continue
                
                # Get the grade - try different field names
                grade = row.get('Final Grade') or row.get('Grade') or row.get('Score')
                max_grade = row.get('Max Grade', 15)  # Default max grade
                
                if grade is not None:
                    try:
                        # Parse grade - might be "X / Y" format or just a number
                        grade_str = str(grade).strip()
                        
                        # Handle "X / Y" format
                        if '/' in grade_str:
                            parts = grade_str.split('/')
                            if len(parts) == 2:
                                num = float(parts[0].strip())
                                denom = float(parts[1].strip())
                                if denom > 0:
                                    score_val = (num / denom) * 10
                                else:
                                    continue
                            else:
                                continue
                        else:
                            # Just a number - normalize by max_grade
                            grade_num = float(grade_str)
                            max_grade_num = float(max_grade) if max_grade else 15
                            if max_grade_num > 0:
                                score_val = (grade_num / max_grade_num) * 10
                            else:
                                continue
                        
                        # Clamp to 0-10
                        score_val = max(0, min(10, score_val))
                        
                        for skill_id in other_skill_ids:
                            student_skill_scores[student][skill_id].append(score_val)
                    except (ValueError, TypeError):
                        pass
    
    # Build result rows with averaged scores
    results = []
    
    for student in sorted(student_skill_scores.keys()):
        row = {'Student Name': student}
        
        for skill_id in skill_ids:
            skill_name = skill_names[skill_id]
            scores = student_skill_scores[student].get(skill_id, [])
            
            if scores:
                # Calculate average - scores are already 0-10 scale
                avg = sum(scores) / len(scores)
                row[skill_name] = round(avg)  # Round to nearest whole number
            else:
                row[skill_name] = None
        
        results.append(row)
    
    # Build ordered skill columns
    skill_columns = [skill_names[sid] for sid in skill_ids]
    
    return results, skill_columns


def _parse_score(score) -> Optional[float]:
    """Parse a score value to a float (0-100 scale)."""
    if score is None:
        return None
    
    if isinstance(score, (int, float)):
        return float(score)
    
    if isinstance(score, str):
        # Remove percentage sign and whitespace
        score = score.strip().replace('%', '')
        if not score:
            return None
        try:
            return float(score)
        except ValueError:
            # Handle fraction format like "8/10"
            if '/' in score:
                parts = score.split('/')
                if len(parts) == 2:
                    try:
                        num = float(parts[0])
                        denom = float(parts[1])
                        if denom > 0:
                            return (num / denom) * 100
                    except ValueError:
                        pass
    
    return None


def _parse_score_normalized(score) -> Optional[float]:
    """
    Parse a score value and normalize to 0-10 scale.
    Handles percentages, fractions, and raw numbers.
    """
    if score is None:
        return None
    
    if isinstance(score, (int, float)):
        val = float(score)
        # If it looks like a percentage (> 10), convert to 0-10
        if val > 10:
            return val / 10
        return val
    
    if isinstance(score, str):
        score_str = score.strip().replace('%', '')
        if not score_str:
            return None
        
        try:
            val = float(score_str)
            # If it looks like a percentage, convert to 0-10
            if val > 10:
                return val / 10
            return val
        except ValueError:
            # Handle fraction format like "8/10"
            if '/' in score_str:
                parts = score_str.split('/')
                if len(parts) == 2:
                    try:
                        num = float(parts[0])
                        denom = float(parts[1])
                        if denom > 0:
                            return (num / denom) * 10  # Normalize to 0-10
                    except ValueError:
                        pass
    
    return None


def get_available_quizzes(quiz_data) -> List[str]:
    """
    Get list of quiz names from Practice Quiz data.
    Handles both list of dicts and pandas DataFrame.
    """
    if quiz_data is None:
        return []
    
    # Handle pandas DataFrame
    if hasattr(quiz_data, 'empty'):
        if quiz_data.empty:
            return []
        return [col for col in quiz_data.columns if col != 'Student Name']
    
    # Handle list of dicts
    if not quiz_data or not quiz_data[0]:
        return []
    
    # Get column names except 'Student Name'
    return [col for col in quiz_data[0].keys() if col != 'Student Name']


def get_available_quizizz_names(quizizz_data) -> List[str]:
    """
    Get unique quiz names from Quizizz data.
    Handles both list of dicts and pandas DataFrame.
    """
    if quizizz_data is None:
        return []
    
    # Handle pandas DataFrame
    if hasattr(quizizz_data, 'empty'):
        if quizizz_data.empty:
            return []
        if 'Quiz Name' in quizizz_data.columns:
            return sorted(quizizz_data['Quiz Name'].dropna().unique().tolist())
        return []
    
    # Handle list of dicts
    if not quizizz_data:
        return []
    
    quiz_names = set()
    for row in quizizz_data:
        name = row.get('Quiz Name')
        if name:
            quiz_names.add(name)
    
    return sorted(list(quiz_names))


def load_all_task_submissions(course_id: int, tasks_data: Optional[List[Dict]] = None) -> Tuple[Dict[str, List[Dict]], List[Dict]]:
    """
    Load all available task submissions from disk.
    
    Args:
        course_id: Course ID
        tasks_data: Optional list of tasks with 'Task Name' and 'Module ID'
    
    Returns:
        Tuple of (submissions_dict, available_tasks) where:
        - submissions_dict: {task_key: [submission_rows]}
        - available_tasks: List of tasks that have saved submissions
    """
    from core.persistence import get_output_dir, load_csv_from_disk
    import re
    
    output_dir = get_output_dir(course_id)
    submissions_dict = {}
    available_tasks = []
    
    # Find all submission files
    submission_files = list(output_dir.glob("submissions_*.csv"))
    
    for file_path in submission_files:
        # Parse module ID from filename: submissions_450_mod12345.csv or submissions_450_mod12345_grpXXX.csv
        match = re.search(r'submissions_\d+_mod(\d+)', file_path.name)
        if not match:
            continue
        
        module_id = match.group(1)
        
        # Load the submissions
        rows = load_csv_from_disk(course_id, file_path.name)
        if not rows:
            continue
        
        # Check if Is_On_Time is missing - calculate it on-the-fly for old CSVs
        if rows and 'Is_On_Time' not in rows[0]:
            # Try to determine timeliness from Status field
            for row in rows:
                status = row.get('Status', '')
                if 'late' in status.lower():
                    row['Is_On_Time'] = 'Late'
                elif 'overdue' in status.lower():
                    row['Is_On_Time'] = 'Late'
                elif 'submitted' in status.lower() and 'graded' in status.lower():
                    # Submitted and graded, likely on time (conservative assumption)
                    row['Is_On_Time'] = 'On Time'
                elif 'no submission' in status.lower():
                    row['Is_On_Time'] = 'Late'  # Past due with no submission
                else:
                    row['Is_On_Time'] = 'Unknown'
        
        # Find task name - first from the submission row, then from tasks_data
        task_name = None
        
        # Try to get from the first row of submissions (they usually all have the same task name)
        if rows and rows[0].get('Task Name'):
            task_name = rows[0].get('Task Name')
        
        # Fallback to tasks_data lookup
        if not task_name:
            for task in (tasks_data or []):
                if str(task.get('Module ID')) == module_id:
                    task_name = task.get('Task Name')
                    break
        
        # Use task name as key if available, otherwise module ID
        task_key = task_name if task_name else f"Task (Module {module_id})"
        
        # Store or merge with existing (in case multiple group files)
        if task_key in submissions_dict:
            # Merge and dedupe by student name
            existing_names = {r.get('Name') for r in submissions_dict[task_key]}
            for row in rows:
                if row.get('Name') not in existing_names:
                    submissions_dict[task_key].append(row)
                    existing_names.add(row.get('Name'))
        else:
            submissions_dict[task_key] = rows
            available_tasks.append({
                'task_key': task_key,
                'module_id': module_id,
                'count': len(rows)
            })
    
    return submissions_dict, available_tasks


def get_available_tasks(course_id: int, tasks_data: Optional[List[Dict]] = None) -> List[str]:
    """
    Get list of task names/keys that have saved submissions.
    """
    _, available_tasks = load_all_task_submissions(course_id, tasks_data)
    return [t['task_key'] for t in available_tasks]


