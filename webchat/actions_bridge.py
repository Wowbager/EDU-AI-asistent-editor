"""Adapters and dispatchers for running actions and formatting responses."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from actions import Action, ActionQuiz
from schemas import DeepChatResponse

logger = logging.getLogger(__name__)


class RasaDispatcher:
    """Dispatcher for Rasa webchat Socket.IO protocol."""
    
    def __init__(self, sio, sid: str) -> None:
        self.sio = sio
        self.sid = sid
        self.messages: List[Dict[str, Any]] = []
    
    def utter_message(
        self,
        text: Optional[str] = None,
        buttons: Optional[List[Dict[str, Any]]] = None,
        image: Optional[str] = None,
        attachment: Optional[Dict[str, Any]] = None,
        button_type: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Queue a bot message following Rasa webchat protocol."""
        timestamp = int(time.time() * 1000)
        
        if text or buttons:
            message: Dict[str, Any] = {}
            if text and text.strip():
                message["text"] = text

            if buttons:
                message["quick_replies"] = [
                    {
                        "content_type": "text",
                        "title": btn.get("title", ""),
                        "payload": btn.get("payload", btn.get("title", "")),
                    }
                    for btn in buttons
                ]
                if "text" not in message:
                    message["text"] = ""

            if "text" in message or "quick_replies" in message:
                self.messages.append(message)

        if image:
            self.messages.append(
                {
                    "attachment": {
                        "type": "image",
                        "payload": {"src": image},
                    }
                }
            )

        if attachment:
            self.messages.append({"attachment": attachment})
    
    def utter_custom_json(self, message: Dict[str, Any]) -> None:
        """Send custom JSON data."""
        self.messages.append({"data": message})
    
    async def send_all(self) -> None:
        """Send all queued messages to client with small delays."""
        import asyncio
        for i, msg in enumerate(self.messages):
            await self.sio.emit("bot_uttered", msg, room=self.sid)
            if i < len(self.messages) - 1:
                await asyncio.sleep(0.3)
        self.messages.clear()


class DeepChatDispatcher:
    """Collects bot utterances and converts them to Deep Chat payloads."""

    def __init__(self) -> None:
        self.messages: List[DeepChatResponse] = []

    def utter_message(
        self,
        text: Optional[str] = None,
        buttons: Optional[List[Dict[str, Any]]] = None,
        image: Optional[str] = None,
        attachment: Optional[Dict[str, Any]] = None,
        button_type: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        if text or buttons:
            html_content = ""
            if text:
                escaped_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html_content = escaped_text.replace("\n", "<br>")
            if buttons:
                button_html = '<div style="margin-top: 10px; display: flex; flex-direction: column; gap: 8px;">'
                for button in buttons:
                    title = button.get("title", "")
                    payload = button.get("payload", title)
                    button_html += f'''
                    <button 
                        onclick="document.querySelector('deep-chat').submitUserMessage('{payload}')"
                        style="padding: 10px 15px; background: #007bff; color: white; border: none; border-radius: 5px; cursor: pointer; text-align: left; font-size: 14px; transition: background 0.2s;"
                        onmouseover="this.style.background='#0056b3'"
                        onmouseout="this.style.background='#007bff'"
                    >
                        {title}
                    </button>
                    '''
                button_html += '</div>'
                html_content = f"{html_content}{button_html}" if html_content else button_html
            
            if html_content:
                self.messages.append(DeepChatResponse(html=html_content))

        if image:
            self.messages.append(
                DeepChatResponse(files=[{"name": image.split("/")[-1], "src": image}])
            )

        if attachment:
            self.messages.append(DeepChatResponse(text=str(attachment)))

    def utter_custom_json(self, message: Dict[str, Any]) -> None:
        self.messages.append(DeepChatResponse(text=message.get("text") or str(message)))


class TrackerAdapter:
    def __init__(
        self,
        sender_id: str,
        events: List[Dict[str, Any]],
        latest_input_channel: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.sender_id = sender_id
        self._events = events
        self._latest_input_channel = latest_input_channel
        self._metadata = metadata or {}
        self._latest_message = self._find_latest_user_event()

    def _find_latest_user_event(self) -> Dict[str, Any]:
        for event in reversed(self._events):
            if event.get("event") == "user":
                return {"text": event.get("text", ""), "metadata": event.get("metadata", {})}
        return {"text": "", "metadata": {}}

    @property
    def latest_message(self) -> Dict[str, Any]:
        return self._latest_message

    @property
    def events(self) -> List[Dict[str, Any]]:
        return self._events

    def current_state(self) -> Dict[str, Any]:
        return {
            "sender_id": self.sender_id,
            "events": self._events,
            "latest_input_channel": self._latest_input_channel,
            "metadata": self._metadata,
        }

    def get_latest_input_channel(self) -> Optional[str]:
        return self._latest_input_channel


class ActionBridge:
    """Executes selected Rasa actions with patched tracker/dispatcher."""

    def __init__(self, slot_cache=None) -> None:
        self._actions: Dict[str, Action] = {"action_quiz": ActionQuiz()}
        self.slot_cache = slot_cache

    def set_slot_cache(self, slot_cache) -> None:
        self.slot_cache = slot_cache

    async def run(
        self, action_name: str, tracker: TrackerAdapter, dispatcher
    ) -> Optional[List[Any]]:
        """Run action and return events (FollowupAction, SlotSet, etc.)."""
        action = self._actions.get(action_name)
        if not action:
            raise ValueError(f"Unknown action {action_name}")

        try:
            if hasattr(action, "slot_cache"):
                action.slot_cache = self.slot_cache
            events = await action.run(dispatcher, tracker, {})
            return events if events else []
        except Exception as exc:  # noqa: BLE001
            logger.exception("Action %s failed", action_name)
            if hasattr(dispatcher, "utter_message"):
                dispatcher.utter_message(text="Došlo k neočekávané chybě.")
            return []
