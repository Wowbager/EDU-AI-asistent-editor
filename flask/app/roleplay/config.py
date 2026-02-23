"""
Roleplay module configuration constants.
Centralized configuration for the AI roleplay competition feature.
"""
import os

# Import AI-specific configuration from dedicated module
from .ai_prompts import (
    CHAT_MODEL,
    CHAT_TEMPERATURE,
    CHAT_MAX_TOKENS,
    CHAT_TIMEOUT,
    ROLE_GENERATION_MODEL,
    ROLE_GENERATION_TIMEOUT,
    ROLE_GENERATION_MAX_TOKENS,
    MAX_AI_RESPONSES,
    MAX_MESSAGE_LENGTH,
    MAX_CUSTOM_INSTRUCTIONS_LENGTH,
    GENERAL_INSTRUCTIONS,
    ROLE_GENERATION_SYSTEM_PROMPT
)

# Competition settings
COMPETITION_RUNNING = True  # Set to False to disable all competition features

# Team invitation safety limits
TEAM_INVITE_MAX_EMAILS_PER_REQUEST = int(os.getenv('TEAM_INVITE_MAX_EMAILS_PER_REQUEST', '5'))
TEAM_INVITE_MAX_PER_HOUR_PER_INVITER = int(os.getenv('TEAM_INVITE_MAX_PER_HOUR_PER_INVITER', '20'))
TEAM_INVITE_MAX_PER_DAY_PER_TEAM = int(os.getenv('TEAM_INVITE_MAX_PER_DAY_PER_TEAM', '50'))
TEAM_INVITE_RESEND_COOLDOWN_HOURS = int(os.getenv('TEAM_INVITE_RESEND_COOLDOWN_HOURS', '24'))
TEAM_INVITE_MAX_MESSAGE_LENGTH = int(os.getenv('TEAM_INVITE_MAX_MESSAGE_LENGTH', '500'))

# Redis settings
CHAT_HISTORY_TTL = 86400 * 14  # Chat history TTL in Redis (14 days)

# Content moderation
AI_CONTENT_ANALYSIS_MODEL = os.getenv('CONTENT_ANALYSIS_MODEL', 'llama-3.3-70b-versatile')
AI_CONTENT_ANALYSIS_TIMEOUT = int(os.getenv('CONTENT_ANALYSIS_TIMEOUT', '30'))

# Re-export for backward compatibility
ROLE_GEN_MAX_TOKENS = ROLE_GENERATION_MAX_TOKENS

