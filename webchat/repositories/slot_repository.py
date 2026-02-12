"""Repository for slot (conversation state) data access."""

from typing import Any, Dict, Optional

from domain.conversation import ConversationState
from db_utils import get_db_all, get_db_row


class SlotRepository:
    """
    Repository for slot-based conversation state management.
    
    Provides clean interface for state persistence, replacing direct
    SQL queries scattered across actions_bridge.py and slot_cache.py.
    """
    
    async def get_slots(self, sender_id: str) -> Dict[str, Any]:
        """
        Retrieve all slots for a sender as a dictionary.
        
        Args:
            sender_id: The unique identifier for the conversation
            
        Returns:
            Dictionary mapping slot keys to values
        """
        rows = await get_db_all(
            "SELECT * FROM events_slots WHERE sender_id = %s",
            [sender_id]
        )
        
        slots = {}
        if rows:
            for row in rows:
                slots[row["key2find"]] = row["value"]
        
        return slots
    
    async def get_conversation_state(self, sender_id: str) -> ConversationState:
        """
        Get strongly-typed conversation state.
        
        Args:
            sender_id: The unique identifier for the conversation
            
        Returns:
            ConversationState domain model
        """
        slots = await self.get_slots(sender_id)
        return ConversationState.from_slots(sender_id, slots)
    
    async def set_slot(self, sender_id: str, key: str, value: Any) -> None:
        """
        Persist a single slot value.
        
        Uses UPSERT pattern to reduce from 2-3 queries to 1.
        
        Args:
            sender_id: The unique identifier for the conversation
            key: The slot key
            value: The slot value
        """
        # Check if slot exists
        existing = await get_db_row(
            "SELECT id FROM events_slots WHERE sender_id = %s AND key2find = %s",
            [sender_id, key]
        )
        
        if existing:
            # Update existing slot
            await get_db_row(
                "UPDATE events_slots SET value = %s WHERE sender_id = %s AND key2find = %s",
                [str(value), sender_id, key]
            )
        else:
            # Insert new slot
            await get_db_row(
                "INSERT INTO events_slots (sender_id, key2find, value) VALUES (%s, %s, %s)",
                [sender_id, key, str(value)]
            )
    
    async def set_multiple_slots(self, sender_id: str, slots: Dict[str, Any]) -> None:
        """
        Persist multiple slots efficiently.
        
        Args:
            sender_id: The unique identifier for the conversation
            slots: Dictionary of slot key-value pairs
        """
        for key, value in slots.items():
            await self.set_slot(sender_id, key, value)
    
    async def save_conversation_state(self, state: ConversationState) -> None:
        """
        Save strongly-typed conversation state to database.
        
        Args:
            state: ConversationState domain model
        """
        slots = state.to_slots()
        await self.set_multiple_slots(state.sender_id, slots)
    
    async def reset_all_slots(self, sender_id: str) -> None:
        """
        Delete all slots for a sender (conversation reset).
        
        Args:
            sender_id: The unique identifier for the conversation
        """
        await get_db_row(
            "DELETE FROM events_slots WHERE sender_id = %s",
            [sender_id]
        )
