"""Action execution interface shared by legacy and future implementations."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@dataclass
class ActionResult:
    """Container for action responses and state changes."""

    messages: List[Dict[str, Any]] = field(default_factory=list)
    slot_updates: Dict[str, Any] = field(default_factory=dict)
    followup_action: Optional[str] = None
    should_pause: bool = False
    
    def add_text_message(self, text: str) -> None:
        """Add a simple text message to the response."""
        self.messages.append({"type": "text", "text": text})
    
    def add_message_with_buttons(
        self, 
        text: str, 
        buttons: List[Dict[str, str]]
    ) -> None:
        """Add a message with button options."""
        self.messages.append({
            "type": "text",
            "text": text,
            "buttons": buttons
        })
    
    def set_slot(self, key: str, value: Any) -> None:
        """Add a slot update."""
        self.slot_updates[key] = value


@runtime_checkable
class ActionExecutor(Protocol):
    """Protocol for executing actions with a tracker and dispatcher."""
    
    async def run(
        self,
        dispatcher: Any,  # RasaDispatcher or DeepChatDispatcher
        tracker: Any,     # TrackerAdapter
        domain: Any = None
    ) -> List[Any]:
        """Execute the action and return events in Rasa format."""
        ...


class LegacyActionAdapter:
    """Adapter to wrap legacy Action classes into ActionExecutor protocol."""
    
    def __init__(self, action_instance: Any) -> None:
        """Initialize adapter with a legacy action instance."""
        self.action = action_instance
    
    async def run(
        self,
        dispatcher: Any,
        tracker: Any,
        domain: Any = None
    ) -> List[Any]:
        """Delegate to the wrapped action's run method."""
        return await self.action.run(dispatcher, tracker, domain)
    
    @property
    def name(self) -> str:
        """Get the action name from the wrapped instance."""
        return self.action.name()


class AgenticActionExecutor:
    """Placeholder for future agentic LLM flow implementation."""
    
    def __init__(self) -> None:
        raise NotImplementedError(
            "AgenticActionExecutor is a placeholder for future implementation. "
            "Use LegacyActionAdapter with existing actions.py classes."
        )
    
    async def run(
        self,
        dispatcher: Any,
        tracker: Any,
        domain: Any = None
    ) -> List[Any]:
        """Execute action using agentic LLM flow."""
        raise NotImplementedError("Future implementation required")
