"""Simple async task scheduler for webchat - replaces Celery for web-only use."""
import asyncio
import datetime
import logging
from typing import Dict, Any, Optional
from db_utils import get_db_row, get_db_all

logger = logging.getLogger(__name__)


class TaskScheduler:
    """In-memory task scheduler for delayed actions (no external queue needed)."""
    
    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}
        
    async def schedule_reminder(
        self, 
        sender_id: str, 
        countdown: int,
        callback,
        *args,
        **kwargs
    ) -> str:
        """Schedule a reminder to trigger after countdown seconds."""
        import uuid
        task_id = str(uuid.uuid4())
        
        # Store in database
        target_eta = datetime.datetime.now() + datetime.timedelta(seconds=countdown)
        target_datetime = target_eta.strftime("%Y-%m-%d %H:%M:%S")
        await get_db_row(
            "INSERT INTO `planned_tasks` (`sender_id`, `task_id`, `eta`) VALUES (%s, %s, %s)",
            [sender_id, task_id, target_datetime],
        )
        
        # Schedule async task
        async def delayed_callback():
            await asyncio.sleep(countdown)
            try:
                await callback(*args, **kwargs)
            finally:
                # Mark as finished
                await get_db_row(
                    "UPDATE planned_tasks SET is_finished = 1 WHERE task_id = %s", 
                    [task_id]
                )
                # Clean up
                if task_id in self._tasks:
                    del self._tasks[task_id]
        
        task = asyncio.create_task(delayed_callback())
        self._tasks[task_id] = task
        return task_id
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a scheduled task."""
        if task_id in self._tasks:
            self._tasks[task_id].cancel()
            del self._tasks[task_id]
            # Note: DB update needs to be async, caller should use cancel_task_async
            return True
        return False
    
    async def cancel_task_async(self, task_id: str) -> bool:
        """Cancel a scheduled task (async version with DB update)."""
        if task_id in self._tasks:
            self._tasks[task_id].cancel()
            del self._tasks[task_id]
            await get_db_row(
                "UPDATE planned_tasks SET is_finished = 1 WHERE task_id = %s", 
                [task_id]
            )
            return True
        return False
    
    async def cancel_all_for_sender(self, sender_id: str) -> int:
        """Cancel all tasks for a specific sender."""
        tasks = await get_db_all(
            "SELECT task_id FROM planned_tasks WHERE sender_id = %s AND is_finished = 0",
            [sender_id],
        )
        
        count = 0
        for task_record in tasks:
            task_id = task_record["task_id"]
            if task_id in self._tasks:
                self._tasks[task_id].cancel()
                del self._tasks[task_id]
                count += 1
            
            # Mark as finished in DB
            await get_db_row(
                "UPDATE planned_tasks SET is_finished = 1 WHERE task_id = %s", 
                [task_id]
            )
        
        return count


# Global scheduler instance
_scheduler: Optional[TaskScheduler] = None


def get_scheduler() -> TaskScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
    return _scheduler
