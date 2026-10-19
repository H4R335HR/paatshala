"""
Ungraded Activities Detector Component
Automatically detects ungraded activities upon opening a course and allows one-click evaluation.
Respects user settings:
- Only evaluates the group selected in the sidebar
- Pauses to approve missing rubrics
- Reviews grades before submitting to Moodle
"""

import logging
from typing import Any, Dict, List, Optional
import streamlit as st

from core.ai import generate_rubric, load_rubric, save_rubric
from core.api import fetch_submissions, fetch_tasks_list
from core.grading_pipeline import (
    get_task_grading_status,
    run_batch_scoring,
    scan_course_ungraded_tasks,
)
from core.persistence import load_csv_from_disk, save_csv_to_disk, save_meta

logger = logging.getLogger(__name__)


@st.dialog("📋 Approve Rubric Before Evaluation", width="large")
def show_rubric_approval_dialog(
    course: Dict[str, Any],
    module_id: int,
    task_name: str,
    task_description: str,
    group_id: Optional[int] = None,
    on_approved_callback_key: Optional[str] = None,
):
    """Dialog that pauses and asks user to review/approve a rubric before scoring."""
    st.subheader(f"Approve Rubric: {task_name}")
    st.caption("AI scoring requires an approved rubric. Please review or adjust the criteria below:")

    if not task_description:
        st.warning("⚠️ No task description found. The rubric below uses default evaluation criteria.")

    temp_rubric_key = f"_temp_generated_rubric_{module_id}"
    if temp_rubric_key not in st.session_state or st.session_state[temp_rubric_key] is None:
        with st.spinner("Generating rubric from task description..."):
            gen = generate_rubric(task_description or task_name)
            if not gen:
                # Fallback standard rubric if AI fails
                gen = [
                    {"criterion": "Requirements & Completeness", "description": "Submission meets all stated requirements.", "weight_percent": 40},
                    {"criterion": "Technical Quality", "description": "Correct implementation, syntax, and accuracy.", "weight_percent": 35},
                    {"criterion": "Timely Submission", "description": "Submitted on or before the due date.", "weight_percent": 25},
                ]
            st.session_state[temp_rubric_key] = gen

    criteria = st.session_state[temp_rubric_key]

    st.markdown("#### Rubric Criteria & Weights")
    updated_criteria = []
    total_weight = 0

    for idx, c in enumerate(criteria):
        c_col1, c_col2, c_col3 = st.columns([3, 5, 2])
        with c_col1:
            name_val = st.text_input(
                f"Criterion {idx + 1}",
                value=c.get("criterion", ""),
                key=f"rubric_dlg_name_{module_id}_{idx}",
            )
        with c_col2:
            desc_val = st.text_input(
                f"Description {idx + 1}",
                value=c.get("description", ""),
                key=f"rubric_dlg_desc_{module_id}_{idx}",
            )
        with c_col3:
            weight_val = st.number_input(
                f"Weight % {idx + 1}",
                min_value=0,
                max_value=100,
                step=5,
                value=int(c.get("weight_percent", 0)),
                key=f"rubric_dlg_wt_{module_id}_{idx}",
            )
            total_weight += weight_val

        updated_criteria.append({
            "criterion": name_val,
            "description": desc_val,
            "weight_percent": weight_val,
        })

    # Weight check indicator
    if total_weight == 100:
        st.success(f"✓ Total Weight: **100%**")
    else:
        st.error(f"⚠️ Total Weight is **{total_weight}%** (must sum to exactly 100%)")

    btn_col1, btn_col2 = st.columns([2, 1])
    with btn_col1:
        if st.button("✅ Approve & Start Evaluation", type="primary", use_container_width=True, disabled=(total_weight != 100)):
            # Save approved rubric to disk
            save_rubric(course["id"], module_id, updated_criteria, group_id)
            # Also cache in session state for tabs
            st.session_state[f"rubric_{module_id}"] = updated_criteria
            if group_id:
                st.session_state[f"rubric_{module_id}_grp{group_id}"] = updated_criteria

            st.toast("Rubric approved & saved!", icon="✅")
            # Signal that evaluation should start
            st.session_state[f"start_evaluation_after_rubric_{module_id}"] = True
            st.session_state[temp_rubric_key] = None
            st.rerun()

    with btn_col2:
        if st.button("Cancel", use_container_width=True):
            st.session_state[temp_rubric_key] = None
            st.rerun()


