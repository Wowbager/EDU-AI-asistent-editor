"""Domain models for course content."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Course:
    """Represents a course in the system."""
    
    id: int
    name: str
    description: Optional[str] = None
    position: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    @classmethod
    def from_db_row(cls, row: dict) -> "Course":
        """Create Course from database row."""
        return cls(
            id=row["id"],
            name=row.get("name", ""),
            description=row.get("description"),
            position=row.get("position", 0),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )


@dataclass
class Lecture:
    """Represents a lecture within a course."""
    
    id: int
    course_id: int
    name: str
    description: Optional[str] = None
    position: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    @classmethod
    def from_db_row(cls, row: dict) -> "Lecture":
        """Create Lecture from database row."""
        return cls(
            id=row["id"],
            course_id=row.get("course_id", 0),
            name=row.get("name", ""),
            description=row.get("description"),
            position=row.get("position", 0),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )


@dataclass
class LectureStep:
    """Represents a step within a lecture."""
    
    id: int
    lecture_id: int
    parent_id: int
    text: Optional[str] = None
    position: int = 0
    created_at: Optional[datetime] = None
    
    @classmethod
    def from_db_row(cls, row: dict) -> "LectureStep":
        """Create LectureStep from database row."""
        return cls(
            id=row["id"],
            lecture_id=row.get("lecture_id", 0),
            parent_id=row.get("parent_id", 0),
            text=row.get("text"),
            position=row.get("position", 0),
            created_at=row.get("created_at"),
        )


@dataclass
class LectureAnswer:
    """Represents an answer option for a lecture step."""
    
    id: int
    step_id: int
    parent_id: int
    text: Optional[str] = None
    position: int = 0
    is_correct: bool = False
    
    @classmethod
    def from_db_row(cls, row: dict) -> "LectureAnswer":
        """Create LectureAnswer from database row."""
        return cls(
            id=row["id"],
            step_id=row.get("step_id", 0),
            parent_id=row.get("parent_id", 0),
            text=row.get("text"),
            position=row.get("position", 0),
            is_correct=bool(row.get("is_correct", False)),
        )
