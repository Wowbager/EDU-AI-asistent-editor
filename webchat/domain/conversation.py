"""Domain models for conversation state management."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ChatSession:
    """Represents a chat session with metadata."""
    
    sender_id: str
    conversation_id: str
    latest_input_channel: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class ConversationState:
    """
    Strongly-typed conversation state replacing string-based slot manipulation.
    
    This model encapsulates all conversation context, making it easier to:
    - Replace actions.py with agentic LLM flow
    - Test conversation logic in isolation
    - Track state changes explicitly
    """
    
    sender_id: str
    
    # Course navigation
    current_course: Optional[str] = None
    current_lecture: Optional[str] = None
    current_step: Optional[str] = None
    
    # Conversation flow
    being_asked: Optional[str] = None
    conversation_started: bool = False
    gpt_conversation: Optional[str] = None  # "1", "edu", "max", or None
    gpt_conversation_counter: int = 0
    use_gemma: bool = False
    
    # Quiz state
    lecture_question: Optional[str] = None
    number_tries: int = 0
    latest_message2check: Optional[str] = None
    
    # Task management
    delayed_answers: List[Dict[str, Any]] = field(default_factory=list)
    
    # Control flags
    resetted: bool = False
    command: Optional[str] = None
    
    # Additional context
    custom_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_slots(self) -> Dict[str, Any]:
        """Convert domain model to legacy slot format for backward compatibility."""
        return {
            "current_course": self.current_course or "",
            "current_lecture": self.current_lecture or "",
            "current_step": self.current_step or "",
            "being_asked": self.being_asked or "",
            "conversation_started": "1" if self.conversation_started else "",
            "gpt_conversation": self.gpt_conversation or "",
            "gpt_conversation_counter": str(self.gpt_conversation_counter),
            "use_gemma": "1" if self.use_gemma else "0",
            "lecture_question": self.lecture_question or "",
            "number_tries": str(self.number_tries),
            "latest_message2check": self.latest_message2check or "",
            "delayed_answers": self._serialize_delayed_answers(),
            "resetted": "1" if self.resetted else "",
            "command": self.command or "",
        }
    
    def _serialize_delayed_answers(self) -> str:
        """Serialize delayed answers to JSON string."""
        import json
        return json.dumps(self.delayed_answers) if self.delayed_answers else ""
    
    @classmethod
    def from_slots(cls, sender_id: str, slots: Dict[str, Any]) -> "ConversationState":
        """Create domain model from legacy slot format."""
        import json
        
        delayed_answers_str = slots.get("delayed_answers", "")
        delayed_answers = []
        if delayed_answers_str:
            try:
                delayed_answers = json.loads(delayed_answers_str)
            except (json.JSONDecodeError, TypeError):
                pass
        
        return cls(
            sender_id=sender_id,
            current_course=slots.get("current_course") or None,
            current_lecture=slots.get("current_lecture") or None,
            current_step=slots.get("current_step") or None,
            being_asked=slots.get("being_asked") or None,
            conversation_started=slots.get("conversation_started") == "1",
            gpt_conversation=slots.get("gpt_conversation") or None,
            gpt_conversation_counter=int(slots.get("gpt_conversation_counter", "0") or "0"),
            use_gemma=slots.get("use_gemma") == "1",
            lecture_question=slots.get("lecture_question") or None,
            number_tries=int(slots.get("number_tries", "0") or "0"),
            latest_message2check=slots.get("latest_message2check") or None,
            delayed_answers=delayed_answers,
            resetted=slots.get("resetted") == "1",
            command=slots.get("command") or None,
        )
