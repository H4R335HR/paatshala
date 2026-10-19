"""
Core Grading Pipeline
Automated grading detection, batch AI evaluation, and Moodle grade submission.
UI-agnostic: can be called from Streamlit pages, background workers, or CLI.
"""

import ast
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.ai import (
    clear_failed_queue,
    fetch_submission_content,
    generate_rubric,
    load_evaluation,
    load_failed_queue,
    load_rubric,
    save_evaluation,
    save_failed_queue,
    save_rubric,
    score_submission,
)
from core.api import (
    check_submission_timeliness,
    download_file,
    get_assignment_dates,
    get_fresh_sesskey,
    setup_session,
    submit_grade,
)
from core.persistence import get_output_dir, load_csv_from_disk

logger = logging.getLogger(__name__)


def parse_moodle_grade(grade_str: Any) -> Tuple[Optional[float], Optional[float]]:
    """Parse Moodle grade string like '12.75 / 15.00' into (score, max) tuple."""
    if not grade_str or grade_str == "-":
        return None, None

    match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", str(grade_str))
    if match:
        try:
            return float(match.group(1)), float(match.group(2))
        except (ValueError, TypeError):
            pass
    try:
        val = float(str(grade_str).strip())
        return val, None
    except (ValueError, TypeError):
        return None, None


def parse_submission_files(submission_files: Any) -> List[Any]:
    """Safely parse submission files string or list."""
    if isinstance(submission_files, str) and submission_files.startswith("["):
        try:
            return ast.literal_eval(submission_files)
        except Exception:
            return []
    return submission_files if isinstance(submission_files, list) else []


def is_submission_empty(row: Dict[str, Any]) -> bool:
    """Check if student has actually submitted anything."""
    sub_type = row.get("Submission_Type", "")
    content = str(row.get("Submission", "")).strip()
    files = parse_submission_files(row.get("Submission_Files", []))

    if sub_type == "empty":
        return True
    if not content and not files:
        return True
    return False


def get_task_grading_status(
    course_id: int,
    module_id: int,
    group_id: Optional[int] = None,
    submissions_data: Optional[List[Dict[str, Any]]] = None,
    max_grade: Optional[float] = None,
) -> Dict[str, Any]:
    """Calculate evaluation & grading metrics for an assignment.

    Args:
        course_id: Course ID
        module_id: Assignment module ID
        group_id: Optional group ID
        submissions_data: Optional pre-loaded submissions list. If None, tries disk CSV.
        max_grade: Optional assignment max grade

    Returns:
        Dict of status metrics and flags.
    """
    # 1. Resolve submissions data
    data = submissions_data
    if data is None:
        filename = f"submissions_{course_id}_mod{module_id}"
        if group_id:
            filename += f"_grp{group_id}"
        filename += ".csv"
        data = load_csv_from_disk(course_id, filename) or []

    total_submissions = len(data)
    submitted_count = 0
    empty_count = 0
    ai_evaluated_count = 0
    ai_pending_count = 0
    moodle_ungraded_count = 0
    ready_for_moodle_count = 0

    effective_max = max_grade if (max_grade and 1 <= max_grade <= 1000) else 15.0

    for row in data:
        student_name = row.get("Name", "Unknown")
        has_sub = not is_submission_empty(row)
        if has_sub:
            submitted_count += 1
        else:
            empty_count += 1

        # Check Moodle grade status
        moodle_score, student_max = parse_moodle_grade(row.get("Final Grade", ""))
        is_graded_in_moodle = moodle_score is not None

        # Check local AI evaluation
        existing_eval = load_evaluation(course_id, module_id, student_name, group_id)
        has_ai_score = existing_eval and existing_eval.get("total_score") is not None

        if has_ai_score:
            ai_evaluated_count += 1
        elif has_sub and not is_graded_in_moodle:
            # Only pending AI if student submitted AND is not already graded in Moodle!
            ai_pending_count += 1

        # Check Moodle grading status
        if not is_graded_in_moodle:
            moodle_ungraded_count += 1
            if has_ai_score:
                ready_for_moodle_count += 1
        elif has_ai_score:
            ai_score = existing_eval.get("total_score", 0)
            target_max = student_max or effective_max
            scaled_ai = round((ai_score / 100) * target_max)
            if abs(moodle_score - scaled_ai) >= 0.5:
                ready_for_moodle_count += 1

    # Check rubric
    rubric_doc = load_rubric(course_id, module_id, group_id)
    rubric = rubric_doc.get("criteria", []) if rubric_doc else None
    has_rubric = bool(rubric and len(rubric) > 0)

    # Check failed queue
    failed_q = load_failed_queue(course_id, module_id) or []

    return {
        "module_id": module_id,
        "group_id": group_id,
        "total_submissions": total_submissions,
        "submitted_count": submitted_count,
        "empty_count": empty_count,
        "ai_evaluated_count": ai_evaluated_count,
        "ai_pending_count": ai_pending_count,
        "moodle_ungraded_count": moodle_ungraded_count,
        "ready_for_moodle_count": ready_for_moodle_count,
        "has_rubric": has_rubric,
        "rubric": rubric,
        "failed_queue_count": len(failed_q),
        "has_data": total_submissions > 0,
    }


