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


# ------------------ Local Intent Detection ----------------
#
# The phrase lists live in VoiceSettings (end_conversation_phrases and
# human_handoff_phrases) so there is a single place to configure them.

def _normalize_for_match(text: str) -> str:
    """Lowercase and drop punctuation so 'Goodbye.' matches 'goodbye'.

    STT providers with formatted turns add capitalization and
    punctuation ("Bye!", "Thanks, bye."), which must not defeat matching.
    """
    return clean_text(re.sub(r"[^\w\s']", " ", text))


def _normalize_phrases(phrases) -> set[str]:
    return {_normalize_for_match(p) for p in phrases if p and p.strip()}


def matches_phrase(text: str, phrases, max_words: int | None = None) -> bool:
    """Match user text against configured phrases.

    With max_words=None the whole utterance must equal a phrase (high
    confidence, used for local intents). With max_words set, a phrase may
    appear inside a message of at most that many words (looser, used only
    as a last-resort fallback when the LLM gave no intent).
    """
    normalized = _normalize_for_match(text)

    if max_words is None:
        return normalized in _normalize_phrases(phrases)

    if len(normalized.split()) > max_words:
        return False

    padded = f" {normalized} "
    return any(f" {p} " in padded for p in _normalize_phrases(phrases))


def detect_local_intent(
    text: str,
    end_conversation_phrases,
    human_handoff_phrases,
) -> str | None:
    """
    Detect high-confidence intents without calling the LLM.

    Returns:
        'end_conversation' when the whole utterance is a goodbye phrase.
        'human_handoff' when the whole utterance is a handoff phrase.
        None when the utterance needs LLM interpretation.

    Ambiguous phrases such as 'I am done' or 'that's it' should not be
    added to the lists; they need context and are left to the LLM.
    """
    if matches_phrase(text, end_conversation_phrases):
        return "end_conversation"

    if matches_phrase(text, human_handoff_phrases):
        return "human_handoff"

    return None


def prepare_text_for_tts(text: str) -> str:
    """
    Prepare LLM-generated text for smooth text-to-speech playback.

    Removes visual formatting such as Markdown while preserving
    meaningful spoken content.
    """

    if not text:
        return ""

    # Remove Markdown code blocks.
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)

    # Remove Markdown headings.
    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.MULTILINE)

    # Remove bullet points and numbered-list markers.
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+[.)]\s+", "", text, flags=re.MULTILINE)

    # Remove Markdown bold / italic markers.
    text = text.replace("**", "")
    text = text.replace("__", "")
    text = text.replace("*", "")
    text = text.replace("_", "")

    # Convert Markdown links:
    # [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Remove blockquote marker.
    text = re.sub(r"^\s*>\s*", "", text, flags=re.MULTILINE)

    # Collapse newlines and repeated whitespace.
    text = re.sub(r"\s+", " ", text)

    return text.strip()