"""Repository layer for data access abstraction."""

from .course_repository import CourseRepository
from .slot_repository import SlotRepository
from .task_repository import TaskRepository

__all__ = [
    "CourseRepository",
    "SlotRepository",
    "TaskRepository",
]
