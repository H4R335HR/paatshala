"""
Tab registry for dynamic tab management.
Defines all available tabs with metadata and provides helper functions.
"""

# Tab registry with metadata for each tab
TAB_REGISTRY = {
    'tasks': {
        'id': 'tasks',
        'name': '📋 Tasks',
        'description': 'Assignment tasks',
        'module': 'streamlit_modules.pages',
        'function': 'render_tasks_tab',
    },
    'quiz': {
        'id': 'quiz',
        'name': '📊 Quiz Scores',
        'description': 'Practice quiz scores',
        'module': 'streamlit_modules.pages',
        'function': 'render_quiz_tab',
    },
    'submissions': {
        'id': 'submissions',
        'name': '📝 Submissions',
        'description': 'Assignment submissions',
        'module': 'streamlit_modules.pages',
        'function': 'render_submissions_tab',
    },
    'evaluation': {
        'id': 'evaluation',
        'name': '🔍 Evaluation',
        'description': 'Submission evaluation',
        'module': 'streamlit_modules.pages',
        'function': 'render_evaluation_tab',
    },
    'workshops': {
        'id': 'workshops',
        'name': '🔧 Workshops',
        'description': 'Workshop activities',
        'module': 'streamlit_modules.pages',
        'function': 'render_workshop_tab',
    },
    'feedback': {
        'id': 'feedback',
        'name': '📣 Feedback',
        'description': 'Feedback forms',
        'module': 'streamlit_modules.pages',
        'function': 'render_feedback_tab',
    },
    'tryhackme': {
        'id': 'tryhackme',
        'name': '🎯 TryHackMe',
        'description': 'TryHackMe tracking',
        'module': 'streamlit_modules.pages',
        'function': 'render_tryhackme_tab',
    },
    'quizizz': {
        'id': 'quizizz',
        'name': '📝 Quizizz',
        'description': 'Quizizz results',
        'module': 'streamlit_modules.pages',
        'function': 'render_quizizz_tab',
    },
    'video_importer': {
        'id': 'video_importer',
        'name': '📹 Video Importer',
        'description': 'Import Google Drive videos',
        'module': 'streamlit_modules.pages',
        'function': 'render_video_importer_tab',
    },
    'ai_debug': {
        'id': 'ai_debug',
        'name': '🔬 AI Debug',
        'description': 'AI request/response logs for debugging',
        'module': 'streamlit_modules.pages',
        'function': 'render_ai_debug_tab',
    },
}

# Default tabs to enable on first run
DEFAULT_ENABLED_TABS = ['tasks', 'quiz', 'submissions', 'evaluation']

# Tab order (for consistent display)
TAB_ORDER = ['tasks', 'quiz', 'submissions', 'evaluation', 'workshops', 'feedback', 'tryhackme', 'quizizz', 'video_importer', 'ai_debug']


def get_all_tab_ids():
    """Get list of all available tab IDs in order"""
    return TAB_ORDER


def get_tab_info(tab_id):
    """Get metadata for a specific tab"""
    return TAB_REGISTRY.get(tab_id)


def get_tab_renderer(tab_id):
    """
    Lazy load and return tab renderer function.
    Only imports the module when needed for better performance.
    """
    tab_info = TAB_REGISTRY.get(tab_id)
    if not tab_info:
        return None
    
    try:
        # Dynamic import - only load when tab is enabled
        import importlib
        module = importlib.import_module(tab_info['module'])
        return getattr(module, tab_info['function'])
    except (ImportError, AttributeError) as e:
        print(f"Error loading tab renderer for {tab_id}: {e}")
        return None
