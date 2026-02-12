"""Repository for task scheduling data access."""

from typing import Any, Dict, List, Optional
from datetime import datetime

from db_utils import get_db_all, get_db_row


class TaskRepository:
    """
    Repository for task scheduling and management.
    
    Abstracts task-related queries to enable clean testing and
    replacement of actions.py with agentic flow.
    """
    
    async def get_active_tasks(self, sender_id: str) -> List[Dict[str, Any]]:
        """
        Get all active (non-deleted) tasks for a sender.
        
        Args:
            sender_id: The unique identifier for the conversation
            
        Returns:
            List of task dictionaries
        """
        rows = await get_db_all(
            "SELECT * FROM events_tasks WHERE sender_id = %s AND deleted = 0 ORDER BY eta",
            [sender_id]
        )
        return list(rows) if rows else []
    
    async def get_first_active_task(self, sender_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the first scheduled task (earliest eta).
        
        Args:
            sender_id: The unique identifier for the conversation
            
        Returns:
            Task dictionary or None
        """
        row = await get_db_row(
            "SELECT * FROM events_tasks WHERE sender_id = %s AND deleted = 0 ORDER BY eta LIMIT 1",
            [sender_id]
        )
        return dict(row) if row else None
    
    async def create_task(
        self,
        sender_id: str,
        eta: datetime,
        task_type: str = "reminder",
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Create a new scheduled task.
        
        Args:
            sender_id: The unique identifier for the conversation
            eta: When the task should be executed
            task_type: Type of task (e.g., "reminder", "quiz")
            metadata: Additional task metadata
        """
        import json
        
        metadata_json = json.dumps(metadata) if metadata else None
        
        await get_db_row(
            "INSERT INTO events_tasks (sender_id, eta, task_type, metadata, deleted) VALUES (%s, %s, %s, %s, 0)",
            [sender_id, eta, task_type, metadata_json]
        )
    
    async def delete_task(self, task_id: int) -> None:
        """
        Mark a task as deleted (soft delete).
        
        Args:
            task_id: The task ID to delete
        """
        await get_db_row(
            "UPDATE events_tasks SET deleted = 1 WHERE id = %s",
            [task_id]
        )
    
    async def reset_all_tasks(self, sender_id: str) -> None:
        """
        Mark all tasks for a sender as deleted.
        
        Args:
            sender_id: The unique identifier for the conversation
        """
        await get_db_row(
            "UPDATE events_tasks SET deleted = 1 WHERE sender_id = %s",
            [sender_id]
        )
    
    async def get_task_count(self, sender_id: str) -> int:
        """
        Get count of active tasks for a sender.
        
        Args:
            sender_id: The unique identifier for the conversation
            
        Returns:
            Number of active tasks
        """
        tasks = await self.get_active_tasks(sender_id)
        return len(tasks)
