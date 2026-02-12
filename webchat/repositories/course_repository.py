"""Repository for course-related data access."""

from typing import List, Optional

from domain.course import Course, Lecture, LectureStep, LectureAnswer
from db_utils import get_db_all, get_db_row


class CourseRepository:
    """
    Repository pattern for course data access.
    
    Abstracts all SQL queries related to courses, lectures, steps, and answers,
    enabling the future agentic LLM flow to use clean data interfaces.
    """
    
    async def get_course_by_id(self, course_id: int) -> Optional[Course]:
        """Get a course by its ID."""
        row = await get_db_row(
            "SELECT * FROM courses WHERE id = %s LIMIT 1",
            [course_id]
        )
        return Course.from_db_row(row) if row else None
    
    async def get_course_description(self, course_id: int) -> Optional[str]:
        """Get course description for prompt generation."""
        row = await get_db_row(
            "SELECT description FROM courses WHERE id = %s",
            [course_id]
        )
        return row.get("description") if row else None
    
    async def get_course_name(self, course_id: int) -> Optional[str]:
        """Get course name."""
        row = await get_db_row(
            "SELECT name FROM courses WHERE id = %s",
            [course_id]
        )
        return row.get("name") if row else None
    
    async def get_lecture_by_id(self, lecture_id: int) -> Optional[Lecture]:
        """Get a lecture by its ID."""
        row = await get_db_row(
            "SELECT * FROM lectures WHERE id = %s LIMIT 1",
            [lecture_id]
        )
        return Lecture.from_db_row(row) if row else None
    
    async def get_first_lecture_in_course(self, course_id: int) -> Optional[Lecture]:
        """Get the first lecture in a course (by position)."""
        row = await get_db_row(
            "SELECT id FROM lectures WHERE course_id = %s ORDER BY position LIMIT 1",
            [course_id]
        )
        if row:
            return await self.get_lecture_by_id(row["id"])
        return None
    
    async def get_lectures_in_course(self, course_id: int) -> List[Lecture]:
        """Get all lectures in a course ordered by position."""
        rows = await get_db_all(
            "SELECT * FROM lectures WHERE course_id = %s ORDER BY position",
            [course_id]
        )
        return [Lecture.from_db_row(row) for row in rows]
    
    async def get_lecture_step_by_id(
        self, 
        lecture_id: int, 
        step_id: int,
        parent_id: int = 0
    ) -> Optional[LectureStep]:
        """Get a specific lecture step."""
        row = await get_db_row(
            "SELECT * FROM lectures_steps WHERE lecture_id = %s AND parent_id = %s AND id = %s LIMIT 1",
            [lecture_id, parent_id, step_id]
        )
        return LectureStep.from_db_row(row) if row else None
    
    async def get_root_steps(self, lecture_id: int) -> List[LectureStep]:
        """Get all root-level steps in a lecture (parent_id = 0)."""
        rows = await get_db_all(
            "SELECT * FROM lectures_steps WHERE parent_id = 0 AND lecture_id = %s ORDER BY position",
            [lecture_id]
        )
        return [LectureStep.from_db_row(row) for row in rows]
    
    async def get_child_steps(self, lecture_id: int, parent_id: int) -> List[LectureStep]:
        """Get child steps for a given parent step."""
        rows = await get_db_all(
            "SELECT * FROM lectures_steps WHERE lecture_id = %s AND parent_id = %s ORDER BY position",
            [lecture_id, parent_id]
        )
        return [LectureStep.from_db_row(row) for row in rows]
    
    async def get_answers_for_step(
        self, 
        step_id: int,
        parent_id: int = 0
    ) -> List[LectureAnswer]:
        """Get all answer options for a lecture step."""
        rows = await get_db_all(
            "SELECT * FROM lectures_answers WHERE step_id = %s AND parent_id = %s ORDER BY position",
            [step_id, parent_id]
        )
        return [LectureAnswer.from_db_row(row) for row in rows]
