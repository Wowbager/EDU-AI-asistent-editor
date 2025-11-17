from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class MessageContent(BaseModel):
    role: Literal["user", "assistant", "system", "tool", "function"] = "user"
    text: Optional[str] = None
    html: Optional[str] = None


class DeepChatRequest(BaseModel):
    messages: List[MessageContent] = Field(default_factory=list)

    def latest_user_text(self) -> Optional[str]:
        for message in reversed(self.messages):
            if message.role == "user" and message.text:
                return message.text.strip()
        return None


class SessionRequest(BaseModel):
    sender_id: Optional[str] = None
    custom_data: Optional[dict] = None


class SessionResponse(BaseModel):
    conversation_id: str


class DeepChatResponse(BaseModel):
    text: Optional[str] = None
    html: Optional[str] = None
    files: Optional[list] = None
    error: Optional[str] = None
    overwrite: Optional[bool] = None

    def as_payload(self):
        payload = {}
        if self.text:
            payload["text"] = self.text
        if self.html:
            payload["html"] = self.html
        if self.files:
            payload["files"] = self.files
        if self.error:
            payload["error"] = self.error
        if self.overwrite is not None:
            payload["overwrite"] = self.overwrite
        return payload
