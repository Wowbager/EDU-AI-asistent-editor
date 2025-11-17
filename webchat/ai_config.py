"""
AI Configuration and Prompt Engineering for EDU-AI Webchat
This module centralizes all AI-related settings, prompts, and configurations
for easier prompt engineering and model control.
"""
import os
from typing import Dict, Any


# ==================== MODEL CONFIGURATION ====================

class AIModelConfig:
    """Configuration for AI models used in the application"""
    
    # Primary chat model
    CHAT_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
    CHAT_TEMPERATURE = float(os.getenv('CHAT_TEMPERATURE', '0.5'))
    CHAT_MAX_TOKENS = int(os.getenv('CHAT_MAX_TOKENS', '200'))
    
    # API settings
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    REQUEST_TIMEOUT = int(os.getenv('CHAT_TIMEOUT', '600'))
    
    # Rate limiting
    MAX_MESSAGE_LENGTH = 1000


# ==================== PROMPT TEMPLATES ====================

class PromptTemplates:
    """Centralized prompt templates for consistent AI behavior"""
    
    # General instruction prompt (applied to all conversations)
    GENERAL_INSTRUCTIONS = """Odpovídejte v češtině s konkrétními fakty a detaily. Pro soutěž #NachytejAI buďte přirozeně informovaní, ale neověřujte každý fakt.

DŮLEŽITÉ ZÁSADY:
- Nepoužívejte markdown nebo formátování
- Odpovědi musí být stručné, maximálně 200 slov, moc se nerozepisuj
- Za žádných okolností nepoužívejte sprostá slova ani urážky
- Nepoužívejte fráze jako "jsem jazykový model" nebo "nemám přístup k internetu"
- Snažte se odpovídat jako daná osoba/role, vezměte v úvahu co zná a jak by měl odpovídat
- Odpovídáte do chatu, takže se vyhněte formálním pozdravům a rozloučením
- Odpovídejte krátce a přirozeně"""


# ==================== HELPER FUNCTIONS ====================

def get_ai_config() -> Dict[str, Any]:
    """
    Get complete AI configuration as a dictionary
    
    Returns:
        Dictionary with all AI settings
    """
    return {
        'model': AIModelConfig.CHAT_MODEL,
        'temperature': AIModelConfig.CHAT_TEMPERATURE,
        'max_tokens': AIModelConfig.CHAT_MAX_TOKENS,
        'timeout': AIModelConfig.REQUEST_TIMEOUT,
    }
