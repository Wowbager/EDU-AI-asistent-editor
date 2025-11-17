"""Standalone ActionQuiz implementation for webchat beta handler."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Text

import requests


logger = logging.getLogger(__name__)


class Action:
    """Base action class without Rasa SDK dependency."""

    def name(self) -> Text:
        return self.__class__.__name__

    async def run(self, dispatcher, tracker, domain):  # noqa: ANN001, ARG002
        raise NotImplementedError("Override run() in subclasses")


# Slots are now handled via SlotCache in main.py
# These functions are kept for backward compatibility but should use the cache
async def get_slots(sender_id: str, slot_cache=None) -> Dict[str, Any]:
    """Retrieve slots from cache (or database if cache not available)."""
    if slot_cache:
        return await slot_cache.get_slots(sender_id)
    
    # Fallback to database (for backward compatibility)
    from db_utils import get_db_all
    tmp_query = await get_db_all(
        "SELECT * FROM events_slots WHERE sender_id = %s", [sender_id]
    )

    slots = {}
    if tmp_query is not None:
        for _slot in tmp_query:
            slots[_slot["key2find"]] = _slot["value"]

    return slots


async def set_slot(sender_id: str, key: str, value: Any, slot_cache=None) -> None:
    """Persist slot using cache (or database if cache not available)."""
    if slot_cache:
        await slot_cache.set_slot(sender_id, key, value)
        return
    
    # Fallback to database (for backward compatibility)
    # Use UPSERT to reduce queries
    from db_utils import get_db_row
    await get_db_row(
        """INSERT INTO events_slots (sender_id, key2find, value) 
           VALUES (%s, %s, %s)
           ON DUPLICATE KEY UPDATE value = %s""",
        [sender_id, key, value, value],
    )


def translate_text(key: str) -> str:
    """Translation stub - returns key as-is for beta."""
    return key


def get_utterances(
    events: List[Dict[str, Any]],
    sender_is_user: bool = True,
    message_position: int = 0,
    latest_question: Optional[Dict[str, Any]] = None,
) -> str:
    """Extract utterances from event history."""
    import string

    def format_question_with_buttons(question: Dict[str, Any]) -> str:
        options = [
            f"{letter}: {option}"
            for letter, option in zip(string.ascii_lowercase, question["options"])
        ]
        return f'{question["text"]}\nmožnosti na výběr:\n{" | ".join(options)}'

    sender = "user" if sender_is_user else "bot"

    if latest_question and sender == "bot":
        return format_question_with_buttons(latest_question)

    text = ""
    last_message_sender = ""
    found_right_message = False

    for e in reversed(events):
        if e["event"] in ["user", "bot"]:
            if (
                e["event"] == sender
                and (last_message_sender != sender or found_right_message)
                and e.get("text", "") != "EXTERNAL: EXTERNAL_reminder"
            ):
                if message_position != 0 and last_message_sender != sender:
                    message_position -= 1
                    last_message_sender = e["event"]
                    continue

                found_right_message = True
                message = e.get("text", "")
                if sender == "bot":
                    try:
                        if len(e.get("data", {}).get("buttons", [])) > 0:
                            question = {"text": message, "options": []}
                            for btn in e["data"]["buttons"]:
                                option_text = btn.get("title", "") or btn.get("payload", "")
                                question["options"].append(option_text)
                            if question["options"]:
                                message = format_question_with_buttons(question)
                    except Exception:  # noqa: S110
                        ...
                else:
                    text = f"{message}\n{text}"
            else:
                last_message_sender = e["event"]

    return text


def get_formated_chat_history(
    events: List[Dict[str, Any]], gpt_type: str = ""
) -> List[Dict[str, str]]:
    """Format event history for LLM chat API."""
    chat_history = []

    for e in events:
        if e["event"] in ["user", "bot"]:
            if e.get("text", "") not in ["EXTERNAL: EXTERNAL_reminder", "/get_started"]:
                if e["event"] == "user":
                    text = e.get("text", "")
                    if gpt_type == "1" and len(text) > 300:
                        text = text[:300]

                    chat_history.append({"role": "user", "content": text})
                    if "reset" in text.lower() or "restart" in text.lower():
                        chat_history = []
                else:
                    chat_history.append({"role": "assistant", "content": e.get("text", "")})

    return chat_history


class ActionQuiz(Action):
    """Simplified ActionQuiz for webchat beta - no Celery notifications."""

    def __init__(self) -> None:
        super().__init__()
        self.slot_cache = None

    def name(self) -> Text:
        return "action_quiz"

    async def run(self, dispatcher, tracker, domain):  # noqa: ANN001, ARG002, C901, PLR0912, PLR0915
        latest_message = tracker.latest_message.get("text", "")
        sender_id = tracker.current_state()["sender_id"]

        slots = await get_slots(sender_id, self.slot_cache)

        if latest_message == "/get_started" and slots.get("gpt_conversation", ""):
            if slots.get("conversation_started") == "1":
                return []
            await set_slot(sender_id, "conversation_started", "1", self.slot_cache)

        # Handle reset command
        if latest_message.lower() in ["reset", "restart"] and not slots.get("resetted"):
            dispatcher.utter_message(text=translate_text("Resetováno"))
            # Clear slots without Celery task cancellation
            return []

        # Handle gemma model switch
        if latest_message.lower() == "/use_gemma":
            dispatcher.utter_message(
                text="Nyní bude využíván model gemma3 12b. Pokud jej chcete vypnout je nutné resetovat konverzaci."
            )
            await set_slot(sender_id, "use_gemma", "1", self.slot_cache)
            return []

        # MFF Wiki query
        if "/w" in latest_message.lower() and len(latest_message) > 2 and not slots.get("command"):
            message2send = latest_message.split("/w")[1]
            await set_slot(sender_id, "command", "1", self.slot_cache)
            try:
                events = tracker.current_state()["events"]
                latest_bot_event = ""
                for e in tracker.events:
                    if e.get("event") == "bot" and e.get("text"):
                        latest_bot_event = e["text"]
                        break

                mffcuni = requests.post(
                    os.environ.get("MFF_URL", ""),
                    json={
                        "q": message2send,
                        "exact": 1,
                        "w": 1,
                        "last": latest_bot_event,
                        "site": tracker.get_latest_input_channel() or "webchat",
                        "course": 0,
                        "user_id": sender_id,
                    },
                    timeout=10,
                )

                mff_text = mffcuni.json().get("a", "")
                if mff_text:
                    dispatcher.utter_message(text=mff_text)
                return []
            except Exception as exc:
                logger.exception("MFF query failed: %s", exc)
                dispatcher.utter_message(text="Omlouvám se, část mozku mi právě nefunguje.")
                return []

        # Educational materials search
        if "/e" in latest_message.lower() and len(latest_message) > 2 and not slots.get("command"):
            import urllib.parse

            message2send = latest_message.split("/e")[1].strip()
            await set_slot(sender_id, "command", "1", self.slot_cache)
            dispatcher.utter_message(
                text=f"https://ema.rvp.cz/vyhledat-material?searchForm-type=wizard&searchForm-filter[search]={urllib.parse.quote(message2send)}"
            )
            return []

        # GPT conversation mode
        gpt_conversation = slots.get("gpt_conversation", "")
        if gpt_conversation in ["1", "edu", "max"] and latest_message != "/get_started":
            if latest_message.lower().strip() == "/model":
                dispatcher.utter_message(text="Model info not available in beta")
                return []

            gpt_conversation_counter = int(slots.get("gpt_conversation_counter", "0"))
            if gpt_conversation_counter > 15 and gpt_conversation == "1":
                dispatcher.utter_message(
                    text="Omlouvám se, ale už jsem toho řekl dost. Jdu spát."
                )
                return []

            # Increment conversation counter
            await set_slot(sender_id, "gpt_conversation_counter", str(gpt_conversation_counter + 1), self.slot_cache)

            # Build chat history for LLM
            events = tracker.current_state()["events"]
            chat_history = get_formated_chat_history(events, gpt_type=gpt_conversation)

            # TODO: Integrate with LLM service (langchain-openai already in requirements)
            dispatcher.utter_message(
                text="GPT conversation mode active - LLM integration pending for beta."
            )
            return []

        # Default fallback
        dispatcher.utter_message(text="Beta handler received your message.")
        return []
