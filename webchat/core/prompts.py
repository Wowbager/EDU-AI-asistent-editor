"""Prompt templates and AI configuration helpers."""

import os

class AIModelConfig:
    """Configuration for AI models used in the application."""

    CHAT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    CHAT_TEMPERATURE = float(os.getenv("CHAT_TEMPERATURE", "0.5"))
    CHAT_MAX_TOKENS = int(os.getenv("CHAT_MAX_TOKENS", "200"))
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    REQUEST_TIMEOUT = int(os.getenv("CHAT_TIMEOUT", "600"))
    MAX_MESSAGE_LENGTH = 1000

class SystemPrompts:
    """System-level prompts for AI behavior."""
    
    GENERAL_INSTRUCTIONS = """Odpovídejte v češtině s konkrétními fakty a detaily. Pro soutěž #NachytejAI buďte přirozeně informovaní, ale neověřujte každý fakt.

DŮLEŽITÉ ZÁSADY:
- Nepoužívejte markdown nebo formátování
- Odpovědi musí být stručné, maximálně 200 slov, moc se nerozepisuj
- Za žádných okolností nepoužívejte sprostá slova ani urážky
- Nepoužívejte fráze jako "jsem jazykový model" nebo "nemám přístup k internetu"
- Snažte se odpovídat jako daná osoba/role, vezměte v úvahu co zná a jak by měl odpovídat
- Odpovídáte do chatu, takže se vyhněte formálním pozdravům a rozloučením
- Odpovídejte krátce a přirozeně"""
    
    BRIEF_MODE = "system: Odpovídej stručně (max 100 slov) a jasně. Klidně používej emoji. "
    EDUCATIONAL_MODE = "system: Odpovídej stručně (max 250 slov) a jasně. Klidně používej emoji. "
    EXTENDED_MODE = ""  # No specific system prompt for extended mode

class ResponseTemplates:
    """Templates for common bot responses."""
    RESET_CONFIRMED = "Resetováno"
    GEMMA_ENABLED = "Nyní bude využíván model gemma3 12b. Pokud jej chcete vypnout je nutné resetovat konverzaci."
    MODEL_INFO = "Používám model: gpt-4o-mini (nebo gemma3 pokud je zapnutý)"
    
    ERROR_SERVICE_UNAVAILABLE = "Omlouvám se, část mozku mi právě nefunguje."
    ERROR_CANNOT_RESPOND = "Omlouvám se, momentálně nemohu odpovědět."
    ERROR_RATE_LIMIT = "Příliš mnoho požadavků, zkuste to prosím později."
    
    LIMIT_BRIEF = "Omlouvám se, ale už jsem už jsem toho řekl dost. Jdu spát."
    LIMIT_EDU = "Omlouvám se, ale už jsem už jsem toho řekl dost. Napište mi kontakt a lidský kolega se vám ozve."
    LIMIT_EXTENDED = "Už jsem toho řekl dost. Prosím zvažte napsání: reset nebo restart pro nový začátek."
    
    PAUSE_TILL_TEMPLATE = "edu.pause_till"  # Translation key
    
    @staticmethod
    def pause_message(eta_seconds: int) -> str:
        """Format pause message with ETA."""
        from actions import translate_text
        return f"{translate_text('edu.pause_till')} {eta_seconds} s"
    
    @staticmethod
    def educational_materials_link(query: str) -> str:
        """Generate link to educational materials search."""
        import urllib.parse
        encoded_query = urllib.parse.quote(query)
        return f"https://ema.rvp.cz/vyhledat-material?searchForm-type=wizard&searchForm-filter[search]={encoded_query}"

class PromptBuilder:
    """Helper class for building complex prompts."""
    
    @staticmethod
    def build_conversation_prompt(
        mode: str,
        course_description: str,
        chat_history: list
    ) -> list:
        """Build a conversation prompt from mode, description, and history."""
        description = course_description or ""
        description = description.replace("##GPT##", "").replace("##GPT_EDU##", "").replace("##GPT_MAX##", "")
        if mode == "1":
            system_prompt = SystemPrompts.BRIEF_MODE
        elif mode == "edu":
            system_prompt = SystemPrompts.EDUCATIONAL_MODE
        else:
            system_prompt = SystemPrompts.EXTENDED_MODE
        prompt = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": description},
        ] + chat_history + [
            {"role": "system", "content": system_prompt}
        ]
        return [msg for msg in prompt if msg.get("content") not in [None, ""]]
    
    @staticmethod
    def format_question_with_buttons(question_dict: dict) -> str:
        """Format a question with lettered options."""
        import string
        options = [
            f"{letter}: {option}"
            for letter, option in zip(string.ascii_lowercase, question_dict["options"])
        ]
        return f'{question_dict["text"]}\nmožnosti na výběr:\n{" | ".join(options)}'

def get_ai_config() -> dict:
    """Return AI configuration as a dictionary."""
    return {
        "model": AIModelConfig.CHAT_MODEL,
        "temperature": AIModelConfig.CHAT_TEMPERATURE,
        "max_tokens": AIModelConfig.CHAT_MAX_TOKENS,
        "timeout": AIModelConfig.REQUEST_TIMEOUT,
    }
