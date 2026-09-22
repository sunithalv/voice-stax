# Provides text-cleaning, tokenization, and simple phrase-detection utilities.
import re
from typing import List


# ------------------ Text Cleaning ----------------

def clean_text(text: str) -> str:
    """Lowercase, strip, and normalize whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


# ------------------ Short Word Check ----------------

def is_short_word(text: str) -> bool:
    """Return True if text is a short word such as yes/no."""
    return clean_text(text) in {"yes", "no"}


# ------------------ Tokenization ----------------

def split_into_words(text: str) -> List[str]:
    """Split text into words, stripping punctuation."""
    text_clean = re.sub(r"[^\w\s]", "", text)
    return text_clean.split()


# ------------------ Goodbye Detection ----------------

GOODBYE_PHRASES = {
    "bye",
    "goodbye",
    "bye bye",
    "good bye",
    "see you",
    "see you later",
    "talk to you later",
    "have a good day",
    "have a nice day",
    "thanks bye",
    "thank you bye",
    "you can end the call",
    "end the call",
}


def is_goodbye(text: str) -> bool:
    """
    Return True only for a clear, standalone goodbye phrase.

    Ambiguous phrases such as 'I am done' or 'that's it' are
    intentionally not included because they require context.
    """
    return clean_text(text) in GOODBYE_PHRASES


# ------------------ Human Handoff Detection ----------------

HUMAN_HANDOFF_PHRASES = {
    "connect me to a human",
    "connect me to an agent",
    "speak to a human",
    "speak to an agent",
    "talk to a human",
    "talk to an agent",
    "transfer me to an agent",
    "i want a human",
}


def is_human_handoff_request(text: str) -> bool:
    """Return True for clear requests to speak with a human agent."""
    return clean_text(text) in HUMAN_HANDOFF_PHRASES


# ------------------ Local Intent Detection ----------------

def detect_local_intent(text: str) -> str | None:
    """
    Detect high-confidence intents without calling the LLM.

    Returns:
        'end_conversation' for explicit goodbye phrases.
        'human_handoff' for explicit human-agent requests.
        None when the utterance needs LLM interpretation.
    """
    if is_goodbye(text):
        return "end_conversation"

    if is_human_handoff_request(text):
        return "human_handoff"

    return None