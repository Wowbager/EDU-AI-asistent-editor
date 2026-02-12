"""Constants for slot keys, actions, and special messages."""

class SlotKeys:
    """Slot key constants for conversation state management."""

    CURRENT_COURSE = "current_course"
    CURRENT_LECTURE = "current_lecture"
    CURRENT_STEP = "current_step"

    BEING_ASKED = "being_asked"
    CONVERSATION_STARTED = "conversation_started"
    GPT_CONVERSATION = "gpt_conversation"
    GPT_CONVERSATION_COUNTER = "gpt_conversation_counter"
    USE_GEMMA = "use_gemma"

    LECTURE_QUESTION = "lecture_question"
    NUMBER_TRIES = "number_tries"
    LATEST_MESSAGE_TO_CHECK = "latest_message2check"

    DELAYED_ANSWERS = "delayed_answers"

    RESETTED = "resetted"
    COMMAND = "command"

    NLU_OPENAI = "NLU_OpenAI2"

class ConversationMode:
    """Constants for GPT conversation modes."""
    BRIEF = "1"          # Short responses (max 100 words)
    EDUCATIONAL = "edu"  # Medium responses (max 250 words)
    EXTENDED = "max"     # Extended conversation

class SpecialMessages:
    """Special message constants."""
    
    GET_STARTED = "/get_started"
    EXTERNAL_REMINDER = "EXTERNAL: EXTERNAL_reminder"
    RESET = "reset"
    RESTART = "restart"
    USE_GEMMA = "/use_gemma"
    MODEL_INFO = "/model"
    
    PREFIX_WIKI = "/w"
    PREFIX_EDUCATIONAL_MATERIALS = "/e"

class ActionNames:
    """Action name constants."""
    ACTION_QUIZ = "action_quiz"
    ACTION_LISTEN = "action_listen"

class EventTypes:
    """Event type constants for tracker events."""
    USER = "user"
    BOT = "bot"
    SLOT_SET = "slot"
    FOLLOWUP = "followup"

class ResponseLimits:
    """Limits for conversation and responses."""
    MAX_CONVERSATION_BRIEF = 15      # Max messages in brief mode
    MAX_CONVERSATION_EDU = 25        # Max messages in educational mode
    MAX_CONVERSATION_EXTENDED = 25   # Max messages in extended mode
    MIN_PAUSE_SECONDS = 120          # Minimum pause time before reminder
    MAX_MESSAGE_LENGTH = 1000        # Maximum user message length

class DatabaseDefaults:
    """Database-related constants."""
    PARENT_ID_ROOT = 0  # Root level for lecture steps
    DELETED_FLAG = 0    # Active task
    DELETED_TRUE = 1    # Deleted task

class PromptMarkers:
    """Markers used in course descriptions for GPT modes."""
    
    GPT_MARKER = "##GPT##"
    GPT_EDU_MARKER = "##GPT_EDU##"
    GPT_MAX_MARKER = "##GPT_MAX##"
