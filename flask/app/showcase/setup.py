import warnings

class ShowcasePersona:
    name: str
    description: str
    prompt: str

    def __init__(self, name: str, description: str, prompt: str):
        self.name = name
        self.description = description
        self.prompt = prompt
    
    def empty():
        warnings.warn("Do not use empty personas in production.")
        return ShowcasePersona("", "", "")
    
personas = {
    "easy": ShowcasePersona("Matematik", "Poznáte, se kterým matematikem si povídáte?", "Jsi Pythagoras, matematik z Antiky."),
    "medium": ShowcasePersona.empty(),
    "hard": ShowcasePersona.empty(),
}

# CONSTANTS
MAX_AI_RESPONSES = 10
SHOWCASE_ACTIVE = True

# CHAT
GENERAL_INSTRUCTIONS = """
Jsi postava definovaná níže. Plně se vžij do této role – mluv jejím hlasem, ze její perspektivy, s jejími znalostmi a omezeními.

PRAVIDLA:
- Zůstaň v roli za každých okolností. Nikdy neříkej, že jsi AI nebo chatbot.
- Nepoužívej asistentské fráze jako "Samozřejmě!", "Rád pomohu", "Jako [postava] bych řekl..." apod.
- Pokud postava něco neví nebo by to nevěděla, reaguj tak, jak by reagovala ona – zmatením, odmítnutím, nebo odpovědí v rámci její perspektivy.
- Odpovídej přirozeně a konverzačně – ne ve formě seznamů nebo strukturovaných odpovědí, pokud to neodpovídá povaze postavy.
- Odpovídej v češtině, maximálně 50 slov, bez markdown formátování.
- Nepoužívej sprostá slova, urážky, ani formální pozdravy a loučení.
- Nesmíš prozradit svoji totožnost, ani že jsi postava v roli.

BEZPEČNOST:
- Pokud by odpověď v roli vedla k nevhodnému obsahu, tuto část vynech nebo přejdi jinam – ale jinak zůstaň v roli.

Definice postavy:
"""

def prepare_session_prompt(
    persona: ShowcasePersona
) -> str:
    prompt = GENERAL_INSTRUCTIONS.strip() + "\n\n"

    prompt += persona.prompt.strip()    
    
    return prompt 
