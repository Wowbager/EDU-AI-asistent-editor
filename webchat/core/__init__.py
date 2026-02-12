"""Core interfaces and protocols for the webchat service."""

from .action_interface import ActionExecutor, ActionResult

__all__ = [
    "ActionExecutor",
    "ActionResult",
]
