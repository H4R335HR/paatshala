"""
Page modules for Streamlit app.
Each module contains the render function for one tab.
"""

from .tasks import render_tasks_tab
from .quiz import render_quiz_tab
from .submissions import render_submissions_tab
from .evaluation import render_evaluation_tab
from .workshop import render_workshop_tab
from .feedback import render_feedback_tab

__all__ = [
    'render_tasks_tab',
    'render_quiz_tab', 
    'render_submissions_tab',
    'render_evaluation_tab',
    'render_workshop_tab',
    'render_feedback_tab'
]