def render_ungraded_detector(course: Dict[str, Any], meta: Dict[str, Any]):
    """Renders the top-level Ungraded Activities Detector banner."""
    course_id = course["id"]
    selected_group_id = st.session_state.selected_group["id"] if st.session_state.selected_group else None
    selected_group_name = st.session_state.selected_group["name"] if st.session_state.selected_group else "All Students"

    # Check dismiss toggle in session state
    dismiss_key = f"dismiss_detector_{course_id}_{selected_group_id}"
    if st.session_state.get(dismiss_key, False):
        # Show mini banner with un-dismiss button
        st.caption(f"🔔 Activity Inbox minimized for {selected_group_name}. ")
        if st.button("🔍 Open Activity Inbox", key=f"reopen_inbox_{course_id}", type="tertiary"):
            st.session_state[dismiss_key] = False
            st.rerun()
        return

    # Load tasks data (from session state or disk)
    tasks_data = st.session_state.tasks_data
    if not tasks_data:
        tasks_data = load_csv_from_disk(course_id, f"tasks_{course_id}.csv")
        if tasks_data:
            st.session_state.tasks_data = tasks_data

    # If tasks are still not loaded, show quick scan option
    if not tasks_data:
        with st.container(border=True):
            st.markdown("#### 📥 Automated Activity Detector")
            st.write(
                "Detect all ungraded assignments, check rubric status, and evaluate pending submissions with one click."
            )
            col1, col2 = st.columns([1, 3])
            with col1:
                if st.button("🔍 Scan Course Tasks", type="primary", use_container_width=True):
                    with st.spinner("Fetching tasks from Paatshala..."):
                        rows = fetch_tasks_list(st.session_state.session_id, course_id)
                        if rows:
                            st.session_state.tasks_data = rows
                            save_csv_to_disk(course_id, f"tasks_{course_id}.csv", rows)
                            save_meta(course_id, "tasks", len(rows))
                            st.rerun()
                        else:
                            st.warning("No tasks found in this course.")
            with col2:
                st.caption(f"Filtering strictly by sidebar group: **{selected_group_name}**")
        return

    # Fetch/load restrictions map for the course
    restr_map = None
    if st.session_state.get('session_id'):
        try:
            from core.auth import setup_session
            from core.api import get_course_activity_restrictions
            session = setup_session(st.session_state.session_id)
            restr_map = get_course_activity_restrictions(session, course_id)
        except Exception as e:
            logger.debug(f"Could not load restrictions map: {e}")

    # Scan tasks for ungraded items (automatically filtering by permitted batch)
    scanned_tasks = scan_course_ungraded_tasks(
        course_id=course_id,
        tasks_data=tasks_data,
        group_id=selected_group_id,
        selected_group=st.session_state.selected_group,
        restrictions_map=restr_map,
    )
    ungraded_tasks = [t for t in scanned_tasks if t["needs_attention"]]

    if not ungraded_tasks:
        # All clean - show a subtle positive confirmation
        st.caption(f"✅ **Activity Inbox:** No pending ungraded submissions for {selected_group_name}.")
        return

    # Render Active Inbox Card
    total_ungraded = sum(
        t["status"]["ai_pending_count"] or t["moodle_needs_grading_int"]
        for t in ungraded_tasks
    )

    with st.container(border=True):
        head_col1, head_col2, head_col3 = st.columns([3, 1, 1])
        with head_col1:
            st.markdown(
                f"### 📥 Activity Inbox: **{len(ungraded_tasks)}** Activities Need Grading "
                f"<span style='font-size:14px; color:#aaa; font-weight:normal;'>({total_ungraded} pending | Filter: {selected_group_name})</span>",
                unsafe_allow_html=True,
            )
        with head_col2:
            if st.button("🔄 Sync with Moodle", key=f"inbox_sync_moodle_{course_id}", help="Re-fetch tasks list from Moodle to update grading status", use_container_width=True):
                with st.spinner("Syncing latest task grading counts from Paatshala..."):
                    rows = fetch_tasks_list(st.session_state.session_id, course_id)
                    if rows:
                        st.session_state.tasks_data = rows
                        save_csv_to_disk(course_id, f"tasks_{course_id}.csv", rows)
                        save_meta(course_id, "tasks", len(rows))
                        st.toast("Synced tasks with Moodle!", icon="🔄")
                        st.rerun()
        with head_col3:
            if st.button("✕ Dismiss", key=f"dismiss_btn_{course_id}", use_container_width=True):
                st.session_state[dismiss_key] = True
                st.rerun()

        st.caption(
            "Paatshala detected assignments with ungraded submissions. "
            "You can evaluate them with AI right here, approve missing rubrics, or click 🔄 to sync manual grades from Moodle."
        )

        # Loop through each ungraded task
        for t in ungraded_tasks:
            mod_id = t["module_id"]
            task_name = t["task_name"]
            status = t["status"]
            has_rubric = t["has_rubric"]
            desc = t["description"]

            # Check if evaluation was just approved via rubric dialog
            start_eval_key = f"start_evaluation_after_rubric_{mod_id}"
            if st.session_state.get(start_eval_key, False):
                st.session_state[start_eval_key] = False
                _execute_inbox_evaluation(course, t, selected_group_id)
                st.rerun()

            card_col1, card_col2, card_col3, card_col4 = st.columns([5, 3, 2, 1])

            with card_col1:
                st.markdown(f"**📋 {task_name}**")
                rubric_badge = "✅ Rubric Ready" if has_rubric else "⚠️ Needs Rubric"
                st.caption(f"Module ID: `{mod_id}` | {rubric_badge}")

            with card_col2:
                # Show numbers
                sub_count = status["submitted_count"]
                ai_count = status["ai_evaluated_count"]
                pending_ai = status["ai_pending_count"]
                moodle_pending = t["moodle_needs_grading_int"]

                if status["has_data"]:
                    st.write(f"📝 Submissions: **{sub_count}** | Scored: **{ai_count}** | Pending AI: **{pending_ai}**")
                else:
                    st.write(f"Moodle Reports: **{moodle_pending}** needing grading (not yet downloaded)")

            with card_col3:
                btn_key = f"inbox_eval_btn_{mod_id}_{selected_group_id}"
                if st.button(f"⚡ Evaluate", key=btn_key, type="primary", use_container_width=True):
                    # Check rubric first (Rule 1: Pause and ask to approve)
                    if not has_rubric:
                        show_rubric_approval_dialog(
                            course=course,
                            module_id=mod_id,
                            task_name=task_name,
                            task_description=desc,
                            group_id=selected_group_id,
                        )
                    else:
                        _execute_inbox_evaluation(course, t, selected_group_id)
                        st.rerun()

            with card_col4:
                # Quick Refresh Submissions from Moodle
                if st.button("🔄", key=f"inbox_refresh_sub_{mod_id}_{selected_group_id}", help="Re-fetch submissions from Moodle to sync manual grades", use_container_width=True):
                    with st.spinner(f"Syncing {task_name} from Moodle..."):
                        sub_rows, asgn_id, max_grd = fetch_submissions(st.session_state.session_id, mod_id, selected_group_id)
                        if sub_rows:
                            for r in sub_rows:
                                r["Task Name"] = task_name
                                r["Module ID"] = mod_id
                            sub_fname = f"submissions_{course_id}_mod{mod_id}"
                            if selected_group_id:
                                sub_fname += f"_grp{selected_group_id}"
                            sub_fname += ".csv"
                            save_csv_to_disk(course_id, sub_fname, sub_rows)
                            save_meta(course_id, f"submissions_{mod_id}", len(sub_rows))
                            st.toast(f"Synced {task_name} with Moodle!", icon="✅")
                            st.rerun()

            st.divider()


