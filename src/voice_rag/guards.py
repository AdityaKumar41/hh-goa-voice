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


def answer_overlap_ratio(answer: str, evidence: list[str]) -> float:
    """Fraction of answer content words that appear in the retrieved evidence."""
    words = re.findall(r"[a-zA-Z\u0900-\u0d7f]+", answer.casefold())
    content_words = [word for word in words if len(word) > 2 and word not in {
        "the", "and", "for", "with", "from", "that", "this", "have", "are", "was", "were",
        "not", "but", "you", "your", "can", "will", "about", "their", "what", "where",
        "when", "who", "how", "which", "there",
    }]
    if not content_words:
        return 1.0
    evidence_terms = set()
    for chunk in evidence:
        evidence_terms.update(
            word for word in re.findall(r"[a-zA-Z\u0900-\u0d7f]+", chunk.casefold())
        )
    matched = sum(word in evidence_terms for word in content_words)
    return matched / len(content_words)
