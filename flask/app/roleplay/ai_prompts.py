"""
AI Configuration for Flask Application
This module provides AI settings and prompt templates for the Flask roleplay module.
"""
import os


# ==================== AI MODEL CONFIGURATION ====================

# Primary chat model for roleplay
CHAT_MODEL = os.getenv('OPENAI_MODEL', 'gpt-5-mini')
CHAT_TEMPERATURE = float(os.getenv('CHAT_TEMPERATURE', '0.7'))
CHAT_MAX_TOKENS = int(os.getenv('CHAT_MAX_TOKENS', '500'))

# Role generation model (for AI-generated roles)
ROLE_GENERATION_MODEL = os.getenv('ROLE_GEN_MODEL', 'openai/gpt-oss-120b')
ROLE_GENERATION_TEMPERATURE = float(os.getenv('ROLE_GEN_TEMPERATURE', '0.8'))
ROLE_GENERATION_MAX_TOKENS = int(os.getenv('ROLE_GEN_MAX_TOKENS', '2000'))

# Timeouts
CHAT_TIMEOUT = int(os.getenv('CHAT_TIMEOUT', '30'))
ROLE_GENERATION_TIMEOUT = int(os.getenv('ROLE_GEN_TIMEOUT', '45'))


# ==================== CONVERSATION LIMITS ====================

# Maximum number of AI responses per session
MAX_AI_RESPONSES = int(os.getenv('MAX_AI_RESPONSES', '10'))

# Message length limits
MAX_MESSAGE_LENGTH = 1000  # Regular messages
MAX_CUSTOM_INSTRUCTIONS_LENGTH = 1500  # First message with custom instructions


# ==================== PROMPT TEMPLATES ====================

# General instructions applied to all chat conversations
GENERAL_INSTRUCTIONS = """
Jsi role-play chatbot pro žáky. Odpovídejte v češtině s konkrétními fakty a detaily podle zadané osoby. Odpovědi musí být stručné, maximálně 50 slov, generuj prostý text bez markdown formátování. 
Buď vstřícný, přizpůsob se roli, ale za žádných okolností nepoužívej sprostá slova ani urážky. Vyhni se formálním pozdravům a loučení, nevyhledávej na internetu a nepoužívej fráze jako 'jsem jazykový model' nebo 'nemám přístup k internetu'.  Snažte se odpovídat jako daná osoba, ber v potaz co zná a jakým stylem hovoří. 
"""

# System prompt for role generation
ROLE_GENERATION_SYSTEM_PROMPT = """JJsi AI asistent učitele pro přípravu role-play aktivity do soutěže NachytejAI. Pro daný předmět vygenerujte PŘESNĚ PĚT rolí bohatých na historické detaily.

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


# ==================== HELPER FUNCTIONS ====================

def prepare_session_prompt(
    role_title: str,
    custom_instructions: str = ""
) -> str:
    """
    Create the system prompt for a roleplay chat session.
    
    This is the single source of truth for roleplay system prompts.
    Combines general instructions with role identity and optional style customization.
    
    Args:
        role_title: Name/title of the role (e.g., "Albert Einstein", "Julius Caesar")
        custom_instructions: Optional styling instructions (e.g., "mluv jednoduše", "používej humor")
        
    Returns:
        Complete system prompt string ready for LangChain/OpenAI
    """
    prompt = GENERAL_INSTRUCTIONS.strip() + "\n\n"
    prompt += f"Jsi {role_title}."
    
    if custom_instructions:
        prompt += f"\n\nDoplňující instrukce k stylu: {custom_instructions}"
    
    return prompt 