def _execute_inbox_evaluation(course: Dict[str, Any], task_info: Dict[str, Any], group_id: Optional[int]):
    """Helper to fetch submissions if needed and execute batch scoring for a task."""
    mod_id = task_info["module_id"]
    course_id = course["id"]
    task_name = task_info["task_name"]
    desc = task_info["description"]

    # 1. Ensure submissions are downloaded
    submissions_filename = f"submissions_{course_id}_mod{mod_id}"
    if group_id:
        submissions_filename += f"_grp{group_id}"
    submissions_filename += ".csv"

    data = load_csv_from_disk(course_id, submissions_filename)
    if not data:
        with st.spinner(f"Fetching submissions from Paatshala for {task_name}..."):
            rows, assignment_id, max_grade = fetch_submissions(
                st.session_state.session_id, mod_id, group_id
            )
            if rows:
                for r in rows:
                    r["Task Name"] = task_name
                    r["Module ID"] = mod_id
                save_csv_to_disk(course_id, submissions_filename, rows)
                save_meta(course_id, f"submissions_{mod_id}", len(rows))
                data = rows
                if assignment_id:
                    st.session_state[f"assignment_id_{mod_id}"] = assignment_id
                if max_grade:
                    st.session_state[f"max_grade_{mod_id}"] = max_grade

    if not data:
        st.error(f"Could not load submissions for {task_name}.")
        return

    # 2. Load rubric
    rubric_doc = load_rubric(course_id, mod_id, group_id)
    rubric = rubric_doc.get("criteria", []) if rubric_doc else []
    if not rubric:
        st.error("No approved rubric found.")
        return

    # 3. Run scoring with progress bar
    progress_bar = st.progress(0, text=f"Scoring {task_name}...")
    status_text = st.empty()

    def update_progress(info):
        curr = info.get("current", 0)
        tot = info.get("total", 1)
        prog = (curr / tot) if tot > 0 else 0
        progress_bar.progress(prog, text=f"{info.get('message', '')}")
        if info.get("type") in ["success", "warning", "error", "skipped"]:
            status_text.caption(f"{info.get('message', '')}")

    res = run_batch_scoring(
        course_id=course_id,
        module_id=mod_id,
        group_id=group_id,
        submissions_data=data,
        rubric=rubric,
        task_description=desc or task_name,
        session_id=st.session_state.session_id,
        progress_callback=update_progress,
        auto_fetch=True,
    )

    st.toast(f"✅ {task_name}: Scored {res['scored']} submissions!", icon="🎯")
    st.success(f"✓ Completed evaluation for **{task_name}**: {res['scored']} scored, {res['failed']} failed.")