def is_task_permitted_for_group(
    task: Dict[str, Any],
    selected_group: Optional[Dict[str, Any]],
    restrictions_map: Optional[Dict[str, Any]] = None,
) -> bool:
    """Check if a task is accessible/permitted for the selected group.

    Rules:
    1. If selected_group is None ("All" in sidebar), show all tasks except hidden ones.
    2. If the task is explicitly marked hidden ("Hidden from students"), exclude it.
    3. If the task has NO group restrictions (neither activity nor topic level),
       it is shared across all batches -> Permitted!
    4. If the task HAS group restrictions:
       Permitted IF AND ONLY IF one of the restricted groups matches the selected group!
    """
    is_hidden_val = str(task.get("Is Hidden", "0")).lower()
    if is_hidden_val in ["1", "true", "yes"]:
        return False

    if not selected_group:
        return True

    mod_id = str(task.get("Module ID", ""))
    groups_list = []

    # Check restrictions_map if provided
    if restrictions_map and mod_id in restrictions_map:
        info = restrictions_map[mod_id]
        if info.get("is_hidden"):
            return False
        groups_list = info.get("groups", [])
    elif "Restricted Groups" in task:
        raw_groups = task.get("Restricted Groups", "")
        if isinstance(raw_groups, list):
            groups_list = raw_groups
        elif isinstance(raw_groups, str) and raw_groups.strip():
            groups_list = [g.strip() for g in raw_groups.split(",") if g.strip()]

    # If no group restrictions, it's shared across all batches
    if not groups_list:
        return True

    # Check match against selected group
    group_name = str(selected_group.get("name", "")).strip().lower()
    group_id_str = str(selected_group.get("id", "")).strip()

    for g in groups_list:
        g_clean = str(g).strip().lower()
        if g_clean in group_name or group_name in g_clean:
            return True
        if group_id_str and group_id_str == str(g).strip():
            return True

        # Extract tokens for batch code comparison (e.g. 0023csa)
        tokens_g = re.findall(r"[a-z0-9]+", g_clean)
        tokens_grp = re.findall(r"[a-z0-9]+", group_name)
        for tok in tokens_g:
            if len(tok) >= 5 and tok in tokens_grp:
                return True

    return False


