"""
AI Configuration and Prompt Engineering for EDU-AI Chat
This module centralizes all AI-related settings, prompts, and configurations
for easier prompt engineering and model control.
"""
import os
from typing import Dict, Any


# ==================== MODEL CONFIGURATION ====================

class AIModelConfig:
    """Configuration for AI models used in the application"""
    
    # Primary chat model
    CHAT_MODEL = os.getenv('OPENAI_MODEL', 'gpt-5.1')
    CHAT_TEMPERATURE = float(os.getenv('CHAT_TEMPERATURE', '0.7'))
    CHAT_MAX_TOKENS = int(os.getenv('CHAT_MAX_TOKENS', '500'))
    
    # Role generation model (can be different for cost optimization)
    ROLE_GEN_MODEL = os.getenv('ROLE_GEN_MODEL', 'openai/gpt-oss-120b')
    ROLE_GEN_TEMPERATURE = float(os.getenv('ROLE_GEN_TEMPERATURE', '0.8'))
    ROLE_GEN_MAX_TOKENS = int(os.getenv('ROLE_GEN_MAX_TOKENS', '2000'))
    
    # API settings
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    REQUEST_TIMEOUT = int(os.getenv('CHAT_TIMEOUT', '30'))
    
    # Rate limiting
    MAX_ASSISTANT_RESPONSES = int(os.getenv('MAX_AI_RESPONSES', '10'))
    MAX_MESSAGE_LENGTH = 1000
    MAX_FIRST_MESSAGE_LENGTH = 500


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

    # System prompt template for roleplay
    @staticmethod
    def create_roleplay_system_prompt(
        role_title: str,
        role_description: str,
        subject: str = ""
    ) -> str:
        """
        Create a system prompt for roleplay scenarios
        
        Args:
            role_title: Name/title of the role (e.g., "Albert Einstein")
            role_description: Brief description of the role
            subject: Optional subject/domain context
            
        Returns:
            Formatted system prompt
        """
        base_prompt = f"Jsi {role_title}."
        
        if role_description:
            base_prompt += f" {role_description}"
        
        if subject:
            base_prompt += f" Jsi expert v oblasti '{subject}'."
        
        return base_prompt
    
    # First message template for starting conversations
    @staticmethod
    def create_first_user_message(
        role_title: str,
        role_description: str,
        subject: str = "",
        custom_instructions: str = ""
    ) -> str:
        """
        Create the first user message to initialize the conversation
        
        Args:
            role_title: Name/title of the role
            role_description: Brief description
            subject: Subject/domain context
            custom_instructions: Optional custom user instructions
            
        Returns:
            Formatted first message
        """
        if custom_instructions:
            # User provided custom instructions
            return custom_instructions
        
        # Default first message
        message = f"Představ se."
        
        if subject:
            message += f" Stručně vysvětli svou specializaci v oblasti '{subject}'."
        
        message += " Řekni, jakým stylem budeš komunikovat. Poté vyčkej na mé pokyny."
        
        return message
    
    # Role generation prompt (for AI to generate roles)
    ROLE_GENERATION_PROMPT = """Jsi AI asistent učitele pro přípravu role-play aktivity do soutěže NachytejAI. Pro daný předmět vygenerujte PŘESNĚ PĚT rolí bohatých na historické detaily.

KRITICKÉ: Odpověď MUSÍ být POUZE platný JSON. Žádný text před ani po JSON!

PRAVIDLA:
• Role nesmí být urážlivé nebo nevhodné.
• Pro neplatné předměty navrhni možné související osoby/role.
• Předmět může být hovorový (čeština, matika, děják, zemák).
• Odpověď: JSON pole s pěti objekty:
[
  {"id": "unikátni_id", "title": "Název role", "brief": "Popis role (2-3 věty)"}
]
• Jazyk: Čeština.
• Role: Historicky reálné osobnosti, profese, předměty, fyzikální děje nebo koncepty.
• Soutěž: Role souvisí se školními fakty.

PŘÍKLAD pro 'Starověký Řím':
[
  {"id": "julius_caesar", "title": "Julius Caesar", "brief": "Římský vojevůdce, dobyl Galii, zavražděn v Senátu."},
  {"id": "rimsky_legionar", "title": "Římský legionář", "brief": "Veterán Caesarovy legie, bojoval u Alessie."},
  {"id": "marcus_aurelius", "title": "Marcus Aurelius", "brief": "Římský císař filozof, vedl války s Markomany."},
  {"id": "cicero", "title": "Cicero", "brief": "Římský řečník, odhalil Catilinu spiknutí."},
  {"id": "spartacus", "title": "Spartacus", "brief": "Gladiátor, vedl povstání otroků proti Římu."}
]"""


# ==================== RESPONSE VALIDATION ====================

class ResponseValidator:
    """Validate and sanitize AI responses"""
    
    @staticmethod
    def validate_response(response: str) -> tuple[bool, str]:
        """
        Validate AI response for inappropriate content
        
        Args:
            response: AI generated response
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not response or not response.strip():
            return False, "Prázdná odpověď od AI"
        
        # Check for forbidden phrases (AI revealing its nature)
        forbidden_phrases = [
            "jsem AI",
            "jsem umělá inteligence",
            "jsem jazykový model",
            "nemám tělo",
            "nemohu fyzicky"
        ]
        
        response_lower = response.lower()
        for phrase in forbidden_phrases:
            if phrase in response_lower:
                return False, f"Odpověď obsahuje zakázanou frázi: {phrase}"
        
        return True, ""
    
    @staticmethod
    def sanitize_response(response: str) -> str:
        """
        Sanitize AI response (remove unwanted formatting, etc.)
        
        Args:
            response: Raw AI response
            
        Returns:
            Sanitized response
        """
        # Remove markdown code blocks if present
        if response.startswith("```") and response.endswith("```"):
            lines = response.split('\n')
            response = '\n'.join(lines[1:-1])
        
        # Remove excessive whitespace
        response = response.strip()
        
        return response


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
        'max_responses': AIModelConfig.MAX_ASSISTANT_RESPONSES
    }


def create_session_prompts(
    role_title: str,
    role_description: str,
    subject: str = "",
    custom_instructions: str = ""
) -> Dict[str, str]:
    """
    Create all prompts needed for a chat session
    
    Args:
        role_title: Title of the role
        role_description: Brief description
        subject: Subject/domain
        custom_instructions: Optional custom instructions
        
    Returns:
        Dictionary with 'system_prompt', 'general_info', and 'first_message'
    """
    return {
        'system_prompt': PromptTemplates.create_roleplay_system_prompt(
            role_title, role_description, subject
        ),
        'general_info': PromptTemplates.GENERAL_INSTRUCTIONS,
        'first_message': PromptTemplates.create_first_user_message(
            role_title, role_description, subject, custom_instructions
        )
    }
