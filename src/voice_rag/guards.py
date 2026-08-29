import re
from dataclasses import dataclass
from enum import Enum


class GuardCategory(str, Enum):
    ALLOWED = "allowed"
    UNSAFE = "unsafe"
    OFF_TOPIC = "off_topic"
    PRIVACY = "privacy"


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    reason: str | None = None
    category: str = GuardCategory.ALLOWED.value


class QueryGuard:
    """Cheap, deterministic safety gate that runs before retrieval or generation."""

    blocked_patterns = (
        "ignore previous instructions",
        "ignore all previous instructions",
        "reveal your system prompt",
        "repeat your system prompt",
        "show your instructions",
        "what are your instructions",
        "print your prompt",
        "how to make a bomb",
        "how to build a bomb",
        "how to make a molotov",
        "how to synthesize sarin",
        "how to hotwire a car",
        "inject your system prompt",
        "system prompt",
        "developer message",
        "jailbreak",
        "dan mode",
        "simulate a gangster",
        "credit card number",
        "social security number",
    )
    off_topic_patterns = (
        "write malware",
        "write a keylogger",
        "steal a password",
        "bypass authentication",
        "hack into",
        "ddos",
        "phishing email",
        "create a fake id",
        "forge a signature",
    )
    privacy_patterns = (
        "my medical records",
        "private messages of",
        "someone else's",
        "leak the email",
        "list all users",
    )

    def check(self, text: str) -> GuardDecision:
        lowered = text.casefold()
        if any(pattern in lowered for pattern in self.blocked_patterns):
            return GuardDecision(False, "unsafe or prompt-injection content", GuardCategory.UNSAFE.value)
        if any(pattern in lowered for pattern in self.off_topic_patterns):
            return GuardDecision(
                False, "request is outside the research assistant scope", GuardCategory.OFF_TOPIC.value
            )
        if any(pattern in lowered for pattern in self.privacy_patterns):
            return GuardDecision(False, "request targets private or personal data", GuardCategory.PRIVACY.value)
        return GuardDecision(True)


def _stem(word: str) -> str:
    """Light suffix stemmer so plural/tense variants (team/teams, hold/held) still match.

    Devanagari/Indic words are returned unchanged (no latin suffixes to strip).
    """
    if not word or not word.isascii():
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ing") and len(word) > 5:
        base = word[:-3]
        return base.removesuffix("e")
    if word.endswith("es") and len(word) > 4:
        return word[:-2] if not word.endswith("ies") else word
    if word.endswith("s") and len(word) > 3 and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def answer_overlap_ratio(answer: str, evidence: list[str]) -> float:
    """Fraction of answer content words (stemmed) that appear in the retrieved evidence."""
    words = re.findall(r"[a-zA-Z\u0900-\u0d7f]+", answer.casefold())
    content_words = [_stem(word) for word in words if len(word) > 2 and word not in {
        "the", "and", "for", "with", "from", "that", "this", "have", "are", "was", "were",
        "not", "but", "you", "your", "can", "will", "about", "their", "what", "where",
        "when", "who", "how", "which", "there",
    }]
    if not content_words:
        return 1.0
    evidence_terms = set()
    for chunk in evidence:
        evidence_terms.update(
            _stem(word)
            for word in re.findall(r"[a-zA-Z\u0900-\u0d7f]+", chunk.casefold())
        )
    matched = sum(word in evidence_terms for word in content_words)
    return matched / len(content_words)


def detect_smalltalk(text: str) -> str | None:
    """Recognize pure greetings/thanks/farewell so they are not sent to retrieval.

    Small talk must never be answered by quoting a random dataset passage — it gets a
    friendly canned reply instead. Returns the category name or None.
    """
    t = text.casefold().strip()
    patterns = {
        "greeting": (
            "hi", "hello", "hey", "heya", "hola", "namaste", "नमस्ते", "vanakkam", "வணக்கம்",
            "good morning", "good afternoon", "good evening", "good day", "wassup",
            "what's up", "how are you", "how r u", "kaise ho", "कैसे हो", "kem cho", "સત શ્રી અકાલ",
        ),
        "thanks": (
            "thank you", "thanks", "thank you very much", "thx", "dhanyavad", "धन्यवाद",
            "shukriya", "शुक्रिया", "you're great", "great work",
        ),
        "farewell": ("bye", "goodbye", "see you", "alvida", "अलविदा", "see you later"),
    }
    for category, words in patterns.items():
        for word in words:
            marker = word.casefold()
            if t == marker or t.startswith(marker + " ") or t.endswith(marker) or f" {marker} " in f" {t} ":
                return category
    return None
