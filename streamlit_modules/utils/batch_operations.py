"""
Reusable batch operation framework

This module eliminates duplicate batch operation code patterns
found in the original shiny_app.py (lines 1683-1856)
"""
from shiny import ui
import logging

logger = logging.getLogger(__name__)


class BatchOperationExecutor:
    """
    Executes batch operations with progress tracking

    This class provides a reusable pattern for batch operations,
    eliminating the need for nearly-identical functions like:
    - do_add_group_batch()
    - do_clear_groups_batch()
    - do_clear_all_restrictions_batch()
    """

    def __init__(self, operation_name, progress_message):
        """
        Initialize batch operation executor

        Args:
            operation_name: Name for logging purposes
            progress_message: Message shown in progress dialog
        """
        self.operation_name = operation_name
        self.progress_message = progress_message

    def execute(self, indices, items, processor_func):
        """
        Execute batch operation on selected items

        Args:
            indices: List of indices to process
            items: List of items to operate on
            processor_func: Function(item, index) -> bool
                          Returns True on success, False on failure

        Returns:
            tuple: (success_count, error_count)
        """
        success_count = 0
        error_count = 0

        with ui.Progress(min=0, max=len(indices)) as p:
            p.set(message=self.progress_message)

            for i, idx in enumerate(indices):
                try:
                    if idx < len(items):
                        result = processor_func(items[idx], idx)
                        if result:
                            success_count += 1
                        else:
                            error_count += 1
                    else:
                        logger.warning(f"{self.operation_name}: Invalid index {idx}")
                        error_count += 1
                except Exception as e:
                    logger.error(f"Error in {self.operation_name} at index {idx}: {e}")
                    error_count += 1

                p.set(i + 1)

        logger.info(
            f"{self.operation_name} completed: "
            f"{success_count} successful, {error_count} errors"
        )

        return success_count, error_count


# Example usage patterns:
"""
# Before (original code ~70 lines each):
@reactive.Effect
@reactive.event(input.batch_add_group)
def do_add_group_batch():
    indices = selected_indices()
    if not indices: return
    cid = input.course_id()
    group_id = input.batch_group_id()
    if not group_id: return

    current = list(topics_list())
    s = setup_session(user_session_id())

    with ui.Progress(min=0, max=len(indices)) as p:
        p.set(message="Adding group restriction...")
        for i, idx in enumerate(indices):
            if idx >= len(current): continue
            try:
                add_or_update_group_restriction(s, current[idx], [group_id], cid)
                current[idx]['group_restriction_summary'] = f"Group: {group_id}"
            except Exception as e:
                logger.error(f"Error adding group: {e}")
            p.set(i + 1)

    topics_list.set(current)
    save_cache(f"course_{cid}_topics", current)
    trigger_background_refresh(cid)

# After (with BatchOperationExecutor ~15 lines):
@reactive.Effect
@reactive.event(input.batch_add_group)
def do_add_group_batch():
    indices = selected_indices()
    if not indices: return
    cid = input.course_id()
    group_id = input.batch_group_id()
    if not group_id: return

    current = list(topics_list())
    s = setup_session(user_session_id())

    def add_group_to_topic(topic, idx):
        add_or_update_group_restriction(s, topic, [group_id], cid)
        topic['group_restriction_summary'] = f"Group: {group_id}"
        return True

    executor = BatchOperationExecutor("Add Group", "Adding group restriction...")
    success, errors = executor.execute(indices, current, add_group_to_topic)

    if success > 0:
        topics_list.set(current)
        save_cache(f"course_{cid}_topics", current)
        trigger_background_refresh(cid)
        ui.notification_show(f"Added group to {success} topics", type="message")
"""
