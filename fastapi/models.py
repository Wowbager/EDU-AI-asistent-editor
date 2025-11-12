"""Minimal SQLAlchemy models for FastAPI - mirrors Flask models"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from .database import Base


class ChatSession(Base):
    """Chat session model - mirrors Flask's ChatSession"""
    __tablename__ = "chat_sessions"
    
    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role_id = Column(String(64))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ChatMessage(Base):
    """Individual chat message model - mirrors Flask's ChatMessage"""
    __tablename__ = "chat_messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # 'system', 'user', or 'assistant'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, server_default=func.now())
    message_index = Column(Integer, nullable=False)


class FlaggedResponse(Base):
    """Flagged response model - mirrors Flask's FlaggedResponse (for reference only)"""
    __tablename__ = "flagged_responses"
    
    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id"), nullable=False)
    content = Column(Text)
    message_index = Column(Integer, nullable=True)
    summary = Column(Text, nullable=True)
    timestamp = Column(DateTime, server_default=func.now())
    is_public = Column(Boolean, default=False)