def scan_course_ungraded_tasks(
    course_id: int,
    tasks_data: List[Dict[str, Any]],
    group_id: Optional[int] = None,
    selected_group: Optional[Dict[str, Any]] = None,
    restrictions_map: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Scan all tasks in a course to identify which ones have pending evaluations.
    Filters out activities that are restricted to other batches.

    Args:
        course_id: Course ID
        tasks_data: List of task dicts (from tasks_<id>.csv or fetch_tasks_list)
        group_id: Optional group ID for filtered view
        selected_group: Optional group dict {'id': ..., 'name': ...}
        restrictions_map: Optional restrictions lookup map

    Returns:
        List of task summary dicts sorted by urgency (needs attention first).
    """
    results = []
    effective_group_id = selected_group["id"] if selected_group else group_id

    for task in tasks_data:
        mod_id = task.get("Module ID")
        if not mod_id:
            continue

        try:
            mod_id_int = int(mod_id)
        except ValueError:
            continue

        # Filter out tasks restricted to other batches!
        if selected_group and not is_task_permitted_for_group(task, selected_group, restrictions_map):
            continue

        task_name = task.get("Task Name", f"Task {mod_id}")
        moodle_needs_grading = task.get("Needs Grading", "")
        moodle_submitted = task.get("Submitted", "")
        max_grade_str = task.get("Max Grade", "")

        parsed_max = None
        if max_grade_str:
            try:
                parsed_max = float(str(max_grade_str).replace("/100.00", "").strip())
            except Exception:
                pass

        # Try to read local submissions if available
        status = get_task_grading_status(
            course_id=course_id,
            module_id=mod_id_int,
            group_id=effective_group_id,
            max_grade=parsed_max,
        )

        # Check if Moodle reports pending grading
        moodle_pending_int = 0
        if moodle_needs_grading:
            try:
                moodle_pending_int = int(str(moodle_needs_grading).strip())
            except ValueError:
                pass

        # Determine if this task needs attention:
        # If we have local submissions data on disk, use that as source of truth.
        # If no local data exists yet, check if Moodle reports needs_grading > 0.
        if status["has_data"]:
            needs_attention = (status["ai_pending_count"] > 0)
        else:
            needs_attention = (moodle_pending_int > 0)

        results.append({
            "module_id": mod_id_int,
            "task_name": task_name,
            "due_date": task.get("Due Date", ""),
            "time_remaining": task.get("Time Remaining", ""),
            "description": task.get("description", ""),
            "moodle_needs_grading": moodle_needs_grading,
            "moodle_needs_grading_int": moodle_pending_int,
            "moodle_submitted": moodle_submitted,
            "status": status,
            "needs_attention": needs_attention,
            "has_rubric": status["has_rubric"],
        })

    # Sort: tasks needing attention first, then by pending count descending
    results.sort(
        key=lambda x: (
            1 if x["needs_attention"] else 0,
            x["status"]["ai_pending_count"] + x["moodle_needs_grading_int"],
        ),
        reverse=True,
    )

    return results


def run_batch_scoring(
    course_id: int,
    module_id: int,
    group_id: Optional[int],
    submissions_data: List[Dict[str, Any]],
    rubric: List[Dict[str, Any]],
    task_description: str,
    session_id: Optional[str] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    auto_fetch: bool = True,
    override_lookup: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Execute AI scoring on all pending submissions for an assignment.

    Args:
        course_id: Course ID
        module_id: Module ID
        group_id: Optional group ID
        submissions_data: List of submission rows
        rubric: Rubric criteria list
        task_description: Task description text for AI prompt
        session_id: Optional Moodle session cookie for downloading files
        progress_callback: Callback taking a dict:
            {
                'current': int,
                'total': int,
                'student_name': str,
                'message': str,
                'type': str ('start', 'progress', 'success', 'warning', 'error', 'skipped')
            }
        auto_fetch: Automatically download missing files before scoring
        override_lookup: Optional callable to get submission overrides

    Returns:
        Dict of results:
        {'scored': int, 'failed': int, 'skipped': int, 'fetched': int, 'failed_queue': list}
    """
    def notify(current: int, total: int, student_name: str, message: str, msg_type: str = "progress"):
        if progress_callback:
            try:
                progress_callback({
                    "current": current,
                    "total": total,
                    "student_name": student_name,
                    "message": message,
                    "type": msg_type,
                })
            except Exception as e:
                logger.debug(f"Progress callback error: {e}")

    # 1. Filter to pending submissions
    pending = []
    skipped_no_sub = 0

    for idx, row in enumerate(submissions_data):
        student_name = row.get("Name", "Unknown")
        if is_submission_empty(row):
            skipped_no_sub += 1
            continue

        existing_eval = load_evaluation(course_id, module_id, student_name, group_id)
        if not existing_eval or existing_eval.get("total_score") is None:
            pending.append((idx, row))

    total_pending = len(pending)
    results = {
        "scored": 0,
        "failed": 0,
        "skipped": 0,
        "fetched": 0,
        "skipped_no_submission": skipped_no_sub,
        "failed_queue": [],
    }

    if total_pending == 0:
        notify(0, 0, "", "All submissions already evaluated.", "success")
        return results

    notify(0, total_pending, "", f"Starting AI scoring for {total_pending} submissions...", "start")

    # Setup session for file downloading
    moodle_session = None
    if auto_fetch and session_id:
        try:
            moodle_session = setup_session(session_id)
        except Exception as e:
            logger.warning(f"Failed to setup Moodle session for auto-fetch: {e}")

    # Assignment deadline info if available
    deadline_str = None
    due_date_obj = None
    if moodle_session:
        try:
            dates_info = get_assignment_dates(moodle_session, module_id)
            if dates_info and dates_info.get("due_date_enabled") and dates_info.get("due_date"):
                due_date_obj = dates_info["due_date"]
                deadline_str = due_date_obj.strftime("%A, %d %B %Y, %I:%M %p")
        except Exception as e:
            logger.debug(f"Could not load assignment dates: {e}")

    for step, (row_idx, row) in enumerate(pending):
        student_name = row.get("Name", "Unknown")
        sub_type = row.get("Submission_Type", "")

        notify(
            step + 1,
            total_pending,
            student_name,
            f"Evaluating ({step + 1}/{total_pending}): {student_name}...",
            "progress",
        )

        try:
            # Handle file downloads
            if sub_type == "file":
                sub_files = parse_submission_files(row.get("Submission_Files", []))
                safe_student = "".join([c for c in student_name if c.isalnum() or c in (" ", "-", "_")]).strip()
                has_unfetched = False

                for f in sub_files:
                    fname = f[0] if isinstance(f, (list, tuple)) else str(f)
                    furl = f[1] if isinstance(f, (list, tuple)) and len(f) > 1 else None
                    safe_filename = "".join([c for c in fname if c.isalnum() or c in (" ", "-", "_", ".")]).strip()
                    local_path = Path(f"output/course_{course_id}/downloads/{safe_student}/{safe_filename}")

                    if not local_path.exists():
                        if auto_fetch and furl and moodle_session:
                            notify(step + 1, total_pending, student_name, f"Downloading {fname}...", "progress")
                            saved = download_file(moodle_session, furl, course_id, student_name, fname)
                            if saved:
                                results["fetched"] += 1
                            else:
                                has_unfetched = True
                        else:
                            has_unfetched = True

                if has_unfetched and not auto_fetch:
                    notify(step + 1, total_pending, student_name, "Skipped (files not fetched)", "skipped")
                    results["skipped"] += 1
                    continue

            # Apply override if any
            if override_lookup:
                override = override_lookup(row)
                if override:
                    notify(step + 1, total_pending, student_name, f"Using override ({override.get('type')})", "info")

            # Fetch submission content
            sub_content = fetch_submission_content(row, course_id)

            if deadline_str and due_date_obj:
                sub_content["deadline"] = deadline_str
                last_modified = row.get("Last Modified", "")
                if last_modified:
                    try:
                        parsed_time = datetime.strptime(last_modified, "%A, %d %B %Y, %I:%M %p")
                        sub_content["on_time"] = parsed_time <= due_date_obj
                    except ValueError:
                        pass

            # Score submission with retry & backoff
            max_retries = 3
            retry_delay = 3
            eval_result = None

            for attempt in range(max_retries):
                eval_result = score_submission(
                    sub_content,
                    rubric,
                    task_description,
                    student_name,
                )

                if eval_result and eval_result.get("error"):
                    err_msg = str(eval_result.get("error", "")).lower()
                    is_server_overloaded = any(x in err_msg for x in ["503", "overloaded", "unavailable"])
                    is_not_found = any(x in err_msg for x in ["404", "not_found", "no longer available"])
                    is_rate_limited = any(x in err_msg for x in ["429", "rate", "resource_exhausted", "quota"])

                    if is_not_found:
                        notify(step + 1, total_pending, student_name, "Model unavailable", "error")
                        break
                    elif is_server_overloaded:
                        notify(step + 1, total_pending, student_name, "Server overloaded (503), queued", "warning")
                        break
                    elif is_rate_limited and attempt < max_retries - 1:
                        notify(step + 1, total_pending, student_name, f"Rate limited, retrying in {retry_delay}s...", "warning")
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue

                break

            if eval_result and eval_result.get("error"):
                err_str = str(eval_result["error"])
                notify(step + 1, total_pending, student_name, f"Failed: {err_str[:60]}", "error")
                results["failed"] += 1
                results["failed_queue"].append({
                    "student_name": student_name,
                    "row_index": row_idx,
                    "error": err_str[:200],
                    "failed_at": datetime.now().isoformat(),
                })
            elif eval_result and eval_result.get("total_score") is not None:
                save_evaluation(course_id, module_id, student_name, eval_result, group_id)
                notify(step + 1, total_pending, student_name, f"Scored: {eval_result['total_score']}/100", "success")
                results["scored"] += 1
            else:
                results["failed"] += 1
                results["failed_queue"].append({
                    "student_name": student_name,
                    "row_index": row_idx,
                    "error": "No score returned",
                    "failed_at": datetime.now().isoformat(),
                })

        except Exception as e:
            logger.error(f"Error scoring {student_name}: {e}", exc_info=True)
            notify(step + 1, total_pending, student_name, f"Error: {str(e)[:50]}", "error")
            results["failed"] += 1
            results["failed_queue"].append({
                "student_name": student_name,
                "row_index": row_idx,
                "error": str(e)[:200],
                "failed_at": datetime.now().isoformat(),
            })

        # Pacing delay to prevent rate limits
        if step < total_pending - 1:
            time.sleep(1.2)

    # Persist or clear failed queue
    if results["failed_queue"]:
        save_failed_queue(course_id, module_id, results["failed_queue"], group_id)
    else:
        clear_failed_queue(course_id, module_id)

    notify(
        total_pending,
        total_pending,
        "",
        f"Completed: {results['scored']} scored, {results['failed']} failed.",
        "success" if results["failed"] == 0 else "warning",
    )

    return results


def format_feedback_html(evaluation: Dict[str, Any]) -> str:
    """Format evaluation as HTML for Moodle feedback comments."""
    html_parts = []
    criteria_scores = evaluation.get("criteria_scores", [])
    if criteria_scores:
        html_parts.append("<p><strong>Per-Criterion Breakdown:</strong></p>")
        html_parts.append("<table border='1' cellpadding='5' cellspacing='0' style='border-collapse: collapse;'>")
        html_parts.append("<tr><th>Criterion</th><th>Score</th><th>Feedback</th></tr>")
        for cs in criteria_scores:
            crit = cs.get("criterion", "")
            score = cs.get("score", 0)
            max_s = cs.get("max_score", 0)
            comment = cs.get("comment", "")
            html_parts.append(f"<tr><td>{crit}</td><td>{score}/{max_s}</td><td>{comment}</td></tr>")
        html_parts.append("</table><br>")

    comments = evaluation.get("comments", "")
    if comments:
        html_parts.append("<p><strong>Overall Feedback:</strong></p>")
        html_parts.append(f"<p>{comments}</p>")

    return "".join(html_parts)


def run_batch_moodle_submit(
    course_id: int,
    module_id: int,
    group_id: Optional[int],
    submissions_data: List[Dict[str, Any]],
    session_id: str,
    assignment_id: Optional[str] = None,
    max_grade: float = 15.0,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Submit AI evaluation scores and feedback to Moodle.

    Args:
        course_id: Course ID
        module_id: Module ID
        group_id: Optional group ID
        submissions_data: List of submission rows
        session_id: Moodle session ID
        assignment_id: Moodle assign instance ID
        max_grade: Assignment max grade
        progress_callback: Notification callback

    Returns:
        Dict with 'submitted' and 'failed' counts.
    """
    def notify(current: int, total: int, student_name: str, message: str, msg_type: str = "progress"):
        if progress_callback:
            try:
                progress_callback({
                    "current": current,
                    "total": total,
                    "student_name": student_name,
                    "message": message,
                    "type": msg_type,
                })
            except Exception:
                pass

    session = setup_session(session_id)
    sesskey = get_fresh_sesskey(session, course_id)
    if not sesskey:
        raise ValueError("Could not obtain session key (sesskey) from Moodle.")

    if not assignment_id:
        raise ValueError("Assignment ID is missing. Please re-fetch submissions first.")

    # Find evaluations ready to submit
    pending = []
    for idx, row in enumerate(submissions_data):
        student_name = row.get("Name", "Unknown")
        existing_eval = load_evaluation(course_id, module_id, student_name, group_id)
        if existing_eval and existing_eval.get("total_score") is not None:
            moodle_score, student_max = parse_moodle_grade(row.get("Final Grade", ""))
            target_max = student_max or max_grade
            ai_score = existing_eval.get("total_score", 0)
            scaled_ai = round((ai_score / 100) * target_max)

            if moodle_score is None or abs(moodle_score - scaled_ai) >= 0.5:
                pending.append((idx, row, existing_eval, target_max))

    results = {"submitted": 0, "failed": 0, "total": len(pending)}
    if not pending:
        notify(0, 0, "", "All AI evaluations are already submitted to Moodle.", "success")
        return results

    notify(0, len(pending), "", f"Submitting {len(pending)} evaluations to Moodle...", "start")

    for step, (idx, row, evaluation, target_max) in enumerate(pending):
        student_name = row.get("Name", "Unknown")
        user_id = row.get("User_ID")

        if not user_id:
            notify(step + 1, len(pending), student_name, "No User ID found, skipping", "warning")
            results["failed"] += 1
            continue

        try:
            total_score = evaluation.get("total_score", 0)
            scaled_grade = round((total_score / 100) * target_max)
            feedback_html = format_feedback_html(evaluation)

            res = submit_grade(
                session,
                assignment_id,
                user_id,
                module_id,
                scaled_grade,
                feedback_html,
                sesskey,
            )

            if res.get("success"):
                notify(step + 1, len(pending), student_name, f"Submitted: {scaled_grade}/{int(target_max)}", "success")
                results["submitted"] += 1
            else:
                err = res.get("error", "Unknown error")
                notify(step + 1, len(pending), student_name, f"Failed: {err[:50]}", "error")
                results["failed"] += 1

        except Exception as e:
            logger.error(f"Error submitting {student_name}: {e}")
            notify(step + 1, len(pending), student_name, f"Error: {str(e)[:50]}", "error")
            results["failed"] += 1

        if step < len(pending) - 1:
            time.sleep(0.5)

    notify(
        len(pending),
        len(pending),
        "",
        f"Moodle submission complete: {results['submitted']} submitted, {results['failed']} failed.",
        "success" if results["failed"] == 0 else "warning",
    )

    return results
