"""Domain models for quiz functionality."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class QuizAnswer:
    """Represents a single answer option in a quiz question."""
    
    text: str
    is_correct: bool = False
    letter: Optional[str] = None  # a, b, c, d, etc.


@dataclass
class QuizQuestion:
    """Represents a quiz question with multiple answers."""
    
    text: str
    options: List[QuizAnswer] = field(default_factory=list)
    
    def format_with_buttons(self) -> str:
        """Format question with lettered options (a, b, c, d)."""
        import string
        
        option_texts = [
            f"{letter}: {answer.text}"
            for letter, answer in zip(string.ascii_lowercase, self.options)
        ]
        return f'{self.text}\nmožnosti na výběr:\n{" | ".join(option_texts)}'
    
    def get_correct_answer(self) -> Optional[QuizAnswer]:
        """Get the first correct answer."""
        for answer in self.options:
            if answer.is_correct:
                return answer
        return None


@dataclass
class Quiz:
    """Represents a complete quiz session."""
    
    course_id: Optional[int] = None
    lecture_id: Optional[int] = None
    questions: List[QuizQuestion] = field(default_factory=list)
    current_question_index: int = 0
    score: int = 0
    
    @property
    def current_question(self) -> Optional[QuizQuestion]:
        """Get the current question being asked."""
        if 0 <= self.current_question_index < len(self.questions):
            return self.questions[self.current_question_index]
        return None
    
    @property
    def is_complete(self) -> bool:
        """Check if all questions have been answered."""
        return self.current_question_index >= len(self.questions)
    
    def advance(self) -> None:
        """Move to the next question."""
        self.current_question_index += 1
