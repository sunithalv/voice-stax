# VoiceStax/utils/text_processing.py

import re
from typing import List

# ------------------ Text Cleaning ----------------
def clean_text(text: str) -> str:
    """Lowercase, strip, and normalize whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())

# ------------------ Short Word Check ----------------
def is_short_word(text: str) -> bool:
    """Return True if text is a short word (yes/no)."""
    return clean_text(text) in {"yes", "no"}

# ------------------ Tokenization ----------------
def split_into_words(text: str) -> List[str]:
    """Split text into words, stripping punctuation."""
    text_clean = re.sub(r"[^\w\s]", "", text)
    return text_clean.split()

# ------------------ Goodbye Detection ----------------
def is_goodbye(text: str) -> bool:
    """Return True if text contains a goodbye keyword."""
    GOODBYE_KEYWORDS = {"bye", "goodbye", "exit", "quit", "stop"}
    return clean_text(text) in GOODBYE_KEYWORDS
