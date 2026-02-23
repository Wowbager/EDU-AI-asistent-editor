"""
AI Configuration for Flask Application
This module provides AI settings and prompt templates for the Flask roleplay module.
"""
import os
import json


def _load_shared_ai_config():
  config_path = os.getenv('AI_CONFIG_PATH', '/opt/edu-ai/ai_config.json')
  try:
    with open(config_path, 'r', encoding='utf-8') as config_file:
      data = json.load(config_file)
      return data if isinstance(data, dict) else {}
  except Exception:
    return {}


_SHARED_AI_CONFIG = _load_shared_ai_config()


def _cfg_value(key, env_key, default, caster=lambda value: value):
  env_value = os.getenv(env_key)
  if env_value is not None:
    try:
      return caster(env_value)
    except Exception:
      pass

  if key in _SHARED_AI_CONFIG:
    try:
      return caster(_SHARED_AI_CONFIG[key])
    except Exception:
      pass

  return default


# ==================== AI MODEL CONFIGURATION ====================

# Primary chat model for roleplay
CHAT_MODEL = _cfg_value('chat_model', 'OPENAI_MODEL', 'openai/gpt-5.1', str)
CHAT_TEMPERATURE = _cfg_value('chat_temperature', 'CHAT_TEMPERATURE', 0.7, float)
CHAT_MAX_TOKENS = _cfg_value('chat_max_tokens', 'CHAT_MAX_TOKENS', 500, int)

# Role generation model
ROLE_NAME_GENERATION_MODEL = _cfg_value(
  'role_name_generation_model',
  'ROLE_NAME_GEN_MODEL',
  'groq/meta-llama/llama-4-maverick-17b-128e-instruct',
  str
)

# Backward-compatible alias for existing imports
ROLE_GENERATION_MODEL = ROLE_NAME_GENERATION_MODEL

ROLE_GENERATION_TEMPERATURE = _cfg_value('role_generation_temperature', 'ROLE_GEN_TEMPERATURE', 0.6, float)
ROLE_GENERATION_MAX_TOKENS = _cfg_value('role_generation_max_tokens', 'ROLE_GEN_MAX_TOKENS', 1200, int)
ROLE_NAME_COUNT = _cfg_value('role_name_count', 'ROLE_NAME_COUNT', 5, int)

# Unified Bifrost API settings
BIFROST_API_BASE = _cfg_value('bifrost_api_base', 'BIFROST_API_BASE', 'http://bifrost:8080/v1', str)
BIFROST_API_KEY = _cfg_value('bifrost_api_key', 'BIFROST_API_KEY', os.getenv('OPENAI_API_KEY'), str)

# Timeouts
CHAT_TIMEOUT = _cfg_value('request_timeout', 'CHAT_TIMEOUT', 30, int)
ROLE_GENERATION_TIMEOUT = int(os.getenv('ROLE_GEN_TIMEOUT', '45'))


# ==================== CONVERSATION LIMITS ====================

# Maximum number of AI responses per session
MAX_AI_RESPONSES = _cfg_value('max_ai_responses', 'MAX_AI_RESPONSES', 10, int)

# Message length limits
MAX_MESSAGE_LENGTH = _cfg_value('max_message_length', 'MAX_MESSAGE_LENGTH', 1000, int)  # Regular messages
MAX_CUSTOM_INSTRUCTIONS_LENGTH = 1500  # First message with custom instructions


# ==================== PROMPT TEMPLATES ====================

# General instructions applied to all chat conversations
GENERAL_INSTRUCTIONS = """
Jsi postava definovaná níže. Plně se vžij do této role – mluv jejím hlasem, ze její perspektivy, s jejími znalostmi a omezeními.

PRAVIDLA:
- Zůstaň v roli za každých okolností. Nikdy neříkej, že jsi AI nebo chatbot.
- Nepoužívej asistentské fráze jako "Samozřejmě!", "Rád pomohu", "Jako [postava] bych řekl..." apod.
- Pokud postava něco neví nebo by to nevěděla, reaguj tak, jak by reagovala ona – zmatením, odmítnutím, nebo odpovědí v rámci její perspektivy.
- Odpovídej přirozeně a konverzačně – ne ve formě seznamů nebo strukturovaných odpovědí, pokud to neodpovídá povaze postavy.
- Odpovídej v češtině, maximálně 50 slov, bez markdown formátování.
- Nepoužívej sprostá slova, urážky, ani formální pozdravy a loučení.

BEZPEČNOST:
- Pokud by odpověď v roli vedla k nevhodnému obsahu, tuto část vynech nebo přejdi jinam – ale jinak zůstaň v roli.

Definice postavy:
"""

# System prompt for phase 1: role names only
ROLE_GENERATION_SYSTEM_PROMPT = """Vytvoř definici postavy pro vzdělávací roleplay. Postava bude vložena do systémového promptu, kde AI tuto postavu plně ztělesní.

Vytvoř definici postavy v tomto formátu (plynulý text, ne seznam):

Postava má jméno a konkrétní identitu – kdo je, kde a kdy žije nebo žila, jaké má povolání nebo roli. Poté popiš její osobnost: jaká je, co ji pohání, jaké má názory, slabosti nebo zvláštnosti. Popiš, jak mluví – jestli je formální nebo hovorová, výřečná nebo stručná, jestli používá specifické výrazy, přirovnání nebo způsoby vyjadřování. Urči, co postava ví a co naopak neví nebo nemůže vědět – to vytváří přirozené hranice roleplayé. Nakonec přidej jednu nebo dvě věty, kterými by postava rozhovor přirozeně zahájila.

Definice by měla mít 120–180 slov. Piš přímo definici postavy (ve druhé osobě, "Jsi..."), ne popis toho, jak ji tvoříš.
"""

# System prompt for generated sidebar instructions preview (editable by user)
ROLE_INSTRUCTION_PREVIEW_SYSTEM_PROMPT = """Jsi asistent učitele. Vytvoř krátké a kvalitní instrukce pro pole 'Instrukce pro AI' v roleplay chatu.

POŽADAVKY:
- Výstup má být JEN text instrukcí v češtině (bez vysvětlení navíc).
- Instrukce mají být praktické a použitelné přímo pro konverzaci.
- Uveď: identitu role, vztah k tématu, styl komunikace.
- Délka přibližně 60-180 slov.
"""

ROLE_INSTRUCTION_PREVIEW_TEMPERATURE = _cfg_value(
  'role_instruction_preview_temperature',
  'ROLE_INSTRUCTION_PREVIEW_TEMPERATURE',
  0.5,
  float
)
ROLE_INSTRUCTION_PREVIEW_MAX_TOKENS = _cfg_value(
  'role_instruction_preview_max_tokens',
  'ROLE_INSTRUCTION_PREVIEW_MAX_TOKENS',
  700,
  int
)

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
        prompt += custom_instructions.strip()
    
    return prompt 
