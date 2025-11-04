"""
Roleplay module configuration constants.
Centralized configuration for the AI roleplay competition feature.
"""

# Competition settings
COMPETITION_RUNNING = True  # Set to False to disable all competition features
MAX_AI_RESPONSES = 10  # Maximum number of AI responses per chat session
MAX_MESSAGE_LENGTH = 1000  # Maximum user message length in characters
MAX_CUSTOM_INSTRUCTIONS_LENGTH = 1500  # Maximum length for custom role instructions

# AI Model settings
CHAT_MODEL = "openai/gpt-oss-120b"  # Groq model for regular chat responses
ROLE_GENERATION_MODEL = "openai/gpt-oss-120b"  # Groq model for generating role suggestions
ROLE_GENERATION_TIMEOUT = 600  # Timeout for role generation API calls (seconds)
CHAT_TIMEOUT = 600  # Timeout for chat API calls (seconds)

# AI generation parameters
CHAT_TEMPERATURE = 1  # Temperature for chat responses
CHAT_MAX_TOKENS = 400  # Max tokens for chat responses
ROLE_GEN_MAX_TOKENS = 1200  # Max tokens for role generation

# Redis settings
CHAT_HISTORY_TTL = 86400 * 14  # Chat history TTL in Redis (14 days)

# Content moderation
AI_CONTENT_ANALYSIS_MODEL = "llama-3.3-70b-versatile"  # Groq model for flagged content analysis
AI_CONTENT_ANALYSIS_TIMEOUT = 30  # Timeout for content analysis (seconds)
