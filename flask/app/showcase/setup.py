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
    "easy": ShowcasePersona.empty(),
    "medium": ShowcasePersona.empty(),
    "hard": ShowcasePersona.empty(),
}

# CONSTANTS
MAX_AI_RESPONSES = 10
SHOWCASE_ACTIVE = True