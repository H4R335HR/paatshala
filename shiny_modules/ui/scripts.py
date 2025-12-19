"""
Custom JavaScript for the Shiny application
"""

def get_custom_js():
    """Returns the custom JavaScript for the Shiny application"""
    return """
// ============================================================================
// THEME TOGGLE SYSTEM
// ============================================================================
function initTheme() {
    const saved = localStorage.getItem('theme');
    if (saved) {
        document.documentElement.setAttribute('data-theme', saved);
    } else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
        document.documentElement.setAttribute('data-theme', 'dark');
    }
    updateThemeIcon();
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    updateThemeIcon();
}

function updateThemeIcon() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const btn = document.getElementById('theme-toggle-btn');
    if (btn) {
        btn.innerHTML = isDark 
            ? '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>'
            : '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>';
    }
}

// Initialize theme on load
document.addEventListener('DOMContentLoaded', initTheme);

// ============================================================================
// SORTABLE INITIALIZATION
// ============================================================================
let sortableInstance = null;
let lastSelectedIdx = null;


function initSortable() {
    const el = document.getElementById('topics_list_body');
    if (!el) return;

    if (sortableInstance) sortableInstance.destroy();

    sortableInstance = new Sortable(el, {
        animation: 150,
        handle: '.drag-handle',
        ghostClass: 'sortable-ghost',
        onEnd: function (evt) {
            // Notify Shiny of the move
            Shiny.setInputValue("drag_move", {
                from: evt.oldIndex,
                to: evt.newIndex,
                nonce: Math.random()
            }, {priority: "event"});
        }
    });
}

// Click handler
document.addEventListener('click', function(e) {
    // Check if clicked boolean checkbox
    if (e.target.matches('.row-checkbox')) {
        updateSelection();
        e.stopPropagation(); // prevent row click
        return;
    }

    // Check if clicked action button
    const actionVis = e.target.closest('.action-vis');
    const actionDel = e.target.closest('.action-del');

    if (actionVis) {
         e.stopPropagation();
         Shiny.setInputValue("row_action_vis", {
             index: parseInt(actionVis.dataset.index),
             nonce: Math.random()
         }, {priority: "event"});
         return;
    }

    if (actionDel) {
         e.stopPropagation();
         Shiny.setInputValue("row_action_del", {
             index: parseInt(actionDel.dataset.index),
             nonce: Math.random()
         }, {priority: "event"});
         return;
    }

    // Check if clicked lock button
    const actionLock = e.target.closest('.action-lock');
    if (actionLock) {
         e.stopPropagation();
         Shiny.setInputValue("row_action_lock", {
             index: parseInt(actionLock.dataset.index),
             nonce: Math.random()
         }, {priority: "event"});
         return;
    }

    // Check if clicked activities button
    const actionActivities = e.target.closest('.action-activities');
    if (actionActivities) {
         e.stopPropagation();
         Shiny.setInputValue("row_action_activities", {
             index: parseInt(actionActivities.dataset.index),
             nonce: Math.random()
         }, {priority: "event"});
         return;
    }

    // Check if clicked editable name
    const editableName = e.target.closest('.editable-topic-name');
    if (editableName) {
        e.stopPropagation();
        makeEditable(editableName);
        return;
    }

    const row = e.target.closest('tr.topic-row');
    if (!row) return; // Clicked outside row

    // Row Click -> Single Select
    document.querySelectorAll('.row-checkbox').forEach(cb => cb.checked = false);

    const cb = row.querySelector('.row-checkbox');
    if (cb) cb.checked = true;

    updateSelection();
});

// Select All Handler
document.addEventListener('change', function(e) {
    if (e.target.id === 'select-all-cb') {
        const isChecked = e.target.checked;
        document.querySelectorAll('.row-checkbox').forEach(cb => cb.checked = isChecked);
        updateSelection();
    }
});

function updateSelection() {
    const checkedBoxes = Array.from(document.querySelectorAll('.row-checkbox:checked'));
    const indices = checkedBoxes.map(cb => parseInt(cb.dataset.index));

    // Update Shiny
    Shiny.setInputValue("selected_row_indices", indices);

    // Update Styles
    document.querySelectorAll('tr.topic-row').forEach(r => {
        const cb = r.querySelector('.row-checkbox');
        if (cb && cb.checked) r.classList.add('selected-row');
        else r.classList.remove('selected-row');
    });
}

// Inline Editing Logic
function makeEditable(el) {
    const currentText = el.innerText;
    const idx = el.dataset.index;

    const input = document.createElement('input');
    input.type = 'text';
    input.value = currentText;
    input.className = 'rename-input';

    // Replace span with input
    el.replaceWith(input);
    input.focus();

    // Save on Blur or Enter
    let saved = false;

    function save() {
        if (saved) return;
        saved = true;

        const newText = input.value.trim();

        // Revert to span
        const newSpan = document.createElement('span');
        newSpan.className = 'editable-topic-name';
        newSpan.dataset.index = idx;
        newSpan.innerText = newText; // Optimistic update
        newSpan.title = "Click to rename";

        input.replaceWith(newSpan);

        if (newText && newText !== currentText) {
             Shiny.setInputValue("inline_rename_event", {
                 index: parseInt(idx),
                 name: newText,
                 nonce: Math.random()
             }, {priority: "event"});
        }
    }

    input.addEventListener('blur', save);
    input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            save();
        } else if (e.key === 'Escape') {
            saved = true; // Cancel without save
            el.innerText = currentText; // Restore original
            input.replaceWith(el);
        }
    });
}

// Re-init on new data
$(document).on('shiny:value', function(event) {
    if (event.name === 'topics_table_html') {
        setTimeout(initSortable, 100); // Wait for render
    }
});

// Activity Context Menu for Move
let activeContextMenu = null;

function hideActivityContextMenu() {
    if (activeContextMenu) {
        activeContextMenu.remove();
        activeContextMenu = null;
    }
}

document.addEventListener('click', function(e) {
    if (!e.target.closest('.activity-context-menu')) {
        hideActivityContextMenu();
    }
});

document.addEventListener('contextmenu', function(e) {
    const row = e.target.closest('tr[data-activity-id]');
    if (row) {
        e.preventDefault();
        showActivityContextMenu(e.clientX, e.clientY, row);
    }
});

function showActivityContextMenu(x, y, row) {
    hideActivityContextMenu();

    const activityId = row.dataset.activityId;
    const activityName = row.dataset.activityName;
    const currentSectionId = row.dataset.sectionId;

    // Get topics from global variable (set by Shiny)
    const topicsData = window.activityModalTopics || [];
    if (!topicsData.length) {
        console.log('No topics data available');
        return;
    }

    // Create menu
    const menu = document.createElement('div');
    menu.className = 'activity-context-menu';

    // Header
    menu.innerHTML = `<div class="menu-header">Move "${activityName}" to:</div>`;

    // Topic items
    topicsData.forEach(function(topic) {
        const item = document.createElement('div');
        item.className = 'menu-item' + (topic.sectionId == currentSectionId ? ' current-section' : '');
        item.innerHTML = topic.sectionId == currentSectionId
            ? `📍 ${topic.name} (current)`
            : `📁 ${topic.name}`;

        if (topic.sectionId != currentSectionId) {
            item.onclick = function() {
                hideActivityContextMenu();
                Shiny.setInputValue('activity_move_to_topic', {
                    activityId: activityId,
                    activityName: activityName,
                    targetSectionId: topic.sectionId,
                    targetSectionDbId: topic.dbId,
                    targetSectionName: topic.name,
                    nonce: Math.random()
                }, {priority: 'event'});
            };
        }
        menu.appendChild(item);
    });

    // Position menu
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';

    document.body.appendChild(menu);
    activeContextMenu = menu;

    // Adjust if off screen
    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) {
        menu.style.left = (window.innerWidth - rect.width - 10) + 'px';
    }
    if (rect.bottom > window.innerHeight) {
        menu.style.top = (window.innerHeight - rect.height - 10) + 'px';
    }
}

// Sortable for Activities Table (drag-drop reordering)
let activitySortableInstance = null;

function initActivitySortable() {
    const el = document.getElementById('activities_table_body');
    if (!el) return;

    if (activitySortableInstance) activitySortableInstance.destroy();

    activitySortableInstance = new Sortable(el, {
        animation: 150,
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        handle: '.drag-handle',
        onEnd: function(evt) {
            const rows = el.querySelectorAll('tr[data-activity-id]');
            const activityIds = Array.from(rows).map(r => r.dataset.activityId);
            const movedId = evt.item.dataset.activityId;
            const newIndex = evt.newIndex;
            const beforeId = (newIndex < activityIds.length - 1) ? activityIds[newIndex + 1] : null;

            Shiny.setInputValue("activity_reorder", {
                activityId: movedId,
                newIndex: newIndex,
                beforeId: beforeId,
                nonce: Math.random()
            }, {priority: "event"});
        }
    });
}

// Duplicate button click handler
document.addEventListener('click', function(e) {
    const dupBtn = e.target.closest('.btn-duplicate-activity');
    if (dupBtn) {
        e.preventDefault();
        e.stopPropagation();
        const activityId = dupBtn.dataset.activityId;
        const activityName = dupBtn.dataset.activityName;

        Shiny.setInputValue("activity_duplicate", {
            activityId: activityId,
            activityName: activityName,
            nonce: Math.random()
        }, {priority: "event"});
    }

    // Rename button handler
    const renameBtn = e.target.closest('.btn-rename-activity');
    if (renameBtn) {
        e.preventDefault();
        e.stopPropagation();
        const activityId = renameBtn.dataset.activityId;
        const activityName = renameBtn.dataset.activityName;
        const activityType = renameBtn.dataset.activityType;

        const newName = prompt(`Rename activity:`, activityName);
        if (newName && newName.trim() && newName.trim() !== activityName) {
            Shiny.setInputValue("activity_rename", {
                activityId: activityId,
                oldName: activityName,
                newName: newName.trim(),
                activityType: activityType,
                nonce: Math.random()
            }, {priority: "event"});
        }
    }

    // Visibility toggle button handler
    const visBtn = e.target.closest('.btn-toggle-visibility-activity');
    if (visBtn) {
        e.preventDefault();
        e.stopPropagation();
        const activityId = visBtn.dataset.activityId;
        const isVisible = visBtn.dataset.visible === 'true';
        const row = visBtn.closest('tr');

        // Optimistic UI update
        if (row) {
            const newVisible = !isVisible;
            row.dataset.visible = newVisible.toString();
            visBtn.dataset.visible = newVisible.toString();
            visBtn.textContent = newVisible ? '👁️' : '🚫';
            visBtn.title = newVisible ? 'Hide' : 'Show';
        }

        Shiny.setInputValue("activity_toggle_visibility", {
            activityId: activityId,
            hide: isVisible,
            nonce: Math.random()
        }, {priority: "event"});
        return;
    }

    // Delete button handler - with optimistic UI update
    const delBtn = e.target.closest('.btn-delete-activity');
    if (delBtn) {
        e.preventDefault();
        e.stopPropagation();
        const activityId = delBtn.dataset.activityId;
        const activityName = delBtn.dataset.activityName;
        const row = delBtn.closest('tr');

        if (confirm(`Are you sure you want to delete "${activityName}"?`)) {
            // Optimistic UI: fade out and remove the row immediately
            if (row) {
                row.style.transition = 'opacity 0.3s';
                row.style.opacity = '0.3';
            }

            Shiny.setInputValue("activity_delete", {
                activityId: activityId,
                activityName: activityName,
                nonce: Math.random()
            }, {priority: "event"});
        }
    }
});

// Listen for successful delete to fully remove row
Shiny.addCustomMessageHandler('activity_deleted', function(data) {
    const row = document.querySelector(`tr[data-activity-id="${data.activityId}"]`);
    if (row) {
        row.style.transition = 'all 0.3s';
        row.style.opacity = '0';
        row.style.transform = 'translateX(-20px)';
        setTimeout(() => row.remove(), 300);
    }
});

// Listen for successful duplicate to add a new row
Shiny.addCustomMessageHandler('activity_duplicated', function(data) {
    const originalRow = document.querySelector(`tr[data-activity-id="${data.originalId}"]`);
    if (originalRow && data.newRowHtml) {
        // Insert the new row after the original
        originalRow.insertAdjacentHTML('afterend', data.newRowHtml);
        const newRow = originalRow.nextElementSibling;
        if (newRow) {
            newRow.style.opacity = '0';
            newRow.style.transition = 'opacity 0.3s';
            setTimeout(() => newRow.style.opacity = '1', 10);
        }
    }
});

// Initialize activity sortable when modal opens
$(document).on('shiny:value', function(event) {
    if (event.name === 'activities_modal_content') {
        setTimeout(initActivitySortable, 100);
    }
});

// ============================================================================
// BATCH DELETE FUNCTIONALITY
// ============================================================================

// Update batch delete button based on selected checkboxes
function updateBatchDeleteButton() {
    const checkboxes = document.querySelectorAll('.activity-checkbox:checked');
    const btn = document.getElementById('btn-batch-delete');
    if (!btn) return;
    
    const count = checkboxes.length;
    btn.textContent = `🗑️ Delete (${count})`;
    btn.disabled = count === 0;
}

// Select All checkbox handler
document.addEventListener('change', function(e) {
    if (e.target.id === 'activity-select-all') {
        const isChecked = e.target.checked;
        document.querySelectorAll('.activity-checkbox').forEach(cb => cb.checked = isChecked);
        updateBatchDeleteButton();
    }
    
    // Individual checkbox handler
    if (e.target.classList.contains('activity-checkbox')) {
        updateBatchDeleteButton();
        
        // Update select-all state
        const allCheckboxes = document.querySelectorAll('.activity-checkbox');
        const checkedCheckboxes = document.querySelectorAll('.activity-checkbox:checked');
        const selectAll = document.getElementById('activity-select-all');
        if (selectAll) {
            selectAll.checked = allCheckboxes.length === checkedCheckboxes.length && allCheckboxes.length > 0;
            selectAll.indeterminate = checkedCheckboxes.length > 0 && checkedCheckboxes.length < allCheckboxes.length;
        }
    }
});

// Batch delete button click handler
document.addEventListener('click', function(e) {
    if (e.target.id === 'btn-batch-delete') {
        e.preventDefault();
        e.stopPropagation();
        
        const checkboxes = document.querySelectorAll('.activity-checkbox:checked');
        if (checkboxes.length === 0) return;
        
        const activities = Array.from(checkboxes).map(cb => ({
            id: cb.dataset.activityId,
            name: cb.dataset.activityName
        }));
        
        const confirmMsg = activities.length === 1
            ? `Delete "${activities[0].name}"?`
            : `Delete ${activities.length} activities? This cannot be undone.`;
        
        if (confirm(confirmMsg)) {
            // Optimistic UI: fade out selected rows
            checkboxes.forEach(cb => {
                const row = cb.closest('tr');
                if (row) {
                    row.style.transition = 'opacity 0.3s';
                    row.style.opacity = '0.3';
                }
            });
            
            Shiny.setInputValue("activity_batch_delete", {
                activities: activities,
                nonce: Math.random()
            }, {priority: "event"});
        }
    }
});
"""
