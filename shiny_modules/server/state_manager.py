"""
Topics state management with auto-caching.

This module eliminates 23+ repetitions of topics_list.set() with save_cache().
"""
from core.persistence import save_cache


class TopicsStateManager:
    """
    Manages topics list reactive state with automatic cache persistence.
    
    Usage:
        topics_state = TopicsStateManager(topics_list, lambda: input.course_id())
        topics_state.update(new_topics)  # Updates reactive value AND saves cache
    """
    
    def __init__(self, topics_list, course_id_getter, refresh_callback=None):
        """
        Initialize topics state manager.
        
        Args:
            topics_list: Shiny reactive.Value for topics
            course_id_getter: Callable that returns current course ID
            refresh_callback: Optional callable(course_id) to trigger background refresh
        """
        self.topics_list = topics_list
        self.course_id_getter = course_id_getter
        self.refresh_callback = refresh_callback
    
    def get(self):
        """Get current topics as mutable list."""
        return list(self.topics_list())
    
    def get_readonly(self):
        """Get current topics (read-only, no copy)."""
        return self.topics_list()
    
    def update(self, new_topics, save_to_cache=True, trigger_refresh=True):
        """
        Update topics and optionally persist to cache.
        
        Args:
            new_topics: New topics list
            save_to_cache: Whether to save to disk cache (default True)
            trigger_refresh: Whether to trigger background refresh (default True)
        """
        self.topics_list.set(new_topics)
        
        if save_to_cache:
            cid = self.course_id_getter()
            save_cache(f"course_{cid}_topics", new_topics)
        
        if trigger_refresh and self.refresh_callback:
            self.refresh_callback(self.course_id_getter())
    
    def update_at_index(self, idx, updates):
        """
        Update specific topic by index.
        
        Args:
            idx: Index of topic to update
            updates: Dict of updates to apply to the topic
        """
        current = self.get()
        if idx < len(current):
            current[idx].update(updates)
            self.update(current)
    
    def remove_at_index(self, idx):
        """Remove topic at index."""
        current = self.get()
        if idx < len(current):
            del current[idx]
            self.update(current)
    
    def insert_at_index(self, idx, topic):
        """Insert topic at index."""
        current = self.get()
        current.insert(idx, topic)
        self.update(current)
    
    def move(self, from_idx, to_idx):
        """Move topic from one index to another."""
        current = self.get()
        if from_idx < len(current) and to_idx <= len(current):
            topic = current.pop(from_idx)
            current.insert(to_idx, topic)
            self.update(current)
